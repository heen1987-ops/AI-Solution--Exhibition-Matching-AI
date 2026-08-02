from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.services.matching.cold_start_policy import (
    ColdStartEvidence,
    apply_cold_start_annotations,
    bayesian_rate,
    evaluate_cold_start,
    question_information_gain,
)
from app.services.matching.types import MatchCandidate, ResolvedProfile, TaxonomyItem


def _profile(*, user_type: str = "GENERAL_VISITOR", completeness: float = 20) -> ResolvedProfile:
    return ResolvedProfile(
        profile_id=uuid.uuid4(),
        profile_version=1,
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


def _candidate(*, category: str, created_at: datetime | None = None) -> MatchCandidate:
    object_id = uuid.uuid4()
    return MatchCandidate(
        object_type="PRODUCT",
        object_id=object_id,
        recommendable_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        participation_id=uuid.uuid4(),
        public_object_id=str(object_id),
        source_channels={"CATEGORY"},
        payload={
            "category_code": category,
            "product_name": f"{category} product",
            "event_price_amount": 30_000,
            "taste_json": {"DRY": 0.8},
            "created_at": created_at,
            "participation_status": "APPROVED",
            "master_approval_status": "APPROVED",
            "consultation_enabled": True,
            "operating_status": "OPEN",
            "supply_profile": {
                "approval_status": "APPROVED",
                "data_trust_score": 0.9,
                "trade_readiness_score": 90,
            },
        },
        final_score=0.8,
        context_blended_score=0.8,
        directional_confidence=0.9,
        features={"novelty_score": 0.7},
    )


def test_new_visitor_uses_bounded_confidence_and_exploration() -> None:
    decision = evaluate_cold_start(_profile())

    assert decision.state == "COLD"
    assert decision.exploration_ratio == 0.25
    assert decision.recommendation_confidence_cap == 0.60
    assert "COLD.NEW_USER" in decision.type_codes
    assert decision.next_question_codes[0] == "VISIT_GOAL"


def test_stable_visitor_removes_confidence_cap() -> None:
    profile = _profile(completeness=90)
    profile.categories.append(TaxonomyItem("ALCOHOL.DISTILLED", "PREFERRED", 0.9))
    evidence = ColdStartEvidence(
        explicit_signal_count=5,
        valid_behavior_count=8,
        feedback_count=2,
        average_confidence=0.9,
    )

    decision = evaluate_cold_start(profile, evidence)

    assert decision.state == "STABLE"
    assert decision.recommendation_confidence_cap is None
    assert decision.exploration_ratio == 0.075


def test_buyer_exploration_never_exceeds_ten_percent() -> None:
    decision = evaluate_cold_start(_profile(user_type="BUYER"))

    assert decision.state == "COLD"
    assert decision.exploration_ratio == 0.10
    assert "COLD.UNVERIFIED" in decision.type_codes


def test_annotations_preserve_relevance_and_hash_final_learning_slot() -> None:
    now = datetime(2026, 8, 2, 12, tzinfo=UTC)
    candidates = [
        _candidate(category="TAKJU", created_at=now - timedelta(days=2)),
        _candidate(category="YAKJU"),
        _candidate(category="DISTILLED"),
        _candidate(category="FRUIT"),
        _candidate(category="TAKJU_ALT"),
        _candidate(category="YAKJU_ALT"),
        _candidate(category="DISTILLED_ALT"),
        _candidate(category="FRUIT_ALT"),
    ]
    before = [item.final_score for item in candidates]
    profile = _profile()
    decision = evaluate_cold_start(profile)

    apply_cold_start_annotations(
        candidates,
        profile=profile,
        decision=decision,
        server_time=now,
    )

    assert [item.final_score for item in candidates] == before
    assert all(item.cold_start_input_fingerprint for item in candidates)
    assert candidates[0].recommendation_confidence == 0.60
    assert "COLD_START_QUALITY" in candidates[0].source_channels
    learning = [
        item for item in candidates if "PREFERENCE_LEARNING_SLOT" in item.cold_start_reason_codes
    ]
    assert len(learning) == 1


def test_question_information_gain_detects_candidate_separation() -> None:
    candidates = [_candidate(category="TAKJU"), _candidate(category="DISTILLED")]

    assert question_information_gain(candidates, "PRODUCT_CATEGORY") == 1.0
    assert question_information_gain(candidates, "AVAILABLE_MINUTES") == 0.0


def test_bayesian_rate_validates_observations() -> None:
    assert bayesian_rate(
        prior_mean=0.5,
        prior_count=2,
        successes=3,
        observations=4,
    ) == pytest.approx(2 / 3)
    with pytest.raises(ValueError):
        bayesian_rate(
            prior_mean=0.5,
            prior_count=1,
            successes=2,
            observations=1,
        )
