"""Offline non-inferiority evaluation for the hybrid RRF shadow policy."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from meet_ai.engine import (
    HYBRID_RRF_SHADOW_COMMAND_V1,
    CandidateSignalDiagnostics,
    HybridRrfShadowCommand,
    RecallChannel,
    RecallChannelRanking,
    RecallChannelState,
    execute_hybrid_rrf_shadow,
)

HYBRID_SHADOW_FIXTURE_SCHEMA_V1 = "hybrid-rrf-shadow-fixture-v1"
HYBRID_SHADOW_EVALUATOR_VERSION = "hybrid-rrf-shadow-evaluator-v1.0"


class HybridShadowFixtureValidationError(ValueError):
    """Raised when a labeled hybrid-shadow fixture is invalid."""


@dataclass(frozen=True, slots=True)
class HybridShadowThresholds:
    recall_at_k_drop_max: float
    ndcg_at_k_drop_max: float


@dataclass(frozen=True, slots=True)
class HybridShadowScenario:
    scenario_id: str
    k: int
    gold_relevance: Mapping[str, int]
    command: HybridRrfShadowCommand


@dataclass(frozen=True, slots=True)
class HybridShadowFixture:
    schema_version: str
    fixture_version: str
    thresholds: HybridShadowThresholds
    scenarios: tuple[HybridShadowScenario, ...]
    input_fingerprint: str


@dataclass(frozen=True, slots=True)
class HybridShadowScenarioReport:
    scenario_id: str
    k: int
    vector_state: str
    published_recall_at_k: float
    shadow_recall_at_k: float
    recall_delta: float
    published_ndcg_at_k: float
    shadow_ndcg_at_k: float
    ndcg_delta: float
    published_ranking: tuple[str, ...]
    shadow_ranking: tuple[str, ...]
    fallback_applied: bool
    fallback_order_preserved: bool
    unknown_signals_preserved: bool
    missing_signals_preserved: bool
    shadow_only: bool
    promotion_allowed: bool
    input_fingerprint: str
    result_fingerprint: str
    failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class HybridShadowEvaluationReport:
    evaluator_version: str
    fixture_version: str
    status: Literal["PASS", "FAIL"]
    scenario_count: int
    average_published_recall_at_k: float
    average_shadow_recall_at_k: float
    average_published_ndcg_at_k: float
    average_shadow_ndcg_at_k: float
    input_fingerprint: str
    scenarios: tuple[HybridShadowScenarioReport, ...]
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


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise HybridShadowFixtureValidationError(f"{field} must be an object")
    return value


def _array(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise HybridShadowFixtureValidationError(f"{field} must be an array")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HybridShadowFixtureValidationError(
            f"{field} must be a non-empty string"
        )
    return value.strip()


def _ratio(value: Any, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise HybridShadowFixtureValidationError(f"{field} must be numeric")
    converted = float(value)
    if not math.isfinite(converted) or not 0 <= converted <= 1:
        raise HybridShadowFixtureValidationError(f"{field} must be between 0 and 1")
    return converted


def _strings(value: Any, field: str) -> tuple[str, ...]:
    values = tuple(_text(item, f"{field}[]") for item in _array(value, field))
    if len(values) != len(set(values)):
        raise HybridShadowFixtureValidationError(f"{field} must not contain duplicates")
    return values


def _command(value: Any, field: str) -> HybridRrfShadowCommand:
    payload = _object(value, field)
    contract_version = _text(
        payload.get("contract_version", HYBRID_RRF_SHADOW_COMMAND_V1),
        f"{field}.contract_version",
    )
    channels = tuple(
        RecallChannelRanking(
            channel=_text(item.get("channel"), f"{field}.channels[{index}].channel"),
            state=_text(item.get("state"), f"{field}.channels[{index}].state"),
            ranked_candidate_ids=_strings(
                item.get("ranked_candidate_ids", []),
                f"{field}.channels[{index}].ranked_candidate_ids",
            ),
        )
        for index, raw in enumerate(_array(payload.get("channels"), f"{field}.channels"))
        for item in (_object(raw, f"{field}.channels[{index}]"),)
    )
    signals = tuple(
        CandidateSignalDiagnostics(
            candidate_id=_text(
                item.get("candidate_id"),
                f"{field}.candidate_signals[{index}].candidate_id",
            ),
            unknown_signals=_strings(
                item.get("unknown_signals", []),
                f"{field}.candidate_signals[{index}].unknown_signals",
            ),
            missing_signals=_strings(
                item.get("missing_signals", []),
                f"{field}.candidate_signals[{index}].missing_signals",
            ),
        )
        for index, raw in enumerate(
            _array(payload.get("candidate_signals", []), f"{field}.candidate_signals")
        )
        for item in (_object(raw, f"{field}.candidate_signals[{index}]"),)
    )
    try:
        return HybridRrfShadowCommand(
            candidate_ids=_strings(payload.get("candidate_ids"), f"{field}.candidate_ids"),
            published_ranking=_strings(
                payload.get("published_ranking"), f"{field}.published_ranking"
            ),
            channels=channels,
            candidate_signals=signals,
            contract_version=contract_version,
        )
    except ValueError as exc:
        raise HybridShadowFixtureValidationError(f"{field}: {exc}") from exc


def _normalized_command(command: HybridRrfShadowCommand) -> dict[str, Any]:
    return {
        "contract_version": command.contract_version,
        "candidate_ids": list(command.candidate_ids),
        "published_ranking": list(command.published_ranking),
        "channels": [
            {
                "channel": item.channel.value,
                "state": item.state.value,
                "ranked_candidate_ids": list(item.ranked_candidate_ids),
            }
            for item in command.channels
        ],
        "candidate_signals": [asdict(item) for item in command.candidate_signals],
    }


def load_hybrid_shadow_fixture_payload(value: Any) -> HybridShadowFixture:
    payload = _object(value, "fixture")
    schema_version = _text(payload.get("schema_version"), "schema_version")
    if schema_version != HYBRID_SHADOW_FIXTURE_SCHEMA_V1:
        raise HybridShadowFixtureValidationError(
            f"schema_version must be {HYBRID_SHADOW_FIXTURE_SCHEMA_V1}"
        )
    fixture_version = _text(payload.get("fixture_version"), "fixture_version")
    raw_thresholds = _object(payload.get("thresholds"), "thresholds")
    thresholds = HybridShadowThresholds(
        recall_at_k_drop_max=_ratio(
            raw_thresholds.get("recall_at_k_drop_max"),
            "thresholds.recall_at_k_drop_max",
        ),
        ndcg_at_k_drop_max=_ratio(
            raw_thresholds.get("ndcg_at_k_drop_max"),
            "thresholds.ndcg_at_k_drop_max",
        ),
    )
    scenarios: list[HybridShadowScenario] = []
    scenario_ids: set[str] = set()
    for index, raw in enumerate(_array(payload.get("scenarios"), "scenarios")):
        field = f"scenarios[{index}]"
        item = _object(raw, field)
        scenario_id = _text(item.get("scenario_id"), f"{field}.scenario_id")
        if scenario_id in scenario_ids:
            raise HybridShadowFixtureValidationError(
                f"duplicate scenario_id: {scenario_id}"
            )
        scenario_ids.add(scenario_id)
        command = _command(item.get("command"), f"{field}.command")
        raw_relevance = _object(item.get("gold_relevance"), f"{field}.gold_relevance")
        if set(raw_relevance) != set(command.candidate_ids):
            raise HybridShadowFixtureValidationError(
                f"{field}.gold_relevance must cover every candidate exactly once"
            )
        relevance: dict[str, int] = {}
        for candidate_id, relevance_value in raw_relevance.items():
            if (
                isinstance(relevance_value, bool)
                or not isinstance(relevance_value, int)
                or not 0 <= relevance_value <= 3
            ):
                raise HybridShadowFixtureValidationError(
                    f"{field}.gold_relevance.{candidate_id} must be an integer from 0 to 3"
                )
            relevance[candidate_id] = relevance_value
        k = item.get("k")
        if isinstance(k, bool) or not isinstance(k, int) or not 1 <= k <= len(command.candidate_ids):
            raise HybridShadowFixtureValidationError(
                f"{field}.k must be between 1 and candidate count"
            )
        scenarios.append(
            HybridShadowScenario(
                scenario_id=scenario_id,
                k=k,
                gold_relevance=dict(sorted(relevance.items())),
                command=command,
            )
        )
    if not scenarios:
        raise HybridShadowFixtureValidationError("scenarios must be non-empty")
    normalized = tuple(sorted(scenarios, key=lambda item: item.scenario_id))
    normalized_payload = {
        "schema_version": schema_version,
        "fixture_version": fixture_version,
        "thresholds": asdict(thresholds),
        "scenarios": [
            {
                "scenario_id": item.scenario_id,
                "k": item.k,
                "gold_relevance": dict(item.gold_relevance),
                "command": _normalized_command(item.command),
            }
            for item in normalized
        ],
    }
    return HybridShadowFixture(
        schema_version=schema_version,
        fixture_version=fixture_version,
        thresholds=thresholds,
        scenarios=normalized,
        input_fingerprint=_fingerprint(normalized_payload),
    )


def load_hybrid_shadow_fixture(path: str | Path) -> HybridShadowFixture:
    artifact = Path(path)
    try:
        payload = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HybridShadowFixtureValidationError(
            f"cannot load hybrid shadow fixture: {artifact}"
        ) from exc
    return load_hybrid_shadow_fixture_payload(payload)


def _recall_at_k(ranking: tuple[str, ...], relevance: Mapping[str, int], k: int) -> float:
    relevant = {candidate_id for candidate_id, value in relevance.items() if value > 0}
    if not relevant:
        return 1.0
    return sum(candidate_id in relevant for candidate_id in ranking[:k]) / len(relevant)


def _ndcg_at_k(ranking: tuple[str, ...], relevance: Mapping[str, int], k: int) -> float:
    def dcg(values: list[int]) -> float:
        return sum(
            (2**value - 1) / math.log2(index + 2)
            for index, value in enumerate(values[:k])
        )

    actual = dcg([relevance[candidate_id] for candidate_id in ranking])
    ideal = dcg(sorted(relevance.values(), reverse=True))
    return actual / ideal if ideal else 1.0


def _rounded(value: float) -> float:
    return round(value, 6)


def evaluate_hybrid_shadow_scenario(
    scenario: HybridShadowScenario,
    thresholds: HybridShadowThresholds,
) -> HybridShadowScenarioReport:
    result = execute_hybrid_rrf_shadow(scenario.command)
    shadow_ranking = tuple(item.candidate_id for item in result.shadow_ranking)
    published_recall = _recall_at_k(
        scenario.command.published_ranking, scenario.gold_relevance, scenario.k
    )
    shadow_recall = _recall_at_k(
        shadow_ranking, scenario.gold_relevance, scenario.k
    )
    published_ndcg = _ndcg_at_k(
        scenario.command.published_ranking, scenario.gold_relevance, scenario.k
    )
    shadow_ndcg = _ndcg_at_k(shadow_ranking, scenario.gold_relevance, scenario.k)
    vector_state = next(
        item.state
        for item in scenario.command.channels
        if item.channel is RecallChannel.VECTOR
    )
    expected_signals = {
        item.candidate_id: (item.unknown_signals, item.missing_signals)
        for item in scenario.command.candidate_signals
    }
    observed_signals = {
        item.candidate_id: (item.unknown_signals, item.missing_signals)
        for item in result.shadow_ranking
        if item.unknown_signals or item.missing_signals
    }
    expected_unknown = {
        key: value[0] for key, value in expected_signals.items() if value[0]
    }
    observed_unknown = {
        key: value[0] for key, value in observed_signals.items() if value[0]
    }
    expected_missing = {
        key: value[1] for key, value in expected_signals.items() if value[1]
    }
    observed_missing = {
        key: value[1] for key, value in observed_signals.items() if value[1]
    }
    fallback_preserved = (
        vector_state is RecallChannelState.AVAILABLE
        or shadow_ranking == scenario.command.published_ranking
    )
    unknown_preserved = expected_unknown == observed_unknown
    missing_preserved = expected_missing == observed_missing
    failures: list[str] = []
    if shadow_recall + thresholds.recall_at_k_drop_max < published_recall:
        failures.append("RECALL_AT_K_NON_INFERIORITY_FAILED")
    if shadow_ndcg + thresholds.ndcg_at_k_drop_max < published_ndcg:
        failures.append("NDCG_AT_K_NON_INFERIORITY_FAILED")
    if not fallback_preserved:
        failures.append("VECTOR_FALLBACK_ORDER_CHANGED")
    if not unknown_preserved:
        failures.append("UNKNOWN_SIGNAL_STATE_LOST")
    if not missing_preserved:
        failures.append("MISSING_SIGNAL_STATE_LOST")
    if not result.shadow_only or result.promotion_allowed:
        failures.append("SHADOW_PROMOTION_BOUNDARY_VIOLATED")
    return HybridShadowScenarioReport(
        scenario_id=scenario.scenario_id,
        k=scenario.k,
        vector_state=vector_state.value,
        published_recall_at_k=_rounded(published_recall),
        shadow_recall_at_k=_rounded(shadow_recall),
        recall_delta=_rounded(shadow_recall - published_recall),
        published_ndcg_at_k=_rounded(published_ndcg),
        shadow_ndcg_at_k=_rounded(shadow_ndcg),
        ndcg_delta=_rounded(shadow_ndcg - published_ndcg),
        published_ranking=scenario.command.published_ranking,
        shadow_ranking=shadow_ranking,
        fallback_applied=result.fallback_applied,
        fallback_order_preserved=fallback_preserved,
        unknown_signals_preserved=unknown_preserved,
        missing_signals_preserved=missing_preserved,
        shadow_only=result.shadow_only,
        promotion_allowed=result.promotion_allowed,
        input_fingerprint=result.input_fingerprint,
        result_fingerprint=result.result_fingerprint,
        failures=tuple(failures),
    )


def evaluate_hybrid_shadow_fixture(
    fixture: HybridShadowFixture,
) -> HybridShadowEvaluationReport:
    scenarios = tuple(
        evaluate_hybrid_shadow_scenario(item, fixture.thresholds)
        for item in fixture.scenarios
    )
    failures = tuple(
        f"{scenario.scenario_id}:{failure}"
        for scenario in scenarios
        for failure in scenario.failures
    )
    count = len(scenarios)
    result_payload = {
        "evaluator_version": HYBRID_SHADOW_EVALUATOR_VERSION,
        "fixture_version": fixture.fixture_version,
        "input_fingerprint": fixture.input_fingerprint,
        "scenario_fingerprints": [item.result_fingerprint for item in scenarios],
        "failures": list(failures),
    }
    return HybridShadowEvaluationReport(
        evaluator_version=HYBRID_SHADOW_EVALUATOR_VERSION,
        fixture_version=fixture.fixture_version,
        status="FAIL" if failures else "PASS",
        scenario_count=count,
        average_published_recall_at_k=_rounded(
            sum(item.published_recall_at_k for item in scenarios) / count
        ),
        average_shadow_recall_at_k=_rounded(
            sum(item.shadow_recall_at_k for item in scenarios) / count
        ),
        average_published_ndcg_at_k=_rounded(
            sum(item.published_ndcg_at_k for item in scenarios) / count
        ),
        average_shadow_ndcg_at_k=_rounded(
            sum(item.shadow_ndcg_at_k for item in scenarios) / count
        ),
        input_fingerprint=fixture.input_fingerprint,
        scenarios=scenarios,
        failures=failures,
        result_fingerprint=_fingerprint(result_payload),
    )
