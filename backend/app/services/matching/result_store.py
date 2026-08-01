"""Stage 13 result persistence with exact policy and calculation provenance.

The recommendation, hard-filter evaluation, score details, reasons, and version
references are committed as one transaction. Missing registry rows are contract
failures; this module never invents foreign keys or reports success after rollback.
"""

from __future__ import annotations

import uuid
from datetime import timedelta

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.ai import ModelVersion
from app.models.common import new_uuid7
from app.models.matching import MatchReason, MatchResult, MatchRun
from app.models.policy import MatchPolicyVersion
from app.services.matching import errors
from app.services.matching.ontology_support import get_catalog
from app.services.matching.types import (
    MatchCandidate,
    PipelineTrace,
    RecommendationOutcome,
    ResolvedContext,
    ResolvedProfile,
    ValidatedRequest,
)

RECOMMENDATION_TTL_MINUTES = 10
RANKING_VERSION = "match-v1.0-baseline"
EXPLANATION_VERSION = "explain-v1.0-template"


def _contract_error(message: str) -> errors.RecommendationError:
    return errors.RecommendationError(
        "PERSISTENCE_CONTRACT_VIOLATION",
        message,
        http_status=500,
        retryable=False,
    )


async def _resolve_taxonomy_version_id(
    db: AsyncSession, semantic_version: str
) -> uuid.UUID:
    row = (
        await db.execute(
            text(
                "SELECT taxonomy_version_id FROM ontology.taxonomy_version "
                "WHERE semantic_version = :version LIMIT 1"
            ),
            {"version": semantic_version},
        )
    ).first()
    if row is None:
        raise _contract_error(
            f"게시된 온톨로지 버전을 찾을 수 없습니다: {semantic_version}"
        )
    return row[0]


async def _resolve_policy(db: AsyncSession, version: str) -> MatchPolicyVersion:
    policy = (
        await db.execute(
            select(MatchPolicyVersion).where(
                MatchPolicyVersion.version == version,
                MatchPolicyVersion.status == "PUBLISHED",
            )
        )
    ).scalar_one_or_none()
    if policy is None:
        raise _contract_error(f"게시된 매칭 정책을 찾을 수 없습니다: {version}")
    return policy


async def _resolve_ranking_model(db: AsyncSession, version: str) -> ModelVersion:
    model = (
        await db.execute(
            select(ModelVersion).where(
                ModelVersion.model_type == "RANKING",
                ModelVersion.version == version,
                ModelVersion.status == "DEPLOYED",
            )
        )
    ).scalar_one_or_none()
    if model is None:
        raise _contract_error(f"배포된 랭킹 모델 버전을 찾을 수 없습니다: {version}")
    return model


def _filter_evaluation_id(candidates: list[MatchCandidate]) -> uuid.UUID:
    raw_ids = {candidate.filter_evaluation_id for candidate in candidates}
    if None in raw_ids or len(raw_ids) != 1:
        raise _contract_error(
            "모든 추천 결과는 동일한 하드필터 평가 ID를 가져야 합니다."
        )
    raw_id = raw_ids.pop()
    try:
        return uuid.UUID(str(raw_id))
    except ValueError as exc:
        raise _contract_error("하드필터 평가 ID가 UUID 형식이 아닙니다.") from exc


def _validate_candidates(candidates: list[MatchCandidate]) -> None:
    if not candidates:
        raise errors.no_candidate()
    ranks = [candidate.rank for candidate in candidates]
    if any(rank <= 0 for rank in ranks) or len(ranks) != len(set(ranks)):
        raise _contract_error("추천 결과 순위는 양수이며 중복될 수 없습니다.")
    for candidate in candidates:
        if candidate.recommendable_id is None:
            raise _contract_error(
                f"추천대상 레지스트리가 없습니다: {candidate.object_type} "
                f"{candidate.object_id}"
            )
        if not candidate.directional_policy_version:
            raise _contract_error("방향별 점수 정책 버전이 없습니다.")
        if not candidate.directional_score_fingerprint:
            raise _contract_error("방향별 점수 계산 지문이 없습니다.")
        if candidate.exhibitor_directional_policy_version and not (
            candidate.exhibitor_directional_score_fingerprint
        ):
            raise _contract_error("업체 방향 점수 계산 지문이 없습니다.")
        if candidate.reciprocal_policy_version and not (
            candidate.reciprocal_score_fingerprint
        ):
            raise _contract_error("양면 점수 계산 지문이 없습니다.")
        for reason in candidate.reasons:
            if reason.generated_by == "LLM" and reason.ai_run_id is None:
                raise _contract_error(
                    "LLM 추천 이유에는 검증된 AI 실행 ID가 필요합니다."
                )


def _reciprocal_details(candidate: MatchCandidate) -> dict | None:
    if candidate.reciprocal_policy_version is None:
        return None
    return {
        "policy_version": candidate.reciprocal_policy_version,
        "buyer_to_exhibitor": candidate.buyer_to_exhibitor,
        "exhibitor_to_buyer": candidate.exhibitor_to_buyer,
        "base_score": candidate.reciprocal_base_score,
        "minimum_direction_score": candidate.minimum_direction_score,
        "minimum_direction_cap": candidate.minimum_direction_cap,
        "imbalance_value": candidate.imbalance_value,
        "imbalance_penalty": candidate.imbalance_penalty,
        "confidence_adjustment": candidate.confidence_adjustment,
        "acceptance_capacity_score": candidate.acceptance_capacity_score,
        "acceptance_adjustment": candidate.acceptance_adjustment,
        "final_score": candidate.reciprocal_score,
        "grade": candidate.reciprocal_grade,
        "status": candidate.reciprocal_status,
        "recommended_action": candidate.reciprocal_recommended_action,
        "applied_cap_codes": list(candidate.reciprocal_applied_cap_codes),
        "capped": candidate.reciprocal_capped,
    }


async def _persist(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    validated: ValidatedRequest,
    profile: ResolvedProfile,
    context: ResolvedContext,
    candidates: list[MatchCandidate],
    trace: PipelineTrace,
    generated_at,
    expires_at,
    fallback_strategy: str | None,
) -> tuple[str, str]:
    _validate_candidates(candidates)
    filter_evaluation_id = _filter_evaluation_id(candidates)
    if profile.profile_version_id is None:
        raise errors.profile_incomplete(
            "추천 결과 저장에는 고정된 프로파일 버전이 필요합니다."
        )

    catalog = get_catalog()
    taxonomy_version_id = await _resolve_taxonomy_version_id(db, catalog.version)
    ranking_model = await _resolve_ranking_model(db, RANKING_VERSION)

    policy_versions = {
        version
        for candidate in candidates
        for version in (
            candidate.directional_policy_version,
            candidate.exhibitor_directional_policy_version,
            candidate.reciprocal_policy_version,
        )
        if version is not None
    }
    policies = {
        version: await _resolve_policy(db, version)
        for version in sorted(policy_versions)
    }
    primary_versions = {
        candidate.directional_policy_version for candidate in candidates
    }
    if len(primary_versions) != 1:
        raise _contract_error(
            "한 추천 실행에는 하나의 주 방향 정책만 사용할 수 있습니다."
        )
    primary_version = primary_versions.pop()
    if primary_version is None:  # guarded by _validate_candidates
        raise AssertionError("unreachable")
    primary_policy = policies[primary_version]

    match_run = MatchRun(
        recommendation_session_id=session_id,
        tenant_id=validated.subject.tenant_id,
        event_id=validated.subject.event_id,
        profile_id=profile.profile_id,
        profile_version_id=profile.profile_version_id,
        visit_session_id=validated.subject.visit_session_id,
        filter_evaluation_id=filter_evaluation_id,
        recommendation_type=validated.recommendation_type,
        policy_version_id=primary_policy.match_policy_version_id,
        ranking_model_version_id=ranking_model.model_version_id,
        explanation_model_version_id=None,
        taxonomy_version_id=taxonomy_version_id,
        context_snapshot={
            "current_zone": context.current_zone,
            "current_zone_id": (
                str(context.current_zone_id) if context.current_zone_id else None
            ),
            "remaining_minutes": context.remaining_minutes,
            "operational_snapshot_version": context.operational_snapshot_version,
            "exploration_mode": validated.exploration_mode,
            "source_channel_counts": trace.source_channel_counts,
        },
        candidate_count=trace.candidate_count,
        filtered_count=trace.filtered_count,
        result_count=len(candidates),
        fallback_strategy=fallback_strategy,
        status="ACTIVE",
        generated_at=generated_at,
        expires_at=expires_at,
        latency_ms=trace.latency_ms.get("total"),
    )
    db.add(match_run)
    await db.flush()

    for candidate in candidates:
        directional_policy = policies[candidate.directional_policy_version]
        exhibitor_policy = (
            policies[candidate.exhibitor_directional_policy_version]
            if candidate.exhibitor_directional_policy_version
            else None
        )
        reciprocal_policy = (
            policies[candidate.reciprocal_policy_version]
            if candidate.reciprocal_policy_version
            else None
        )
        match_result = MatchResult(
            tenant_id=validated.subject.tenant_id,
            event_id=validated.subject.event_id,
            recommendation_session_id=session_id,
            recommendable_id=candidate.recommendable_id,
            directional_policy_version_id=(directional_policy.match_policy_version_id),
            exhibitor_policy_version_id=(
                exhibitor_policy.match_policy_version_id if exhibitor_policy else None
            ),
            reciprocal_policy_version_id=(
                reciprocal_policy.match_policy_version_id if reciprocal_policy else None
            ),
            raw_score=candidate.raw_score,
            normalized_score=candidate.normalized_score,
            final_score=candidate.final_score,
            rank=candidate.rank,
            directional_components=candidate.directional_components,
            directional_effective_weights=candidate.directional_effective_weights,
            directional_contributions=candidate.directional_contributions,
            directional_missing_components=list(
                candidate.directional_missing_components
            ),
            directional_confidence=candidate.directional_confidence,
            directional_grade=candidate.directional_grade,
            directional_score_fingerprint=(candidate.directional_score_fingerprint),
            exhibitor_directional_components=(
                candidate.exhibitor_directional_components or None
            ),
            exhibitor_directional_effective_weights=(
                candidate.exhibitor_directional_effective_weights or None
            ),
            exhibitor_directional_contributions=(
                candidate.exhibitor_directional_contributions or None
            ),
            exhibitor_directional_missing_components=(
                list(candidate.exhibitor_directional_missing_components)
                if candidate.exhibitor_directional_policy_version
                else None
            ),
            exhibitor_directional_confidence=(
                candidate.exhibitor_directional_confidence
            ),
            exhibitor_directional_score_fingerprint=(
                candidate.exhibitor_directional_score_fingerprint
            ),
            reciprocal_details=_reciprocal_details(candidate),
            reciprocal_score_fingerprint=candidate.reciprocal_score_fingerprint,
            preference_score=candidate.score_components.get("preference_score"),
            goal_score=candidate.score_components.get("goal_score"),
            trade_score=candidate.score_components.get("trade_score"),
            context_score=candidate.score_components.get("context_score"),
            behavior_score=candidate.score_components.get("behavior_score"),
            diversity_adjustment=candidate.diversity_adjustment,
            trust_score=candidate.score_components.get("trust_score"),
            recommended_action=candidate.recommended_action,
        )
        db.add(match_result)
        await db.flush()
        candidate.match_result_id = match_result.match_result_id

        for reason in candidate.reasons:
            db.add(
                MatchReason(
                    match_result_id=match_result.match_result_id,
                    reason_code=reason.code,
                    reason_text=reason.text,
                    evidence_refs=reason.evidence_refs,
                    contribution_score=reason.contribution_score,
                    display_order=reason.display_order,
                    generated_by=reason.generated_by,
                    ai_run_id=reason.ai_run_id,
                    validation_status="VALID",
                )
            )

    await db.flush()
    return primary_version, RANKING_VERSION


async def store_recommendation(
    db: AsyncSession,
    *,
    validated: ValidatedRequest,
    profile: ResolvedProfile,
    context: ResolvedContext,
    candidates: list[MatchCandidate],
    trace: PipelineTrace,
) -> RecommendationOutcome:
    generated_at = context.server_time
    expires_at = generated_at + timedelta(minutes=RECOMMENDATION_TTL_MINUTES)
    session_id = new_uuid7()
    fallback_strategy = "CATEGORY_BROWSE" if validated.exploration_mode else None

    policy_version, ranking_version = await _persist(
        db,
        session_id=session_id,
        validated=validated,
        profile=profile,
        context=context,
        candidates=candidates,
        trace=trace,
        generated_at=generated_at,
        expires_at=expires_at,
        fallback_strategy=fallback_strategy,
    )
    await db.commit()

    return RecommendationOutcome(
        recommendation_session_id=session_id,
        generated_at=generated_at,
        expires_at=expires_at,
        profile_version=profile.profile_version,
        ranking_version=ranking_version,
        explanation_version=EXPLANATION_VERSION,
        policy_version=policy_version,
        items=candidates,
        trace=trace,
    )
