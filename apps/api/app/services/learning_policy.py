"""Pure stage-17 behavior interpretation and bounded profile learning policy."""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

LEARNING_POLICY_VERSION = "behavior-learning-policy-v1.0"

VISITOR_SIGNALS: dict[str, float] = {
    "VIEW.IMPRESSION": 0.00,
    "VIEW.CLICK": 0.08,
    "VIEW.DETAIL": 0.12,
    "VIEW.LONG_READ": 0.18,
    "VIEW.COMPARE": 0.28,
    "INTENT.FAVORITE": 0.45,
    "INTENT.ROUTE_ADD": 0.55,
    "FIELD.CHECK_IN": 0.65,
    "FIELD.TASTING": 0.00,
    "FIELD.PURCHASE": 0.95,
    "FEEDBACK.RELEVANT": 1.00,
    "VIEW.DISMISS": -0.08,
    "FIELD.SKIP": -0.12,
    "FEEDBACK.IRRELEVANT": -0.90,
}

BUYER_SIGNALS: dict[str, float] = {
    "VIEW.DETAIL": 0.10,
    "B2B.COMPARE": 0.20,
    "B2B.TRADE_TERM_VIEW": 0.25,
    "INTENT.FAVORITE": 0.35,
    "B2B.MEETING_VIEW": 0.45,
    "B2B.MEETING_REQUEST": 0.65,
    "B2B.MEETING_ACCEPT": 0.75,
    "B2B.MEETING_COMPLETE": 0.85,
    "B2B.SAMPLE_REQUEST": 0.88,
    "B2B.QUOTE_REQUEST": 0.92,
    "B2B.QUALIFIED_LEAD": 1.00,
    "B2B.FOLLOW_UP": 1.00,
    "B2B.MEETING_CANCEL": -0.25,
    "B2B.MEETING_REJECT": -0.40,
    "B2B.CONDITION_MISMATCH": -0.80,
    "B2B.SPAM_CONFIRMED": -1.00,
}

ALIASES = {
    "RECOMMENDATION_IMPRESSION": "VIEW.IMPRESSION",
    "RECOMMENDATION_OPENED": "VIEW.DETAIL",
    "RECOMMENDATION_SAVED": "INTENT.FAVORITE",
    "RECOMMENDATION_DISMISSED": "VIEW.DISMISS",
    "BOOTH_CHECKED_IN": "FIELD.CHECK_IN",
    "MEETING_REQUESTED": "B2B.MEETING_REQUEST",
}

PROPAGATION = {
    "GENERAL_VISITOR": {
        "PRODUCT": 1.00,
        "EXHIBITOR": 0.15,
        "CATEGORY": 0.45,
        "TASTE": 0.35,
        "INGREDIENT": 0.20,
        "PRICE": 0.18,
        "USAGE": 0.30,
        "REGION": 0.10,
    },
    "BUYER": {
        "EXHIBITOR": 1.00,
        "PRODUCT": 0.60,
        "CHANNEL": 0.35,
        "TRADE_TYPE": 0.40,
        "MOQ": 0.30,
        "REGION": 0.25,
        "COOPERATION": 0.35,
        "CAPACITY": 0.20,
    },
}

CAUSE_SCOPE = {
    "TASTE": "LONG_TERM_PREFERENCE",
    "ALCOHOL": "LONG_TERM_PREFERENCE",
    "PRICE": "PRICE_PREFERENCE",
    "CONGESTION": "SESSION_CONTEXT",
    "DISTANCE": "SESSION_CONTEXT",
    "OUT_OF_STOCK": "OPERATIONAL_STATE",
    "SCHEDULE_CONFLICT": "SESSION_CONTEXT",
    "INFORMATION": "DATA_QUALITY",
    "TRUST": "DATA_QUALITY",
    "MOQ": "PAIRWISE_TRADE_FIT",
    "CHANNEL": "PAIRWISE_TRADE_FIT",
    "SUPPLY_REGION": "PAIRWISE_TRADE_FIT",
    "NEW_TRADES_PAUSED": "EXHIBITOR_ACCEPTANCE",
    "BUYER_UNVERIFIED": "BUYER_TRUST",
    "NO_RESPONSE": "CONSULTATION_OPERATIONS",
}

LEARNING_POLICY_CONFIG: dict[str, Any] = {
    "visitor_signals": VISITOR_SIGNALS,
    "buyer_signals": BUYER_SIGNALS,
    "propagation": PROPAGATION,
    "single_update_cap": {"GENERAL_VISITOR": 0.10, "BUYER": 0.05},
    "daily_automatic_cap": 0.20,
    "personal_weight_caps": {"single": 0.02, "session": 0.08, "long_term": 0.15},
    "tasting_without_feedback": "NEUTRAL_EXPERIENCE",
    "non_response": "EXPOSURE_POLICY_ONLY",
    "explicit_input_precedence": True,
    "position_propensity_floor": 0.20,
    "consent_required": True,
    "global_policy_online_update": False,
}


@dataclass(frozen=True)
class AttributeTarget:
    code: str
    target_level: str
    propagation_weight: float


@dataclass(frozen=True)
class BehaviorEventFacts:
    event_id: str
    event_type: str
    user_type: str
    occurred_at: datetime
    received_at: datetime
    cause_code: str | None = None
    attribute_targets: tuple[AttributeTarget, ...] = ()
    learning_consent: bool = False
    actual_impression: bool = True
    duplicate: bool = False
    is_bot: bool = False
    is_employee: bool = False
    is_test: bool = False
    is_advertising: bool = False
    repeat_count: int = 1
    independent_evidence_count: int = 1
    position_propensity: float | None = None
    explicit_attribute_codes: frozenset[str] = frozenset()
    context: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AttributeAdjustment:
    attribute_code: str
    target_level: str
    adjustment: float
    confidence: float
    application_status: str
    reason_code: str


@dataclass(frozen=True)
class BehaviorDecision:
    validation_status: str
    signal_type: str
    signal_strength: float
    decayed_signal: float
    cause_code: str | None
    cause_scope: str
    profile_update_required: bool
    recommendation_refresh_required: bool
    processing_mode: str
    adjustments: tuple[AttributeAdjustment, ...]
    invalid_reason_codes: tuple[str, ...]
    policy_version: str
    input_fingerprint: str


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return min(max(float(value), low), high)


def _fingerprint(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(payload).hexdigest()


def canonical_event_type(event_type: str) -> str:
    return ALIASES.get(event_type, event_type)


def repeated_evidence_confidence(count: int, sensitivity: float = 0.30) -> float:
    return 1.0 - math.exp(-sensitivity * max(0, count))


def decay_signal(signal: float, *, age_hours: float, event_type: str) -> float:
    event_type = canonical_event_type(event_type)
    if event_type in ("FEEDBACK.RELEVANT", "FEEDBACK.IRRELEVANT", "FIELD.PURCHASE", "B2B.DEAL_CLOSED"):
        half_life_hours = 24 * 180
    elif event_type.startswith("B2B.MEETING") or event_type in ("INTENT.FAVORITE", "FIELD.CHECK_IN"):
        half_life_hours = 24 * 30
    else:
        half_life_hours = 24 * 3
    return signal * math.exp(-math.log(2) * max(age_hours, 0.0) / half_life_hours)


def _base_signal(facts: BehaviorEventFacts) -> float | None:
    event_type = canonical_event_type(facts.event_type)
    table = BUYER_SIGNALS if facts.user_type == "BUYER" else VISITOR_SIGNALS
    signal = table.get(event_type)
    if event_type == "FIELD.TASTING":
        if facts.cause_code in ("TASTE_POSITIVE", "FEEDBACK.RELEVANT"):
            return 0.90
        if facts.cause_code in ("TASTE_NEGATIVE", "FEEDBACK.IRRELEVANT", "TASTE"):
            return -0.90
        return 0.0
    return signal


def _invalid_reasons(facts: BehaviorEventFacts) -> tuple[str, ...]:
    reasons: list[str] = []
    if not facts.learning_consent:
        reasons.append("LEARNING_CONSENT_MISSING")
    if facts.duplicate:
        reasons.append("DUPLICATE_EVENT")
    if facts.is_bot:
        reasons.append("BOT_TRAFFIC")
    if facts.is_employee:
        reasons.append("EMPLOYEE_ACTIVITY")
    if facts.is_test:
        reasons.append("TEST_ACTIVITY")
    if facts.is_advertising:
        reasons.append("ADVERTISING_EXPOSURE")
    if canonical_event_type(facts.event_type) in ("VIEW.CLICK", "VIEW.DETAIL") and not facts.actual_impression:
        reasons.append("UNVERIFIED_IMPRESSION")
    if facts.occurred_at > facts.received_at:
        reasons.append("OCCURRED_AFTER_RECEIVED")
    return tuple(reasons)


def _processing_mode(event_type: str, signal: float, cause_scope: str) -> str:
    if event_type in ("FEEDBACK.IRRELEVANT", "FIELD.PURCHASE") or abs(signal) >= 0.90:
        return "IMMEDIATE"
    if event_type in (
        "INTENT.FAVORITE",
        "VIEW.COMPARE",
        "INTENT.ROUTE_ADD",
        "FIELD.CHECK_IN",
        "FIELD.TASTING",
        "B2B.MEETING_REQUEST",
        "B2B.SAMPLE_REQUEST",
    ):
        return "NEAR_REAL_TIME"
    if cause_scope in ("LONG_TERM_PREFERENCE", "PRICE_PREFERENCE"):
        return "BATCH"
    return "NO_PROFILE_UPDATE"


def evaluate_behavior(facts: BehaviorEventFacts, *, now: datetime | None = None) -> BehaviorDecision:
    now = now or datetime.now(UTC)
    invalid = _invalid_reasons(facts)
    event_type = canonical_event_type(facts.event_type)
    signal = _base_signal(facts)
    input_data = {**facts.__dict__, "event_type": event_type, "policy_version": LEARNING_POLICY_VERSION}
    fingerprint = _fingerprint(input_data)
    if invalid or signal is None:
        if signal is None:
            invalid = (*invalid, "UNSUPPORTED_EVENT_TYPE")
        return BehaviorDecision(
            "INVALID",
            "NEUTRAL",
            0.0,
            0.0,
            facts.cause_code,
            "NONE",
            False,
            False,
            "NO_PROFILE_UPDATE",
            (),
            invalid,
            LEARNING_POLICY_VERSION,
            fingerprint,
        )

    cause_scope = CAUSE_SCOPE.get(facts.cause_code or "", "TARGET_INTEREST")
    age_hours = max(0.0, (now - facts.occurred_at).total_seconds() / 3600)
    decayed = decay_signal(signal, age_hours=age_hours, event_type=event_type)
    repeat_confidence = repeated_evidence_confidence(facts.independent_evidence_count)
    propensity = facts.position_propensity
    if propensity is not None and event_type in ("VIEW.CLICK", "VIEW.DETAIL"):
        propensity = max(propensity, LEARNING_POLICY_CONFIG["position_propensity_floor"])
        decayed = _clamp(decayed / propensity)

    # Context/operations/data-quality causes must never leak into taste/category.
    profile_scopes = {"LONG_TERM_PREFERENCE", "PRICE_PREFERENCE", "TARGET_INTEREST", "PAIRWISE_TRADE_FIT"}
    updates_allowed = cause_scope in profile_scopes and signal != 0
    cap = LEARNING_POLICY_CONFIG["single_update_cap"][facts.user_type]
    adjustments: list[AttributeAdjustment] = []
    if updates_allowed:
        for target in facts.attribute_targets:
            propagation_cap = PROPAGATION[facts.user_type].get(target.target_level, 0.0)
            if propagation_cap <= 0:
                continue
            adjustment = _clamp(
                decayed * min(target.propagation_weight, propagation_cap) * max(repeat_confidence, 0.25),
                -cap,
                cap,
            )
            conflict = target.code in facts.explicit_attribute_codes
            adjustments.append(
                AttributeAdjustment(
                    attribute_code=target.code,
                    target_level=target.target_level,
                    adjustment=adjustment,
                    confidence=repeat_confidence,
                    application_status="CONFIRMATION_REQUIRED" if conflict else "APPLY_CANDIDATE",
                    reason_code="EXPLICIT_INPUT_CONFLICT" if conflict else "BOUNDED_BEHAVIOR_EVIDENCE",
                )
            )

    refresh = (
        event_type
        in {
            "FEEDBACK.IRRELEVANT",
            "FIELD.PURCHASE",
            "FIELD.CHECK_IN",
            "INTENT.FAVORITE",
            "VIEW.COMPARE",
            "INTENT.ROUTE_ADD",
            "B2B.MEETING_REJECT",
            "B2B.MEETING_REQUEST",
            "B2B.SAMPLE_REQUEST",
        }
        or bool(adjustments)
    )
    return BehaviorDecision(
        validation_status="VALID",
        signal_type="POSITIVE" if signal > 0 else "NEGATIVE" if signal < 0 else "NEUTRAL",
        signal_strength=signal,
        decayed_signal=decayed,
        cause_code=facts.cause_code,
        cause_scope=cause_scope,
        profile_update_required=any(item.application_status == "APPLY_CANDIDATE" for item in adjustments),
        recommendation_refresh_required=refresh,
        processing_mode=_processing_mode(event_type, signal, cause_scope),
        adjustments=tuple(adjustments),
        invalid_reason_codes=(),
        policy_version=LEARNING_POLICY_VERSION,
        input_fingerprint=fingerprint,
    )


def progressive_update(old_value: float, evidence: float, alpha: float) -> float:
    if not 0 <= alpha <= 1:
        raise ValueError("alpha must be in [0, 1]")
    proposed = old_value * (1 - alpha) + evidence * alpha
    return _clamp(proposed, -1.0, 1.0)


def reward_value(user_type: str, outcomes: dict[str, float]) -> float:
    weights = (
        {"click": 0.10, "save": 0.20, "visit": 0.25, "tasting": 0.15, "purchase": 0.20, "positive_feedback": 0.10}
        if user_type == "GENERAL_VISITOR"
        else {"detail_view": 0.10, "compare": 0.15, "meeting_request": 0.20, "meeting_complete": 0.20, "qualified_lead": 0.15, "follow_up": 0.20}
    )
    return _clamp(sum(weights[key] * float(outcomes.get(key, 0.0)) for key in weights))
