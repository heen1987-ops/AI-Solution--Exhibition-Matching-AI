"""ai/buyer_matching 평가 하네스.

``run_evaluation()``이 scenarios.build_scenarios()의 10개 시나리오 각각에 대해
``pipeline.evaluate_candidates()``를 돌리고 다음 불변식을 검증한다:

1. **하드필터 위반 0건**: hard_filter를 통과하지 못한 후보는 어떤 결과에서도 점수
   (b2e/e2b/final_score/grade)를 갖지 않는다. 이 하네스가 세는 "violation"이란 바로
   이 불변식이 깨진 경우의 수이며, 항상 0이어야 한다(임무 지시).
2. **재현성(reproducibility)**: 같은 입력으로 두 번 실행하면 완전히 동일한 결과가 나온다
   (dataclass 동등비교로 확인) - 난수·시각 의존이 없다는 증거.
3. **온톨로지 코드 유효성**: 시나리오가 쓰는 모든 코드값이
   ``src/meet_ai/ontology/catalog.v1.json``에 실재한다(DECISION-004).

CLI로도 실행 가능: ``python -m ai.evaluation.buyer_matching.harness``.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path

# ai/tests/conftest.py와 동일한 패턴: 이 파일을 단독 실행(-m)하거나 리포지토리 루트 밖에서
# import할 때도 `import ai...`/`import meet_ai...`가 항상 되도록 리포지토리 루트를 sys.path에
# 넣는다.
_REPO_ROOT = Path(__file__).resolve().parents[3]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ai.buyer_matching.pipeline import evaluate_candidates
from ai.buyer_matching.types import BuyerMatchResult
from ai.evaluation.buyer_matching.scenarios import Scenario, build_scenarios
from meet_ai.ontology import load_catalog


@dataclass
class ScenarioReport:
    scenario_id: str
    note: str
    total_candidates: int
    passed_hard_filter: int
    hard_filter_violations: int  # 항상 0이어야 한다
    reproducible: bool
    grades: dict[str, int] = field(default_factory=dict)


@dataclass
class EvaluationReport:
    scenario_reports: tuple[ScenarioReport, ...]

    @property
    def total_hard_filter_violations(self) -> int:
        return sum(r.hard_filter_violations for r in self.scenario_reports)

    @property
    def all_reproducible(self) -> bool:
        return all(r.reproducible for r in self.scenario_reports)


def _count_hard_filter_violations(results: list[BuyerMatchResult]) -> int:
    """하드필터를 통과 못 했는데도 점수가 매겨진 결과의 수. 파이프라인이 올바르면 항상 0."""

    violations = 0
    for result in results:
        scored = (
            result.b2e is not None
            or result.e2b is not None
            or result.final_score is not None
            or result.grade is not None
        )
        if not result.hard_filter.passed and scored:
            violations += 1
    return violations


def _run_scenario(scenario: Scenario) -> ScenarioReport:
    first = evaluate_candidates(scenario.buyer, scenario.candidates)
    second = evaluate_candidates(scenario.buyer, scenario.candidates)

    violations = _count_hard_filter_violations(first)
    passed = sum(1 for r in first if r.hard_filter.passed)

    grades: dict[str, int] = {}
    for r in first:
        if r.grade is not None:
            grades[r.grade] = grades.get(r.grade, 0) + 1

    return ScenarioReport(
        scenario_id=scenario.id,
        note=scenario.note,
        total_candidates=len(scenario.candidates),
        passed_hard_filter=passed,
        hard_filter_violations=violations,
        reproducible=(first == second),
        grades=grades,
    )


def _collect_codes(scenario: Scenario) -> set[str]:
    codes: set[str] = set()
    buyer = scenario.buyer
    codes.update(buyer.required_product_codes)
    codes.update(buyer.preferred_product_codes)
    codes.update(buyer.required_technology_codes)
    codes.update(buyer.preferred_technology_codes)
    codes.update(buyer.business_goal_codes)
    codes.update(buyer.channel_codes)
    codes.update(buyer.required_region_codes)
    codes.update(buyer.preferred_region_codes)
    codes.update(buyer.required_cooperation_type_codes)
    codes.update(buyer.preferred_cooperation_type_codes)
    if buyer.buyer_type_code:
        codes.add(buyer.buyer_type_code)

    for exhibitor in scenario.candidates:
        codes.update(exhibitor.product_codes)
        codes.update(exhibitor.technology_codes)
        codes.update(exhibitor.cooperation_type_codes)
        codes.update(exhibitor.declared_capability_codes)
        codes.update(exhibitor.business_goal_codes)
        codes.update(exhibitor.channel_codes)
        codes.update(exhibitor.supply_region_codes)
        pref = exhibitor.buyer_preference
        if pref is not None:
            codes.update(pref.required_buyer_type_codes)
            codes.update(pref.preferred_buyer_type_codes)
            codes.update(pref.excluded_buyer_type_codes)
            codes.update(pref.required_channel_codes)
            codes.update(pref.preferred_channel_codes)
            codes.update(pref.excluded_channel_codes)
            codes.update(pref.required_region_codes)
            codes.update(pref.preferred_region_codes)
            codes.update(pref.excluded_region_codes)
            codes.update(pref.required_cooperation_type_codes)
            codes.update(pref.preferred_cooperation_type_codes)
            codes.update(pref.excluded_cooperation_type_codes)
    return codes


def assert_scenario_codes_in_catalog(scenarios: tuple[Scenario, ...]) -> None:
    """평가 시나리오가 쓰는 온톨로지 코드가 전부 카탈로그에 실재하는지 검증한다
    (DECISION-004 - 카탈로그에 없는 코드를 만들어내지 않는다).
    """

    catalog = load_catalog()
    known = set(catalog.by_code)
    for scenario in scenarios:
        used = _collect_codes(scenario)
        unknown = used - known
        if unknown:
            raise AssertionError(
                f"scenario '{scenario.id}' uses codes not present in catalog.v1.json: {sorted(unknown)}"
            )


def run_evaluation() -> EvaluationReport:
    scenarios = build_scenarios()
    assert_scenario_codes_in_catalog(scenarios)
    reports = tuple(_run_scenario(s) for s in scenarios)
    return EvaluationReport(scenario_reports=reports)


def _print_report(report: EvaluationReport) -> None:
    for r in report.scenario_reports:
        print(
            f"[{r.scenario_id}] candidates={r.total_candidates} "
            f"passed_hard_filter={r.passed_hard_filter} "
            f"violations={r.hard_filter_violations} "
            f"reproducible={r.reproducible} grades={r.grades}"
        )
    print(
        f"TOTAL hard_filter_violations={report.total_hard_filter_violations} "
        f"all_reproducible={report.all_reproducible}"
    )


if __name__ == "__main__":
    _report = run_evaluation()
    _print_report(_report)
    if _report.total_hard_filter_violations != 0:
        raise SystemExit(1)
    if not _report.all_reproducible:
        raise SystemExit(1)
