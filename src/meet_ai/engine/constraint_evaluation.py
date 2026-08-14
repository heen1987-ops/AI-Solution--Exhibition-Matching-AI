"""Evaluate projected hard constraints against verified candidate observations.

Only a fully ELIGIBLE result may be adapted to the scoring core's EligibilityDecision.
Unknown, missing, stale, conditional, or negotiable candidate values remain
INFORMATION_REQUIRED and are never coerced to a pass, mismatch, or numeric zero.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from meet_ai.ontology import Catalog, load_catalog
from meet_ai.scoring import EligibilityDecision

from .intent_projection import (
    CANDIDATE_CAPABILITY_VERSION,
    INTENT_PROJECTION_POLICY_VERSION,
    INTENT_PROJECTION_RESULT_V1,
    PUBLISHED_RANKING_STATE,
    CatalogScope,
    ConstraintOperator,
    HardFilterConstraint,
    IntentProjectionPlan,
    VerificationMode,
)

CONSTRAINT_EVALUATION_RESULT_V1 = "constraint-evaluation-result-v1.0"
CONSTRAINT_EVALUATION_POLICY_VERSION = "constraint-evaluation-v1.0"

_OPAQUE_REFERENCE = re.compile(r"^[A-Za-z0-9._:/-]{1,160}$")
_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")
_TRADE_STATUSES = frozenset({"YES", "NO", "CONDITIONAL", "NEGOTIABLE"})


class ConstraintEvaluationValidationError(ValueError):
    """Raised when a plan or candidate observation is not safe to evaluate."""


class EligibilityAdmissionError(ValueError):
    """Raised when a non-eligible three-state result is offered to scoring."""


class ObservationState(StrEnum):
    KNOWN = "KNOWN"
    UNKNOWN = "UNKNOWN"
    MISSING = "MISSING"
    STALE = "STALE"


class CandidateEligibilityState(StrEnum):
    ELIGIBLE = "ELIGIBLE"
    FILTERED_OUT = "FILTERED_OUT"
    INFORMATION_REQUIRED = "INFORMATION_REQUIRED"


@dataclass(frozen=True, slots=True, repr=False)
class CandidateFieldObservation:
    candidate_field: str
    state: ObservationState | str
    ontology_codes: tuple[str, ...] = field(default=(), repr=False)
    numeric_value: float | int | None = field(default=None, repr=False)
    status_value: str | None = field(default=None, repr=False)
    evidence_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        try:
            normalized_state = ObservationState(self.state)
        except (TypeError, ValueError) as exc:
            raise ConstraintEvaluationValidationError(
                "observation state is invalid"
            ) from exc
        if not re.fullmatch(r"[a-z][a-z0-9_.]{0,127}", self.candidate_field):
            raise ConstraintEvaluationValidationError(
                "candidate_field must be a canonical field path"
            )
        codes = tuple(sorted(self.ontology_codes))
        if len(codes) != len(set(codes)):
            raise ConstraintEvaluationValidationError(
                "observation ontology_codes contains duplicates"
            )
        refs = tuple(sorted(self.evidence_refs))
        if not refs or len(refs) != len(set(refs)):
            raise ConstraintEvaluationValidationError(
                "observation requires unique evidence_refs"
            )
        if any(not _OPAQUE_REFERENCE.fullmatch(value) for value in refs):
            raise ConstraintEvaluationValidationError(
                "observation evidence_refs must be opaque references"
            )
        if normalized_state is not ObservationState.KNOWN and (
            codes or self.numeric_value is not None or self.status_value is not None
        ):
            raise ConstraintEvaluationValidationError(
                "non-known observations cannot carry candidate values"
            )
        if self.numeric_value is not None:
            if isinstance(self.numeric_value, bool) or not isinstance(
                self.numeric_value, (int, float)
            ):
                raise ConstraintEvaluationValidationError(
                    "numeric_value must be finite numeric data"
                )
            if not math.isfinite(float(self.numeric_value)):
                raise ConstraintEvaluationValidationError(
                    "numeric_value must be finite numeric data"
                )
        if self.status_value is not None and self.status_value not in _TRADE_STATUSES:
            raise ConstraintEvaluationValidationError(
                "status_value must be YES, NO, CONDITIONAL, or NEGOTIABLE"
            )
        object.__setattr__(self, "state", normalized_state)
        object.__setattr__(self, "ontology_codes", codes)
        object.__setattr__(self, "evidence_refs", refs)


@dataclass(frozen=True, slots=True)
class ConstraintDecision:
    concept_code: str
    operator: ConstraintOperator
    outcome: CandidateEligibilityState
    reason_code: str
    evidence_refs: tuple[str, ...]
    decision_fingerprint: str


@dataclass(frozen=True, slots=True)
class CandidateConstraintEvaluation:
    contract_version: str
    policy_version: str
    capability_version: str
    ontology_version: str
    candidate_ref: str
    outcome: CandidateEligibilityState
    constraint_decisions: tuple[ConstraintDecision, ...]
    reason_codes: tuple[str, ...]
    evidence_refs: tuple[str, ...]
    plan_fingerprint: str
    input_fingerprint: str
    evaluation_id: str
    result_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fingerprint(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _published_catalog(catalog: Catalog | None) -> Catalog:
    selected = catalog or load_catalog()
    selected.validate()
    if selected.metadata.get("status") != "PUBLISHED":
        raise ConstraintEvaluationValidationError(
            "constraint evaluation requires a published ontology"
        )
    return selected


def _validate_plan(plan: IntentProjectionPlan, catalog: Catalog) -> None:
    if plan.contract_version != INTENT_PROJECTION_RESULT_V1:
        raise ConstraintEvaluationValidationError(
            f"plan contract must be {INTENT_PROJECTION_RESULT_V1}"
        )
    if plan.policy_version != INTENT_PROJECTION_POLICY_VERSION:
        raise ConstraintEvaluationValidationError(
            f"plan policy must be {INTENT_PROJECTION_POLICY_VERSION}"
        )
    if plan.capability_version != CANDIDATE_CAPABILITY_VERSION:
        raise ConstraintEvaluationValidationError(
            f"capability version must be {CANDIDATE_CAPABILITY_VERSION}"
        )
    if plan.ontology_version != catalog.version:
        raise ConstraintEvaluationValidationError(
            "plan ontology_version must match the published ontology"
        )
    try:
        catalog_scope = CatalogScope(plan.catalog_scope)
    except (TypeError, ValueError) as exc:
        raise ConstraintEvaluationValidationError("plan catalog_scope is invalid") from exc
    if plan.ranking_state != PUBLISHED_RANKING_STATE:
        raise ConstraintEvaluationValidationError("plan ranking_state is invalid")
    for name, value in (
        ("source_intent_fingerprint", plan.source_intent_fingerprint),
        ("semantic_input_fingerprint", plan.semantic_input_fingerprint),
        ("plan_fingerprint", plan.plan_fingerprint),
        ("result_fingerprint", plan.result_fingerprint),
    ):
        if not _FINGERPRINT.fullmatch(value):
            raise ConstraintEvaluationValidationError(f"plan {name} is invalid")

    concepts: set[str] = set()
    for constraint in plan.hard_filter_constraints:
        concept = catalog.by_code.get(constraint.concept_code)
        if concept is None or concept.get("assignable", True) is False:
            raise ConstraintEvaluationValidationError(
                "constraint must use a published assignable concept"
            )
        if concept.get("concept_type") != constraint.concept_type:
            raise ConstraintEvaluationValidationError(
                "constraint concept_type does not match the ontology"
            )
        if constraint.unknown_outcome != "INFORMATION_REQUIRED" or (
            constraint.missing_outcome != "INFORMATION_REQUIRED"
        ):
            raise ConstraintEvaluationValidationError(
                "constraint must preserve unknown and missing information states"
            )
        if constraint.concept_code in concepts:
            raise ConstraintEvaluationValidationError(
                "plan contains duplicate constraint concepts"
            )
        concepts.add(constraint.concept_code)

    plan_payload = {
        "contract_version": plan.contract_version,
        "policy_version": plan.policy_version,
        "capability_version": plan.capability_version,
        "ontology_version": plan.ontology_version,
        "catalog_scope": catalog_scope.value,
        "retrieval_features": [asdict(item) for item in plan.retrieval_features],
        "hard_filter_constraints": [
            asdict(item) for item in plan.hard_filter_constraints
        ],
        "information_required": [asdict(item) for item in plan.information_required],
        "deferred": [asdict(item) for item in plan.deferred],
        "ranking_state": plan.ranking_state,
        "semantic_input_fingerprint": plan.semantic_input_fingerprint,
    }
    expected_plan_fingerprint = _fingerprint(plan_payload)
    if plan.plan_fingerprint != expected_plan_fingerprint:
        raise ConstraintEvaluationValidationError("plan_fingerprint does not match plan")
    expected_result_fingerprint = _fingerprint(
        {
            **plan_payload,
            "plan_fingerprint": expected_plan_fingerprint,
            "source_intent_fingerprint": plan.source_intent_fingerprint,
        }
    )
    if plan.result_fingerprint != expected_result_fingerprint:
        raise ConstraintEvaluationValidationError("result_fingerprint does not match plan")


def _validate_observation_for_constraint(
    observation: CandidateFieldObservation,
    constraints: tuple[HardFilterConstraint, ...],
    catalog: Catalog,
) -> None:
    modes = {item.verification_mode for item in constraints}
    if len(modes) != 1:
        raise ConstraintEvaluationValidationError(
            "one candidate field cannot use multiple verification modes"
        )
    if observation.state is not ObservationState.KNOWN:
        return
    mode = next(iter(modes))
    if mode is VerificationMode.ONTOLOGY_MATCH:
        if not observation.ontology_codes or (
            observation.numeric_value is not None
            or observation.status_value is not None
        ):
            raise ConstraintEvaluationValidationError(
                "ontology observations require only ontology_codes"
            )
        for code in observation.ontology_codes:
            concept = catalog.by_code.get(code)
            if concept is None or concept.get("assignable", True) is False:
                raise ConstraintEvaluationValidationError(
                    "observation contains a code outside the published ontology"
                )
    elif mode is VerificationMode.DERIVED_BAND_MATCH:
        if observation.numeric_value is None or (
            observation.ontology_codes or observation.status_value is not None
        ):
            raise ConstraintEvaluationValidationError(
                "derived-band observations require only numeric_value"
            )
    elif mode is VerificationMode.TRADE_STATUS:
        if observation.status_value is None or (
            observation.ontology_codes or observation.numeric_value is not None
        ):
            raise ConstraintEvaluationValidationError(
                "trade-status observations require only status_value"
            )


def _match_state(
    constraint: HardFilterConstraint,
    observation: CandidateFieldObservation,
    catalog: Catalog,
) -> tuple[bool | None, str]:
    if observation.state is ObservationState.UNKNOWN:
        return None, "CANDIDATE_VALUE_UNKNOWN"
    if observation.state is ObservationState.MISSING:
        return None, "CANDIDATE_VALUE_MISSING"
    if observation.state is ObservationState.STALE:
        return None, "CANDIDATE_VALUE_STALE"

    if constraint.verification_mode is VerificationMode.ONTOLOGY_MATCH:
        matched = any(
            catalog.match_strength(constraint.concept_code, offered) > 0
            for offered in observation.ontology_codes
        )
        return matched, "ONTOLOGY_MATCH_EVALUATED"
    if constraint.verification_mode is VerificationMode.DERIVED_BAND_MATCH:
        try:
            band = catalog.derive_band(
                "alcohol_percentage", float(observation.numeric_value)
            )
        except (KeyError, ValueError):
            return None, "CANDIDATE_VALUE_INVALID"
        return (
            catalog.match_strength(constraint.concept_code, band) > 0,
            "DERIVED_BAND_EVALUATED",
        )
    if observation.status_value in {"CONDITIONAL", "NEGOTIABLE"}:
        return None, "CANDIDATE_VALUE_CONDITIONAL"
    return observation.status_value == "YES", "TRADE_STATUS_EVALUATED"


def _constraint_decision(
    constraint: HardFilterConstraint,
    observation: CandidateFieldObservation | None,
    *,
    catalog: Catalog,
    plan_fingerprint: str,
) -> ConstraintDecision:
    if observation is None:
        evidence_refs = (f"plan:{plan_fingerprint}:observation-missing",)
        matched: bool | None = None
        reason = "CANDIDATE_OBSERVATION_MISSING"
    else:
        evidence_refs = observation.evidence_refs
        matched, reason = _match_state(constraint, observation, catalog)

    if matched is None:
        outcome = CandidateEligibilityState.INFORMATION_REQUIRED
        reason_code = reason
    else:
        violates = (
            constraint.operator is ConstraintOperator.REQUIRE_MATCH and not matched
        ) or (constraint.operator is ConstraintOperator.FORBID_MATCH and matched)
        outcome = (
            CandidateEligibilityState.FILTERED_OUT
            if violates
            else CandidateEligibilityState.ELIGIBLE
        )
        if violates:
            reason_code = (
                "MUST_CONSTRAINT_NOT_MATCHED"
                if constraint.operator is ConstraintOperator.REQUIRE_MATCH
                else "EXCLUDED_CONCEPT_MATCHED"
            )
        else:
            reason_code = "CONSTRAINT_SATISFIED"
    payload = {
        "concept_code": constraint.concept_code,
        "operator": constraint.operator.value,
        "outcome": outcome.value,
        "reason_code": reason_code,
        "evidence_refs": list(evidence_refs),
        "plan_fingerprint": plan_fingerprint,
    }
    return ConstraintDecision(
        concept_code=constraint.concept_code,
        operator=constraint.operator,
        outcome=outcome,
        reason_code=reason_code,
        evidence_refs=evidence_refs,
        decision_fingerprint=_fingerprint(payload),
    )


def evaluate_candidate_constraints(
    plan: IntentProjectionPlan,
    *,
    candidate_ref: str,
    observations: tuple[CandidateFieldObservation, ...] = (),
    catalog: Catalog | None = None,
) -> CandidateConstraintEvaluation:
    """Evaluate a candidate without exposing observed business values in the result."""

    selected_catalog = _published_catalog(catalog)
    _validate_plan(plan, selected_catalog)
    if not _OPAQUE_REFERENCE.fullmatch(candidate_ref):
        raise ConstraintEvaluationValidationError(
            "candidate_ref must be an opaque non-PII reference"
        )

    by_field: dict[str, CandidateFieldObservation] = {}
    constraints_by_field: dict[str, list[HardFilterConstraint]] = {}
    for constraint in plan.hard_filter_constraints:
        constraints_by_field.setdefault(constraint.candidate_field, []).append(
            constraint
        )
    for observation in observations:
        if observation.candidate_field in by_field:
            raise ConstraintEvaluationValidationError(
                "candidate observations contain duplicate fields"
            )
        if observation.candidate_field not in constraints_by_field:
            raise ConstraintEvaluationValidationError(
                "candidate observation is outside the projection plan"
            )
        by_field[observation.candidate_field] = observation

    for field_name, observation in by_field.items():
        _validate_observation_for_constraint(
            observation,
            tuple(constraints_by_field[field_name]),
            selected_catalog,
        )

    decisions = tuple(
        sorted(
            (
                _constraint_decision(
                    constraint,
                    by_field.get(constraint.candidate_field),
                    catalog=selected_catalog,
                    plan_fingerprint=plan.plan_fingerprint,
                )
                for constraint in plan.hard_filter_constraints
            ),
            key=lambda item: (item.concept_code, item.operator.value),
        )
    )
    if any(
        item.outcome is CandidateEligibilityState.FILTERED_OUT for item in decisions
    ):
        outcome = CandidateEligibilityState.FILTERED_OUT
    elif plan.information_required or any(
        item.outcome is CandidateEligibilityState.INFORMATION_REQUIRED
        for item in decisions
    ):
        outcome = CandidateEligibilityState.INFORMATION_REQUIRED
    else:
        outcome = CandidateEligibilityState.ELIGIBLE

    reason_codes = {item.reason_code for item in decisions}
    reason_codes.update(item.reason_code for item in plan.information_required)
    if not reason_codes:
        reason_codes.add("ALL_CONSTRAINTS_SATISFIED")
    normalized_reasons = tuple(sorted(reason_codes))
    evidence_ref_set = {ref for item in decisions for ref in item.evidence_refs}
    evidence_ref_set.add(f"plan:{plan.plan_fingerprint}")
    evidence_ref_set.update(
        f"plan:{plan.plan_fingerprint}:information-required:"
        f"{_fingerprint((item.concept_code, item.reason_code))[:16]}"
        for item in plan.information_required
    )
    evidence_refs = tuple(sorted(evidence_ref_set))
    normalized_observations = [
        {
            "candidate_field": item.candidate_field,
            "state": item.state.value,
            "ontology_codes": list(item.ontology_codes),
            "numeric_value": item.numeric_value,
            "status_value": item.status_value,
            "evidence_refs": list(item.evidence_refs),
        }
        for item in sorted(observations, key=lambda value: value.candidate_field)
    ]
    input_fingerprint = _fingerprint(
        {
            "plan_fingerprint": plan.plan_fingerprint,
            "candidate_ref": candidate_ref,
            "observations": normalized_observations,
        }
    )
    result_payload = {
        "contract_version": CONSTRAINT_EVALUATION_RESULT_V1,
        "policy_version": CONSTRAINT_EVALUATION_POLICY_VERSION,
        "capability_version": plan.capability_version,
        "ontology_version": selected_catalog.version,
        "candidate_ref": candidate_ref,
        "outcome": outcome.value,
        "constraint_decisions": [asdict(item) for item in decisions],
        "reason_codes": list(normalized_reasons),
        "evidence_refs": list(evidence_refs),
        "plan_fingerprint": plan.plan_fingerprint,
        "input_fingerprint": input_fingerprint,
    }
    result_fingerprint = _fingerprint(result_payload)
    return CandidateConstraintEvaluation(
        contract_version=CONSTRAINT_EVALUATION_RESULT_V1,
        policy_version=CONSTRAINT_EVALUATION_POLICY_VERSION,
        capability_version=plan.capability_version,
        ontology_version=selected_catalog.version,
        candidate_ref=candidate_ref,
        outcome=outcome,
        constraint_decisions=decisions,
        reason_codes=normalized_reasons,
        evidence_refs=evidence_refs,
        plan_fingerprint=plan.plan_fingerprint,
        input_fingerprint=input_fingerprint,
        evaluation_id=f"intent-filter:{result_fingerprint}",
        result_fingerprint=result_fingerprint,
    )


def to_scoring_eligibility(
    evaluation: CandidateConstraintEvaluation,
) -> EligibilityDecision:
    """Admit only fully eligible candidates to the existing scoring contract."""

    if evaluation.contract_version != CONSTRAINT_EVALUATION_RESULT_V1:
        raise ConstraintEvaluationValidationError(
            f"evaluation contract must be {CONSTRAINT_EVALUATION_RESULT_V1}"
        )
    if evaluation.policy_version != CONSTRAINT_EVALUATION_POLICY_VERSION:
        raise ConstraintEvaluationValidationError(
            f"evaluation policy must be {CONSTRAINT_EVALUATION_POLICY_VERSION}"
        )
    if evaluation.capability_version != CANDIDATE_CAPABILITY_VERSION:
        raise ConstraintEvaluationValidationError(
            f"capability version must be {CANDIDATE_CAPABILITY_VERSION}"
        )
    if evaluation.outcome is not CandidateEligibilityState.ELIGIBLE or any(
        item.outcome is not CandidateEligibilityState.ELIGIBLE
        for item in evaluation.constraint_decisions
    ):
        raise EligibilityAdmissionError(
            f"only ELIGIBLE evaluations can enter scoring: {evaluation.outcome.value}"
        )
    if not _FINGERPRINT.fullmatch(evaluation.result_fingerprint):
        raise ConstraintEvaluationValidationError(
            "evaluation result_fingerprint is invalid"
        )
    if evaluation.evaluation_id != f"intent-filter:{evaluation.result_fingerprint}":
        raise ConstraintEvaluationValidationError("evaluation_id is invalid")
    return EligibilityDecision(True, evaluation.evaluation_id)
