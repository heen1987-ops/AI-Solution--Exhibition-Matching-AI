from __future__ import annotations

from datetime import UTC, datetime

import pytest
from app.services.learning_policy import (
    AttributeTarget,
    BehaviorEventFacts,
    evaluate_behavior,
    progressive_update,
    reward_value,
)

NOW = datetime(2026, 8, 2, 12, tzinfo=UTC)


def _facts(**overrides: object) -> BehaviorEventFacts:
    values: dict[str, object] = {
        "event_id": "evt-1",
        "event_type": "RECOMMENDATION_SAVED",
        "user_type": "GENERAL_VISITOR",
        "occurred_at": NOW,
        "received_at": NOW,
        "learning_consent": True,
        "attribute_targets": (AttributeTarget("TASTE.DRY", "TASTE", 0.35),),
    }
    values.update(overrides)
    return BehaviorEventFacts(**values)  # type: ignore[arg-type]


def test_learning_requires_consent() -> None:
    decision = evaluate_behavior(_facts(learning_consent=False), now=NOW)

    assert decision.validation_status == "INVALID"
    assert decision.profile_update_required is False
    assert "LEARNING_CONSENT_MISSING" in decision.invalid_reason_codes


def test_explicit_preference_is_never_overwritten_automatically() -> None:
    decision = evaluate_behavior(
        _facts(explicit_attribute_codes=frozenset({"TASTE.DRY"})),
        now=NOW,
    )

    assert decision.validation_status == "VALID"
    assert decision.profile_update_required is False
    assert decision.adjustments[0].application_status == "CONFIRMATION_REQUIRED"
    assert decision.adjustments[0].reason_code == "EXPLICIT_INPUT_CONFLICT"


def test_operational_feedback_refreshes_without_changing_taste() -> None:
    decision = evaluate_behavior(
        _facts(
            event_type="FEEDBACK.IRRELEVANT",
            cause_code="CONGESTION",
        ),
        now=NOW,
    )

    assert decision.signal_type == "NEGATIVE"
    assert decision.cause_scope == "SESSION_CONTEXT"
    assert decision.adjustments == ()
    assert decision.profile_update_required is False
    assert decision.recommendation_refresh_required is True


def test_neutral_tasting_does_not_create_a_preference() -> None:
    decision = evaluate_behavior(
        _facts(event_type="FIELD.TASTING", cause_code=None),
        now=NOW,
    )

    assert decision.signal_type == "NEUTRAL"
    assert decision.adjustments == ()


def test_buyer_adjustment_obeys_single_event_cap() -> None:
    decision = evaluate_behavior(
        _facts(
            event_type="B2B.QUALIFIED_LEAD",
            user_type="BUYER",
            attribute_targets=(AttributeTarget("CHANNEL.BOTTLE_SHOP", "EXHIBITOR", 1.0),),
            independent_evidence_count=20,
        ),
        now=NOW,
    )

    assert decision.profile_update_required is True
    assert decision.adjustments[0].adjustment == pytest.approx(0.05)


def test_progressive_update_and_reward_stay_bounded() -> None:
    assert progressive_update(0.5, 1.0, 0.2) == pytest.approx(0.6)
    assert reward_value("GENERAL_VISITOR", {"purchase": 10}) == 1.0
