"""Stages 11 and 12 scoring adapter for the backend pipeline.

This module maps normalized features produced by the backend into the immutable
policies in :mod:`meet_ai.scoring`.  It intentionally owns no weights or score
formula.  A stage-10 evaluation identifier is required so the scoring result can
always be traced back to the eligibility decision that admitted the candidate.
"""

from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.profile import InferredPreference
from app.services.matching.engine_adapter import execute_directional_score
from app.services.matching.ontology_support import (
    Catalog,
    get_catalog,
    max_match_strength,
)
from app.services.matching.types import MatchCandidate, ResolvedProfile
from meet_ai.engine import MatchingMode
from meet_ai.scoring import (
    BUYER_SCORE_V1,
    CONSUMER_SCORE_V1,
    DirectionalScoreResult,
    EligibilityDecision,
    ScoreValidationError,
    ScoringPolicy,
)


def _candidate_behavior_codes(candidate: MatchCandidate) -> set[str]:
    payload = candidate.payload
    codes: set[str] = set()
    if payload.get("category_code"):
        codes.add(payload["category_code"])
    codes.update((payload.get("taste_json") or {}).keys())
    codes.update((payload.get("aroma_json") or {}).keys())
    codes.update(payload.get("usage_json") or [])
    codes.update(payload.get("feature_json") or [])
    supply_profile = payload.get("supply_profile") or {}
    codes.update(supply_profile.get("business_types") or [])
    return codes


async def _load_inferred_preferences(
    db: AsyncSession, profile_id: object
) -> dict[str, tuple[float, float]]:
    rows = await db.execute(
        select(
            InferredPreference.attribute_code,
            InferredPreference.inferred_score,
            InferredPreference.confidence,
        ).where(InferredPreference.profile_id == profile_id)
    )
    return {
        row.attribute_code: (
            float(row.inferred_score),
            float(row.confidence),
        )
        for row in rows
    }


def _behavior_score(
    candidate: MatchCandidate,
    inferred: Mapping[str, tuple[float, float]],
    catalog: Catalog,
) -> float | None:
    """Return ``None`` when there is no behavioral evidence.

    Missing evidence must not become a neutral 0.5 because stage 11 requires the
    component to be removed and the remaining weights to be normalized.
    """

    if not inferred:
        return None
    candidate_codes = _candidate_behavior_codes(candidate)
    if not candidate_codes:
        return None

    weighted_sum = 0.0
    weight_total = 0.0
    for code, (score, confidence) in inferred.items():
        strength = max_match_strength(catalog, candidate_codes, {code})
        if strength <= 0:
            continue
        weighted_sum += strength * confidence * score
        weight_total += strength * confidence

    if weight_total == 0:
        return 0.0
    normalized = weighted_sum / weight_total
    return min(max((normalized + 1.0) / 2.0, 0.0), 1.0)


def _consumer_components(
    candidate: MatchCandidate, behavior_score: float | None
) -> dict[str, float | None]:
    features = candidate.features
    return {
        "goal": features.get("goal_match"),
        "category": features.get("category_match"),
        "sensory": features.get("sensory_match"),
        "price": features.get("price_match"),
        "alcohol": features.get("alcohol_match"),
        "service": features.get("service_match"),
        "usage": features.get("usage_feature_match"),
        "behavior": behavior_score,
        "trust": features.get("data_trust"),
    }


def _buyer_components(candidate: MatchCandidate) -> dict[str, float | None]:
    features = candidate.features
    return {
        "business_goal": features.get("business_goal_match"),
        "product": features.get("product_match"),
        "channel": features.get("channel_match"),
        "price": features.get("price_match"),
        "moq": features.get("moq_match"),
        "capacity": features.get("capacity_match"),
        "region": features.get("region_match"),
        "cooperation": features.get("cooperation_match"),
        "meeting": features.get("meeting_match"),
        "trust": features.get("trade_trust"),
    }


def _score_confidence(
    policy: ScoringPolicy,
    components: Mapping[str, float | None],
    *,
    profile_completeness: float,
    candidate_trust: float | None,
) -> float:
    coverage = sum(
        float(policy.weights[name])
        for name, value in components.items()
        if value is not None
    )
    profile_confidence = min(max(profile_completeness / 100.0, 0.0), 1.0)
    if candidate_trust is None:
        source_confidence = profile_confidence
    else:
        source_confidence = (profile_confidence + candidate_trust) / 2.0
    return min(max(coverage * source_confidence, 0.0), 1.0)


def _weighted_projection(
    policy: ScoringPolicy,
    components: Mapping[str, float | None],
    names: tuple[str, ...],
) -> float | None:
    present = [name for name in names if components.get(name) is not None]
    if not present:
        return None
    weight_total = sum(float(policy.weights[name]) for name in present)
    return (
        sum(
            float(components[name]) * float(policy.weights[name])
            for name in present
            if components[name] is not None
        )
        / weight_total
    )


def _apply_directional_result(
    candidate: MatchCandidate,
    result: DirectionalScoreResult,
    *,
    policy: ScoringPolicy,
) -> None:
    candidate.filter_evaluation_id = result.eligibility_evaluation_id
    candidate.directional_policy_version = result.policy_version
    candidate.directional_components = {
        key: None if value is None else float(value)
        for key, value in result.component_values.items()
    }
    candidate.directional_effective_weights = {
        key: float(value) for key, value in result.effective_weights.items()
    }
    candidate.directional_contributions = {
        key: float(value) for key, value in result.contributions.items()
    }
    candidate.directional_missing_components = result.missing_components
    candidate.directional_confidence = (
        None if result.confidence is None else float(result.confidence)
    )
    candidate.directional_grade = result.grade
    candidate.directional_score_fingerprint = result.calculation_fingerprint

    # The existing persistence projection stores normalized values in [0, 1].
    # Exact 0..100 policy results remain reproducible through the fields above.
    candidate.raw_score = float(result.uncapped_score) / 100.0
    candidate.normalized_score = float(result.final_score) / 100.0
    candidate.final_score = candidate.normalized_score

    components = candidate.directional_components
    if policy is CONSUMER_SCORE_V1:
        preference_names = (
            "category",
            "sensory",
            "price",
            "alcohol",
            "service",
            "usage",
        )
        candidate.score_components = {
            "preference_score": _weighted_projection(
                policy, components, preference_names
            ),
            "goal_score": components.get("goal"),
            "trade_score": None,
            "context_score": None,
            "behavior_score": components.get("behavior"),
            "trust_score": components.get("trust"),
        }
    else:
        trade_names = (
            "channel",
            "price",
            "moq",
            "capacity",
            "region",
            "cooperation",
            "meeting",
        )
        candidate.score_components = {
            "preference_score": components.get("product"),
            "goal_score": components.get("business_goal"),
            "trade_score": _weighted_projection(policy, components, trade_names),
            "context_score": None,
            "behavior_score": None,
            "trust_score": components.get("trust"),
        }


def score_candidate(
    candidate: MatchCandidate,
    *,
    profile: ResolvedProfile,
    eligibility: EligibilityDecision,
    behavior_score: float | None = None,
) -> DirectionalScoreResult:
    """Score one already-eligible candidate and attach full provenance."""

    if candidate.filter_evaluation_id not in (
        None,
        eligibility.evaluation_id,
    ):
        raise ScoreValidationError(
            "candidate filter_evaluation_id does not match the scoring request"
        )

    if profile.user_type == "BUYER":
        policy = BUYER_SCORE_V1
        components = _buyer_components(candidate)
        candidate_trust = candidate.features.get("trade_trust")
    else:
        policy = CONSUMER_SCORE_V1
        components = _consumer_components(candidate, behavior_score)
        candidate_trust = candidate.features.get("data_trust")

    confidence = _score_confidence(
        policy,
        components,
        profile_completeness=profile.completeness,
        candidate_trust=candidate_trust,
    )
    engine_result = execute_directional_score(
        candidate_id=str(candidate.public_object_id or candidate.object_id),
        exhibitor_id=str(candidate.exhibitor_id),
        mode=(
            MatchingMode.BUYER_TO_EXHIBITOR
            if policy is BUYER_SCORE_V1
            else MatchingMode.GENERAL_VISITOR
        ),
        components=components,
        eligibility=eligibility,
        confidence=confidence,
    )
    result = engine_result.directional_result
    if result is None:
        raise ScoreValidationError("directional engine result is missing provenance")
    _apply_directional_result(candidate, result, policy=policy)
    return result


async def score_candidates(
    db: AsyncSession,
    candidates: list[MatchCandidate],
    *,
    profile: ResolvedProfile,
    eligibility_evaluation_id: str,
) -> None:
    """Score a batch admitted by one immutable stage-10 evaluation."""

    if not eligibility_evaluation_id.strip():
        raise ScoreValidationError("eligibility_evaluation_id is required")

    inferred: Mapping[str, tuple[float, float]] = {}
    catalog: Catalog | None = None
    if profile.user_type != "BUYER":
        inferred = await _load_inferred_preferences(db, profile.profile_id)
        catalog = get_catalog()

    eligibility = EligibilityDecision(
        passed=True,
        evaluation_id=eligibility_evaluation_id,
    )
    for candidate in candidates:
        behavior = (
            _behavior_score(candidate, inferred, catalog)
            if catalog is not None
            else None
        )
        score_candidate(
            candidate,
            profile=profile,
            eligibility=eligibility,
            behavior_score=behavior,
        )
