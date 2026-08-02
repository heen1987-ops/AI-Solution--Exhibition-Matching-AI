"""Deterministic stage-16 cold-start policy.

Cold-start affects confidence, exploration allocation and progressive questions;
it never fabricates missing preferences or replaces the stage-11~15 relevance
score.  The pure functions in this module are intentionally portable to a PHP
BFF, a Netlify Function or the FastAPI service.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from app.services.matching.types import MatchCandidate, ResolvedProfile

COLD_START_POLICY_VERSION = "cold-start-policy-v1.0"
NEW_ENTITY_WINDOW_DAYS = 30

COLD_START_POLICY_CONFIG: dict[str, Any] = {
    "states": ["COLD", "WARMING", "STABLE", "RESET"],
    "visitor_stable": {
        "profile_completeness": 0.60,
        "valid_behavior_count": 5,
        "average_confidence": 0.70,
    },
    "buyer_stable": {
        "profile_completeness": 0.70,
        "verified": True,
        "valid_consultation_count": 2,
    },
    "exploration_ratio": {
        "COLD": 0.25,
        "WARMING": 0.15,
        "STABLE": 0.075,
        "BUYER_MAX": 0.10,
    },
    "new_exhibitor_quality_weights": {
        "profile_completeness": 0.25,
        "product_data_quality": 0.20,
        "trade_readiness": 0.20,
        "verification": 0.15,
        "consultation_readiness": 0.10,
        "runtime_availability": 0.10,
    },
    "new_exhibitor": {
        "minimum_completeness": 0.70,
        "minimum_relevance": 0.45,
        "max_top10": 1,
    },
    "confidence_caps": {
        "minimum_three_answers": 0.60,
        "five_answers": 0.72,
        "three_behaviors": 0.78,
        "feedback": 0.85,
    },
    "bayesian_prior": {"minimum_count": 1.0},
    "protected_attribute_inference": False,
    "popularity_role": "LAST_RESORT_SUPPLEMENT",
    "bandit_enabled": False,
}


@dataclass(frozen=True)
class ColdStartEvidence:
    explicit_signal_count: int = 0
    valid_behavior_count: int = 0
    detail_view_count: int = 0
    favorite_count: int = 0
    check_in_count: int = 0
    feedback_count: int = 0
    valid_consultation_count: int = 0
    average_confidence: float = 0.0
    verified: bool = False
    reset_requested: bool = False


@dataclass(frozen=True)
class ColdStartDecision:
    state: str
    type_codes: tuple[str, ...]
    stability_score: float
    exploration_ratio: float
    recommendation_confidence_cap: float | None
    next_question_codes: tuple[str, ...]
    policy_version: str
    input_fingerprint: str
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class CandidateColdStartAssessment:
    is_new: bool
    eligible_for_exploration: bool
    quality_score: float | None
    confidence_cap: float | None
    reason_codes: tuple[str, ...]


QUESTION_ORDER: dict[str, tuple[str, ...]] = {
    "GENERAL_VISITOR": (
        "VISIT_GOAL",
        "PRODUCT_CATEGORY",
        "AVAILABLE_MINUTES",
        "PRICE_RANGE",
        "TASTE_PREFERENCE",
        "ALCOHOL_RANGE",
        "SERVICE_INTENT",
        "MOBILITY_PREFERENCE",
    ),
    "BUYER": (
        "BUYER_TYPE",
        "PRODUCT_CATEGORY",
        "CHANNEL",
        "MONTHLY_ORDER_VOLUME",
        "SUPPLY_REGION",
        "TARGET_PRICE",
        "TRADE_TYPE",
        "DECISION_TIMELINE",
        "MEETING_TOPIC",
    ),
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(float(value), low), high)


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def explicit_signal_count(profile: ResolvedProfile) -> int:
    buckets: Iterable[Iterable[Any]] = (
        profile.goals,
        profile.categories,
        profile.channels,
        profile.regions,
        profile.taste,
        profile.aroma,
        *(profile.extra.values()),
    )
    return sum(len(tuple(bucket)) for bucket in buckets) + len(
        profile.numeric_conditions
    )


def average_profile_confidence(profile: ResolvedProfile) -> float:
    values = [float(item.confidence) for item in profile.goals]
    for bucket in (
        profile.categories,
        profile.channels,
        profile.regions,
        profile.taste,
        profile.aroma,
        *(profile.extra.values()),
    ):
        values.extend(float(item.confidence) for item in bucket)
    return sum(values) / len(values) if values else 0.0


def evaluate_cold_start(
    profile: ResolvedProfile,
    evidence: ColdStartEvidence | None = None,
) -> ColdStartDecision:
    evidence = evidence or ColdStartEvidence(
        explicit_signal_count=explicit_signal_count(profile),
        average_confidence=average_profile_confidence(profile),
        verified=float(profile.raw_context.get("buyer_verification") or 0) >= 0.75,
    )
    completeness = _clamp(profile.completeness / 100.0)
    explicit_ratio = _clamp(evidence.explicit_signal_count / (5 if profile.user_type == "BUYER" else 4))
    behavior_ratio = _clamp(evidence.valid_behavior_count / 5)
    feedback_ratio = _clamp(evidence.feedback_count / 2)
    consistency = _clamp(float(profile.raw_context.get("preference_consistency", 0.5)))
    stability = _clamp(
        0.35 * completeness
        + 0.25 * explicit_ratio
        + 0.20 * behavior_ratio
        + 0.10 * feedback_ratio
        + 0.10 * consistency
    )

    types: list[str] = []
    if evidence.reset_requested:
        state = "RESET"
        types.append("COLD.RESET")
    elif profile.user_type == "BUYER":
        stable = (
            completeness >= 0.70
            and evidence.verified
            and evidence.valid_consultation_count >= 2
        )
        warming = (
            evidence.explicit_signal_count >= 5
            or evidence.verified
            or evidence.detail_view_count >= 3
            or evidence.favorite_count >= 1
        )
        state = "STABLE" if stable else "WARMING" if warming else "COLD"
        if state != "STABLE":
            types.append("COLD.NEW_BUYER")
        if not evidence.verified:
            types.append("COLD.UNVERIFIED")
    else:
        stable = (
            completeness >= 0.60
            and evidence.valid_behavior_count >= 5
            and evidence.average_confidence >= 0.70
        )
        warming = (
            evidence.explicit_signal_count >= 4
            or evidence.favorite_count >= 2
            or evidence.detail_view_count >= 5
            or evidence.check_in_count >= 2
            or evidence.feedback_count >= 2
        )
        state = "STABLE" if stable else "WARMING" if warming else "COLD"
        if state != "STABLE":
            types.append("COLD.NEW_USER")

    if completeness < (0.70 if profile.user_type == "BUYER" else 0.60):
        types.append("COLD.SPARSE_PROFILE")
    if evidence.valid_behavior_count < 5:
        types.append("COLD.SPARSE_BEHAVIOR")

    ratio = COLD_START_POLICY_CONFIG["exploration_ratio"].get(state, 0.25)
    if profile.user_type == "BUYER":
        ratio = min(ratio, COLD_START_POLICY_CONFIG["exploration_ratio"]["BUYER_MAX"])

    cap: float | None
    if state == "STABLE":
        cap = None
    elif evidence.feedback_count:
        cap = 0.85
    elif evidence.valid_behavior_count >= 3:
        cap = 0.78
    elif evidence.explicit_signal_count >= 5:
        cap = 0.72
    else:
        cap = 0.60

    answered = _answered_question_codes(profile)
    next_questions = tuple(
        code for code in QUESTION_ORDER[profile.user_type] if code not in answered
    )[:3]
    input_data = {
        "policy_version": COLD_START_POLICY_VERSION,
        "profile_id": str(profile.profile_id),
        "profile_version": profile.profile_version,
        "user_type": profile.user_type,
        "completeness": completeness,
        "evidence": evidence.__dict__,
    }
    return ColdStartDecision(
        state=state,
        type_codes=tuple(dict.fromkeys(types)),
        stability_score=stability,
        exploration_ratio=float(ratio),
        recommendation_confidence_cap=cap,
        next_question_codes=next_questions,
        policy_version=COLD_START_POLICY_VERSION,
        input_fingerprint=_fingerprint(input_data),
        reason_codes=(
            "MISSING_AWARE",
            "STRUCTURED_SIGNALS_FIRST",
            "POPULARITY_SUPPLEMENT_ONLY",
        ),
    )


def _answered_question_codes(profile: ResolvedProfile) -> set[str]:
    answered: set[str] = set()
    if profile.goals:
        answered.add("VISIT_GOAL")
    if profile.categories:
        answered.add("PRODUCT_CATEGORY")
    if profile.channels:
        answered.add("CHANNEL")
    if profile.regions:
        answered.add("SUPPLY_REGION")
    if profile.taste:
        answered.add("TASTE_PREFERENCE")
    if profile.numeric_conditions:
        answered.update({"PRICE_RANGE", "TARGET_PRICE", "MONTHLY_ORDER_VOLUME"})
    if profile.raw_context.get("remaining_minutes") is not None:
        answered.add("AVAILABLE_MINUTES")
    if profile.raw_context.get("decision_timeline"):
        answered.add("DECISION_TIMELINE")
    if profile.extra.get("business_type"):
        answered.add("BUYER_TYPE")
    if profile.extra.get("meeting_topic"):
        answered.add("MEETING_TOPIC")
    return answered


def question_information_gain(
    candidates: list[MatchCandidate], question_code: str
) -> float:
    """Normalized entropy of the candidate attribute affected by a question."""

    extractors = {
        "PRODUCT_CATEGORY": lambda c: c.payload.get("category_code"),
        "PRICE_RANGE": lambda c: _price_band(c.payload),
        "TARGET_PRICE": lambda c: _price_band(c.payload),
        "TASTE_PREFERENCE": lambda c: next(iter(c.payload.get("taste_json") or {}), None),
        "CHANNEL": lambda c: next(iter(((c.payload.get("supply_profile") or {}).get("trade_profile") or {}).get("channels") or []), None),
        "SUPPLY_REGION": lambda c: next(iter(((c.payload.get("supply_profile") or {}).get("trade_profile") or {}).get("regions") or []), None),
    }
    extractor = extractors.get(question_code)
    if extractor is None or len(candidates) < 2:
        return 0.0
    counts = Counter(value for item in candidates if (value := extractor(item)) is not None)
    total = sum(counts.values())
    if total < 2 or len(counts) < 2:
        return 0.0
    entropy = -sum((count / total) * math.log2(count / total) for count in counts.values())
    return _clamp(entropy / math.log2(len(counts)))


def rank_next_questions(
    decision: ColdStartDecision, candidates: list[MatchCandidate]
) -> list[tuple[str, float]]:
    return sorted(
        (
            (code, question_information_gain(candidates, code))
            for code in decision.next_question_codes
        ),
        key=lambda item: (-item[1], item[0]),
    )


def _price_band(payload: dict[str, Any]) -> str | None:
    value = payload.get("event_price_amount")
    if value is None:
        value = payload.get("retail_price_amount")
    if value is None:
        return None
    price = float(value)
    if price <= 20_000:
        return "UNDER_20K"
    if price <= 50_000:
        return "20K_50K"
    return "OVER_50K"


def bayesian_rate(
    *, prior_mean: float, prior_count: float, successes: float, observations: float
) -> float:
    if not 0 <= prior_mean <= 1:
        raise ValueError("prior_mean must be in [0, 1]")
    if prior_count < 1 or observations < 0 or successes < 0 or successes > observations:
        raise ValueError("invalid Bayesian prior or observations")
    return (prior_count * prior_mean + successes) / (prior_count + observations)


def assess_candidate(
    candidate: MatchCandidate,
    *,
    user_type: str,
    server_time: datetime,
) -> CandidateColdStartAssessment:
    created_at = candidate.payload.get("created_at")
    is_new = bool(
        isinstance(created_at, datetime)
        and timedelta(0) <= server_time - created_at <= timedelta(days=NEW_ENTITY_WINDOW_DAYS)
    )
    if not is_new:
        return CandidateColdStartAssessment(False, False, None, None, ())

    supply = candidate.payload.get("supply_profile") or {}
    completeness = _clamp(float(supply.get("data_trust_score") or 0.0))
    product_quality_parts = (
        candidate.payload.get("category_code"),
        candidate.payload.get("product_name"),
        candidate.payload.get("retail_price_amount") or candidate.payload.get("event_price_amount"),
        candidate.payload.get("taste_json") or candidate.payload.get("trade_profile"),
    )
    product_quality = sum(value is not None and value != {} for value in product_quality_parts) / len(product_quality_parts)
    trade_readiness = _clamp(float(supply.get("trade_readiness_score") or 0.0) / 100.0)
    verification = 1.0 if (
        supply.get("approval_status") == "APPROVED"
        and candidate.payload.get("master_approval_status") == "APPROVED"
    ) else 0.0
    consultation = 1.0 if candidate.payload.get("consultation_enabled") else 0.0
    operating = candidate.payload.get("operating_status")
    runtime = 1.0 if operating in (None, "OPEN", "NORMAL") else 0.0
    weights = COLD_START_POLICY_CONFIG["new_exhibitor_quality_weights"]
    quality = (
        weights["profile_completeness"] * completeness
        + weights["product_data_quality"] * product_quality
        + weights["trade_readiness"] * trade_readiness
        + weights["verification"] * verification
        + weights["consultation_readiness"] * consultation
        + weights["runtime_availability"] * runtime
    )
    relevance = candidate.context_blended_score if candidate.context_blended_score is not None else candidate.final_score
    participation_ok = candidate.payload.get("participation_status") in ("APPROVED", "ACTIVE")
    eligible = bool(
        participation_ok
        and completeness >= 0.70
        and verification > 0
        and runtime > 0
        and relevance >= 0.45
    )
    cap = None if quality >= 0.85 else 0.85 if verification else 0.75 if completeness >= 0.70 else 0.65
    reasons = ["COLD.NEW_PRODUCT" if candidate.object_type == "PRODUCT" else "COLD.NEW_EXHIBITOR"]
    reasons.append("NEW_ENTITY_QUALITY_GATE_PASSED" if eligible else "NEW_ENTITY_QUALITY_GATE_FAILED")
    return CandidateColdStartAssessment(is_new, eligible, quality, cap, tuple(reasons))


def apply_cold_start_annotations(
    candidates: list[MatchCandidate],
    *,
    profile: ResolvedProfile,
    decision: ColdStartDecision,
    server_time: datetime,
) -> list[MatchCandidate]:
    """Annotate confidence and eligible exploration without changing relevance."""

    for candidate in candidates:
        assessment = assess_candidate(candidate, user_type=profile.user_type, server_time=server_time)
        candidate.cold_start_policy_version = decision.policy_version
        candidate.cold_start_state = decision.state
        candidate.cold_start_reason_codes = (
            *decision.reason_codes,
            *assessment.reason_codes,
        )
        candidate.cold_start_quality_score = assessment.quality_score
        caps = [value for value in (decision.recommendation_confidence_cap, assessment.confidence_cap) if value is not None]
        cap = min(caps) if caps else None
        base_confidence = candidate.directional_confidence if candidate.directional_confidence is not None else 1.0
        candidate.recommendation_confidence = min(base_confidence, cap) if cap is not None else base_confidence
        if assessment.is_new:
            if assessment.eligible_for_exploration:
                candidate.source_channels.update({"EXPLORATION", "COLD_START_QUALITY"})
            else:
                candidate.source_channels.discard("EXPLORATION")
    if decision.state in ("COLD", "WARMING"):
        target = max(1, round(min(len(candidates), 10) * decision.exploration_ratio))
        already = sum("COLD_START_QUALITY" in item.source_channels for item in candidates)
        learning_slots = max(0, target - min(already, 1))
        learning_pool = [
            item
            for item in candidates
            if "COLD_START_QUALITY" not in item.source_channels
            and (item.context_blended_score if item.context_blended_score is not None else item.final_score) >= 0.45
        ]
        learning_pool.sort(
            key=lambda item: (
                -float(item.features.get("novelty_score") or 0.0),
                -(item.context_blended_score if item.context_blended_score is not None else item.final_score),
                str(item.object_id),
            )
        )
        selected_categories: set[str] = set()
        selected = 0
        for item in learning_pool:
            if learning_slots == 0:
                break
            category = str(item.payload.get("category_code") or "UNCLASSIFIED")
            if category in selected_categories and len(selected_categories) > 0:
                continue
            item.source_channels.update({"EXPLORATION", "PREFERENCE_LEARNING"})
            item.cold_start_reason_codes = (
                *item.cold_start_reason_codes,
                "PREFERENCE_LEARNING_SLOT",
            )
            selected_categories.add(category)
            selected += 1
            if selected >= learning_slots:
                break

    # Preference-learning slots are selected after the per-candidate quality
    # assessment.  Compute the lineage fingerprint only after those annotations
    # are final, otherwise persisted reasons cannot be reproduced from the hash.
    for candidate in candidates:
        candidate.cold_start_input_fingerprint = _fingerprint(
            {
                "decision": decision.input_fingerprint,
                "object_id": str(candidate.object_id),
                "quality": candidate.cold_start_quality_score,
                "confidence": candidate.recommendation_confidence,
                "reasons": candidate.cold_start_reason_codes,
                "source_channels": sorted(candidate.source_channels),
            }
        )
    return candidates
