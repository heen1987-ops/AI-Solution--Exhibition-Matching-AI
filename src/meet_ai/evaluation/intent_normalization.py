"""Regression fixture gate for the shared intent-normalization contract."""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from meet_ai.engine import (
    CanonicalProfileIntentCommand,
    NaturalLanguageIntentCommand,
    NormalizedIntent,
    normalize_canonical_profile_intent,
    normalize_natural_language_intent,
)

INTENT_FIXTURE_SCHEMA_V1 = "intent-normalization-fixture-v1.0"
INTENT_EVALUATOR_VERSION = "intent-normalization-evaluator-v1.0"


class IntentFixtureValidationError(ValueError):
    """Raised when the intent regression artifact violates its schema."""


@dataclass(frozen=True, slots=True)
class ExpectedUnresolved:
    reason_code: str
    candidate_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExpectedIntent:
    must_codes: tuple[str, ...]
    prefer_codes: tuple[str, ...]
    exclude_codes: tuple[str, ...]
    unknown_fields: tuple[str, ...]
    unresolved: tuple[ExpectedUnresolved, ...]


@dataclass(frozen=True, slots=True)
class IntentFixtureScenario:
    scenario_id: str
    source: Literal["NATURAL_LANGUAGE", "CANONICAL_PROFILE"]
    command: Mapping[str, Any]
    expected: ExpectedIntent
    parity_group: str | None


@dataclass(frozen=True, slots=True)
class IntentFixture:
    schema_version: str
    fixture_version: str
    scenarios: tuple[IntentFixtureScenario, ...]
    input_fingerprint: str


@dataclass(frozen=True, slots=True)
class IntentScenarioReport:
    scenario_id: str
    status: Literal["PASS", "FAIL"]
    source: str
    parity_group: str | None
    semantic_signature: str
    input_fingerprint: str
    result_fingerprint: str
    failures: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IntentEvaluationReport:
    evaluator_version: str
    fixture_version: str
    status: Literal["PASS", "FAIL"]
    scenario_count: int
    input_fingerprint: str
    scenarios: tuple[IntentScenarioReport, ...]
    failures: tuple[str, ...]
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


def _object(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise IntentFixtureValidationError(f"{field} must be an object")
    return value


def _array(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        raise IntentFixtureValidationError(f"{field} must be an array")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise IntentFixtureValidationError(f"{field} must be non-empty text")
    return value.strip()


def _strings(value: Any, field: str) -> tuple[str, ...]:
    result = tuple(_text(item, f"{field}[]") for item in _array(value, field))
    if len(result) != len(set(result)):
        raise IntentFixtureValidationError(f"{field} contains duplicates")
    return tuple(sorted(result))


def _expected(value: Any, field: str) -> ExpectedIntent:
    payload = _object(value, field)
    allowed = {
        "must_codes",
        "prefer_codes",
        "exclude_codes",
        "unknown_fields",
        "unresolved",
    }
    if set(payload) != allowed:
        raise IntentFixtureValidationError(f"{field} must contain the exact expected fields")
    unresolved = tuple(
        ExpectedUnresolved(
            reason_code=_text(item.get("reason_code"), f"{entry}.reason_code"),
            candidate_codes=_strings(
                item.get("candidate_codes"), f"{entry}.candidate_codes"
            ),
        )
        for index, raw in enumerate(_array(payload["unresolved"], f"{field}.unresolved"))
        for entry in (f"{field}.unresolved[{index}]",)
        for item in (_object(raw, entry),)
    )
    return ExpectedIntent(
        must_codes=_strings(payload["must_codes"], f"{field}.must_codes"),
        prefer_codes=_strings(payload["prefer_codes"], f"{field}.prefer_codes"),
        exclude_codes=_strings(payload["exclude_codes"], f"{field}.exclude_codes"),
        unknown_fields=_strings(payload["unknown_fields"], f"{field}.unknown_fields"),
        unresolved=tuple(
            sorted(unresolved, key=lambda item: (item.reason_code, item.candidate_codes))
        ),
    )


def load_intent_fixture_payload(value: Any) -> IntentFixture:
    payload = _object(value, "fixture")
    if set(payload) != {"schema_version", "fixture_version", "scenarios"}:
        raise IntentFixtureValidationError("fixture must contain the exact schema fields")
    schema_version = _text(payload["schema_version"], "schema_version")
    if schema_version != INTENT_FIXTURE_SCHEMA_V1:
        raise IntentFixtureValidationError(
            f"schema_version must be {INTENT_FIXTURE_SCHEMA_V1}"
        )
    fixture_version = _text(payload["fixture_version"], "fixture_version")
    scenarios: list[IntentFixtureScenario] = []
    scenario_ids: set[str] = set()
    for index, raw in enumerate(_array(payload["scenarios"], "scenarios")):
        field = f"scenarios[{index}]"
        item = _object(raw, field)
        allowed = {"scenario_id", "source", "command", "expected", "parity_group"}
        if set(item) - allowed or not {"scenario_id", "source", "command", "expected"} <= set(item):
            raise IntentFixtureValidationError(f"{field} has invalid fields")
        scenario_id = _text(item["scenario_id"], f"{field}.scenario_id")
        if scenario_id in scenario_ids:
            raise IntentFixtureValidationError(f"duplicate scenario_id: {scenario_id}")
        scenario_ids.add(scenario_id)
        source = _text(item["source"], f"{field}.source")
        if source not in {"NATURAL_LANGUAGE", "CANONICAL_PROFILE"}:
            raise IntentFixtureValidationError(f"{field}.source is invalid")
        command = _object(item["command"], f"{field}.command")
        parity = item.get("parity_group")
        if parity is not None:
            parity = _text(parity, f"{field}.parity_group")
        scenarios.append(
            IntentFixtureScenario(
                scenario_id=scenario_id,
                source=source,
                command=command,
                expected=_expected(item["expected"], f"{field}.expected"),
                parity_group=parity,
            )
        )
    if not scenarios:
        raise IntentFixtureValidationError("scenarios must be non-empty")
    normalized = tuple(sorted(scenarios, key=lambda item: item.scenario_id))
    normalized_payload = {
        "schema_version": schema_version,
        "fixture_version": fixture_version,
        "scenarios": [asdict(item) for item in normalized],
    }
    return IntentFixture(
        schema_version,
        fixture_version,
        normalized,
        _fingerprint(normalized_payload),
    )


def load_intent_fixture(path: str | Path) -> IntentFixture:
    artifact = Path(path)
    try:
        value = json.loads(artifact.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise IntentFixtureValidationError(f"cannot load intent fixture: {artifact}") from exc
    return load_intent_fixture_payload(value)


def _execute(scenario: IntentFixtureScenario) -> NormalizedIntent:
    command = scenario.command
    try:
        if scenario.source == "NATURAL_LANGUAGE":
            if set(command) - {"query", "locale", "context"} or "query" not in command:
                raise IntentFixtureValidationError(
                    f"{scenario.scenario_id} natural-language command has invalid fields"
                )
            return normalize_natural_language_intent(
                NaturalLanguageIntentCommand(
                    query=command["query"],
                    locale=command.get("locale", "ko-KR"),
                    context=command.get("context", "ANY"),
                )
            )
        if set(command) - {
            "must_codes",
            "prefer_codes",
            "exclude_codes",
            "unknown_fields",
        }:
            raise IntentFixtureValidationError(
                f"{scenario.scenario_id} canonical-profile command has invalid fields"
            )
        return normalize_canonical_profile_intent(
            CanonicalProfileIntentCommand(
                must_codes=tuple(command.get("must_codes", ())),
                prefer_codes=tuple(command.get("prefer_codes", ())),
                exclude_codes=tuple(command.get("exclude_codes", ())),
                unknown_fields=tuple(command.get("unknown_fields", ())),
            )
        )
    except (TypeError, ValueError) as exc:
        raise IntentFixtureValidationError(f"{scenario.scenario_id}: {exc}") from exc


def _semantic_payload(result: NormalizedIntent) -> dict[str, Any]:
    return {
        "must_codes": [item.concept_code for item in result.must],
        "prefer_codes": [item.concept_code for item in result.prefer],
        "exclude_codes": [item.concept_code for item in result.exclude],
        "unknown_fields": [item.field_code for item in result.unknown],
        "unresolved": [
            {
                "reason_code": item.reason_code,
                "candidate_codes": list(item.candidate_codes),
            }
            for item in result.unresolved
        ],
    }


def evaluate_intent_fixture(fixture: IntentFixture) -> IntentEvaluationReport:
    reports: list[IntentScenarioReport] = []
    results: dict[str, NormalizedIntent] = {}
    parity_groups: dict[str, list[str]] = defaultdict(list)
    failures: list[str] = []
    for scenario in fixture.scenarios:
        result = _execute(scenario)
        results[scenario.scenario_id] = result
        expected = {
            "must_codes": list(scenario.expected.must_codes),
            "prefer_codes": list(scenario.expected.prefer_codes),
            "exclude_codes": list(scenario.expected.exclude_codes),
            "unknown_fields": list(scenario.expected.unknown_fields),
            "unresolved": [
                {
                    "reason_code": item.reason_code,
                    "candidate_codes": list(item.candidate_codes),
                }
                for item in scenario.expected.unresolved
            ],
        }
        actual = _semantic_payload(result)
        scenario_failures: list[str] = []
        for field in ("must_codes", "prefer_codes", "exclude_codes", "unknown_fields", "unresolved"):
            if actual[field] != expected[field]:
                scenario_failures.append(f"{field.upper()}_MISMATCH")
        if scenario.parity_group:
            parity_groups[scenario.parity_group].append(scenario.scenario_id)
        reports.append(
            IntentScenarioReport(
                scenario_id=scenario.scenario_id,
                status="FAIL" if scenario_failures else "PASS",
                source=scenario.source,
                parity_group=scenario.parity_group,
                semantic_signature=_fingerprint(actual),
                input_fingerprint=result.input_fingerprint,
                result_fingerprint=result.result_fingerprint,
                failures=tuple(scenario_failures),
            )
        )
        failures.extend(f"{scenario.scenario_id}:{item}" for item in scenario_failures)

    report_by_id = {item.scenario_id: item for item in reports}
    for group, scenario_ids in sorted(parity_groups.items()):
        signatures = {report_by_id[item].semantic_signature for item in scenario_ids}
        if len(scenario_ids) < 2:
            failures.append(f"{group}:PARITY_GROUP_TOO_SMALL")
        elif len(signatures) != 1:
            failures.append(f"{group}:SEMANTIC_PARITY_MISMATCH")

    normalized_reports = tuple(sorted(reports, key=lambda item: item.scenario_id))
    result_payload = {
        "evaluator_version": INTENT_EVALUATOR_VERSION,
        "fixture_version": fixture.fixture_version,
        "status": "FAIL" if failures else "PASS",
        "scenario_count": len(normalized_reports),
        "input_fingerprint": fixture.input_fingerprint,
        "scenarios": [asdict(item) for item in normalized_reports],
        "failures": sorted(failures),
    }
    return IntentEvaluationReport(
        evaluator_version=INTENT_EVALUATOR_VERSION,
        fixture_version=fixture.fixture_version,
        status="FAIL" if failures else "PASS",
        scenario_count=len(normalized_reports),
        input_fingerprint=fixture.input_fingerprint,
        scenarios=normalized_reports,
        failures=tuple(sorted(failures)),
        result_fingerprint=_fingerprint(result_payload),
    )
