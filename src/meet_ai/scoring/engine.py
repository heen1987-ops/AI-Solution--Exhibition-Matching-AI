"""Reproducible scoring core for stages 11 through 13.

The scoring core intentionally contains no model or provider call. Candidate eligibility is
decided before scoring, missing signals are excluded and the remaining weights are normalized,
and every result carries a deterministic fingerprint of the inputs and published policy.

LLMs may later propose profile attributes or explanation text through an adapter, but they do
not decide hard constraints or alter the formulas in this module.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation, localcontext
from types import MappingProxyType

Number = Decimal | float | int | str
ComponentInput = Mapping[str, Number | None]

ZERO = Decimal(0)
ONE = Decimal(1)
ONE_HUNDRED = Decimal(100)
SCORE_QUANTUM = Decimal("0.01")


class ScoreValidationError(ValueError):
    """Raised when a policy or score input violates the published contract."""


class IneligibleCandidateError(ScoreValidationError):
    """Raised when a hard-filter failure reaches a scoring function."""

    def __init__(self, decision: EligibilityDecision) -> None:
        self.decision = decision
        reason_text = ", ".join(decision.reason_codes)
        super().__init__(f"candidate is ineligible: {reason_text}")


def _as_decimal(value: Number, *, field_name: str) -> Decimal:
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ScoreValidationError(f"{field_name} must be numeric") from exc
    if not converted.is_finite():
        raise ScoreValidationError(f"{field_name} must be finite")
    return converted


def _in_range(
    value: Decimal, minimum: Decimal, maximum: Decimal, *, field_name: str
) -> None:
    if value < minimum or value > maximum:
        raise ScoreValidationError(
            f"{field_name} must be between {minimum} and {maximum}"
        )


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(ONE))
    return format(normalized, "f")


def _fingerprint(payload: Mapping[str, object]) -> str:
    serialized = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


@dataclass(frozen=True)
class EligibilityDecision:
    """Immutable output of the stage-10 hard-filter evaluation."""

    passed: bool
    evaluation_id: str
    reason_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not self.evaluation_id.strip():
            raise ScoreValidationError("eligibility evaluation_id is required")
        if not self.passed and not self.reason_codes:
            raise ScoreValidationError(
                "failed eligibility requires at least one reason code"
            )
        if any(not code.strip() for code in self.reason_codes):
            raise ScoreValidationError("eligibility reason codes cannot be blank")


@dataclass(frozen=True)
class ScoreCap:
    """An already-evaluated business cap applied after the weighted calculation."""

    code: str
    maximum: Decimal | Number

    def __post_init__(self) -> None:
        maximum = _as_decimal(self.maximum, field_name="score cap maximum")
        _in_range(maximum, ZERO, ONE_HUNDRED, field_name="score cap maximum")
        if not self.code.strip():
            raise ScoreValidationError("score cap code is required")
        object.__setattr__(self, "maximum", maximum)


@dataclass(frozen=True)
class ScoringPolicy:
    """Immutable, versioned weight policy for one directional score."""

    version: str
    audience: str
    weights: Mapping[str, Decimal | Number]
    grade_prefix: str | None = None

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ScoreValidationError("policy version is required")
        if not self.audience.strip():
            raise ScoreValidationError("policy audience is required")
        if not self.weights:
            raise ScoreValidationError("policy must define at least one weight")

        normalized: dict[str, Decimal] = {}
        for component, raw_weight in sorted(self.weights.items()):
            if not component.strip():
                raise ScoreValidationError("component code cannot be blank")
            weight = _as_decimal(raw_weight, field_name=f"weight {component}")
            if weight <= ZERO or weight > ONE:
                raise ScoreValidationError(
                    f"weight {component} must be greater than 0 and at most 1"
                )
            normalized[component] = weight

        total = sum(normalized.values(), ZERO)
        if total != ONE:
            raise ScoreValidationError(f"policy weights must total 1.0; got {total}")
        if self.grade_prefix is not None and not self.grade_prefix.strip():
            raise ScoreValidationError("grade prefix cannot be blank")

        object.__setattr__(self, "weights", MappingProxyType(normalized))


@dataclass(frozen=True)
class DirectionalScoreResult:
    """Append-only calculation result suitable for persistence in the matching domain."""

    policy_version: str
    audience: str
    eligibility_evaluation_id: str
    component_values: Mapping[str, Decimal | None]
    effective_weights: Mapping[str, Decimal]
    contributions: Mapping[str, Decimal]
    missing_components: tuple[str, ...]
    uncapped_score: Decimal
    final_score: Decimal
    grade: str | None
    confidence: Decimal | None
    cap_rules: tuple[ScoreCap, ...]
    applied_cap_codes: tuple[str, ...]
    calculation_fingerprint: str


@dataclass(frozen=True)
class ReciprocalPolicy:
    """Versioned stage-13 formula and minimum-direction gate configuration."""

    version: str
    imbalance_lambda: Decimal | Number = Decimal(10)
    confidence_floor: Decimal | Number = Decimal("0.90")
    confidence_span: Decimal | Number = Decimal("0.10")
    acceptance_floor: Decimal | Number = Decimal("0.80")
    acceptance_span: Decimal | Number = Decimal("0.20")
    minimum_gate_caps: tuple[tuple[Decimal | Number, Decimal | Number], ...] = (
        (Decimal(40), Decimal(45)),
        (Decimal(55), Decimal(65)),
    )

    def __post_init__(self) -> None:
        if not self.version.strip():
            raise ScoreValidationError("reciprocal policy version is required")

        decimal_fields = (
            "imbalance_lambda",
            "confidence_floor",
            "confidence_span",
            "acceptance_floor",
            "acceptance_span",
        )
        for field_name in decimal_fields:
            value = _as_decimal(getattr(self, field_name), field_name=field_name)
            object.__setattr__(self, field_name, value)

        if self.imbalance_lambda < ZERO:
            raise ScoreValidationError("imbalance_lambda cannot be negative")
        for field_name in (
            "confidence_floor",
            "confidence_span",
            "acceptance_floor",
            "acceptance_span",
        ):
            _in_range(getattr(self, field_name), ZERO, ONE, field_name=field_name)
        if self.confidence_floor + self.confidence_span > ONE:
            raise ScoreValidationError("confidence adjustment cannot exceed 1")
        if self.acceptance_floor + self.acceptance_span > ONE:
            raise ScoreValidationError("acceptance adjustment cannot exceed 1")

        normalized_caps: list[tuple[Decimal, Decimal]] = []
        previous_threshold = ZERO
        for raw_threshold, raw_cap in self.minimum_gate_caps:
            threshold = _as_decimal(raw_threshold, field_name="minimum gate threshold")
            cap = _as_decimal(raw_cap, field_name="minimum gate cap")
            _in_range(threshold, ZERO, ONE_HUNDRED, field_name="minimum gate threshold")
            _in_range(cap, ZERO, ONE_HUNDRED, field_name="minimum gate cap")
            if threshold <= previous_threshold:
                raise ScoreValidationError(
                    "minimum gate thresholds must be strictly increasing"
                )
            previous_threshold = threshold
            normalized_caps.append((threshold, cap))
        object.__setattr__(self, "minimum_gate_caps", tuple(normalized_caps))


@dataclass(frozen=True)
class ReciprocalScoreResult:
    """Reproducible result of combining the two directional B2B scores."""

    policy_version: str
    eligibility_evaluation_id: str
    buyer_to_exhibitor_score: Decimal
    exhibitor_to_buyer_score: Decimal
    reciprocal_base_score: Decimal
    minimum_direction_score: Decimal
    minimum_direction_cap: Decimal | None
    imbalance_value: Decimal
    imbalance_penalty: Decimal
    confidence_score: Decimal
    confidence_adjustment: Decimal
    acceptance_capacity_score: Decimal
    acceptance_adjustment: Decimal
    policy_adjustment: Decimal
    uncapped_final_score: Decimal
    final_reciprocal_score: Decimal
    grade: str
    match_status: str
    recommended_action: str
    calculation_fingerprint: str


def _grade(score: Decimal, prefix: str | None) -> str | None:
    if prefix is None:
        return None
    if score >= Decimal(85):
        level = 5
    elif score >= Decimal(70):
        level = 4
    elif score >= Decimal(55):
        level = 3
    elif score >= Decimal(40):
        level = 2
    else:
        level = 1
    return f"{prefix}{level}"


def calculate_directional_score(
    policy: ScoringPolicy,
    components: ComponentInput,
    *,
    eligibility: EligibilityDecision,
    caps: Sequence[ScoreCap] = (),
    confidence: Number | None = None,
) -> DirectionalScoreResult:
    """Calculate one deterministic score after a successful hard-filter decision.

    ``None`` means missing and removes that component from the denominator. Numeric zero remains
    an explicit mismatch and is included. Unknown component names are rejected so policy drift
    cannot silently change production scores.
    """

    if not eligibility.passed:
        raise IneligibleCandidateError(eligibility)

    unknown_components = sorted(set(components) - set(policy.weights))
    if unknown_components:
        joined = ", ".join(unknown_components)
        raise ScoreValidationError(
            f"components are not in policy {policy.version}: {joined}"
        )

    values: dict[str, Decimal | None] = {}
    present: dict[str, Decimal] = {}
    for component in policy.weights:
        raw_value = components.get(component)
        if raw_value is None:
            values[component] = None
            continue
        value = _as_decimal(raw_value, field_name=f"component {component}")
        _in_range(value, ZERO, ONE, field_name=f"component {component}")
        values[component] = value
        present[component] = value

    if not present:
        raise ScoreValidationError("at least one score component is required")

    active_weight_total = sum((policy.weights[name] for name in present), ZERO)
    effective_weights = {
        name: policy.weights[name] / active_weight_total for name in present
    }
    contributions = {name: effective_weights[name] * present[name] for name in present}
    normalized_score = sum(contributions.values(), ZERO)
    uncapped_score = normalized_score * ONE_HUNDRED

    normalized_caps = tuple(caps)
    minimum_cap = min((cap.maximum for cap in normalized_caps), default=None)
    final_score = (
        min(uncapped_score, minimum_cap) if minimum_cap is not None else uncapped_score
    )
    applied_cap_codes = (
        tuple(sorted(cap.code for cap in normalized_caps if cap.maximum == minimum_cap))
        if minimum_cap is not None and final_score < uncapped_score
        else ()
    )

    resolved_confidence: Decimal | None = None
    if confidence is not None:
        resolved_confidence = _as_decimal(confidence, field_name="confidence")
        _in_range(resolved_confidence, ZERO, ONE, field_name="confidence")

    fingerprint_payload = {
        "caps": [
            {"code": cap.code, "maximum": _decimal_text(cap.maximum)}
            for cap in sorted(
                normalized_caps, key=lambda item: (item.maximum, item.code)
            )
        ],
        "components": {
            name: None if value is None else _decimal_text(value)
            for name, value in values.items()
        },
        "confidence": (
            None if resolved_confidence is None else _decimal_text(resolved_confidence)
        ),
        "eligibility_evaluation_id": eligibility.evaluation_id,
        "policy": {
            "audience": policy.audience,
            "version": policy.version,
            "weights": {
                name: _decimal_text(weight) for name, weight in policy.weights.items()
            },
        },
    }

    return DirectionalScoreResult(
        policy_version=policy.version,
        audience=policy.audience,
        eligibility_evaluation_id=eligibility.evaluation_id,
        component_values=MappingProxyType(values),
        effective_weights=MappingProxyType(effective_weights),
        contributions=MappingProxyType(contributions),
        missing_components=tuple(
            name for name, value in values.items() if value is None
        ),
        uncapped_score=uncapped_score,
        final_score=final_score,
        grade=_grade(final_score, policy.grade_prefix),
        confidence=resolved_confidence,
        cap_rules=normalized_caps,
        applied_cap_codes=applied_cap_codes,
        calculation_fingerprint=_fingerprint(fingerprint_payload),
    )


def _harmonic_mean(left: Decimal, right: Decimal) -> Decimal:
    if left == ZERO or right == ZERO:
        return ZERO
    return Decimal(2) * left * right / (left + right)


def _reciprocal_status_and_action(minimum_score: Decimal) -> tuple[str, str]:
    if minimum_score < Decimal(40):
        return "NOT_RECIPROCAL", "DO_NOT_PUSH"
    if minimum_score < Decimal(55):
        return "IMBALANCED_MATCH", "REQUEST_INFORMATION"
    if minimum_score < Decimal(70):
        return "CONDITIONAL_MATCH", "CONFIRM_TRADE_CONDITION"
    return "MUTUAL_MATCH", "REQUEST_MEETING"


def calculate_reciprocal_score(
    *,
    buyer_to_exhibitor_score: Number,
    exhibitor_to_buyer_score: Number,
    buyer_confidence: Number,
    exhibitor_confidence: Number,
    acceptance_capacity_score: Number,
    eligibility: EligibilityDecision,
    policy: ReciprocalPolicy | None = None,
    policy_adjustment: Number = ZERO,
) -> ReciprocalScoreResult:
    """Combine directional B2B scores using the published stage-13 formula."""

    if not eligibility.passed:
        raise IneligibleCandidateError(eligibility)
    active_policy = policy or RECIPROCAL_SCORE_V1

    buyer_score = _as_decimal(
        buyer_to_exhibitor_score, field_name="buyer_to_exhibitor_score"
    )
    exhibitor_score = _as_decimal(
        exhibitor_to_buyer_score, field_name="exhibitor_to_buyer_score"
    )
    buyer_conf = _as_decimal(buyer_confidence, field_name="buyer_confidence")
    exhibitor_conf = _as_decimal(
        exhibitor_confidence, field_name="exhibitor_confidence"
    )
    acceptance = _as_decimal(
        acceptance_capacity_score, field_name="acceptance_capacity_score"
    )
    adjustment = _as_decimal(policy_adjustment, field_name="policy_adjustment")

    _in_range(buyer_score, ZERO, ONE_HUNDRED, field_name="buyer_to_exhibitor_score")
    _in_range(exhibitor_score, ZERO, ONE_HUNDRED, field_name="exhibitor_to_buyer_score")
    _in_range(buyer_conf, ZERO, ONE, field_name="buyer_confidence")
    _in_range(exhibitor_conf, ZERO, ONE, field_name="exhibitor_confidence")
    _in_range(acceptance, ZERO, ONE, field_name="acceptance_capacity_score")
    _in_range(adjustment, -ONE_HUNDRED, ONE_HUNDRED, field_name="policy_adjustment")

    with localcontext() as context:
        context.prec = 38
        # The stage-13 worked example persists the harmonic mean as 89.96 before
        # applying the confidence and acceptance factors. Making that intermediate
        # rounding explicit removes a cross-language 86.87/86.88 ambiguity.
        base_score = _harmonic_mean(buyer_score, exhibitor_score).quantize(
            SCORE_QUANTUM, rounding=ROUND_HALF_UP
        )
        minimum_score = min(buyer_score, exhibitor_score)
        imbalance = abs(buyer_score - exhibitor_score) / ONE_HUNDRED
        imbalance_penalty = active_policy.imbalance_lambda * imbalance
        confidence_score = _harmonic_mean(buyer_conf, exhibitor_conf)
        confidence_adjustment = (
            active_policy.confidence_floor
            + active_policy.confidence_span * confidence_score
        )
        acceptance_adjustment = (
            active_policy.acceptance_floor + active_policy.acceptance_span * acceptance
        )
        uncapped = (
            base_score * confidence_adjustment * acceptance_adjustment
            - imbalance_penalty
            + adjustment
        )
        uncapped = min(ONE_HUNDRED, max(ZERO, uncapped))

        applicable_caps = [
            cap
            for threshold, cap in active_policy.minimum_gate_caps
            if minimum_score < threshold
        ]
        minimum_cap = min(applicable_caps, default=None)
        final_score = (
            min(uncapped, minimum_cap) if minimum_cap is not None else uncapped
        )

    match_status, recommended_action = _reciprocal_status_and_action(minimum_score)
    fingerprint_payload = {
        "acceptance_capacity_score": _decimal_text(acceptance),
        "buyer_confidence": _decimal_text(buyer_conf),
        "buyer_to_exhibitor_score": _decimal_text(buyer_score),
        "eligibility_evaluation_id": eligibility.evaluation_id,
        "exhibitor_confidence": _decimal_text(exhibitor_conf),
        "exhibitor_to_buyer_score": _decimal_text(exhibitor_score),
        "policy": {
            "acceptance_floor": _decimal_text(active_policy.acceptance_floor),
            "acceptance_span": _decimal_text(active_policy.acceptance_span),
            "confidence_floor": _decimal_text(active_policy.confidence_floor),
            "confidence_span": _decimal_text(active_policy.confidence_span),
            "imbalance_lambda": _decimal_text(active_policy.imbalance_lambda),
            "minimum_gate_caps": [
                [_decimal_text(threshold), _decimal_text(cap)]
                for threshold, cap in active_policy.minimum_gate_caps
            ],
            "intermediate_rounding": "ROUND_HALF_UP_0.01",
            "version": active_policy.version,
        },
        "policy_adjustment": _decimal_text(adjustment),
    }

    return ReciprocalScoreResult(
        policy_version=active_policy.version,
        eligibility_evaluation_id=eligibility.evaluation_id,
        buyer_to_exhibitor_score=buyer_score,
        exhibitor_to_buyer_score=exhibitor_score,
        reciprocal_base_score=base_score,
        minimum_direction_score=minimum_score,
        minimum_direction_cap=minimum_cap,
        imbalance_value=imbalance,
        imbalance_penalty=imbalance_penalty,
        confidence_score=confidence_score,
        confidence_adjustment=confidence_adjustment,
        acceptance_capacity_score=acceptance,
        acceptance_adjustment=acceptance_adjustment,
        policy_adjustment=adjustment,
        uncapped_final_score=uncapped,
        final_reciprocal_score=final_score,
        grade=_grade(final_score, "R") or "R1",
        match_status=match_status,
        recommended_action=recommended_action,
        calculation_fingerprint=_fingerprint(fingerprint_payload),
    )


CONSUMER_SCORE_V1 = ScoringPolicy(
    version="consumer-score-v1.0",
    audience="GENERAL_VISITOR",
    grade_prefix="R",
    weights={
        "goal": Decimal("0.20"),
        "category": Decimal("0.18"),
        "sensory": Decimal("0.18"),
        "price": Decimal("0.12"),
        "alcohol": Decimal("0.08"),
        "service": Decimal("0.09"),
        "usage": Decimal("0.06"),
        "behavior": Decimal("0.04"),
        "trust": Decimal("0.05"),
    },
)

BUYER_SCORE_V1 = ScoringPolicy(
    version="buyer-score-v1.0",
    audience="BUYER_TO_EXHIBITOR",
    grade_prefix="B",
    weights={
        "business_goal": Decimal("0.12"),
        "product": Decimal("0.15"),
        "channel": Decimal("0.12"),
        "price": Decimal("0.10"),
        "moq": Decimal("0.12"),
        "capacity": Decimal("0.10"),
        "region": Decimal("0.08"),
        "cooperation": Decimal("0.08"),
        "meeting": Decimal("0.05"),
        "trust": Decimal("0.08"),
    },
)

EXHIBITOR_SCORE_V1 = ScoringPolicy(
    version="exhibitor-score-v1.0",
    audience="EXHIBITOR_TO_BUYER",
    weights={
        "buyer_type": Decimal("0.15"),
        "channel": Decimal("0.16"),
        "order_volume": Decimal("0.16"),
        "region": Decimal("0.10"),
        "trade_type": Decimal("0.12"),
        "portfolio": Decimal("0.10"),
        "decision_timing": Decimal("0.08"),
        "verification": Decimal("0.08"),
        "meeting_readiness": Decimal("0.05"),
    },
)

RECIPROCAL_SCORE_V1 = ReciprocalPolicy(version="reciprocal-score-v1.0")
