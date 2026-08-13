from __future__ import annotations

import uuid

import pytest
from meet_ai.scoring import EligibilityDecision, ScoreValidationError

from app.services.matching.base_scoring import score_candidate
from app.services.matching.reciprocal_matching import apply_reciprocal_matching
from app.services.matching.types import MatchCandidate, ResolvedProfile


def _profile(user_type: str, *, completeness: float = 90.0) -> ResolvedProfile:
    return ResolvedProfile(
        profile_id=uuid.uuid4(),
        profile_version=3,
        profile_version_id=uuid.uuid4(),
        user_type=user_type,
        completeness=completeness,
        goals=[],
        categories=[],
        channels=[],
        regions=[],
        taste=[],
        aroma=[],
        extra={},
        numeric_conditions={},
        raw_context={},
    )


def _candidate(features: dict[str, float | None]) -> MatchCandidate:
    object_id = uuid.uuid4()
    return MatchCandidate(
        object_type="PRODUCT",
        object_id=object_id,
        recommendable_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        participation_id=uuid.uuid4(),
        public_object_id=str(object_id),
        features=features,
    )


def test_consumer_adapter_renormalizes_missing_components() -> None:
    candidate = _candidate(
        {
            "goal_match": 1.0,
            "category_match": 0.8,
            "sensory_match": None,
            "price_match": 0.0,
            "alcohol_match": None,
            "service_match": 1.0,
            "usage_feature_match": 0.6,
            "data_trust": 0.9,
        }
    )

    result = score_candidate(
        candidate,
        profile=_profile("GENERAL_VISITOR"),
        eligibility=EligibilityDecision(True, "filter-eval-001"),
    )

    assert result.policy_version == "consumer-score-v1.0"
    assert set(result.missing_components) == {"sensory", "alcohol", "behavior"}
    assert result.component_values["price"] == 0
    assert sum(result.effective_weights.values()) == 1
    assert candidate.filter_evaluation_id == "filter-eval-001"
    assert candidate.directional_score_fingerprint
    assert candidate.normalized_score == pytest.approx(
        float(result.final_score) / 100.0
    )


def test_buyer_adapter_uses_harmonic_reciprocal_policy() -> None:
    candidate = _candidate(
        {
            "business_goal_match": 0.90,
            "product_match": 0.95,
            "channel_match": 1.0,
            "price_match": 0.80,
            "moq_match": 1.0,
            "capacity_match": 0.85,
            "region_match": 1.0,
            "cooperation_match": 0.75,
            "meeting_match": 0.90,
            "trade_trust": 0.92,
            "buyer_type_match": 0.90,
            "preferred_channel_match": 0.95,
            "order_volume_match": 0.85,
            "preferred_region_match": 1.0,
            "trade_type_match": 0.80,
            "portfolio_match": 0.90,
            "decision_timing_match": 0.80,
            "buyer_verification": 0.90,
            "meeting_readiness": 0.75,
            "exhibitor_preference_available": 1.0,
            "acceptance_capacity": 0.90,
        }
    )
    profile = _profile("BUYER", completeness=95.0)

    score_candidate(
        candidate,
        profile=profile,
        eligibility=EligibilityDecision(True, "filter-eval-002"),
    )
    buyer_score = candidate.normalized_score * 100.0
    apply_reciprocal_matching([candidate], profile=profile)

    assert candidate.directional_policy_version == "buyer-score-v1.0"
    assert candidate.exhibitor_directional_policy_version == ("exhibitor-score-v1.0")
    assert candidate.reciprocal_policy_version == "reciprocal-score-v1.0"
    assert candidate.reciprocal_base_score is not None
    arithmetic_mean = (buyer_score + float(candidate.exhibitor_to_buyer or 0.0)) / 2.0
    assert candidate.reciprocal_base_score <= arithmetic_mean
    assert candidate.reciprocal_score_fingerprint
    assert candidate.normalized_score == pytest.approx(
        float(candidate.reciprocal_score or 0.0) / 100.0
    )


def test_missing_exhibitor_preferences_apply_caps() -> None:
    candidate = _candidate(
        {
            "business_goal_match": 1.0,
            "product_match": 1.0,
            "channel_match": 1.0,
            "price_match": 1.0,
            "moq_match": 1.0,
            "capacity_match": 1.0,
            "region_match": 1.0,
            "cooperation_match": 1.0,
            "meeting_match": 1.0,
            "trade_trust": 1.0,
            "buyer_type_match": 1.0,
            "preferred_channel_match": 1.0,
            "order_volume_match": 1.0,
            "preferred_region_match": 1.0,
            "trade_type_match": 1.0,
            "portfolio_match": 1.0,
            "decision_timing_match": 1.0,
            "buyer_verification": 1.0,
            "meeting_readiness": 1.0,
            "exhibitor_preference_available": 0.0,
            "acceptance_capacity": 1.0,
        }
    )
    profile = _profile("BUYER")

    score_candidate(
        candidate,
        profile=profile,
        eligibility=EligibilityDecision(True, "filter-eval-003"),
    )
    apply_reciprocal_matching([candidate], profile=profile)

    assert "EXHIBITOR_PREFERENCE_UNCONFIRMED" in (
        candidate.reciprocal_applied_cap_codes
    )
    assert candidate.reciprocal_score is not None
    assert candidate.reciprocal_score == 80.0


def test_adapter_rejects_filter_evaluation_mismatch() -> None:
    candidate = _candidate(
        {
            "goal_match": 1.0,
            "category_match": 1.0,
        }
    )
    candidate.filter_evaluation_id = "filter-eval-old"

    with pytest.raises(ScoreValidationError, match="does not match"):
        score_candidate(
            candidate,
            profile=_profile("GENERAL_VISITOR"),
            eligibility=EligibilityDecision(True, "filter-eval-new"),
        )
