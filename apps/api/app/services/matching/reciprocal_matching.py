"""Stage 13 exhibitor-direction and reciprocal B2B scoring adapter."""

from __future__ import annotations

from collections.abc import Mapping

from app.services.matching.engine_adapter import execute_reciprocal_score
from app.services.matching.types import MatchCandidate, ResolvedProfile
from meet_ai.scoring import (
    EXHIBITOR_SCORE_V1,
    DirectionalScoreResult,
    EligibilityDecision,
    ScoreCap,
    ScoreValidationError,
)

_RECIPROCAL_OBJECT_TYPES = ("EXHIBITOR", "BOOTH", "PRODUCT")


def _exhibitor_components(candidate: MatchCandidate) -> dict[str, float | None]:
    features = candidate.features
    return {
        "buyer_type": features.get("buyer_type_match"),
        "channel": features.get("preferred_channel_match"),
        "order_volume": features.get("order_volume_match"),
        "region": features.get("preferred_region_match"),
        "trade_type": features.get("trade_type_match"),
        "portfolio": features.get("portfolio_match"),
        "decision_timing": features.get("decision_timing_match"),
        "verification": features.get("buyer_verification"),
        "meeting_readiness": features.get("meeting_readiness"),
    }


def _confidence(
    components: Mapping[str, float | None],
    *,
    profile_completeness: float,
    preference_profile_available: bool,
) -> float:
    coverage = sum(
        float(EXHIBITOR_SCORE_V1.weights[name])
        for name, value in components.items()
        if value is not None
    )
    profile_confidence = min(max(profile_completeness / 100.0, 0.0), 1.0)
    preference_factor = 1.0 if preference_profile_available else 0.7
    return min(max(coverage * profile_confidence * preference_factor, 0.0), 1.0)


def _directional_caps(
    components: Mapping[str, float | None],
) -> tuple[ScoreCap, ...]:
    caps: list[ScoreCap] = []
    present = [name for name, value in components.items() if value is not None]
    if present == ["buyer_type"]:
        caps.append(ScoreCap("BUYER_TYPE_ONLY", 60))
    if components.get("channel") is None and components.get("order_volume") is None:
        caps.append(ScoreCap("CHANNEL_AND_ORDER_VOLUME_MISSING", 65))
    if components.get("verification") is None:
        caps.append(ScoreCap("COMPANY_VERIFICATION_MISSING", 75))
    if components.get("decision_timing") is None:
        caps.append(ScoreCap("DECISION_TIMING_MISSING", 85))
    if components.get("order_volume") is None:
        caps.append(ScoreCap("ORDER_VOLUME_MISSING", 75))
    return tuple(caps)


def _attach_exhibitor_result(
    candidate: MatchCandidate, result: DirectionalScoreResult
) -> None:
    candidate.exhibitor_directional_policy_version = result.policy_version
    candidate.exhibitor_directional_components = {
        key: None if value is None else float(value)
        for key, value in result.component_values.items()
    }
    candidate.exhibitor_directional_effective_weights = {
        key: float(value) for key, value in result.effective_weights.items()
    }
    candidate.exhibitor_directional_contributions = {
        key: float(value) for key, value in result.contributions.items()
    }
    candidate.exhibitor_directional_missing_components = result.missing_components
    candidate.exhibitor_directional_confidence = (
        None if result.confidence is None else float(result.confidence)
    )
    candidate.exhibitor_directional_score_fingerprint = result.calculation_fingerprint


def apply_reciprocal_matching(
    candidates: list[MatchCandidate], *, profile: ResolvedProfile
) -> None:
    """Apply the published harmonic-mean reciprocal policy in place."""

    if profile.user_type != "BUYER":
        return

    for candidate in candidates:
        if candidate.object_type not in _RECIPROCAL_OBJECT_TYPES:
            continue
        if not candidate.filter_evaluation_id:
            raise ScoreValidationError(
                "reciprocal scoring requires filter_evaluation_id"
            )
        if candidate.directional_policy_version is None:
            raise ScoreValidationError(
                "buyer-to-exhibitor score must be calculated first"
            )

        eligibility = EligibilityDecision(
            passed=True,
            evaluation_id=candidate.filter_evaluation_id,
        )
        components = _exhibitor_components(candidate)
        preference_profile_available = bool(
            candidate.features.get("exhibitor_preference_available")
        )
        exhibitor_confidence = _confidence(
            components,
            profile_completeness=profile.completeness,
            preference_profile_available=preference_profile_available,
        )
        buyer_confidence = candidate.directional_confidence
        if buyer_confidence is None:
            raise ScoreValidationError(
                "buyer-to-exhibitor score confidence is required"
            )

        acceptance_capacity = candidate.features.get("acceptance_capacity")
        if acceptance_capacity is None:
            acceptance_capacity = 0.5

        reciprocal_caps: tuple[ScoreCap, ...] = ()
        if not preference_profile_available:
            reciprocal_caps = (ScoreCap("EXHIBITOR_PREFERENCE_UNCONFIRMED", 80),)

        engine_result = execute_reciprocal_score(
            candidate_id=str(candidate.public_object_id or candidate.object_id),
            exhibitor_id=str(candidate.exhibitor_id),
            buyer_components=candidate.directional_components,
            exhibitor_components=components,
            buyer_confidence=buyer_confidence,
            exhibitor_confidence=exhibitor_confidence,
            acceptance_capacity_score=acceptance_capacity,
            eligibility=eligibility,
            exhibitor_caps=_directional_caps(components),
            score_caps=reciprocal_caps,
        )
        exhibitor_result = engine_result.exhibitor_directional_result
        reciprocal = engine_result.reciprocal_result
        if exhibitor_result is None or reciprocal is None:
            raise ScoreValidationError("reciprocal engine result is missing provenance")
        _attach_exhibitor_result(candidate, exhibitor_result)

        candidate.buyer_to_exhibitor = float(reciprocal.buyer_to_exhibitor_score)
        candidate.exhibitor_to_buyer = float(reciprocal.exhibitor_to_buyer_score)
        candidate.reciprocal_score = float(reciprocal.final_reciprocal_score)
        candidate.reciprocal_capped = bool(reciprocal.applied_cap_codes)
        candidate.reciprocal_policy_version = reciprocal.policy_version
        candidate.reciprocal_base_score = float(reciprocal.reciprocal_base_score)
        candidate.minimum_direction_score = float(reciprocal.minimum_direction_score)
        candidate.minimum_direction_cap = (
            None
            if reciprocal.minimum_direction_cap is None
            else float(reciprocal.minimum_direction_cap)
        )
        candidate.imbalance_value = float(reciprocal.imbalance_value)
        candidate.imbalance_penalty = float(reciprocal.imbalance_penalty)
        candidate.confidence_adjustment = float(reciprocal.confidence_adjustment)
        candidate.acceptance_capacity_score = float(
            reciprocal.acceptance_capacity_score
        )
        candidate.acceptance_adjustment = float(reciprocal.acceptance_adjustment)
        candidate.reciprocal_grade = reciprocal.grade
        candidate.reciprocal_status = reciprocal.match_status
        candidate.reciprocal_recommended_action = reciprocal.recommended_action
        candidate.reciprocal_score_fingerprint = reciprocal.calculation_fingerprint
        candidate.reciprocal_applied_cap_codes = reciprocal.applied_cap_codes

        candidate.raw_score = float(reciprocal.uncapped_final_score) / 100.0
        candidate.normalized_score = float(reciprocal.final_reciprocal_score) / 100.0
        candidate.final_score = candidate.normalized_score
        candidate.score_components["trade_score"] = candidate.normalized_score
