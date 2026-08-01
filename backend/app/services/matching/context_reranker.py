"""Stage 14 context-aware re-ranking orchestration.

Optional meeting availability is read through a capability check.  Every score
is then produced by the pure, versioned policy in :mod:`context_policy` and its
full calculation lineage is attached to the candidate for append-only storage.
"""

from __future__ import annotations

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.matching.context_policy import (
    DISTANCE_UNIT_TO_METERS,
    WALK_SPEED_METERS_PER_MINUTE,
    evaluate_context,
)
from app.services.matching.types import MatchCandidate, ResolvedContext, ResolvedProfile


async def _open_slot_participation_ids(
    db: AsyncSession, participation_ids: set, server_time
) -> set | None:
    if not participation_ids:
        return set()
    table_available = (
        await db.execute(
            text("SELECT to_regclass('interaction.availability_slot') IS NOT NULL")
        )
    ).scalar_one()
    if not table_available:
        return None
    statement = text(
        "SELECT participation_id FROM interaction.availability_slot "
        "WHERE participation_id IN :participation_ids AND status = 'OPEN' "
        "AND reserved_count < capacity AND end_at >= :server_time"
    ).bindparams(bindparam("participation_ids", expanding=True))
    rows = await db.execute(
        statement,
        {
            "participation_ids": tuple(participation_ids),
            "server_time": server_time,
        },
    )
    return {row.participation_id for row in rows}


def _prepare_observed_fields(candidate: MatchCandidate) -> None:
    if "_distance_units" in candidate.payload:
        distance_meters = (
            float(candidate.payload["_distance_units"]) * DISTANCE_UNIT_TO_METERS
        )
        candidate.distance_meters = distance_meters
        candidate.estimated_walk_minutes = max(
            1, round(distance_meters / WALK_SPEED_METERS_PER_MINUTE)
        )
    if candidate.object_type == "BOOTH":
        candidate.estimated_wait_minutes = candidate.payload.get(
            "estimated_wait_minutes"
        )
    candidate.status_observed_at = candidate.payload.get("status_observed_at")

    payload = candidate.payload
    if candidate.object_type == "BOOTH":
        candidate.availability = {"open": payload.get("operating_status") == "OPEN"}
    elif candidate.object_type == "PRODUCT":
        candidate.availability = {
            "purchase": payload.get("purchase_status") in ("AVAILABLE", "LIMITED"),
            "tasting": payload.get("tasting_status") == "AVAILABLE",
        }


async def rerank_by_context(
    db: AsyncSession,
    candidates: list[MatchCandidate],
    *,
    profile: ResolvedProfile,
    context: ResolvedContext,
) -> None:
    participation_ids = {
        candidate.participation_id
        for candidate in candidates
        if candidate.participation_id is not None
    }
    open_slot_ids = (
        await _open_slot_participation_ids(db, participation_ids, context.server_time)
        if profile.user_type == "BUYER"
        else set()
    )

    for candidate in candidates:
        _prepare_observed_fields(candidate)
        meeting_open = (
            None
            if open_slot_ids is None
            else candidate.participation_id in open_slot_ids
        )
        if meeting_open is True:
            candidate.availability["meeting"] = True

        evaluation = evaluate_context(
            candidate,
            profile=profile,
            context=context,
            meeting_open=meeting_open,
        )
        candidate.context_policy_version = evaluation.policy_version
        candidate.context_components = evaluation.components
        candidate.context_effective_weights = evaluation.effective_weights
        candidate.context_contributions = evaluation.contributions
        candidate.context_missing_components = evaluation.missing_components
        candidate.context_input_fingerprint = evaluation.input_fingerprint
        candidate.context_score_fingerprint = evaluation.score_fingerprint
        candidate.context_blended_score = evaluation.final_score
        candidate.score_components["context_score"] = evaluation.context_score
        candidate.final_score = evaluation.final_score
        candidate.context_adjustment = (
            evaluation.final_score - candidate.normalized_score
        )
