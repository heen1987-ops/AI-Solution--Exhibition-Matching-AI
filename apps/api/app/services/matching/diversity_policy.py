"""Stage-15 exposure overlay resolver and slate-policy adapter."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.matching import (
    InteractionEvent,
    RecommendationImpression,
)
from app.services.matching.cold_start_policy import ColdStartDecision
from app.services.matching.slate_policy import (
    ExposureOverlay,
    SlateBuildResult,
    build_slate,
)
from app.services.matching.types import (
    MatchCandidate,
    ResolvedProfile,
    SubjectContext,
)

_POSITIVE_EVENT_TYPES = (
    "RECOMMENDATION_OPENED",
    "RECOMMENDATION_SAVED",
    "BOOTH_CHECKED_IN",
    "MEETING_REQUESTED",
)


def _impression_owner_clause(subject: SubjectContext):
    if subject.user_id is not None:
        return RecommendationImpression.user_id == subject.user_id
    if subject.guest_session_id is not None:
        return RecommendationImpression.guest_session_id == subject.guest_session_id
    return RecommendationImpression.visit_session_id == subject.visit_session_id


def _event_owner_clause(subject: SubjectContext):
    if subject.user_id is not None:
        return InteractionEvent.user_id == subject.user_id
    if subject.guest_session_id is not None:
        return InteractionEvent.guest_session_id == subject.guest_session_id
    return InteractionEvent.visit_session_id == subject.visit_session_id


async def resolve_exposure_overlay(
    db: AsyncSession,
    *,
    subject: SubjectContext,
    candidates: list[MatchCandidate],
) -> ExposureOverlay:
    """Resolve actual visible impressions, never server response counts."""

    recommendable_ids = {
        candidate.recommendable_id
        for candidate in candidates
        if candidate.recommendable_id is not None
    }
    if not recommendable_ids:
        return ExposureOverlay()

    window_start = subject.server_time - timedelta(days=1)
    ids_by_type = {
        object_type: {
            candidate.recommendable_id
            for candidate in candidates
            if candidate.object_type == object_type
            and candidate.recommendable_id is not None
        }
        for object_type in ("PRODUCT", "BOOTH", "PROGRAM", "EXHIBITOR")
    }
    impression_scopes = []
    positive_scopes = []
    if ids_by_type["PRODUCT"]:
        impression_scopes.append(
            and_(
                RecommendationImpression.recommendable_id.in_(ids_by_type["PRODUCT"]),
                RecommendationImpression.occurred_at >= window_start,
            )
        )
        positive_scopes.append(
            and_(
                InteractionEvent.recommendable_id.in_(ids_by_type["PRODUCT"]),
                InteractionEvent.occurred_at >= window_start,
            )
        )
    if ids_by_type["BOOTH"]:
        impression_booth_scope = [
            RecommendationImpression.recommendable_id.in_(ids_by_type["BOOTH"])
        ]
        positive_booth_scope = [
            InteractionEvent.recommendable_id.in_(ids_by_type["BOOTH"])
        ]
        if subject.visit_session_id is not None:
            impression_booth_scope.append(
                RecommendationImpression.visit_session_id == subject.visit_session_id
            )
            positive_booth_scope.append(
                InteractionEvent.visit_session_id == subject.visit_session_id
            )
        impression_scopes.append(and_(*impression_booth_scope))
        positive_scopes.append(and_(*positive_booth_scope))
    event_scope_ids = ids_by_type["PROGRAM"] | ids_by_type["EXHIBITOR"]
    if event_scope_ids:
        impression_scopes.append(
            RecommendationImpression.recommendable_id.in_(event_scope_ids)
        )
        positive_scopes.append(InteractionEvent.recommendable_id.in_(event_scope_ids))

    if not impression_scopes:
        return ExposureOverlay()

    impression_rows = await db.execute(
        select(
            RecommendationImpression.recommendable_id,
            func.count(RecommendationImpression.impression_id),
        )
        .where(
            RecommendationImpression.tenant_id == subject.tenant_id,
            RecommendationImpression.event_id == subject.event_id,
            or_(*impression_scopes),
            RecommendationImpression.content_type == "PERSONALIZED_RECOMMENDATION",
            _impression_owner_clause(subject),
        )
        .group_by(RecommendationImpression.recommendable_id)
    )
    user_impressions = {row[0]: int(row[1]) for row in impression_rows}

    positive_rows = await db.execute(
        select(
            InteractionEvent.recommendable_id,
            func.count(InteractionEvent.interaction_event_id),
        )
        .where(
            InteractionEvent.tenant_id == subject.tenant_id,
            InteractionEvent.event_id == subject.event_id,
            or_(*positive_scopes),
            InteractionEvent.event_type.in_(_POSITIVE_EVENT_TYPES),
            _event_owner_clause(subject),
        )
        .group_by(InteractionEvent.recommendable_id)
    )
    positive_actions = {row[0]: int(row[1]) for row in positive_rows}

    exhibitor_rows = await db.execute(
        select(
            RecommendationImpression.exhibitor_id,
            func.count(RecommendationImpression.impression_id),
        )
        .where(
            RecommendationImpression.tenant_id == subject.tenant_id,
            RecommendationImpression.event_id == subject.event_id,
            RecommendationImpression.exhibitor_id.is_not(None),
            RecommendationImpression.content_type == "PERSONALIZED_RECOMMENDATION",
        )
        .group_by(RecommendationImpression.exhibitor_id)
    )
    event_exhibitor_impressions = {
        row[0]: int(row[1]) for row in exhibitor_rows if row[0] is not None
    }
    return ExposureOverlay(
        user_impressions=user_impressions,
        user_positive_actions=positive_actions,
        event_exhibitor_impressions=event_exhibitor_impressions,
        event_total_impressions=sum(event_exhibitor_impressions.values()),
    )


def _decide_action(candidate: MatchCandidate, profile: ResolvedProfile) -> str:
    if candidate.object_type == "PROGRAM":
        return "JOIN_PROGRAM"
    if (
        profile.user_type == "BUYER"
        and candidate.availability.get("meeting")
        and candidate.object_type in ("EXHIBITOR", "BOOTH")
    ):
        return "REQUEST_MEETING"
    if candidate.object_type == "BOOTH":
        wait = candidate.estimated_wait_minutes or 0
        walk = candidate.estimated_walk_minutes or 0
        if candidate.payload.get("operating_status") != "OPEN":
            return "SAVE_FOR_LATER"
        if wait <= 5 and walk <= 10:
            return "VISIT_NOW"
        if candidate.payload.get("congestion_level") == "HIGH" or wait > 15:
            return "SAVE_FOR_LATER"
        return "ADD_TO_ROUTE"
    if candidate.object_type == "PRODUCT":
        if candidate.availability.get("purchase") or candidate.availability.get(
            "tasting"
        ):
            return "SAVE_FOR_LATER" if candidate.context_adjustment < 0 else "VISIT_NOW"
        return "REFINE_PROFILE"
    if candidate.object_type == "EXHIBITOR":
        return "REQUEST_MEETING" if profile.user_type == "BUYER" else "SAVE_FOR_LATER"
    return "SAVE_FOR_LATER"


async def apply_diversity_policy(
    db: AsyncSession,
    candidates: list[MatchCandidate],
    *,
    limit: int,
    profile: ResolvedProfile,
    subject: SubjectContext,
    user_preference: str = "BALANCED",
    cold_start: ColdStartDecision | None = None,
) -> SlateBuildResult:
    overlay = await resolve_exposure_overlay(db, subject=subject, candidates=candidates)
    result = build_slate(
        candidates,
        limit=limit,
        profile=profile,
        server_time=subject.server_time,
        exposure=overlay,
        user_preference=user_preference,
        exploration_ratio=(cold_start.exploration_ratio if cold_start else None),
    )
    for candidate in result.items:
        candidate.recommended_action = _decide_action(candidate, profile)
    return result
