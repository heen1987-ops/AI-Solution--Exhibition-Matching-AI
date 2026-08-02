from __future__ import annotations

import copy
import json
from importlib.resources import files
from pathlib import Path

import pytest

from meet_ai.evaluation import (
    GoldenSetValidationError,
    HybridShadowFixtureValidationError,
    evaluate_golden_set,
    evaluate_hybrid_shadow_fixture,
    load_golden_set,
    load_golden_set_payload,
    load_hybrid_shadow_fixture,
    load_hybrid_shadow_fixture_payload,
)
from meet_ai.evaluation.__main__ import main

FIXTURE = Path(__file__).parent / "fixtures" / "matching" / "golden-set.v1.json"
HYBRID_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "matching"
    / "hybrid-rrf-shadow.v1.json"
)


def _payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _scenario(report, scenario_id: str):
    return next(item for item in report.scenarios if item.scenario_id == scenario_id)


def test_published_golden_set_passes_all_engine_quality_gates() -> None:
    report = evaluate_golden_set(load_golden_set(FIXTURE))

    assert report.status == "PASS"
    assert report.scenario_count == 3
    assert {scenario.mode for scenario in report.scenarios} == {
        "GENERAL_VISITOR",
        "BUYER_TO_EXHIBITOR",
        "RECIPROCAL",
    }
    assert report.average_recall_at_k == 1.0
    assert report.average_fallback_recall_at_k == 0.666667
    assert report.average_ndcg_at_k == 1.0
    assert report.total_hard_filter_violations == 0
    assert report.total_filter_decision_mismatches == 0
    assert report.total_explanation_violations == 0
    assert len(report.input_fingerprint) == 64
    assert len(report.result_fingerprint) == 64
    assert all(not scenario.failures for scenario in report.scenarios)
    assert all(
        len(candidate.score_fingerprint) == 64
        and len(candidate.explanation_fingerprint) == 64
        for scenario in report.scenarios
        for candidate in scenario.ranked_candidates
    )


def test_golden_set_schema_is_packaged_with_the_evaluator() -> None:
    schema = json.loads(
        files("meet_ai.evaluation")
        .joinpath("golden-set.schema.json")
        .read_text(encoding="utf-8")
    )

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["properties"]["schema_version"]["const"] == ("matching-golden-set-v1")


def test_evaluation_is_reproducible_when_component_map_order_changes() -> None:
    payload = _payload()
    first = evaluate_golden_set(load_golden_set_payload(payload))

    changed_order = copy.deepcopy(payload)
    components = changed_order["scenarios"][0]["candidates"][0]["components"]
    changed_order["scenarios"][0]["candidates"][0]["components"] = dict(
        reversed(tuple(components.items()))
    )
    changed_order["scenarios"].reverse()
    changed_order["scenarios"][0]["candidates"].reverse()
    changed_order["scenarios"][-1]["candidates"][0]["recall_channels"].reverse()
    second = evaluate_golden_set(load_golden_set_payload(changed_order))

    assert first.input_fingerprint == second.input_fingerprint
    assert first.result_fingerprint == second.result_fingerprint
    assert first.to_dict() == second.to_dict()


def test_ineligible_candidate_admission_fails_closed() -> None:
    payload = _payload()
    blocked = payload["scenarios"][0]["candidates"][-1]
    blocked["observed_eligibility"] = {"passed": True, "reason_codes": []}

    report = evaluate_golden_set(load_golden_set_payload(payload))
    scenario = _scenario(report, "visitor-gift-tasting")

    assert report.status == "FAIL"
    assert scenario.hard_filter_violations == 1
    assert scenario.filter_decision_mismatches == 1
    assert "visitor-gift-tasting:HARD_FILTER_VIOLATION" in report.failures
    assert "visitor-gift-tasting:FILTER_DECISION_MISMATCH" in report.failures


def test_ungrounded_or_unapproved_explanation_fails_gate() -> None:
    payload = _payload()
    explanation = payload["scenarios"][1]["candidates"][0]["explanations"][0]
    explanation["evidence_refs"] = []

    report = evaluate_golden_set(load_golden_set_payload(payload))

    assert report.status == "FAIL"
    assert report.total_explanation_violations == 1
    assert "buyer-distribution-fit:EXPLANATION_GROUNDING_VIOLATION" in report.failures


def test_structured_fallback_regression_is_measured_separately() -> None:
    payload = _payload()
    for candidate in payload["scenarios"][2]["candidates"][:3]:
        candidate["recall_channels"] = ["VECTOR"]

    report = evaluate_golden_set(load_golden_set_payload(payload))
    scenario = _scenario(report, "reciprocal-supplier-meeting")

    assert scenario.recall_at_k == 1.0
    assert scenario.fallback_recall_at_k == 0.0
    assert scenario.fallback_recall_drop == 1.0
    assert "FALLBACK_RECALL_DROP_ABOVE_MAX" in scenario.failures


def test_policy_version_drift_is_rejected_before_evaluation() -> None:
    payload = _payload()
    payload["policy_versions"]["buyer"] = "buyer-score-v2"

    with pytest.raises(GoldenSetValidationError, match="published policies"):
        load_golden_set_payload(payload)


def test_taxonomy_drift_and_unknown_recall_channel_are_rejected() -> None:
    taxonomy_drift = _payload()
    taxonomy_drift["taxonomy_version"] = "999.0.0"
    with pytest.raises(GoldenSetValidationError, match="published ontology"):
        load_golden_set_payload(taxonomy_drift)

    unknown_channel = _payload()
    unknown_channel["scenarios"][0]["candidates"][0]["recall_channels"].append(
        "MAGIC_MODEL"
    )
    with pytest.raises(GoldenSetValidationError, match="unknown channels"):
        load_golden_set_payload(unknown_channel)


def test_cli_prints_machine_readable_report_and_returns_success(
    capsys: pytest.CaptureFixture[str],
) -> None:
    exit_code = main([str(FIXTURE)])
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 0
    assert output["status"] == "PASS"
    assert output["result_fingerprint"]


def test_cli_returns_nonzero_for_regression(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    payload = _payload()
    payload["scenarios"][0]["candidates"][0]["explanations"][0]["evidence_refs"] = []
    failing_fixture = tmp_path / "failing-golden-set.json"
    failing_fixture.write_text(json.dumps(payload), encoding="utf-8")

    assert main([str(failing_fixture)]) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "FAIL"
    assert main([str(failing_fixture), "--allow-regression"]) == 0


def test_cli_returns_structured_error_for_invalid_artifact(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    invalid_fixture = tmp_path / "invalid-golden-set.json"
    invalid_fixture.write_text("{}", encoding="utf-8")

    assert main([str(invalid_fixture)]) == 2
    output = json.loads(capsys.readouterr().out)
    assert output["status"] == "ERROR"
    assert output["error_code"] == "GOLDEN_SET_INVALID"


def _hybrid_payload() -> dict:
    return json.loads(HYBRID_FIXTURE.read_text(encoding="utf-8"))


def test_hybrid_shadow_fixture_passes_non_inferiority_and_fallback_gates() -> None:
    report = evaluate_hybrid_shadow_fixture(
        load_hybrid_shadow_fixture(HYBRID_FIXTURE)
    )

    assert report.status == "PASS"
    assert report.scenario_count == 3
    assert report.average_shadow_recall_at_k >= report.average_published_recall_at_k
    assert report.average_shadow_ndcg_at_k >= report.average_published_ndcg_at_k
    assert {item.vector_state for item in report.scenarios} == {
        "AVAILABLE",
        "UNAVAILABLE",
        "NOT_INVOKED",
    }
    assert all(item.fallback_order_preserved for item in report.scenarios)
    assert all(item.unknown_signals_preserved for item in report.scenarios)
    assert all(item.missing_signals_preserved for item in report.scenarios)
    assert all(item.shadow_only and not item.promotion_allowed for item in report.scenarios)
    assert len(report.input_fingerprint) == 64
    assert len(report.result_fingerprint) == 64


def test_hybrid_shadow_evaluation_is_reproducible_for_set_like_order() -> None:
    payload = _hybrid_payload()
    first = evaluate_hybrid_shadow_fixture(load_hybrid_shadow_fixture_payload(payload))

    reordered = copy.deepcopy(payload)
    reordered["scenarios"].reverse()
    for scenario in reordered["scenarios"]:
        scenario["command"]["candidate_ids"].reverse()
        scenario["command"]["channels"].reverse()
        scenario["command"]["candidate_signals"].reverse()
    second = evaluate_hybrid_shadow_fixture(
        load_hybrid_shadow_fixture_payload(reordered)
    )

    assert first.input_fingerprint == second.input_fingerprint
    assert first.result_fingerprint == second.result_fingerprint
    assert first.to_dict() == second.to_dict()


def test_hybrid_shadow_detects_ndcg_regression_against_weighted_v1() -> None:
    payload = _hybrid_payload()
    payload["scenarios"][0]["command"]["published_ranking"] = [
        "candidate-a",
        "candidate-b",
        "candidate-c",
        "candidate-d",
        "candidate-e",
    ]

    report = evaluate_hybrid_shadow_fixture(
        load_hybrid_shadow_fixture_payload(payload)
    )

    assert report.status == "FAIL"
    assert (
        "natural-language-vector-available:NDCG_AT_K_NON_INFERIORITY_FAILED"
        in report.failures
    )


def test_hybrid_shadow_fixture_rejects_unknown_relevance_boundary() -> None:
    payload = _hybrid_payload()
    del payload["scenarios"][0]["gold_relevance"]["candidate-e"]

    with pytest.raises(HybridShadowFixtureValidationError, match="must cover every"):
        load_hybrid_shadow_fixture_payload(payload)
