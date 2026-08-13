"""Privacy-minimized runtime adapter for the three-state constraint evaluator.

The adapter projects confirmed profile requirements, maps only approved candidate data into
engine observations, and compares the result with the existing runtime Hard Filter.  It is
diagnostic-only: it never changes admission, score, rank, persistence, or API output.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from meet_ai.engine import (
    CandidateConstraintEvaluation,
    CandidateEligibilityState,
    CandidateFieldObservation,
    CanonicalProfileIntentCommand,
    CatalogScope,
    IntentProjectionPlan,
    ObservationState,
    evaluate_candidate_constraints,
    normalize_canonical_profile_intent,
    project_intent,
)
from meet_ai.evaluation.constraint_shadow import (
    ConstraintShadowGateCommand,
    ConstraintShadowGateResult,
    ConstraintShadowReasonCount,
    ConstraintShadowState,
    ConstraintShadowStateCount,
    evaluate_constraint_shadow_gate,
)

from app.services.matching.ontology_support import get_catalog
from app.services.matching.types import (
    CandidateHardFilterShadow,
    FilterOutcome,
    MatchCandidate,
    ResolvedProfile,
    ShadowParityState,
)

CANDIDATE_OBSERVATION_ADAPTER_VERSION = "candidate-observation-adapter-v1.0"
HARD_FILTER_SHADOW_VERSION = "hard-filter-shadow-v1.0"
HARD_FILTER_SHADOW_ENFORCEMENT = False

_SHA256_HEX = frozenset("0123456789abcdef")

_REQUIRED_LEVELS = frozenset({"REQUIRED", "MUST"})
_PREFERRED_LEVELS = frozenset({"PREFERRED", "HIGH", "HIGHEST"})
_EXCLUDED_LEVELS = frozenset({"EXCLUDED"})
_PUBLIC_FIELDS = frozenset(
    {
        "candidate.category_codes",
        "candidate.taste_codes",
        "candidate.aroma_codes",
        "candidate.usage_codes",
        "candidate.feature_codes",
        "candidate.service_codes",
        "candidate.alcohol_percentage",
    }
)
_BUYER_FIELDS = frozenset(
    {
        "supply_profile.trade_profile.channels",
        "supply_profile.trade_profile.regions",
        "supply_profile.business_types",
        "supply_profile.trade_profile.oem_status",
        "supply_profile.trade_profile.private_label_status",
        "supply_profile.trade_profile.export_status",
    }
)
_LEGACY_CODE_BY_CONCEPT = {
    "BIZ_GOAL.OEM": "OEM_MISMATCH",
    "BIZ_GOAL.PRIVATE_LABEL": "PRIVATE_LABEL_MISMATCH",
    "BIZ_GOAL.EXPORT": "EXPORT_MISMATCH",
}
_LEGACY_CODE_BY_TYPE = {
    "CHANNEL": "CHANNEL_MISMATCH",
    "REGION": "REGION_MISMATCH",
}


def _fingerprint(value: object) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            default=str,
        ).encode("utf-8")
    ).hexdigest()


def _profile_codes(profile: ResolvedProfile) -> CanonicalProfileIntentCommand:
    must: set[str] = set()
    prefer: set[str] = set()
    exclude: set[str] = set()

    def collect(code: str, level: str) -> None:
        normalized = level.upper()
        if normalized in _REQUIRED_LEVELS:
            must.add(code)
        elif normalized in _EXCLUDED_LEVELS:
            exclude.add(code)
        elif normalized in _PREFERRED_LEVELS:
            prefer.add(code)

    for goal in profile.goals:
        collect(goal.code, goal.requirement_level)
    buckets: Iterable[Sequence[Any]] = (
        profile.categories,
        profile.channels,
        profile.regions,
        profile.taste,
        profile.aroma,
        *profile.extra.values(),
    )
    for bucket in buckets:
        for item in bucket:
            collect(item.code, item.level)

    prefer.difference_update(must)
    prefer.difference_update(exclude)
    return CanonicalProfileIntentCommand(
        must_codes=tuple(sorted(must)),
        prefer_codes=tuple(sorted(prefer)),
        exclude_codes=tuple(sorted(exclude)),
    )


def project_runtime_profile(profile: ResolvedProfile) -> IntentProjectionPlan:
    """Project the current canonical profile without interpreting raw text."""

    catalog = get_catalog()
    intent = normalize_canonical_profile_intent(_profile_codes(profile), catalog=catalog)
    scope = (
        CatalogScope.VERIFIED_BUYER_CATALOG
        if profile.user_type == "BUYER"
        else CatalogScope.PUBLIC_CATALOG
    )
    return project_intent(intent, catalog_scope=scope, catalog=catalog)


def _candidate_ref(candidate: MatchCandidate) -> str:
    return f"{candidate.object_type.lower()}:{candidate.object_id}"


def _evidence_ref(candidate: MatchCandidate, candidate_field: str) -> str:
    field_ref = _fingerprint(candidate_field)[:16]
    return f"candidate:{candidate.object_id}:field:{field_ref}"


def _is_publicly_approved(candidate: MatchCandidate) -> bool:
    payload = candidate.payload
    if payload.get("participation_status") == "CANCELLED":
        return False
    if candidate.object_type == "PRODUCT":
        return (
            payload.get("master_approval_status") == "APPROVED"
            and payload.get("approval_status") == "APPROVED"
        )
    if candidate.object_type == "BOOTH":
        return payload.get("exhibitor_master_approval_status") == "APPROVED"
    if candidate.object_type == "EXHIBITOR":
        return payload.get("master_approval_status") == "APPROVED"
    return False


def _is_verified_supply(candidate: MatchCandidate) -> bool:
    supply_profile = candidate.payload.get("supply_profile")
    return bool(
        _is_publicly_approved(candidate)
        and isinstance(supply_profile, Mapping)
        and supply_profile.get("approval_status") == "APPROVED"
    )


def _explicit_state(
    candidate: MatchCandidate, candidate_field: str
) -> ObservationState | None:
    states = candidate.payload.get("observation_states")
    if not isinstance(states, Mapping) or candidate_field not in states:
        return None
    return ObservationState(str(states[candidate_field]))


def _string_codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return ()
    return tuple(sorted({item for item in value if isinstance(item, str) and item}))


def _weighted_codes(value: object) -> tuple[str, ...]:
    if not isinstance(value, Mapping):
        return ()
    codes: set[str] = set()
    for code, weight in value.items():
        if not isinstance(code, str) or not code:
            continue
        try:
            if weight is not None and float(weight) > 0:
                codes.add(code)
        except (TypeError, ValueError):
            continue
    return tuple(sorted(codes))


def _service_codes(candidate: MatchCandidate) -> tuple[str, ...]:
    payload = candidate.payload
    codes = set(_string_codes(payload.get("service_codes")))
    if payload.get("tasting_status") == "AVAILABLE":
        codes.add("SERVICE.TASTING")
    if payload.get("purchase_status") in {"AVAILABLE", "LIMITED"}:
        codes.add("SERVICE.PURCHASE")
    if payload.get("consultation_enabled") is True:
        codes.add("SERVICE.CONSULTATION")
    return tuple(sorted(codes))


def _field_value(candidate: MatchCandidate, candidate_field: str) -> object:
    payload = candidate.payload
    if candidate_field == "candidate.category_codes":
        return (payload["category_code"],) if payload.get("category_code") else ()
    if candidate_field == "candidate.taste_codes":
        return _weighted_codes(payload.get("taste_json"))
    if candidate_field == "candidate.aroma_codes":
        return _weighted_codes(payload.get("aroma_json"))
    if candidate_field == "candidate.usage_codes":
        return _string_codes(payload.get("usage_json"))
    if candidate_field == "candidate.feature_codes":
        return _string_codes(payload.get("feature_json"))
    if candidate_field == "candidate.service_codes":
        return _service_codes(candidate)
    if candidate_field == "candidate.alcohol_percentage":
        return payload.get("alcohol_percentage")

    supply_profile = payload.get("supply_profile")
    if not isinstance(supply_profile, Mapping):
        return None
    trade_profile = supply_profile.get("trade_profile")
    if not isinstance(trade_profile, Mapping):
        trade_profile = {}
    if candidate_field == "supply_profile.business_types":
        return _string_codes(supply_profile.get("business_types"))
    key = candidate_field.rsplit(".", maxsplit=1)[-1]
    if key in {"channels", "regions"}:
        return _string_codes(trade_profile.get(key))
    return trade_profile.get(key)


def map_candidate_observations(
    candidate: MatchCandidate,
    plan: IntentProjectionPlan,
) -> tuple[tuple[CandidateFieldObservation, ...], tuple[str, ...]]:
    """Map only fields requested by a verified plan; raw values stay inside observations."""

    fields = tuple(
        sorted({item.candidate_field for item in plan.hard_filter_constraints})
    )
    observations: list[CandidateFieldObservation] = []
    adapter_reasons: set[str] = set()
    for candidate_field in fields:
        if candidate_field in _PUBLIC_FIELDS and not _is_publicly_approved(candidate):
            adapter_reasons.add("PUBLIC_CATALOG_NOT_APPROVED")
            continue
        if candidate_field in _BUYER_FIELDS and not _is_verified_supply(candidate):
            adapter_reasons.add("VERIFIED_SUPPLY_PROFILE_UNAVAILABLE")
            continue

        evidence_refs = (_evidence_ref(candidate, candidate_field),)
        explicit_state = _explicit_state(candidate, candidate_field)
        if explicit_state is not None and explicit_state is not ObservationState.KNOWN:
            observations.append(
                CandidateFieldObservation(
                    candidate_field,
                    explicit_state,
                    evidence_refs=evidence_refs,
                )
            )
            continue

        value = _field_value(candidate, candidate_field)
        if candidate_field.endswith("_status"):
            if value in (None, ""):
                state = ObservationState.MISSING
                observations.append(
                    CandidateFieldObservation(
                        candidate_field, state, evidence_refs=evidence_refs
                    )
                )
            elif value == "UNKNOWN":
                observations.append(
                    CandidateFieldObservation(
                        candidate_field,
                        ObservationState.UNKNOWN,
                        evidence_refs=evidence_refs,
                    )
                )
            else:
                observations.append(
                    CandidateFieldObservation(
                        candidate_field,
                        ObservationState.KNOWN,
                        status_value=str(value),
                        evidence_refs=evidence_refs,
                    )
                )
        elif candidate_field == "candidate.alcohol_percentage":
            if value is None:
                observations.append(
                    CandidateFieldObservation(
                        candidate_field,
                        ObservationState.MISSING,
                        evidence_refs=evidence_refs,
                    )
                )
            else:
                observations.append(
                    CandidateFieldObservation(
                        candidate_field,
                        ObservationState.KNOWN,
                        numeric_value=value,  # type: ignore[arg-type]
                        evidence_refs=evidence_refs,
                    )
                )
        else:
            codes = tuple(value) if isinstance(value, tuple) else ()
            if not codes:
                observations.append(
                    CandidateFieldObservation(
                        candidate_field,
                        ObservationState.MISSING,
                        evidence_refs=evidence_refs,
                    )
                )
            else:
                observations.append(
                    CandidateFieldObservation(
                        candidate_field,
                        ObservationState.KNOWN,
                        ontology_codes=codes,
                        evidence_refs=evidence_refs,
                    )
                )
    return tuple(observations), tuple(sorted(adapter_reasons))


def _legacy_code_for_constraint(concept_code: str, concept_type: str) -> str | None:
    return _LEGACY_CODE_BY_CONCEPT.get(concept_code) or _LEGACY_CODE_BY_TYPE.get(
        concept_type
    )


def _parity(
    plan: IntentProjectionPlan,
    evaluation: CandidateConstraintEvaluation,
    legacy: FilterOutcome,
) -> tuple[ShadowParityState, str]:
    if legacy.passed:
        if evaluation.outcome is CandidateEligibilityState.ELIGIBLE:
            return ShadowParityState.PARITY, "LEGACY_AND_SHADOW_ELIGIBLE"
        if evaluation.outcome is CandidateEligibilityState.INFORMATION_REQUIRED:
            return ShadowParityState.SAFETY_GAP, "LEGACY_PASSED_INFORMATION_REQUIRED"
        return ShadowParityState.SAFETY_GAP, "LEGACY_PASSED_PROJECTED_VIOLATION"

    comparable_concepts = {
        item.concept_code
        for item in plan.hard_filter_constraints
        if _legacy_code_for_constraint(item.concept_code, item.concept_type)
        == legacy.filter_code
    }
    if not comparable_concepts:
        return (
            ShadowParityState.NOT_COMPARABLE,
            "LEGACY_FILTER_OUTSIDE_PROJECTED_SCOPE",
        )
    reproduced = any(
        item.concept_code in comparable_concepts
        and item.outcome is CandidateEligibilityState.FILTERED_OUT
        for item in evaluation.constraint_decisions
    )
    if reproduced:
        return ShadowParityState.PARITY, "LEGACY_AND_SHADOW_FILTERED"
    return ShadowParityState.DIVERGENCE, "LEGACY_FILTER_NOT_REPRODUCED"


def _result(
    *,
    candidate_ref: str,
    legacy: FilterOutcome,
    parity_state: ShadowParityState,
    reason_codes: Iterable[str],
    plan_fingerprint: str | None,
    evaluation_id: str | None,
    projected_outcome: str | None,
) -> CandidateHardFilterShadow:
    normalized_reasons = tuple(sorted(set(reason_codes)))
    payload = {
        "contract_version": HARD_FILTER_SHADOW_VERSION,
        "adapter_version": CANDIDATE_OBSERVATION_ADAPTER_VERSION,
        "enforcement_enabled": HARD_FILTER_SHADOW_ENFORCEMENT,
        "candidate_ref": candidate_ref,
        "legacy_passed": legacy.passed,
        "legacy_filter_code": legacy.filter_code,
        "projected_outcome": projected_outcome,
        "parity_state": parity_state.value,
        "reason_codes": list(normalized_reasons),
        "plan_fingerprint": plan_fingerprint,
        "constraint_evaluation_id": evaluation_id,
    }
    return CandidateHardFilterShadow(
        contract_version=HARD_FILTER_SHADOW_VERSION,
        adapter_version=CANDIDATE_OBSERVATION_ADAPTER_VERSION,
        enforcement_enabled=HARD_FILTER_SHADOW_ENFORCEMENT,
        candidate_ref=candidate_ref,
        legacy_passed=legacy.passed,
        legacy_filter_code=legacy.filter_code,
        projected_outcome=projected_outcome,
        parity_state=parity_state,
        reason_codes=normalized_reasons,
        plan_fingerprint=plan_fingerprint,
        constraint_evaluation_id=evaluation_id,
        shadow_fingerprint=_fingerprint(payload),
    )


def evaluate_runtime_constraint_shadow(
    *,
    profile: ResolvedProfile,
    candidates: Sequence[MatchCandidate],
    legacy_outcomes: Sequence[FilterOutcome],
) -> tuple[CandidateHardFilterShadow, ...]:
    """Compare runtime outcomes without changing the authoritative legacy decision."""

    by_object = {item.object_id: item for item in legacy_outcomes}
    try:
        plan = project_runtime_profile(profile)
    except (TypeError, ValueError):
        plan = None

    results: list[CandidateHardFilterShadow] = []
    for candidate in sorted(
        candidates, key=lambda item: (item.object_type, str(item.object_id))
    ):
        legacy = by_object.get(candidate.object_id)
        if legacy is None:
            continue
        candidate_ref = _candidate_ref(candidate)
        if plan is None:
            results.append(
                _result(
                    candidate_ref=candidate_ref,
                    legacy=legacy,
                    parity_state=ShadowParityState.ADAPTER_ERROR,
                    reason_codes=("PROFILE_INTENT_INVALID",),
                    plan_fingerprint=None,
                    evaluation_id=None,
                    projected_outcome=None,
                )
            )
            continue
        if not plan.hard_filter_constraints and not plan.information_required:
            results.append(
                _result(
                    candidate_ref=candidate_ref,
                    legacy=legacy,
                    parity_state=ShadowParityState.NOT_APPLICABLE,
                    reason_codes=("NO_PROJECTED_HARD_CONSTRAINTS",),
                    plan_fingerprint=plan.plan_fingerprint,
                    evaluation_id=None,
                    projected_outcome=None,
                )
            )
            continue
        try:
            observations, adapter_reasons = map_candidate_observations(candidate, plan)
            evaluation = evaluate_candidate_constraints(
                plan,
                candidate_ref=candidate_ref,
                observations=observations,
                catalog=get_catalog(),
            )
        except (TypeError, ValueError):
            results.append(
                _result(
                    candidate_ref=candidate_ref,
                    legacy=legacy,
                    parity_state=ShadowParityState.ADAPTER_ERROR,
                    reason_codes=("CANDIDATE_OBSERVATION_INVALID",),
                    plan_fingerprint=plan.plan_fingerprint,
                    evaluation_id=None,
                    projected_outcome=None,
                )
            )
            continue

        parity_state, parity_reason = _parity(plan, evaluation, legacy)
        reasons = set(evaluation.reason_codes)
        reasons.update(adapter_reasons)
        reasons.add(parity_reason)
        if legacy.filter_code:
            reasons.add(f"LEGACY_FILTER_{legacy.filter_code}")
        results.append(
            _result(
                candidate_ref=candidate_ref,
                legacy=legacy,
                parity_state=parity_state,
                reason_codes=reasons,
                plan_fingerprint=plan.plan_fingerprint,
                evaluation_id=evaluation.evaluation_id,
                projected_outcome=evaluation.outcome.value,
            )
        )
    return tuple(results)


def build_runtime_constraint_shadow_gate_command(
    shadows: Sequence[CandidateHardFilterShadow],
    *,
    sample_window_ref: str,
    regression_evidence_refs: Sequence[str] = (),
    rollback_evidence_refs: Sequence[str] = (),
    safety_gap_review_evidence_refs: Sequence[str] = (),
) -> ConstraintShadowGateCommand:
    """Reduce candidate shadows to the privacy-safe aggregate gate contract."""

    state_counts: Counter[str] = Counter()
    safety_reason_counts: Counter[str] = Counter()
    seen_fingerprints: set[str] = set()
    duplicate_shadow_count = 0
    for shadow in shadows:
        if shadow.contract_version != HARD_FILTER_SHADOW_VERSION:
            raise ValueError("shadow contract version mismatch")
        if shadow.adapter_version != CANDIDATE_OBSERVATION_ADAPTER_VERSION:
            raise ValueError("shadow adapter version mismatch")
        if shadow.enforcement_enabled:
            raise ValueError("enforced shadow results cannot enter the offline gate")
        if (
            len(shadow.shadow_fingerprint) != 64
            or not set(shadow.shadow_fingerprint) <= _SHA256_HEX
        ):
            raise ValueError("shadow fingerprint must be lowercase SHA-256 hex")
        if shadow.shadow_fingerprint in seen_fingerprints:
            duplicate_shadow_count += 1
            continue
        seen_fingerprints.add(shadow.shadow_fingerprint)
        state_counts[shadow.parity_state.value] += 1
        if shadow.parity_state is ShadowParityState.SAFETY_GAP:
            safety_reason_counts.update(shadow.reason_codes)

    return ConstraintShadowGateCommand(
        sample_window_ref=sample_window_ref,
        state_counts=tuple(
            ConstraintShadowStateCount(state, state_counts[state.value])
            for state in ConstraintShadowState
        ),
        safety_gap_reason_counts=tuple(
            ConstraintShadowReasonCount(reason_code, count)
            for reason_code, count in sorted(safety_reason_counts.items())
        ),
        source_policy_versions=(
            CANDIDATE_OBSERVATION_ADAPTER_VERSION,
            HARD_FILTER_SHADOW_VERSION,
        ),
        duplicate_shadow_count=duplicate_shadow_count,
        regression_evidence_refs=tuple(regression_evidence_refs),
        rollback_evidence_refs=tuple(rollback_evidence_refs),
        safety_gap_review_evidence_refs=tuple(safety_gap_review_evidence_refs),
    )


def evaluate_runtime_constraint_shadow_gate(
    shadows: Sequence[CandidateHardFilterShadow],
    *,
    sample_window_ref: str,
    regression_evidence_refs: Sequence[str] = (),
    rollback_evidence_refs: Sequence[str] = (),
    safety_gap_review_evidence_refs: Sequence[str] = (),
) -> ConstraintShadowGateResult:
    """Evaluate runtime-safe aggregates; never authorize enforcement directly."""

    command = build_runtime_constraint_shadow_gate_command(
        shadows,
        sample_window_ref=sample_window_ref,
        regression_evidence_refs=regression_evidence_refs,
        rollback_evidence_refs=rollback_evidence_refs,
        safety_gap_review_evidence_refs=safety_gap_review_evidence_refs,
    )
    return evaluate_constraint_shadow_gate(command)
