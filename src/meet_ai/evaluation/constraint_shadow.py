"""Privacy-safe aggregate quality gate for runtime constraint shadow results.

The gate can recommend that evidence is ready for a separate Change Request, but it
cannot enable enforcement.  It consumes aggregate counts only; candidate identifiers,
profile fields, observed values, and raw text are intentionally outside the contract.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

CONSTRAINT_SHADOW_GATE_COMMAND_V1 = "constraint-shadow-gate-command-v1.0"
CONSTRAINT_SHADOW_GATE_RESULT_V1 = "constraint-shadow-gate-result-v1.0"
CONSTRAINT_SHADOW_GATE_POLICY_VERSION = "constraint-shadow-promotion-gate-v1.0"
MINIMUM_RUNTIME_COMPARABLE_SAMPLE = 1_000
CONSTRAINT_SHADOW_ENFORCEMENT_ALLOWED = False

_OPAQUE_REF = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}$")
_REASON_CODE = re.compile(r"^[A-Z][A-Z0-9_]{0,127}$")


class ConstraintShadowGateValidationError(ValueError):
    """Raised when aggregate evidence does not satisfy the gate input contract."""


class ConstraintShadowState(StrEnum):
    PARITY = "PARITY"
    SAFETY_GAP = "SAFETY_GAP"
    DIVERGENCE = "DIVERGENCE"
    NOT_COMPARABLE = "NOT_COMPARABLE"
    NOT_APPLICABLE = "NOT_APPLICABLE"
    ADAPTER_ERROR = "ADAPTER_ERROR"


class ConstraintShadowGateOutcome(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"


@dataclass(frozen=True, slots=True)
class ConstraintShadowStateCount:
    state: ConstraintShadowState
    count: int

    def __post_init__(self) -> None:
        try:
            normalized_state = ConstraintShadowState(self.state)
        except ValueError as exc:
            raise ConstraintShadowGateValidationError(
                f"unsupported shadow state: {self.state}"
            ) from exc
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise ConstraintShadowGateValidationError("state count must be an integer")
        if self.count < 0:
            raise ConstraintShadowGateValidationError("state count must be non-negative")
        object.__setattr__(self, "state", normalized_state)


@dataclass(frozen=True, slots=True)
class ConstraintShadowReasonCount:
    reason_code: str
    count: int

    def __post_init__(self) -> None:
        if not _REASON_CODE.fullmatch(self.reason_code):
            raise ConstraintShadowGateValidationError(
                f"invalid stable reason code: {self.reason_code}"
            )
        if isinstance(self.count, bool) or not isinstance(self.count, int):
            raise ConstraintShadowGateValidationError("reason count must be an integer")
        if self.count <= 0:
            raise ConstraintShadowGateValidationError("reason count must be positive")


def _normalize_refs(values: tuple[str, ...], field: str) -> tuple[str, ...]:
    for value in values:
        if not isinstance(value, str) or not _OPAQUE_REF.fullmatch(value):
            raise ConstraintShadowGateValidationError(
                f"{field} must contain opaque references only"
            )
    normalized = tuple(sorted(set(values)))
    if len(normalized) != len(values):
        raise ConstraintShadowGateValidationError(f"{field} must not contain duplicates")
    return normalized


@dataclass(frozen=True, slots=True)
class ConstraintShadowGateCommand:
    sample_window_ref: str
    state_counts: tuple[ConstraintShadowStateCount, ...]
    safety_gap_reason_counts: tuple[ConstraintShadowReasonCount, ...]
    source_policy_versions: tuple[str, ...]
    duplicate_shadow_count: int = 0
    regression_evidence_refs: tuple[str, ...] = ()
    rollback_evidence_refs: tuple[str, ...] = ()
    safety_gap_review_evidence_refs: tuple[str, ...] = ()
    contract_version: str = CONSTRAINT_SHADOW_GATE_COMMAND_V1

    def __post_init__(self) -> None:
        if self.contract_version != CONSTRAINT_SHADOW_GATE_COMMAND_V1:
            raise ConstraintShadowGateValidationError(
                f"contract_version must be {CONSTRAINT_SHADOW_GATE_COMMAND_V1}"
            )
        if not _OPAQUE_REF.fullmatch(self.sample_window_ref):
            raise ConstraintShadowGateValidationError(
                "sample_window_ref must be an opaque reference"
            )
        if (
            isinstance(self.duplicate_shadow_count, bool)
            or not isinstance(self.duplicate_shadow_count, int)
            or self.duplicate_shadow_count < 0
        ):
            raise ConstraintShadowGateValidationError(
                "duplicate_shadow_count must be a non-negative integer"
            )

        states = tuple(item.state for item in self.state_counts)
        if len(states) != len(set(states)):
            raise ConstraintShadowGateValidationError(
                "state_counts must not contain duplicate states"
            )
        if set(states) != set(ConstraintShadowState):
            raise ConstraintShadowGateValidationError(
                "state_counts must cover every shadow state exactly once"
            )
        reason_codes = tuple(item.reason_code for item in self.safety_gap_reason_counts)
        if len(reason_codes) != len(set(reason_codes)):
            raise ConstraintShadowGateValidationError(
                "safety_gap_reason_counts must not contain duplicates"
            )

        state_counts = tuple(sorted(self.state_counts, key=lambda item: item.state.value))
        reason_counts = tuple(
            sorted(self.safety_gap_reason_counts, key=lambda item: item.reason_code)
        )
        safety_gap_count = next(
            item.count
            for item in state_counts
            if item.state is ConstraintShadowState.SAFETY_GAP
        )
        if safety_gap_count and sum(item.count for item in reason_counts) < safety_gap_count:
            raise ConstraintShadowGateValidationError(
                "every safety gap must contribute at least one stable reason code"
            )
        if not safety_gap_count and reason_counts:
            raise ConstraintShadowGateValidationError(
                "safety gap reasons require at least one SAFETY_GAP result"
            )

        source_versions = _normalize_refs(
            self.source_policy_versions, "source_policy_versions"
        )
        if not source_versions:
            raise ConstraintShadowGateValidationError(
                "source_policy_versions must not be empty"
            )
        object.__setattr__(self, "state_counts", state_counts)
        object.__setattr__(self, "safety_gap_reason_counts", reason_counts)
        object.__setattr__(self, "source_policy_versions", source_versions)
        object.__setattr__(
            self,
            "regression_evidence_refs",
            _normalize_refs(self.regression_evidence_refs, "regression_evidence_refs"),
        )
        object.__setattr__(
            self,
            "rollback_evidence_refs",
            _normalize_refs(self.rollback_evidence_refs, "rollback_evidence_refs"),
        )
        object.__setattr__(
            self,
            "safety_gap_review_evidence_refs",
            _normalize_refs(
                self.safety_gap_review_evidence_refs,
                "safety_gap_review_evidence_refs",
            ),
        )


@dataclass(frozen=True, slots=True)
class ConstraintShadowStateRate:
    state: ConstraintShadowState
    rate: str


@dataclass(frozen=True, slots=True)
class ConstraintShadowGateResult:
    contract_version: str
    policy_version: str
    outcome: ConstraintShadowGateOutcome
    sample_window_ref: str
    total_sample_count: int
    duplicate_shadow_count: int
    comparable_sample_count: int
    minimum_runtime_comparable_sample: int
    state_counts: tuple[ConstraintShadowStateCount, ...]
    state_rates: tuple[ConstraintShadowStateRate, ...]
    safety_gap_reason_counts: tuple[ConstraintShadowReasonCount, ...]
    blocker_reason_codes: tuple[str, ...]
    source_policy_versions: tuple[str, ...]
    regression_evidence_refs: tuple[str, ...]
    rollback_evidence_refs: tuple[str, ...]
    safety_gap_review_evidence_refs: tuple[str, ...]
    change_request_ready: bool
    enforcement_allowed: bool
    input_fingerprint: str
    result_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "contract_version": self.contract_version,
            "policy_version": self.policy_version,
            "outcome": self.outcome.value,
            "sample_window_ref": self.sample_window_ref,
            "total_sample_count": self.total_sample_count,
            "duplicate_shadow_count": self.duplicate_shadow_count,
            "comparable_sample_count": self.comparable_sample_count,
            "minimum_runtime_comparable_sample": self.minimum_runtime_comparable_sample,
            "state_counts": [
                {"state": item.state.value, "count": item.count}
                for item in self.state_counts
            ],
            "state_rates": [
                {"state": item.state.value, "rate": item.rate}
                for item in self.state_rates
            ],
            "safety_gap_reason_counts": [
                {"reason_code": item.reason_code, "count": item.count}
                for item in self.safety_gap_reason_counts
            ],
            "blocker_reason_codes": list(self.blocker_reason_codes),
            "source_policy_versions": list(self.source_policy_versions),
            "regression_evidence_refs": list(self.regression_evidence_refs),
            "rollback_evidence_refs": list(self.rollback_evidence_refs),
            "safety_gap_review_evidence_refs": list(
                self.safety_gap_review_evidence_refs
            ),
            "change_request_ready": self.change_request_ready,
            "enforcement_allowed": self.enforcement_allowed,
            "input_fingerprint": self.input_fingerprint,
            "result_fingerprint": self.result_fingerprint,
        }


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _command_payload(command: ConstraintShadowGateCommand) -> dict[str, Any]:
    return {
        "contract_version": command.contract_version,
        "sample_window_ref": command.sample_window_ref,
        "state_counts": [
            {"state": item.state.value, "count": item.count}
            for item in command.state_counts
        ],
        "safety_gap_reason_counts": [
            {"reason_code": item.reason_code, "count": item.count}
            for item in command.safety_gap_reason_counts
        ],
        "source_policy_versions": list(command.source_policy_versions),
        "duplicate_shadow_count": command.duplicate_shadow_count,
        "regression_evidence_refs": list(command.regression_evidence_refs),
        "rollback_evidence_refs": list(command.rollback_evidence_refs),
        "safety_gap_review_evidence_refs": list(
            command.safety_gap_review_evidence_refs
        ),
    }


def evaluate_constraint_shadow_gate(
    command: ConstraintShadowGateCommand,
) -> ConstraintShadowGateResult:
    """Evaluate aggregate evidence without authorizing runtime enforcement."""

    counts = {item.state: item.count for item in command.state_counts}
    total_count = sum(counts.values())
    comparable_count = sum(
        counts[state]
        for state in (
            ConstraintShadowState.PARITY,
            ConstraintShadowState.SAFETY_GAP,
            ConstraintShadowState.DIVERGENCE,
            ConstraintShadowState.ADAPTER_ERROR,
        )
    )
    blockers: set[str] = set()
    if counts[ConstraintShadowState.DIVERGENCE]:
        blockers.add("DIVERGENCE_PRESENT")
    if counts[ConstraintShadowState.ADAPTER_ERROR]:
        blockers.add("ADAPTER_ERROR_PRESENT")
    if comparable_count < MINIMUM_RUNTIME_COMPARABLE_SAMPLE:
        blockers.add("MINIMUM_RUNTIME_SAMPLE_NOT_MET")
    if not command.regression_evidence_refs:
        blockers.add("REGRESSION_EVIDENCE_REQUIRED")
    if not command.rollback_evidence_refs:
        blockers.add("ROLLBACK_EVIDENCE_REQUIRED")
    if (
        counts[ConstraintShadowState.SAFETY_GAP]
        and not command.safety_gap_review_evidence_refs
    ):
        blockers.add("SAFETY_GAP_REVIEW_REQUIRED")

    fatal = {"DIVERGENCE_PRESENT", "ADAPTER_ERROR_PRESENT"} & blockers
    if fatal:
        outcome = ConstraintShadowGateOutcome.FAIL
    elif blockers:
        outcome = ConstraintShadowGateOutcome.INSUFFICIENT_EVIDENCE
    else:
        outcome = ConstraintShadowGateOutcome.PASS

    denominator = total_count or 1
    rates = tuple(
        ConstraintShadowStateRate(item.state, f"{item.count / denominator:.6f}")
        for item in command.state_counts
    )
    input_fingerprint = _fingerprint(_command_payload(command))
    payload = {
        "contract_version": CONSTRAINT_SHADOW_GATE_RESULT_V1,
        "policy_version": CONSTRAINT_SHADOW_GATE_POLICY_VERSION,
        "outcome": outcome.value,
        "sample_window_ref": command.sample_window_ref,
        "total_sample_count": total_count,
        "duplicate_shadow_count": command.duplicate_shadow_count,
        "comparable_sample_count": comparable_count,
        "minimum_runtime_comparable_sample": MINIMUM_RUNTIME_COMPARABLE_SAMPLE,
        "state_counts": [
            {"state": item.state.value, "count": item.count}
            for item in command.state_counts
        ],
        "state_rates": [
            {"state": item.state.value, "rate": item.rate} for item in rates
        ],
        "safety_gap_reason_counts": [
            {"reason_code": item.reason_code, "count": item.count}
            for item in command.safety_gap_reason_counts
        ],
        "blocker_reason_codes": sorted(blockers),
        "source_policy_versions": list(command.source_policy_versions),
        "regression_evidence_refs": list(command.regression_evidence_refs),
        "rollback_evidence_refs": list(command.rollback_evidence_refs),
        "safety_gap_review_evidence_refs": list(
            command.safety_gap_review_evidence_refs
        ),
        "change_request_ready": outcome is ConstraintShadowGateOutcome.PASS,
        "enforcement_allowed": CONSTRAINT_SHADOW_ENFORCEMENT_ALLOWED,
        "input_fingerprint": input_fingerprint,
    }
    return ConstraintShadowGateResult(
        contract_version=CONSTRAINT_SHADOW_GATE_RESULT_V1,
        policy_version=CONSTRAINT_SHADOW_GATE_POLICY_VERSION,
        outcome=outcome,
        sample_window_ref=command.sample_window_ref,
        total_sample_count=total_count,
        duplicate_shadow_count=command.duplicate_shadow_count,
        comparable_sample_count=comparable_count,
        minimum_runtime_comparable_sample=MINIMUM_RUNTIME_COMPARABLE_SAMPLE,
        state_counts=command.state_counts,
        state_rates=rates,
        safety_gap_reason_counts=command.safety_gap_reason_counts,
        blocker_reason_codes=tuple(sorted(blockers)),
        source_policy_versions=command.source_policy_versions,
        regression_evidence_refs=command.regression_evidence_refs,
        rollback_evidence_refs=command.rollback_evidence_refs,
        safety_gap_review_evidence_refs=command.safety_gap_review_evidence_refs,
        change_request_ready=outcome is ConstraintShadowGateOutcome.PASS,
        enforcement_allowed=CONSTRAINT_SHADOW_ENFORCEMENT_ALLOWED,
        input_fingerprint=input_fingerprint,
        result_fingerprint=_fingerprint(payload),
    )
