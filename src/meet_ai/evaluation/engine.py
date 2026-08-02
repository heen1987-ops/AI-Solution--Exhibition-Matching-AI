"""Versioned offline evaluation for the deterministic matching engine.

The evaluator consumes a checked-in golden set, recalculates scores with the
published policies, and reports ranking, safety, diversity, explanation, fallback,
and reproducibility signals. It performs no database, network, or model call.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal

from meet_ai.engine import (
    MATCHING_ENGINE_RESULT_V1_1,
    MatchingCandidateCommand,
    MatchingEngineCommand,
    MatchingMode,
    ReasonClaim,
    execute_matching,
)
from meet_ai.ontology import load_catalog
from meet_ai.scoring import (
    BUYER_SCORE_V1,
    CONSUMER_SCORE_V1,
    EXHIBITOR_SCORE_V1,
    RECIPROCAL_SCORE_V1,
    EligibilityDecision,
    ScoreCap,
    ScoreValidationError,
)

GOLDEN_SET_SCHEMA_VERSION = "matching-golden-set-v1"
EVALUATOR_VERSION = "matching-evaluator-v1.2"

EvaluationMode = Literal[
    "GENERAL_VISITOR",
    "BUYER_TO_EXHIBITOR",
    "RECIPROCAL",
]

_MODES: tuple[EvaluationMode, ...] = (
    "GENERAL_VISITOR",
    "BUYER_TO_EXHIBITOR",
    "RECIPROCAL",
)
_FALLBACK_CHANNELS = frozenset(
    {"STRUCTURED", "POPULARITY", "OPERATOR_PINNED", "INTEREST", "EXPLORATION"}
)
_RECALL_CHANNELS = _FALLBACK_CHANNELS | {"VECTOR"}
_POLICY_VERSIONS = {
    "consumer": CONSUMER_SCORE_V1.version,
    "buyer": BUYER_SCORE_V1.version,
    "exhibitor": EXHIBITOR_SCORE_V1.version,
    "reciprocal": RECIPROCAL_SCORE_V1.version,
}


class GoldenSetValidationError(ValueError):
    """Raised when an evaluation artifact is ambiguous or contract-incompatible."""


@dataclass(frozen=True, slots=True)
class GoldenEligibility:
    passed: bool
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class GoldenExplanation:
    code: str
    evidence_refs: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class GoldenCandidate:
    candidate_id: str
    exhibitor_id: str
    gold_relevance: int
    expected_eligibility: GoldenEligibility
    observed_eligibility: GoldenEligibility
    recall_channels: tuple[str, ...]
    allowed_reason_codes: tuple[str, ...]
    explanations: tuple[GoldenExplanation, ...]
    components: Mapping[str, Any]
    buyer_components: Mapping[str, Any]
    exhibitor_components: Mapping[str, Any]
    confidence: Any | None
    buyer_confidence: Any | None
    exhibitor_confidence: Any | None
    acceptance_capacity_score: Any | None
    policy_adjustment: Any
    score_caps: tuple[ScoreCap, ...]


@dataclass(frozen=True, slots=True)
class GoldenScenario:
    scenario_id: str
    mode: EvaluationMode
    k: int
    candidates: tuple[GoldenCandidate, ...]


@dataclass(frozen=True, slots=True)
class EvaluationThresholds:
    recall_at_k_min: float
    ndcg_at_k_min: float
    fallback_recall_drop_max: float
    hard_filter_violations_max: int
    filter_decision_mismatches_max: int
    explanation_violations_max: int
    max_exhibitor_share_at_k_max: float


@dataclass(frozen=True, slots=True)
class GoldenSet:
    schema_version: str
    golden_set_version: str
    taxonomy_version: str
    policy_versions: Mapping[str, str]
    thresholds: EvaluationThresholds
    scenarios: tuple[GoldenScenario, ...]
    input_fingerprint: str


@dataclass(frozen=True, slots=True)
class RankedCandidate:
    candidate_id: str
    exhibitor_id: str
    score: float
    gold_relevance: int
    rank: int
    score_fingerprint: str
    explanation_fingerprint: str


@dataclass(frozen=True, slots=True)
class ScenarioEvaluation:
    scenario_id: str
    mode: EvaluationMode
    k: int
    relevant_eligible_count: int
    recalled_count: int
    fallback_recalled_count: int
    recall_at_k: float
    fallback_recall_at_k: float
    fallback_recall_drop: float
    ndcg_at_k: float
    hard_filter_violations: int
    filter_decision_mismatches: int
    explanation_violations: int
    max_exhibitor_share_at_k: float
    exhibitor_hhi_at_k: float
    ranked_candidates: tuple[RankedCandidate, ...]
    failures: tuple[str, ...]
    engine_contract_version: str
    engine_input_fingerprint: str
    engine_result_fingerprint: str
    result_fingerprint: str


@dataclass(frozen=True, slots=True)
class EvaluationReport:
    evaluator_version: str
    golden_set_version: str
    taxonomy_version: str
    policy_versions: Mapping[str, str]
    thresholds: Mapping[str, float | int]
    input_fingerprint: str
    status: Literal["PASS", "FAIL"]
    scenario_count: int
    average_recall_at_k: float
    average_fallback_recall_at_k: float
    average_ndcg_at_k: float
    total_hard_filter_violations: int
    total_filter_decision_mismatches: int
    total_explanation_violations: int
    scenarios: tuple[ScenarioEvaluation, ...]
    failures: tuple[str, ...]
    result_fingerprint: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GoldenSetValidationError(f"{field} must be an object")
    return value


def _sequence(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise GoldenSetValidationError(f"{field} must be an array")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoldenSetValidationError(f"{field} must be a non-empty string")
    return value.strip()


def _number(value: Any, field: str, *, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GoldenSetValidationError(f"{field} must be numeric")
    converted = float(value)
    if not math.isfinite(converted) or not minimum <= converted <= maximum:
        raise GoldenSetValidationError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return converted


def _integer(value: Any, field: str, *, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GoldenSetValidationError(f"{field} must be an integer")
    if not minimum <= value <= maximum:
        raise GoldenSetValidationError(
            f"{field} must be between {minimum} and {maximum}"
        )
    return value


def _strings(value: Any, field: str) -> tuple[str, ...]:
    values = tuple(_text(item, f"{field}[]") for item in _sequence(value, field))
    if len(values) != len(set(values)):
        raise GoldenSetValidationError(f"{field} must not contain duplicates")
    return tuple(sorted(values))


def _eligibility(value: Any, field: str) -> GoldenEligibility:
    payload = _mapping(value, field)
    passed = payload.get("passed")
    if not isinstance(passed, bool):
        raise GoldenSetValidationError(f"{field}.passed must be boolean")
    reason_codes = _strings(payload.get("reason_codes", []), f"{field}.reason_codes")
    if not passed and not reason_codes:
        raise GoldenSetValidationError(f"{field} failure requires reason_codes")
    if passed and reason_codes:
        raise GoldenSetValidationError(f"{field} pass cannot contain reason_codes")
    return GoldenEligibility(passed, reason_codes)


def _explanations(value: Any, field: str) -> tuple[GoldenExplanation, ...]:
    explanations: list[GoldenExplanation] = []
    for index, raw in enumerate(_sequence(value, field)):
        payload = _mapping(raw, f"{field}[{index}]")
        explanations.append(
            GoldenExplanation(
                code=_text(payload.get("code"), f"{field}[{index}].code"),
                evidence_refs=_strings(
                    payload.get("evidence_refs", []),
                    f"{field}[{index}].evidence_refs",
                ),
            )
        )
    return tuple(sorted(explanations, key=lambda item: item.code))


def _score_caps(value: Any, field: str) -> tuple[ScoreCap, ...]:
    caps: list[ScoreCap] = []
    for index, raw in enumerate(_sequence(value, field)):
        payload = _mapping(raw, f"{field}[{index}]")
        caps.append(
            ScoreCap(
                _text(payload.get("code"), f"{field}[{index}].code"),
                payload.get("maximum"),
            )
        )
    return tuple(sorted(caps, key=lambda item: (item.maximum, item.code)))


def _candidate(value: Any, field: str, mode: EvaluationMode) -> GoldenCandidate:
    payload = _mapping(value, field)
    relevance = _integer(
        payload.get("gold_relevance"), f"{field}.gold_relevance", minimum=0, maximum=3
    )
    components = _mapping(payload.get("components", {}), f"{field}.components")
    buyer_components = _mapping(
        payload.get("buyer_components", {}), f"{field}.buyer_components"
    )
    exhibitor_components = _mapping(
        payload.get("exhibitor_components", {}), f"{field}.exhibitor_components"
    )
    if mode in {"GENERAL_VISITOR", "BUYER_TO_EXHIBITOR"} and not components:
        raise GoldenSetValidationError(f"{field}.components is required for {mode}")
    if mode == "RECIPROCAL" and (not buyer_components or not exhibitor_components):
        raise GoldenSetValidationError(
            f"{field}.buyer_components and exhibitor_components are required"
        )

    recall_channels = _strings(
        payload.get("recall_channels", []), f"{field}.recall_channels"
    )
    unknown_channels = sorted(set(recall_channels) - _RECALL_CHANNELS)
    if unknown_channels:
        raise GoldenSetValidationError(
            f"{field}.recall_channels contains unknown channels: {unknown_channels}"
        )

    return GoldenCandidate(
        candidate_id=_text(payload.get("candidate_id"), f"{field}.candidate_id"),
        exhibitor_id=_text(payload.get("exhibitor_id"), f"{field}.exhibitor_id"),
        gold_relevance=relevance,
        expected_eligibility=_eligibility(
            payload.get("expected_eligibility"), f"{field}.expected_eligibility"
        ),
        observed_eligibility=_eligibility(
            payload.get("observed_eligibility"), f"{field}.observed_eligibility"
        ),
        recall_channels=recall_channels,
        allowed_reason_codes=_strings(
            payload.get("allowed_reason_codes", []),
            f"{field}.allowed_reason_codes",
        ),
        explanations=_explanations(
            payload.get("explanations", []), f"{field}.explanations"
        ),
        components=components,
        buyer_components=buyer_components,
        exhibitor_components=exhibitor_components,
        confidence=payload.get("confidence"),
        buyer_confidence=payload.get("buyer_confidence"),
        exhibitor_confidence=payload.get("exhibitor_confidence"),
        acceptance_capacity_score=payload.get("acceptance_capacity_score"),
        policy_adjustment=payload.get("policy_adjustment", 0),
        score_caps=_score_caps(payload.get("score_caps", []), f"{field}.score_caps"),
    )


def load_golden_set_payload(value: Any) -> GoldenSet:
    payload = _mapping(value, "golden_set")
    schema_version = _text(payload.get("schema_version"), "schema_version")
    if schema_version != GOLDEN_SET_SCHEMA_VERSION:
        raise GoldenSetValidationError(
            f"schema_version must be {GOLDEN_SET_SCHEMA_VERSION}"
        )

    policy_versions = {
        str(key): _text(version, f"policy_versions.{key}")
        for key, version in _mapping(
            payload.get("policy_versions"), "policy_versions"
        ).items()
    }
    if policy_versions != _POLICY_VERSIONS:
        raise GoldenSetValidationError(
            f"policy_versions must match published policies {_POLICY_VERSIONS}"
        )

    raw_thresholds = _mapping(payload.get("thresholds"), "thresholds")
    thresholds = EvaluationThresholds(
        recall_at_k_min=_number(
            raw_thresholds.get("recall_at_k_min"),
            "thresholds.recall_at_k_min",
            minimum=0,
            maximum=1,
        ),
        ndcg_at_k_min=_number(
            raw_thresholds.get("ndcg_at_k_min"),
            "thresholds.ndcg_at_k_min",
            minimum=0,
            maximum=1,
        ),
        fallback_recall_drop_max=_number(
            raw_thresholds.get("fallback_recall_drop_max"),
            "thresholds.fallback_recall_drop_max",
            minimum=0,
            maximum=1,
        ),
        hard_filter_violations_max=_integer(
            raw_thresholds.get("hard_filter_violations_max"),
            "thresholds.hard_filter_violations_max",
            minimum=0,
            maximum=1_000_000,
        ),
        filter_decision_mismatches_max=_integer(
            raw_thresholds.get("filter_decision_mismatches_max"),
            "thresholds.filter_decision_mismatches_max",
            minimum=0,
            maximum=1_000_000,
        ),
        explanation_violations_max=_integer(
            raw_thresholds.get("explanation_violations_max"),
            "thresholds.explanation_violations_max",
            minimum=0,
            maximum=1_000_000,
        ),
        max_exhibitor_share_at_k_max=_number(
            raw_thresholds.get("max_exhibitor_share_at_k_max"),
            "thresholds.max_exhibitor_share_at_k_max",
            minimum=0,
            maximum=1,
        ),
    )

    scenarios: list[GoldenScenario] = []
    scenario_ids: set[str] = set()
    for index, raw in enumerate(_sequence(payload.get("scenarios"), "scenarios")):
        field = f"scenarios[{index}]"
        scenario_payload = _mapping(raw, field)
        scenario_id = _text(scenario_payload.get("scenario_id"), f"{field}.scenario_id")
        if scenario_id in scenario_ids:
            raise GoldenSetValidationError(f"duplicate scenario_id: {scenario_id}")
        scenario_ids.add(scenario_id)
        mode_value = _text(scenario_payload.get("mode"), f"{field}.mode")
        if mode_value not in _MODES:
            raise GoldenSetValidationError(f"{field}.mode is invalid: {mode_value}")
        mode: EvaluationMode = mode_value  # type: ignore[assignment]
        candidates = tuple(
            _candidate(candidate, f"{field}.candidates[{candidate_index}]", mode)
            for candidate_index, candidate in enumerate(
                _sequence(scenario_payload.get("candidates"), f"{field}.candidates")
            )
        )
        candidate_ids = [candidate.candidate_id for candidate in candidates]
        if not candidates or len(candidate_ids) != len(set(candidate_ids)):
            raise GoldenSetValidationError(
                f"{field}.candidates must be non-empty with unique candidate_id"
            )
        scenarios.append(
            GoldenScenario(
                scenario_id=scenario_id,
                mode=mode,
                k=_integer(
                    scenario_payload.get("k"), f"{field}.k", minimum=1, maximum=100
                ),
                candidates=tuple(
                    sorted(candidates, key=lambda item: item.candidate_id)
                ),
            )
        )
    if {scenario.mode for scenario in scenarios} != set(_MODES):
        raise GoldenSetValidationError(
            f"scenarios must cover each evaluation mode exactly or repeatedly: {_MODES}"
        )

    taxonomy_version = _text(payload.get("taxonomy_version"), "taxonomy_version")
    published_taxonomy_version = load_catalog().version
    if taxonomy_version != published_taxonomy_version:
        raise GoldenSetValidationError(
            "taxonomy_version must match the published ontology "
            f"{published_taxonomy_version}"
        )

    golden_set_version = _text(payload.get("golden_set_version"), "golden_set_version")
    normalized_scenarios = tuple(sorted(scenarios, key=lambda item: item.scenario_id))
    normalized_payload = {
        "schema_version": schema_version,
        "golden_set_version": golden_set_version,
        "taxonomy_version": taxonomy_version,
        "policy_versions": policy_versions,
        "thresholds": asdict(thresholds),
        "scenarios": [asdict(scenario) for scenario in normalized_scenarios],
    }
    return GoldenSet(
        schema_version=schema_version,
        golden_set_version=golden_set_version,
        taxonomy_version=taxonomy_version,
        policy_versions=policy_versions,
        thresholds=thresholds,
        scenarios=normalized_scenarios,
        input_fingerprint=_fingerprint(normalized_payload),
    )


def load_golden_set(path: str | Path) -> GoldenSet:
    artifact_path = Path(path)
    try:
        payload = json.loads(artifact_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise GoldenSetValidationError(
            f"cannot load golden set: {artifact_path}"
        ) from exc
    return load_golden_set_payload(payload)


@dataclass(frozen=True, slots=True)
class _ScoredCandidate:
    candidate: GoldenCandidate
    score: Decimal
    score_fingerprint: str
    explanation_fingerprint: str
    reason_claims: tuple[ReasonClaim, ...]


def _scoring_eligibility(
    scenario: GoldenScenario, candidate: GoldenCandidate
) -> EligibilityDecision:
    observed = candidate.observed_eligibility
    return EligibilityDecision(
        observed.passed,
        f"gold:{scenario.scenario_id}:{candidate.candidate_id}",
        observed.reason_codes,
    )


def _engine_candidate(
    scenario: GoldenScenario, candidate: GoldenCandidate
) -> MatchingCandidateCommand:
    return MatchingCandidateCommand(
        candidate_id=candidate.candidate_id,
        exhibitor_id=candidate.exhibitor_id,
        eligibility=_scoring_eligibility(scenario, candidate),
        recalled=bool(candidate.recall_channels),
        recall_channels=candidate.recall_channels,
        components=candidate.components,
        buyer_components=candidate.buyer_components,
        exhibitor_components=candidate.exhibitor_components,
        confidence=candidate.confidence,
        buyer_confidence=candidate.buyer_confidence,
        exhibitor_confidence=candidate.exhibitor_confidence,
        acceptance_capacity_score=(
            Decimal("0.5")
            if candidate.acceptance_capacity_score is None
            else candidate.acceptance_capacity_score
        ),
        policy_adjustment=candidate.policy_adjustment,
        score_caps=candidate.score_caps,
        reason_evidence={
            explanation.code: explanation.evidence_refs
            for explanation in candidate.explanations
            if explanation.evidence_refs
        },
    )


def _rank(candidates: Sequence[_ScoredCandidate]) -> list[_ScoredCandidate]:
    return sorted(
        candidates, key=lambda item: (-item.score, item.candidate.candidate_id)
    )


def _recall_at_k(
    ranked: Sequence[_ScoredCandidate], *, relevant_ids: set[str], k: int
) -> float:
    if not relevant_ids:
        return 1.0
    hits = sum(item.candidate.candidate_id in relevant_ids for item in ranked[:k])
    return hits / len(relevant_ids)


def _ndcg_at_k(
    ranked: Sequence[_ScoredCandidate], *, ideal_relevances: Sequence[int], k: int
) -> float:
    def dcg(values: Sequence[int]) -> float:
        return sum(
            (2**relevance - 1) / math.log2(index + 2)
            for index, relevance in enumerate(values[:k])
        )

    actual = dcg([item.candidate.gold_relevance for item in ranked])
    ideal = dcg(sorted(ideal_relevances, reverse=True))
    return actual / ideal if ideal else 1.0


def _concentration(
    ranked: Sequence[_ScoredCandidate], *, k: int
) -> tuple[float, float]:
    top = ranked[:k]
    if not top:
        return 0.0, 0.0
    counts = Counter(item.candidate.exhibitor_id for item in top)
    shares = [count / len(top) for count in counts.values()]
    return max(shares), sum(share * share for share in shares)


def _filter_decision_mismatch(candidate: GoldenCandidate) -> bool:
    expected = candidate.expected_eligibility
    observed = candidate.observed_eligibility
    if expected.passed != observed.passed:
        return True
    return not expected.passed and expected.reason_codes != observed.reason_codes


def _explanation_violations(
    candidate: GoldenCandidate, claims: Sequence[ReasonClaim]
) -> int:
    allowed = set(candidate.allowed_reason_codes)
    observed = {claim.code for claim in claims}
    return len(allowed - observed) + sum(
        not claim.evidence_refs
        or claim.code not in allowed
        or not claim.source_components
        or len(claim.claim_fingerprint) != 64
        for claim in claims
    )


def _rounded(value: float) -> float:
    return round(value, 6)


def evaluate_scenario(
    scenario: GoldenScenario,
    *,
    thresholds: EvaluationThresholds,
    taxonomy_version: str | None = None,
) -> ScenarioEvaluation:
    try:
        engine_result = execute_matching(
            MatchingEngineCommand(
                mode=MatchingMode(scenario.mode),
                taxonomy_version=taxonomy_version or load_catalog().version,
                candidates=tuple(
                    _engine_candidate(scenario, candidate)
                    for candidate in scenario.candidates
                ),
            )
        )
    except ScoreValidationError as exc:
        raise GoldenSetValidationError(
            f"scenario {scenario.scenario_id} contains invalid score input: {exc}"
        ) from exc
    candidates_by_id = {
        candidate.candidate_id: candidate for candidate in scenario.candidates
    }
    ranked = [
        _ScoredCandidate(
            candidate=candidates_by_id[result.candidate_id],
            score=result.score_100,
            score_fingerprint=result.calculation_fingerprint,
            explanation_fingerprint=result.reason_fingerprint
            or _fingerprint([]),
            reason_claims=result.reason_claims,
        )
        for result in engine_result.ranked_candidates
    ]
    fallback_ranked = _rank(
        [
            item
            for item in ranked
            if set(item.candidate.recall_channels) & _FALLBACK_CHANNELS
        ]
    )
    relevant_ids = {
        candidate.candidate_id
        for candidate in scenario.candidates
        if candidate.expected_eligibility.passed and candidate.gold_relevance > 0
    }
    ideal_relevances = [
        candidate.gold_relevance
        for candidate in scenario.candidates
        if candidate.expected_eligibility.passed
    ]
    recall = _recall_at_k(ranked, relevant_ids=relevant_ids, k=scenario.k)
    fallback_recall = _recall_at_k(
        fallback_ranked, relevant_ids=relevant_ids, k=scenario.k
    )
    ndcg = _ndcg_at_k(ranked, ideal_relevances=ideal_relevances, k=scenario.k)
    max_share, hhi = _concentration(ranked, k=scenario.k)
    hard_filter_violations = sum(
        not item.candidate.expected_eligibility.passed for item in ranked
    )
    filter_mismatches = sum(
        _filter_decision_mismatch(candidate) for candidate in scenario.candidates
    )
    explanation_violations = sum(
        _explanation_violations(item.candidate, item.reason_claims) for item in ranked
    )
    fallback_drop = max(0.0, recall - fallback_recall)

    failures: list[str] = []
    checks = (
        (recall < thresholds.recall_at_k_min, "RECALL_AT_K_BELOW_MIN"),
        (ndcg < thresholds.ndcg_at_k_min, "NDCG_AT_K_BELOW_MIN"),
        (
            fallback_drop > thresholds.fallback_recall_drop_max,
            "FALLBACK_RECALL_DROP_ABOVE_MAX",
        ),
        (
            hard_filter_violations > thresholds.hard_filter_violations_max,
            "HARD_FILTER_VIOLATION",
        ),
        (
            filter_mismatches > thresholds.filter_decision_mismatches_max,
            "FILTER_DECISION_MISMATCH",
        ),
        (
            explanation_violations > thresholds.explanation_violations_max,
            "EXPLANATION_GROUNDING_VIOLATION",
        ),
        (
            max_share > thresholds.max_exhibitor_share_at_k_max,
            "EXHIBITOR_CONCENTRATION_ABOVE_MAX",
        ),
    )
    failures.extend(code for failed, code in checks if failed)

    ranked_candidates = tuple(
        RankedCandidate(
            candidate_id=item.candidate.candidate_id,
            exhibitor_id=item.candidate.exhibitor_id,
            score=_rounded(float(item.score)),
            gold_relevance=item.candidate.gold_relevance,
            rank=index,
            score_fingerprint=item.score_fingerprint,
            explanation_fingerprint=item.explanation_fingerprint,
        )
        for index, item in enumerate(ranked[: scenario.k], start=1)
    )
    result_payload = {
        "evaluator_version": EVALUATOR_VERSION,
        "scenario_id": scenario.scenario_id,
        "mode": scenario.mode,
        "engine_contract_version": engine_result.contract_version,
        "engine_input_fingerprint": engine_result.input_fingerprint,
        "engine_result_fingerprint": engine_result.result_fingerprint,
        "ranked_candidates": [asdict(item) for item in ranked_candidates],
        "metrics": {
            "recall_at_k": _rounded(recall),
            "fallback_recall_at_k": _rounded(fallback_recall),
            "ndcg_at_k": _rounded(ndcg),
            "hard_filter_violations": hard_filter_violations,
            "filter_decision_mismatches": filter_mismatches,
            "explanation_violations": explanation_violations,
            "max_exhibitor_share_at_k": _rounded(max_share),
            "exhibitor_hhi_at_k": _rounded(hhi),
        },
        "failures": failures,
    }
    return ScenarioEvaluation(
        scenario_id=scenario.scenario_id,
        mode=scenario.mode,
        k=scenario.k,
        relevant_eligible_count=len(relevant_ids),
        recalled_count=sum(
            item.candidate.candidate_id in relevant_ids for item in ranked[: scenario.k]
        ),
        fallback_recalled_count=sum(
            item.candidate.candidate_id in relevant_ids
            for item in fallback_ranked[: scenario.k]
        ),
        recall_at_k=_rounded(recall),
        fallback_recall_at_k=_rounded(fallback_recall),
        fallback_recall_drop=_rounded(fallback_drop),
        ndcg_at_k=_rounded(ndcg),
        hard_filter_violations=hard_filter_violations,
        filter_decision_mismatches=filter_mismatches,
        explanation_violations=explanation_violations,
        max_exhibitor_share_at_k=_rounded(max_share),
        exhibitor_hhi_at_k=_rounded(hhi),
        ranked_candidates=ranked_candidates,
        failures=tuple(failures),
        engine_contract_version=MATCHING_ENGINE_RESULT_V1_1,
        engine_input_fingerprint=engine_result.input_fingerprint,
        engine_result_fingerprint=engine_result.result_fingerprint,
        result_fingerprint=_fingerprint(result_payload),
    )


def evaluate_golden_set(golden_set: GoldenSet) -> EvaluationReport:
    scenarios = tuple(
        evaluate_scenario(
            scenario,
            thresholds=golden_set.thresholds,
            taxonomy_version=golden_set.taxonomy_version,
        )
        for scenario in golden_set.scenarios
    )
    failures = tuple(
        f"{scenario.scenario_id}:{failure}"
        for scenario in scenarios
        for failure in scenario.failures
    )
    count = len(scenarios)
    summary_payload = {
        "evaluator_version": EVALUATOR_VERSION,
        "golden_set_version": golden_set.golden_set_version,
        "input_fingerprint": golden_set.input_fingerprint,
        "policy_versions": dict(golden_set.policy_versions),
        "thresholds": asdict(golden_set.thresholds),
        "scenario_fingerprints": [
            scenario.result_fingerprint for scenario in scenarios
        ],
        "failures": failures,
    }
    return EvaluationReport(
        evaluator_version=EVALUATOR_VERSION,
        golden_set_version=golden_set.golden_set_version,
        taxonomy_version=golden_set.taxonomy_version,
        policy_versions=dict(golden_set.policy_versions),
        thresholds=asdict(golden_set.thresholds),
        input_fingerprint=golden_set.input_fingerprint,
        status="FAIL" if failures else "PASS",
        scenario_count=count,
        average_recall_at_k=_rounded(
            sum(item.recall_at_k for item in scenarios) / count
        ),
        average_fallback_recall_at_k=_rounded(
            sum(item.fallback_recall_at_k for item in scenarios) / count
        ),
        average_ndcg_at_k=_rounded(sum(item.ndcg_at_k for item in scenarios) / count),
        total_hard_filter_violations=sum(
            item.hard_filter_violations for item in scenarios
        ),
        total_filter_decision_mismatches=sum(
            item.filter_decision_mismatches for item in scenarios
        ),
        total_explanation_violations=sum(
            item.explanation_violations for item in scenarios
        ),
        scenarios=scenarios,
        failures=failures,
        result_fingerprint=_fingerprint(summary_payload),
    )
