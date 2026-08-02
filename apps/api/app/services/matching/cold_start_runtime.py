"""Database adapter for the pure stage-16 cold-start policy."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.cold_start import ColdStartStatus, QuestionResponse
from app.models.matching import InteractionEvent
from app.models.policy import MatchPolicyVersion
from app.services.matching.cold_start_policy import (
    COLD_START_POLICY_VERSION,
    ColdStartDecision,
    ColdStartEvidence,
    apply_cold_start_annotations,
    average_profile_confidence,
    evaluate_cold_start,
    explicit_signal_count,
)
from app.services.matching.errors import RecommendationError
from app.services.matching.types import MatchCandidate, ResolvedProfile, SubjectContext

_DETAIL_EVENTS = ("VIEW.DETAIL", "VIEW_DETAIL", "RECOMMENDATION_OPENED")
_FAVORITE_EVENTS = ("INTENT.FAVORITE", "FAVORITE_ADD", "RECOMMENDATION_SAVED")
_CHECK_IN_EVENTS = ("FIELD.CHECK_IN", "CHECK_IN", "BOOTH_CHECKED_IN")
_FEEDBACK_EVENTS = (
    "FEEDBACK.RELEVANT",
    "FEEDBACK.IRRELEVANT",
    "FEEDBACK_SUBMIT",
)
_CONSULTATION_EVENTS = (
    "B2B.MEETING_VIEW",
    "B2B.MEETING_REQUEST",
    "B2B.MEETING_COMPLETE",
    "B2B.SAMPLE_REQUEST",
    "B2B.QUOTE_REQUEST",
    "MEETING_REQUESTED",
)
_VALID_EVENTS = tuple(
    dict.fromkeys(
        (*_DETAIL_EVENTS, *_FAVORITE_EVENTS, *_CHECK_IN_EVENTS, *_FEEDBACK_EVENTS, *_CONSULTATION_EVENTS)
    )
)


def _owner_clause(subject: SubjectContext):
    if subject.user_id is not None:
        return InteractionEvent.user_id == subject.user_id
    if subject.guest_session_id is not None:
        return InteractionEvent.guest_session_id == subject.guest_session_id
    return InteractionEvent.visit_session_id == subject.visit_session_id


async def resolve_evidence(
    db: AsyncSession, *, subject: SubjectContext, profile: ResolvedProfile
) -> ColdStartEvidence:
    window_start = subject.server_time - timedelta(days=30)
    rows = await db.execute(
        select(InteractionEvent.event_type, func.count(InteractionEvent.interaction_event_id))
        .where(
            InteractionEvent.tenant_id == subject.tenant_id,
            InteractionEvent.event_id == subject.event_id,
            InteractionEvent.occurred_at >= window_start,
            InteractionEvent.event_type.in_(_VALID_EVENTS),
            _owner_clause(subject),
        )
        .group_by(InteractionEvent.event_type)
    )
    counts = {row[0]: int(row[1]) for row in rows}

    def total(names: tuple[str, ...]) -> int:
        return sum(counts.get(name, 0) for name in names)

    valid_count = sum(counts.values())
    response_count = int(
        (
            await db.execute(
                select(func.count(func.distinct(QuestionResponse.question_id))).where(
                    QuestionResponse.profile_id == profile.profile_id
                )
            )
        ).scalar_one()
        or 0
    )
    return ColdStartEvidence(
        explicit_signal_count=explicit_signal_count(profile) + response_count,
        valid_behavior_count=valid_count,
        detail_view_count=total(_DETAIL_EVENTS),
        favorite_count=total(_FAVORITE_EVENTS),
        check_in_count=total(_CHECK_IN_EVENTS),
        feedback_count=total(_FEEDBACK_EVENTS),
        valid_consultation_count=total(_CONSULTATION_EVENTS),
        average_confidence=average_profile_confidence(profile),
        verified=float(profile.raw_context.get("buyer_verification") or 0) >= 0.75,
        reset_requested=bool(profile.raw_context.get("cold_start_reset")),
    )


async def evaluate_and_annotate(
    db: AsyncSession,
    *,
    subject: SubjectContext,
    profile: ResolvedProfile,
    candidates: list[MatchCandidate],
) -> ColdStartDecision:
    evidence = await resolve_evidence(db, subject=subject, profile=profile)
    decision = evaluate_cold_start(profile, evidence)
    apply_cold_start_annotations(
        candidates,
        profile=profile,
        decision=decision,
        server_time=subject.server_time,
    )

    policy = (
        await db.execute(
            select(MatchPolicyVersion).where(
                MatchPolicyVersion.version == COLD_START_POLICY_VERSION,
                MatchPolicyVersion.status == "PUBLISHED",
            )
        )
    ).scalar_one_or_none()
    if policy is None:
        raise RecommendationError(
            "PERSISTENCE_CONTRACT_VIOLATION",
            f"게시된 콜드스타트 정책을 찾을 수 없습니다: {COLD_START_POLICY_VERSION}",
            http_status=500,
        )

    latest = (
        await db.execute(
            select(ColdStartStatus)
            .where(
                ColdStartStatus.tenant_id == subject.tenant_id,
                ColdStartStatus.event_id == subject.event_id,
                ColdStartStatus.object_type == (
                    "BUYER" if profile.user_type == "BUYER" else "USER"
                ),
                ColdStartStatus.object_id == profile.profile_id,
            )
            .order_by(ColdStartStatus.evaluated_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if latest is None or latest.input_fingerprint != decision.input_fingerprint:
        db.add(
            ColdStartStatus(
                tenant_id=subject.tenant_id,
                event_id=subject.event_id,
                object_type="BUYER" if profile.user_type == "BUYER" else "USER",
                object_id=profile.profile_id,
                cold_start_type=list(decision.type_codes),
                status=decision.state,
                previous_status=latest.status if latest is not None else None,
                stability_score=decision.stability_score,
                signal_count=evidence.valid_behavior_count,
                profile_completeness=profile.completeness,
                match_policy_version_id=policy.match_policy_version_id,
                input_fingerprint=decision.input_fingerprint,
                details_json={
                    "exploration_ratio": decision.exploration_ratio,
                    "recommendation_confidence_cap": decision.recommendation_confidence_cap,
                    "next_question_codes": list(decision.next_question_codes),
                    "evidence": evidence.__dict__,
                },
                transitioned_at=(
                    subject.server_time
                    if latest is not None and latest.status != decision.state
                    else None
                ),
                evaluated_at=subject.server_time,
            )
        )
    return decision
