"""Project confirmed intent into retrieval features and hard-filter constraints.

This module does not retrieve, score, rank, or decide candidate eligibility.  It emits a
versioned plan for downstream deterministic adapters.  UNKNOWN, unresolved text, and model
proposals are preserved as deferred diagnostics and can never become search terms, numeric
features, or filter decisions here.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from enum import StrEnum
from typing import Any

from meet_ai.ontology import Catalog, load_catalog

from .intent_normalization import (
    INTENT_NORMALIZATION_POLICY_VERSION,
    INTENT_NORMALIZATION_RESULT_V1,
    IntentRequirement,
    NormalizedIntent,
)

INTENT_PROJECTION_RESULT_V1 = "intent-projection-result-v1.0"
INTENT_PROJECTION_POLICY_VERSION = "intent-projection-v1.0"
CANDIDATE_CAPABILITY_VERSION = "candidate-capability-v1.0"
PUBLISHED_RANKING_STATE = "WEIGHTED_V1_UNCHANGED"

_FINGERPRINT = re.compile(r"^[0-9a-f]{64}$")


class IntentProjectionValidationError(ValueError):
    """Raised when an intent cannot safely enter the projection boundary."""


class CatalogScope(StrEnum):
    PUBLIC_CATALOG = "PUBLIC_CATALOG"
    VERIFIED_BUYER_CATALOG = "VERIFIED_BUYER_CATALOG"


class ConstraintOperator(StrEnum):
    REQUIRE_MATCH = "REQUIRE_MATCH"
    FORBID_MATCH = "FORBID_MATCH"


class VerificationMode(StrEnum):
    ONTOLOGY_MATCH = "ONTOLOGY_MATCH"
    DERIVED_BAND_MATCH = "DERIVED_BAND_MATCH"
    TRADE_STATUS = "TRADE_STATUS"


@dataclass(frozen=True, slots=True)
class RetrievalFeature:
    concept_code: str
    concept_type: str
    channel: str = "STRUCTURED_ONTOLOGY"
    usage: str = "CANDIDATE_RECALL_ONLY"


@dataclass(frozen=True, slots=True)
class HardFilterConstraint:
    concept_code: str
    concept_type: str
    operator: ConstraintOperator
    candidate_field: str
    verification_mode: VerificationMode
    unknown_outcome: str = "INFORMATION_REQUIRED"
    missing_outcome: str = "INFORMATION_REQUIRED"


@dataclass(frozen=True, slots=True)
class InformationRequired:
    concept_code: str
    concept_type: str
    requirement: IntentRequirement
    reason_code: str


@dataclass(frozen=True, slots=True)
class DeferredIntent:
    kind: str
    reference: str
    reason_code: str


@dataclass(frozen=True, slots=True)
class IntentProjectionPlan:
    contract_version: str
    policy_version: str
    capability_version: str
    ontology_version: str
    catalog_scope: CatalogScope
    retrieval_features: tuple[RetrievalFeature, ...]
    hard_filter_constraints: tuple[HardFilterConstraint, ...]
    information_required: tuple[InformationRequired, ...]
    deferred: tuple[DeferredIntent, ...]
    ranking_state: str
    source_intent_fingerprint: str
    semantic_input_fingerprint: str
    plan_fingerprint: str
    result_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class _CapabilityBinding:
    candidate_field: str
    verification_mode: VerificationMode
    minimum_scope: CatalogScope


_TYPE_BINDINGS: dict[str, _CapabilityBinding] = {
    "PRODUCT_CATEGORY": _CapabilityBinding(
        "candidate.category_codes",
        VerificationMode.ONTOLOGY_MATCH,
        CatalogScope.PUBLIC_CATALOG,
    ),
    "TASTE": _CapabilityBinding(
        "candidate.taste_codes",
        VerificationMode.ONTOLOGY_MATCH,
        CatalogScope.PUBLIC_CATALOG,
    ),
    "AROMA": _CapabilityBinding(
        "candidate.aroma_codes",
        VerificationMode.ONTOLOGY_MATCH,
        CatalogScope.PUBLIC_CATALOG,
    ),
    "USE_CASE": _CapabilityBinding(
        "candidate.usage_codes",
        VerificationMode.ONTOLOGY_MATCH,
        CatalogScope.PUBLIC_CATALOG,
    ),
    "PRODUCT_FEATURE": _CapabilityBinding(
        "candidate.feature_codes",
        VerificationMode.ONTOLOGY_MATCH,
        CatalogScope.PUBLIC_CATALOG,
    ),
    "BOOTH_SERVICE": _CapabilityBinding(
        "candidate.service_codes",
        VerificationMode.ONTOLOGY_MATCH,
        CatalogScope.PUBLIC_CATALOG,
    ),
    "ALCOHOL_LEVEL": _CapabilityBinding(
        "candidate.alcohol_percentage",
        VerificationMode.DERIVED_BAND_MATCH,
        CatalogScope.PUBLIC_CATALOG,
    ),
    "CHANNEL": _CapabilityBinding(
        "supply_profile.trade_profile.channels",
        VerificationMode.ONTOLOGY_MATCH,
        CatalogScope.VERIFIED_BUYER_CATALOG,
    ),
    "REGION": _CapabilityBinding(
        "supply_profile.trade_profile.regions",
        VerificationMode.ONTOLOGY_MATCH,
        CatalogScope.VERIFIED_BUYER_CATALOG,
    ),
    "TRADE_TYPE": _CapabilityBinding(
        "supply_profile.business_types",
        VerificationMode.ONTOLOGY_MATCH,
        CatalogScope.VERIFIED_BUYER_CATALOG,
    ),
}

_CODE_BINDINGS: dict[str, _CapabilityBinding] = {
    "BIZ_GOAL.OEM": _CapabilityBinding(
        "supply_profile.trade_profile.oem_status",
        VerificationMode.TRADE_STATUS,
        CatalogScope.VERIFIED_BUYER_CATALOG,
    ),
    "BIZ_GOAL.PRIVATE_LABEL": _CapabilityBinding(
        "supply_profile.trade_profile.private_label_status",
        VerificationMode.TRADE_STATUS,
        CatalogScope.VERIFIED_BUYER_CATALOG,
    ),
    "BIZ_GOAL.EXPORT": _CapabilityBinding(
        "supply_profile.trade_profile.export_status",
        VerificationMode.TRADE_STATUS,
        CatalogScope.VERIFIED_BUYER_CATALOG,
    ),
}

_BUYER_ONLY_TYPES = frozenset(
    {
        "BUSINESS_GOAL",
        "BUYER_TYPE",
        "CHANNEL",
        "MEETING_TOPIC",
        "REGION",
        "SUPPLY_CAPACITY",
        "TRADE_TYPE",
    }
)


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
        raise IntentProjectionValidationError(
            "intent projection requires a published ontology"
        )
    return selected


def _scope_allows(required: CatalogScope, selected: CatalogScope) -> bool:
    return required is CatalogScope.PUBLIC_CATALOG or selected is required


def _semantic_intent_payload(intent: NormalizedIntent) -> dict[str, Any]:
    return {
        "ontology_version": intent.ontology_version,
        "must": sorted(item.concept_code for item in intent.must),
        "prefer": sorted(item.concept_code for item in intent.prefer),
        "exclude": sorted(item.concept_code for item in intent.exclude),
        "unknown": sorted(item.field_code for item in intent.unknown),
        "unresolved": sorted(
            (
                item.reason_code,
                tuple(item.candidate_codes),
                item.term_fingerprint,
            )
            for item in intent.unresolved
        ),
        "proposals": sorted(
            (item.requirement.value, item.concept_code) for item in intent.proposals
        ),
    }


def _validate_intent(intent: NormalizedIntent, catalog: Catalog) -> None:
    if intent.contract_version != INTENT_NORMALIZATION_RESULT_V1:
        raise IntentProjectionValidationError(
            f"intent contract must be {INTENT_NORMALIZATION_RESULT_V1}"
        )
    if intent.policy_version != INTENT_NORMALIZATION_POLICY_VERSION:
        raise IntentProjectionValidationError(
            f"intent policy must be {INTENT_NORMALIZATION_POLICY_VERSION}"
        )
    if intent.ontology_version != catalog.version:
        raise IntentProjectionValidationError(
            "intent ontology_version must match the published ontology"
        )
    if not _FINGERPRINT.fullmatch(intent.result_fingerprint):
        raise IntentProjectionValidationError("intent result_fingerprint is invalid")

    seen: set[str] = set()
    for requirement, items in (
        (IntentRequirement.MUST, intent.must),
        (IntentRequirement.PREFER, intent.prefer),
        (IntentRequirement.EXCLUDE, intent.exclude),
    ):
        for item in items:
            concept = catalog.by_code.get(item.concept_code)
            if concept is None or concept.get("assignable", True) is False:
                raise IntentProjectionValidationError(
                    "resolved intent must use a published assignable concept"
                )
            if item.concept_type != concept.get("concept_type"):
                raise IntentProjectionValidationError(
                    "resolved intent concept_type does not match the ontology"
                )
            if item.requirement is not requirement:
                raise IntentProjectionValidationError(
                    "resolved intent is in the wrong requirement bucket"
                )
            if item.concept_code in seen:
                raise IntentProjectionValidationError(
                    "resolved intent contains conflicting duplicate concepts"
                )
            seen.add(item.concept_code)


def _binding(concept_code: str, concept_type: str) -> _CapabilityBinding | None:
    return _CODE_BINDINGS.get(concept_code) or _TYPE_BINDINGS.get(concept_type)


def _deferred(intent: NormalizedIntent) -> tuple[DeferredIntent, ...]:
    values: list[DeferredIntent] = []
    values.extend(
        DeferredIntent("UNKNOWN", item.field_code, "SUBJECT_VALUE_UNKNOWN")
        for item in intent.unknown
    )
    values.extend(
        DeferredIntent("UNRESOLVED", item.term_fingerprint, item.reason_code)
        for item in intent.unresolved
    )
    values.extend(
        DeferredIntent(
            "PROPOSAL_ONLY",
            _fingerprint(
                {
                    "concept_code": item.concept_code,
                    "requirement": item.requirement.value,
                    "state": item.proposal_state,
                }
            ),
            "MODEL_PROPOSAL_NOT_CONFIRMED",
        )
        for item in intent.proposals
    )
    return tuple(sorted(values, key=lambda item: (item.kind, item.reason_code, item.reference)))


def project_intent(
    intent: NormalizedIntent,
    *,
    catalog_scope: CatalogScope | str,
    catalog: Catalog | None = None,
) -> IntentProjectionPlan:
    """Build a deterministic plan without invoking retrieval, filtering, or ranking."""

    selected_catalog = _published_catalog(catalog)
    try:
        selected_scope = CatalogScope(catalog_scope)
    except ValueError as exc:
        raise IntentProjectionValidationError("catalog_scope is invalid") from exc
    _validate_intent(intent, selected_catalog)

    retrieval: list[RetrievalFeature] = []
    constraints: list[HardFilterConstraint] = []
    information_required: list[InformationRequired] = []
    deferred = list(_deferred(intent))

    for item in intent.prefer:
        if (
            selected_scope is CatalogScope.PUBLIC_CATALOG
            and item.concept_type in _BUYER_ONLY_TYPES
        ):
            deferred.append(
                DeferredIntent(
                    "PREFER",
                    _fingerprint(
                        {
                            "concept_code": item.concept_code,
                            "scope": selected_scope.value,
                        }
                    ),
                    "CATALOG_SCOPE_RESTRICTED",
                )
            )
            continue
        retrieval.append(RetrievalFeature(item.concept_code, item.concept_type))

    for requirement, items, operator in (
        (IntentRequirement.MUST, intent.must, ConstraintOperator.REQUIRE_MATCH),
        (IntentRequirement.EXCLUDE, intent.exclude, ConstraintOperator.FORBID_MATCH),
    ):
        for item in items:
            binding = _binding(item.concept_code, item.concept_type)
            if binding is None:
                information_required.append(
                    InformationRequired(
                        item.concept_code,
                        item.concept_type,
                        requirement,
                        "NO_VERIFIABLE_CANDIDATE_FIELD",
                    )
                )
                continue
            if not _scope_allows(binding.minimum_scope, selected_scope):
                information_required.append(
                    InformationRequired(
                        item.concept_code,
                        item.concept_type,
                        requirement,
                        "CATALOG_SCOPE_RESTRICTED",
                    )
                )
                continue
            constraints.append(
                HardFilterConstraint(
                    concept_code=item.concept_code,
                    concept_type=item.concept_type,
                    operator=operator,
                    candidate_field=binding.candidate_field,
                    verification_mode=binding.verification_mode,
                )
            )

    normalized_retrieval = tuple(
        sorted(retrieval, key=lambda item: (item.concept_type, item.concept_code))
    )
    normalized_constraints = tuple(
        sorted(
            constraints,
            key=lambda item: (item.operator.value, item.concept_type, item.concept_code),
        )
    )
    normalized_required = tuple(
        sorted(
            information_required,
            key=lambda item: (item.requirement.value, item.concept_type, item.concept_code),
        )
    )
    normalized_deferred = tuple(
        sorted(deferred, key=lambda item: (item.kind, item.reason_code, item.reference))
    )
    semantic_input_fingerprint = _fingerprint(_semantic_intent_payload(intent))
    plan_payload = {
        "contract_version": INTENT_PROJECTION_RESULT_V1,
        "policy_version": INTENT_PROJECTION_POLICY_VERSION,
        "capability_version": CANDIDATE_CAPABILITY_VERSION,
        "ontology_version": selected_catalog.version,
        "catalog_scope": selected_scope.value,
        "retrieval_features": [asdict(item) for item in normalized_retrieval],
        "hard_filter_constraints": [asdict(item) for item in normalized_constraints],
        "information_required": [asdict(item) for item in normalized_required],
        "deferred": [asdict(item) for item in normalized_deferred],
        "ranking_state": PUBLISHED_RANKING_STATE,
        "semantic_input_fingerprint": semantic_input_fingerprint,
    }
    plan_fingerprint = _fingerprint(plan_payload)
    return IntentProjectionPlan(
        contract_version=INTENT_PROJECTION_RESULT_V1,
        policy_version=INTENT_PROJECTION_POLICY_VERSION,
        capability_version=CANDIDATE_CAPABILITY_VERSION,
        ontology_version=selected_catalog.version,
        catalog_scope=selected_scope,
        retrieval_features=normalized_retrieval,
        hard_filter_constraints=normalized_constraints,
        information_required=normalized_required,
        deferred=normalized_deferred,
        ranking_state=PUBLISHED_RANKING_STATE,
        source_intent_fingerprint=intent.result_fingerprint,
        semantic_input_fingerprint=semantic_input_fingerprint,
        plan_fingerprint=plan_fingerprint,
        result_fingerprint=_fingerprint(
            {
                **plan_payload,
                "plan_fingerprint": plan_fingerprint,
                "source_intent_fingerprint": intent.result_fingerprint,
            }
        ),
    )
