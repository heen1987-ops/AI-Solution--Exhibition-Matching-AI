"""Versioned, provider-independent execution facade for matching policies.

The facade is the only orchestration layer that selects a published score policy.  It
accepts already-recalled candidates plus immutable eligibility decisions, excludes
failed candidates before scoring, and returns a stable rank with complete version and
fingerprint provenance.  Database access, HTTP frameworks, and AI providers belong in
adapters outside this package.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from enum import Enum
from types import MappingProxyType

from meet_ai.scoring import (
    BUYER_SCORE_V1,
    CONSUMER_SCORE_V1,
    EXHIBITOR_SCORE_V1,
    RECIPROCAL_SCORE_V1,
    DirectionalScoreResult,
    EligibilityDecision,
    ReciprocalScoreResult,
    ScoreCap,
    ScoreValidationError,
    calculate_directional_score,
    calculate_reciprocal_score,
)

Number = Decimal | float | int | str

MATCHING_ENGINE_COMMAND_V1 = "matching-engine-command-v1.0"
MATCHING_ENGINE_RESULT_V1 = "matching-engine-result-v1.0"
MATCHING_ENGINE_COMMAND_V1_1 = "matching-engine-command-v1.1"
MATCHING_ENGINE_RESULT_V1_1 = "matching-engine-result-v1.1"
MATCHING_ENGINE_VERSION_V1 = "matching-engine-v1.0"
MATCHING_ENGINE_VERSION = "matching-engine-v1.1"
CATALOG_SEARCH_POLICY_VERSION = "catalog-search-score-v1.0"
REASON_CLAIM_POLICY_VERSION = "reason-claim-v1.0"

_CATALOG_SEARCH_WEIGHTS = MappingProxyType(
    {
        "semantic": Decimal("0.45"),
        "keyword": Decimal("0.30"),
        "category": Decimal("0.15"),
        "data_quality": Decimal("0.05"),
        "booth_availability": Decimal("0.05"),
    }
)
_EMPTY_MAPPING: Mapping[str, Number | None] = MappingProxyType({})
_EMPTY_EVIDENCE: Mapping[str, tuple[str, ...]] = MappingProxyType({})
_MAX_REASON_CLAIMS = 3


class MatchingMode(str, Enum):
    CATALOG_SEARCH = "CATALOG_SEARCH"
    GENERAL_VISITOR = "GENERAL_VISITOR"
    BUYER_TO_EXHIBITOR = "BUYER_TO_EXHIBITOR"
    RECIPROCAL = "RECIPROCAL"


_DIRECTIONAL_REASON_COMPONENTS = MappingProxyType(
    {
        MatchingMode.GENERAL_VISITOR: MappingProxyType(
            {
                "goal": "GOAL_MATCH",
                "category": "CATEGORY_MATCH",
                "sensory": "TASTE_MATCH",
                "price": "PRICE_MATCH",
                "alcohol": "ALCOHOL_MATCH",
                "service": "SERVICE_MATCH",
                "usage": "USAGE_MATCH",
                "behavior": "BEHAVIOR_MATCH",
                "trust": "DATA_TRUST",
            }
        ),
        MatchingMode.BUYER_TO_EXHIBITOR: MappingProxyType(
            {
                "business_goal": "BUSINESS_GOAL_MATCH",
                "product": "PRODUCT_MATCH",
                "channel": "CHANNEL_MATCH",
                "price": "PRICE_MATCH",
                "moq": "MOQ_MATCH",
                "capacity": "CAPACITY_MATCH",
                "region": "REGION_MATCH",
                "cooperation": "COOPERATION_MATCH",
                "meeting": "MEETING_AVAILABLE",
                "trust": "DATA_TRUST",
            }
        ),
    }
)
_CATALOG_REASON_SIGNALS = MappingProxyType(
    {
        "semantic": "SEMANTIC_MATCH",
        "keyword": "KEYWORD_MATCH",
        "category": "CATEGORY_MATCH",
        "data_quality": "DATA_TRUST",
        "booth_availability": "AVAILABILITY",
    }
)


class MatchingEngineValidationError(ScoreValidationError):
    """Raised when a command violates the facade contract."""


def _decimal(value: Number, *, field_name: str) -> Decimal:
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise MatchingEngineValidationError(f"{field_name} must be numeric") from exc
    if not converted.is_finite():
        raise MatchingEngineValidationError(f"{field_name} must be finite")
    return converted


def _decimal_text(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == normalized.to_integral():
        return str(normalized.quantize(Decimal(1)))
    return format(normalized, "f")


def _canonical_number(value: Number | None) -> str | None:
    if value is None:
        return None
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return str(value)
    return _decimal_text(converted) if converted.is_finite() else str(converted)


def _fingerprint(payload: object) -> str:
    serialized = json.dumps(
        payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


def _frozen_components(
    values: Mapping[str, Number | None], *, field_name: str
) -> Mapping[str, Number | None]:
    normalized: dict[str, Number | None] = {}
    for name, value in sorted(values.items()):
        if not name.strip():
            raise MatchingEngineValidationError(f"{field_name} contains a blank code")
        normalized[name] = value
    return MappingProxyType(normalized)


def _frozen_reason_evidence(
    values: Mapping[str, Sequence[str]], *, field_name: str
) -> Mapping[str, tuple[str, ...]]:
    normalized: dict[str, tuple[str, ...]] = {}
    for raw_code, raw_refs in sorted(values.items(), key=lambda item: str(item[0])):
        if not isinstance(raw_code, str):
            raise MatchingEngineValidationError(f"{field_name} codes must be strings")
        code = raw_code.strip().upper()
        if not code:
            raise MatchingEngineValidationError(f"{field_name} contains a blank code")
        if code in normalized:
            raise MatchingEngineValidationError(
                f"{field_name} contains duplicate normalized code {code}"
            )
        if isinstance(raw_refs, (str, bytes)):
            raise MatchingEngineValidationError(
                f"{field_name}.{code} must be a sequence of evidence refs"
            )
        if any(not isinstance(ref, str) for ref in raw_refs):
            raise MatchingEngineValidationError(
                f"{field_name}.{code} evidence refs must be strings"
            )
        refs = tuple(sorted({ref.strip() for ref in raw_refs if ref.strip()}))
        if not refs:
            raise MatchingEngineValidationError(
                f"{field_name}.{code} requires at least one evidence_ref"
            )
        normalized[code] = refs
    return MappingProxyType(normalized)


@dataclass(frozen=True, slots=True)
class ReasonClaim:
    """A deterministic, evidence-bound claim safe for template rendering."""

    code: str
    evidence_refs: tuple[str, ...]
    source_components: tuple[str, ...]
    contribution_score: Decimal | None
    policy_version: str
    claim_fingerprint: str


@dataclass(frozen=True, slots=True)
class CatalogSearchSignals:
    semantic: Number
    keyword: Number
    category: Number
    data_quality: Number
    booth_availability: Number


@dataclass(frozen=True, slots=True)
class CatalogSearchScoreResult:
    policy_version: str
    normalized_signals: Mapping[str, Decimal]
    final_score: Decimal
    calculation_fingerprint: str


def _clamp_catalog_signal(value: Number) -> Decimal:
    """Preserve the frozen kiosk behavior: invalid values become zero, then clamp."""

    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return Decimal(0)
    if not converted.is_finite():
        return Decimal(0)
    return min(max(converted, Decimal(0)), Decimal(1))


def score_catalog_search(signals: CatalogSearchSignals) -> CatalogSearchScoreResult:
    """Apply the frozen five-signal formula without fallback renormalization."""

    normalized = {
        name: _clamp_catalog_signal(getattr(signals, name))
        for name in _CATALOG_SEARCH_WEIGHTS
    }
    final_score = sum(
        (_CATALOG_SEARCH_WEIGHTS[name] * normalized[name] for name in normalized),
        Decimal(0),
    )
    payload = {
        "policy_version": CATALOG_SEARCH_POLICY_VERSION,
        "signals": {name: _decimal_text(value) for name, value in normalized.items()},
        "weights": {
            name: _decimal_text(value)
            for name, value in _CATALOG_SEARCH_WEIGHTS.items()
        },
    }
    return CatalogSearchScoreResult(
        policy_version=CATALOG_SEARCH_POLICY_VERSION,
        normalized_signals=MappingProxyType(normalized),
        final_score=final_score,
        calculation_fingerprint=_fingerprint(payload),
    )


@dataclass(frozen=True, slots=True)
class MatchingCandidateCommand:
    candidate_id: str
    exhibitor_id: str
    eligibility: EligibilityDecision
    recalled: bool = True
    recall_channels: tuple[str, ...] = ()
    components: Mapping[str, Number | None] = field(
        default_factory=lambda: _EMPTY_MAPPING
    )
    buyer_components: Mapping[str, Number | None] = field(
        default_factory=lambda: _EMPTY_MAPPING
    )
    exhibitor_components: Mapping[str, Number | None] = field(
        default_factory=lambda: _EMPTY_MAPPING
    )
    search_signals: CatalogSearchSignals | None = None
    confidence: Number | None = None
    buyer_confidence: Number | None = None
    exhibitor_confidence: Number | None = None
    acceptance_capacity_score: Number = Decimal("0.5")
    policy_adjustment: Number = Decimal(0)
    score_caps: tuple[ScoreCap, ...] = ()
    buyer_caps: tuple[ScoreCap, ...] = ()
    exhibitor_caps: tuple[ScoreCap, ...] = ()
    reason_evidence: Mapping[str, Sequence[str]] = field(
        default_factory=lambda: _EMPTY_EVIDENCE
    )

    def __post_init__(self) -> None:
        if not self.candidate_id.strip():
            raise MatchingEngineValidationError("candidate_id is required")
        if not self.exhibitor_id.strip():
            raise MatchingEngineValidationError("exhibitor_id is required")
        channels = tuple(sorted(set(self.recall_channels)))
        if any(not channel.strip() for channel in channels):
            raise MatchingEngineValidationError("recall channels cannot be blank")
        object.__setattr__(self, "recall_channels", channels)
        for name in ("components", "buyer_components", "exhibitor_components"):
            object.__setattr__(
                self,
                name,
                _frozen_components(getattr(self, name), field_name=name),
            )
        object.__setattr__(self, "score_caps", tuple(self.score_caps))
        object.__setattr__(self, "buyer_caps", tuple(self.buyer_caps))
        object.__setattr__(self, "exhibitor_caps", tuple(self.exhibitor_caps))
        object.__setattr__(
            self,
            "reason_evidence",
            _frozen_reason_evidence(
                self.reason_evidence, field_name="reason_evidence"
            ),
        )


@dataclass(frozen=True, slots=True)
class MatchingEngineCommand:
    mode: MatchingMode | str
    taxonomy_version: str
    candidates: tuple[MatchingCandidateCommand, ...]
    model_version: str | None = None
    contract_version: str = MATCHING_ENGINE_COMMAND_V1_1

    def __post_init__(self) -> None:
        supported = {MATCHING_ENGINE_COMMAND_V1, MATCHING_ENGINE_COMMAND_V1_1}
        if self.contract_version not in supported:
            raise MatchingEngineValidationError(
                f"unsupported command contract: {self.contract_version}"
            )
        if self.contract_version == MATCHING_ENGINE_COMMAND_V1 and any(
            candidate.reason_evidence for candidate in self.candidates
        ):
            raise MatchingEngineValidationError(
                "matching-engine-command-v1.0 does not support reason_evidence"
            )
        try:
            mode = MatchingMode(self.mode)
        except ValueError as exc:
            raise MatchingEngineValidationError(
                f"unknown matching mode: {self.mode}"
            ) from exc
        if not self.taxonomy_version.strip():
            raise MatchingEngineValidationError("taxonomy_version is required")
        if self.model_version is not None and not self.model_version.strip():
            raise MatchingEngineValidationError("model_version cannot be blank")
        candidate_ids = [candidate.candidate_id for candidate in self.candidates]
        if len(candidate_ids) != len(set(candidate_ids)):
            raise MatchingEngineValidationError(
                "candidate_id must be unique per command"
            )
        object.__setattr__(self, "mode", mode)
        object.__setattr__(self, "candidates", tuple(self.candidates))


@dataclass(frozen=True, slots=True)
class ExcludedCandidateResult:
    candidate_id: str
    exhibitor_id: str
    eligibility_evaluation_id: str
    reason_codes: tuple[str, ...]
    reason_claims: tuple[ReasonClaim, ...] = ()


@dataclass(frozen=True, slots=True)
class RankedCandidateResult:
    candidate_id: str
    exhibitor_id: str
    rank: int
    eligibility_evaluation_id: str
    normalized_score: Decimal
    score_100: Decimal
    grade: str | None
    match_status: str | None
    recommended_action: str | None
    policy_versions: Mapping[str, str]
    score_fingerprints: Mapping[str, str]
    calculation_fingerprint: str
    reason_claims: tuple[ReasonClaim, ...] = ()
    reason_fingerprint: str | None = None
    directional_result: DirectionalScoreResult | None = field(
        default=None, repr=False, compare=False
    )
    buyer_directional_result: DirectionalScoreResult | None = field(
        default=None, repr=False, compare=False
    )
    exhibitor_directional_result: DirectionalScoreResult | None = field(
        default=None, repr=False, compare=False
    )
    reciprocal_result: ReciprocalScoreResult | None = field(
        default=None, repr=False, compare=False
    )
    catalog_search_result: CatalogSearchScoreResult | None = field(
        default=None, repr=False, compare=False
    )


@dataclass(frozen=True, slots=True)
class MatchingEngineResult:
    contract_version: str
    engine_version: str
    mode: MatchingMode
    taxonomy_version: str
    model_version: str | None
    policy_versions: Mapping[str, str]
    input_fingerprint: str
    result_fingerprint: str
    ranked_candidates: tuple[RankedCandidateResult, ...]
    excluded_candidates: tuple[ExcludedCandidateResult, ...]


def _policies_for_mode(mode: MatchingMode) -> Mapping[str, str]:
    if mode is MatchingMode.CATALOG_SEARCH:
        policies = {"catalog_search": CATALOG_SEARCH_POLICY_VERSION}
    elif mode is MatchingMode.GENERAL_VISITOR:
        policies = {"consumer": CONSUMER_SCORE_V1.version}
    elif mode is MatchingMode.BUYER_TO_EXHIBITOR:
        policies = {"buyer": BUYER_SCORE_V1.version}
    else:
        policies = {
            "buyer": BUYER_SCORE_V1.version,
            "exhibitor": EXHIBITOR_SCORE_V1.version,
            "reciprocal": RECIPROCAL_SCORE_V1.version,
        }
    return MappingProxyType(policies)


def _caps_payload(caps: Sequence[ScoreCap]) -> list[dict[str, str]]:
    return [
        {"code": cap.code, "maximum": _decimal_text(cap.maximum)}
        for cap in sorted(caps, key=lambda item: (item.maximum, item.code))
    ]


def _components_payload(values: Mapping[str, Number | None]) -> dict[str, str | None]:
    return {name: _canonical_number(value) for name, value in sorted(values.items())}


def _candidate_input_payload(
    candidate: MatchingCandidateCommand, *, include_reason_evidence: bool
) -> dict[str, object]:
    search_signals = None
    if candidate.search_signals is not None:
        search_signals = {
            name: _canonical_number(getattr(candidate.search_signals, name))
            for name in _CATALOG_SEARCH_WEIGHTS
        }
    payload: dict[str, object] = {
        "candidate_id": candidate.candidate_id,
        "exhibitor_id": candidate.exhibitor_id,
        "eligibility": {
            "evaluation_id": candidate.eligibility.evaluation_id,
            "passed": candidate.eligibility.passed,
            "reason_codes": sorted(candidate.eligibility.reason_codes),
        },
        "recalled": candidate.recalled,
        "recall_channels": list(candidate.recall_channels),
        "components": _components_payload(candidate.components),
        "buyer_components": _components_payload(candidate.buyer_components),
        "exhibitor_components": _components_payload(candidate.exhibitor_components),
        "search_signals": search_signals,
        "confidence": _canonical_number(candidate.confidence),
        "buyer_confidence": _canonical_number(candidate.buyer_confidence),
        "exhibitor_confidence": _canonical_number(candidate.exhibitor_confidence),
        "acceptance_capacity_score": _canonical_number(
            candidate.acceptance_capacity_score
        ),
        "policy_adjustment": _canonical_number(candidate.policy_adjustment),
        "score_caps": _caps_payload(candidate.score_caps),
        "buyer_caps": _caps_payload(candidate.buyer_caps),
        "exhibitor_caps": _caps_payload(candidate.exhibitor_caps),
    }
    if include_reason_evidence:
        payload["reason_evidence"] = {
            code: list(refs) for code, refs in candidate.reason_evidence.items()
        }
    return payload


def _claim(
    reason_evidence: Mapping[str, tuple[str, ...]],
    code: str,
    source_components: Sequence[str],
    contribution: Decimal | None,
) -> ReasonClaim | None:
    evidence_refs = reason_evidence.get(code)
    if not evidence_refs:
        return None
    sources = tuple(sorted(set(source_components)))
    payload = {
        "policy_version": REASON_CLAIM_POLICY_VERSION,
        "code": code,
        "evidence_refs": list(evidence_refs),
        "source_components": list(sources),
        "contribution_score": _canonical_number(contribution),
    }
    return ReasonClaim(
        code=code,
        evidence_refs=evidence_refs,
        source_components=sources,
        contribution_score=contribution,
        policy_version=REASON_CLAIM_POLICY_VERSION,
        claim_fingerprint=_fingerprint(payload),
    )


def _ordered_claims(claims: Sequence[ReasonClaim | None]) -> tuple[ReasonClaim, ...]:
    grounded = [claim for claim in claims if claim is not None]
    return tuple(
        sorted(
            grounded,
            key=lambda item: (
                -(item.contribution_score or Decimal(0)),
                item.code,
                item.evidence_refs,
            ),
        )[:_MAX_REASON_CLAIMS]
    )


def _reason_fingerprint(claims: Sequence[ReasonClaim]) -> str:
    return _fingerprint([claim.claim_fingerprint for claim in claims])


def _eligibility_reason_claims(
    candidate: MatchingCandidateCommand, reason_codes: Sequence[str]
) -> tuple[ReasonClaim, ...]:
    return _ordered_claims(
        [
            _claim(
                candidate.reason_evidence,
                code,
                (f"eligibility:{code}",),
                None,
            )
            for code in sorted(set(reason_codes))
        ]
    )


def derive_directional_reason_claims(
    mode: MatchingMode | str,
    contributions: Mapping[str, Number],
    *,
    recall_channels: Sequence[str] = (),
    reason_evidence: Mapping[str, Sequence[str]],
) -> tuple[ReasonClaim, ...]:
    resolved_mode = MatchingMode(mode)
    if resolved_mode not in _DIRECTIONAL_REASON_COMPONENTS:
        raise MatchingEngineValidationError(
            f"directional reason claims do not support {resolved_mode.value}"
        )
    evidence = _frozen_reason_evidence(reason_evidence, field_name="reason_evidence")
    claims: list[ReasonClaim | None] = []
    for component, code in _DIRECTIONAL_REASON_COMPONENTS[resolved_mode].items():
        raw_contribution = contributions.get(component)
        contribution = (
            None
            if raw_contribution is None
            else _decimal(raw_contribution, field_name=f"contributions.{component}")
        )
        if contribution is not None and contribution > 0:
            claims.append(
                _claim(evidence, code, (f"component:{component}",), contribution)
            )
    if "VECTOR" in recall_channels:
        claims.append(_claim(evidence, "SEMANTIC_MATCH", ("recall:VECTOR",), None))
    return _ordered_claims(claims)


def _directional_reason_claims(
    mode: MatchingMode,
    candidate: MatchingCandidateCommand,
    result: DirectionalScoreResult,
) -> tuple[ReasonClaim, ...]:
    return derive_directional_reason_claims(
        mode,
        result.contributions,
        recall_channels=candidate.recall_channels,
        reason_evidence=candidate.reason_evidence,
    )


def _catalog_reason_claims(
    candidate: MatchingCandidateCommand, result: CatalogSearchScoreResult
) -> tuple[ReasonClaim, ...]:
    claims: list[ReasonClaim | None] = []
    for signal, code in _CATALOG_REASON_SIGNALS.items():
        value = result.normalized_signals[signal]
        if value > 0:
            claims.append(
                _claim(
                    candidate.reason_evidence,
                    code,
                    (f"search_signal:{signal}",),
                    _CATALOG_SEARCH_WEIGHTS[signal] * value,
                )
            )
    return _ordered_claims(claims)


def derive_reciprocal_reason_claims(
    buyer_contributions: Mapping[str, Number],
    exhibitor_contributions: Mapping[str, Number],
    *,
    imbalance_value: Number,
    recall_channels: Sequence[str] = (),
    reason_evidence: Mapping[str, Sequence[str]],
) -> tuple[ReasonClaim, ...]:
    evidence = _frozen_reason_evidence(reason_evidence, field_name="reason_evidence")

    def minimum_contribution(buyer_name: str, exhibitor_name: str) -> Decimal | None:
        buyer_raw = buyer_contributions.get(buyer_name)
        exhibitor_raw = exhibitor_contributions.get(exhibitor_name)
        buyer_value = (
            None
            if buyer_raw is None
            else _decimal(buyer_raw, field_name=f"buyer_contributions.{buyer_name}")
        )
        exhibitor_value = (
            None
            if exhibitor_raw is None
            else _decimal(
                exhibitor_raw,
                field_name=f"exhibitor_contributions.{exhibitor_name}",
            )
        )
        if buyer_value is None or exhibitor_value is None:
            return None
        return min(buyer_value, exhibitor_value)

    claims: list[ReasonClaim | None] = []
    mutual_channel = minimum_contribution("channel", "channel")
    if mutual_channel is not None and mutual_channel > 0:
        claims.append(
            _claim(
                evidence,
                "MUTUAL_CHANNEL_MATCH",
                ("buyer_component:channel", "exhibitor_component:channel"),
                mutual_channel,
            )
        )
    mutual_product = minimum_contribution("product", "portfolio")
    if mutual_product is not None and mutual_product > 0:
        claims.append(
            _claim(
                evidence,
                "MUTUAL_PRODUCT_MATCH",
                ("buyer_component:product", "exhibitor_component:portfolio"),
                mutual_product,
            )
        )
    meeting = minimum_contribution("meeting", "meeting_readiness")
    if meeting is not None and meeting > 0:
        claims.append(
            _claim(
                evidence,
                "MEETING_AVAILABLE",
                ("buyer_component:meeting", "exhibitor_component:meeting_readiness"),
                meeting,
            )
        )
    imbalance = _decimal(imbalance_value, field_name="imbalance_value")
    if imbalance > 0:
        claims.append(
            _claim(
                evidence,
                "DIRECTION_IMBALANCE",
                ("reciprocal:buyer_score", "reciprocal:exhibitor_score"),
                imbalance / Decimal(100),
            )
        )
    if "VECTOR" in recall_channels:
        claims.append(_claim(evidence, "SEMANTIC_MATCH", ("recall:VECTOR",), None))
    return _ordered_claims(claims)


def _reciprocal_reason_claims(
    candidate: MatchingCandidateCommand,
    buyer: DirectionalScoreResult,
    exhibitor: DirectionalScoreResult,
    reciprocal: ReciprocalScoreResult,
) -> tuple[ReasonClaim, ...]:
    return derive_reciprocal_reason_claims(
        buyer.contributions,
        exhibitor.contributions,
        imbalance_value=reciprocal.imbalance_value,
        recall_channels=candidate.recall_channels,
        reason_evidence=candidate.reason_evidence,
    )


def _score_candidate(
    mode: MatchingMode, candidate: MatchingCandidateCommand
) -> RankedCandidateResult:
    eligibility = candidate.eligibility
    if mode is MatchingMode.CATALOG_SEARCH:
        if candidate.search_signals is None:
            raise MatchingEngineValidationError(
                f"candidate {candidate.candidate_id} requires search_signals"
            )
        search = score_catalog_search(candidate.search_signals)
        score_100 = search.final_score * Decimal(100)
        fingerprints = MappingProxyType(
            {"catalog_search": search.calculation_fingerprint}
        )
        policies = MappingProxyType({"catalog_search": search.policy_version})
        combined = _fingerprint(dict(fingerprints))
        claims = _catalog_reason_claims(candidate, search)
        return RankedCandidateResult(
            candidate.candidate_id,
            candidate.exhibitor_id,
            0,
            eligibility.evaluation_id,
            search.final_score,
            score_100,
            None,
            None,
            None,
            policies,
            fingerprints,
            combined,
            claims,
            _reason_fingerprint(claims),
            catalog_search_result=search,
        )

    if mode in (MatchingMode.GENERAL_VISITOR, MatchingMode.BUYER_TO_EXHIBITOR):
        policy = (
            CONSUMER_SCORE_V1
            if mode is MatchingMode.GENERAL_VISITOR
            else BUYER_SCORE_V1
        )
        directional = calculate_directional_score(
            policy,
            candidate.components,
            eligibility=eligibility,
            caps=candidate.score_caps,
            confidence=candidate.confidence,
        )
        key = "consumer" if mode is MatchingMode.GENERAL_VISITOR else "buyer"
        fingerprints = MappingProxyType({key: directional.calculation_fingerprint})
        policies = MappingProxyType({key: directional.policy_version})
        combined = _fingerprint(dict(fingerprints))
        claims = _directional_reason_claims(mode, candidate, directional)
        return RankedCandidateResult(
            candidate.candidate_id,
            candidate.exhibitor_id,
            0,
            eligibility.evaluation_id,
            directional.final_score / Decimal(100),
            directional.final_score,
            directional.grade,
            None,
            None,
            policies,
            fingerprints,
            combined,
            claims,
            _reason_fingerprint(claims),
            directional_result=directional,
        )

    if candidate.buyer_confidence is None or candidate.exhibitor_confidence is None:
        raise MatchingEngineValidationError(
            f"candidate {candidate.candidate_id} requires both directional confidences"
        )
    buyer = calculate_directional_score(
        BUYER_SCORE_V1,
        candidate.buyer_components,
        eligibility=eligibility,
        caps=candidate.buyer_caps,
        confidence=candidate.buyer_confidence,
    )
    exhibitor = calculate_directional_score(
        EXHIBITOR_SCORE_V1,
        candidate.exhibitor_components,
        eligibility=eligibility,
        caps=candidate.exhibitor_caps,
        confidence=candidate.exhibitor_confidence,
    )
    reciprocal = calculate_reciprocal_score(
        buyer_to_exhibitor_score=buyer.final_score,
        exhibitor_to_buyer_score=exhibitor.final_score,
        buyer_confidence=candidate.buyer_confidence,
        exhibitor_confidence=candidate.exhibitor_confidence,
        acceptance_capacity_score=candidate.acceptance_capacity_score,
        eligibility=eligibility,
        policy=RECIPROCAL_SCORE_V1,
        policy_adjustment=candidate.policy_adjustment,
        caps=candidate.score_caps,
    )
    policies = MappingProxyType(
        {
            "buyer": buyer.policy_version,
            "exhibitor": exhibitor.policy_version,
            "reciprocal": reciprocal.policy_version,
        }
    )
    fingerprints = MappingProxyType(
        {
            "buyer": buyer.calculation_fingerprint,
            "exhibitor": exhibitor.calculation_fingerprint,
            "reciprocal": reciprocal.calculation_fingerprint,
        }
    )
    combined = _fingerprint(dict(fingerprints))
    claims = _reciprocal_reason_claims(candidate, buyer, exhibitor, reciprocal)
    return RankedCandidateResult(
        candidate.candidate_id,
        candidate.exhibitor_id,
        0,
        eligibility.evaluation_id,
        reciprocal.final_reciprocal_score / Decimal(100),
        reciprocal.final_reciprocal_score,
        reciprocal.grade,
        reciprocal.match_status,
        reciprocal.recommended_action,
        policies,
        fingerprints,
        combined,
        claims,
        _reason_fingerprint(claims),
        buyer_directional_result=buyer,
        exhibitor_directional_result=exhibitor,
        reciprocal_result=reciprocal,
    )


def execute_matching(command: MatchingEngineCommand) -> MatchingEngineResult:
    """Execute one immutable command and return deterministic rank/provenance."""

    mode = MatchingMode(command.mode)
    policy_versions = _policies_for_mode(mode)
    engine_version = (
        MATCHING_ENGINE_VERSION_V1
        if command.contract_version == MATCHING_ENGINE_COMMAND_V1
        else MATCHING_ENGINE_VERSION
    )
    input_payload = {
        "contract_version": command.contract_version,
        "engine_version": engine_version,
        "mode": mode.value,
        "taxonomy_version": command.taxonomy_version,
        "model_version": command.model_version,
        "policy_versions": dict(policy_versions),
        "candidates": [
            _candidate_input_payload(
                candidate,
                include_reason_evidence=(
                    command.contract_version == MATCHING_ENGINE_COMMAND_V1_1
                ),
            )
            for candidate in sorted(
                command.candidates, key=lambda item: item.candidate_id
            )
        ],
    }
    input_fingerprint = _fingerprint(input_payload)

    scored: list[RankedCandidateResult] = []
    excluded: list[ExcludedCandidateResult] = []
    for candidate in command.candidates:
        if not candidate.recalled:
            reason_codes = ("NOT_RECALLED",)
            excluded.append(
                ExcludedCandidateResult(
                    candidate.candidate_id,
                    candidate.exhibitor_id,
                    candidate.eligibility.evaluation_id,
                    reason_codes,
                    _eligibility_reason_claims(candidate, reason_codes),
                )
            )
            continue
        if not candidate.eligibility.passed:
            reason_codes = tuple(sorted(candidate.eligibility.reason_codes))
            excluded.append(
                ExcludedCandidateResult(
                    candidate.candidate_id,
                    candidate.exhibitor_id,
                    candidate.eligibility.evaluation_id,
                    reason_codes,
                    _eligibility_reason_claims(candidate, reason_codes),
                )
            )
            continue
        scored.append(_score_candidate(mode, candidate))

    ordered = sorted(scored, key=lambda item: (-item.score_100, item.candidate_id))
    ranked = tuple(
        RankedCandidateResult(
            candidate_id=item.candidate_id,
            exhibitor_id=item.exhibitor_id,
            rank=rank,
            eligibility_evaluation_id=item.eligibility_evaluation_id,
            normalized_score=item.normalized_score,
            score_100=item.score_100,
            grade=item.grade,
            match_status=item.match_status,
            recommended_action=item.recommended_action,
            policy_versions=item.policy_versions,
            score_fingerprints=item.score_fingerprints,
            calculation_fingerprint=item.calculation_fingerprint,
            reason_claims=item.reason_claims,
            reason_fingerprint=item.reason_fingerprint,
            directional_result=item.directional_result,
            buyer_directional_result=item.buyer_directional_result,
            exhibitor_directional_result=item.exhibitor_directional_result,
            reciprocal_result=item.reciprocal_result,
            catalog_search_result=item.catalog_search_result,
        )
        for rank, item in enumerate(ordered, start=1)
    )
    excluded_result = tuple(sorted(excluded, key=lambda item: item.candidate_id))
    result_contract_version = (
        MATCHING_ENGINE_RESULT_V1
        if command.contract_version == MATCHING_ENGINE_COMMAND_V1
        else MATCHING_ENGINE_RESULT_V1_1
    )
    result_payload = {
        "contract_version": result_contract_version,
        "engine_version": engine_version,
        "mode": mode.value,
        "taxonomy_version": command.taxonomy_version,
        "model_version": command.model_version,
        "policy_versions": dict(policy_versions),
        "input_fingerprint": input_fingerprint,
        "ranked_candidates": [
            {
                "candidate_id": item.candidate_id,
                "exhibitor_id": item.exhibitor_id,
                "rank": item.rank,
                "eligibility_evaluation_id": item.eligibility_evaluation_id,
                "normalized_score": _decimal_text(item.normalized_score),
                "score_100": _decimal_text(item.score_100),
                "grade": item.grade,
                "match_status": item.match_status,
                "recommended_action": item.recommended_action,
                "policy_versions": dict(item.policy_versions),
                "score_fingerprints": dict(item.score_fingerprints),
                "calculation_fingerprint": item.calculation_fingerprint,
                **(
                    {
                        "reason_claims": [
                            {
                                "code": claim.code,
                                "evidence_refs": list(claim.evidence_refs),
                                "source_components": list(claim.source_components),
                                "contribution_score": _canonical_number(
                                    claim.contribution_score
                                ),
                                "policy_version": claim.policy_version,
                                "claim_fingerprint": claim.claim_fingerprint,
                            }
                            for claim in item.reason_claims
                        ],
                        "reason_fingerprint": item.reason_fingerprint,
                    }
                    if result_contract_version == MATCHING_ENGINE_RESULT_V1_1
                    else {}
                ),
            }
            for item in ranked
        ],
        "excluded_candidates": [
            {
                "candidate_id": item.candidate_id,
                "exhibitor_id": item.exhibitor_id,
                "eligibility_evaluation_id": item.eligibility_evaluation_id,
                "reason_codes": list(item.reason_codes),
                **(
                    {
                        "reason_claims": [
                            {
                                "code": claim.code,
                                "evidence_refs": list(claim.evidence_refs),
                                "source_components": list(claim.source_components),
                                "contribution_score": None,
                                "policy_version": claim.policy_version,
                                "claim_fingerprint": claim.claim_fingerprint,
                            }
                            for claim in item.reason_claims
                        ]
                    }
                    if result_contract_version == MATCHING_ENGINE_RESULT_V1_1
                    else {}
                ),
            }
            for item in excluded_result
        ],
    }
    return MatchingEngineResult(
        contract_version=result_contract_version,
        engine_version=engine_version,
        mode=mode,
        taxonomy_version=command.taxonomy_version,
        model_version=command.model_version,
        policy_versions=policy_versions,
        input_fingerprint=input_fingerprint,
        result_fingerprint=_fingerprint(result_payload),
        ranked_candidates=ranked,
        excluded_candidates=excluded_result,
    )
