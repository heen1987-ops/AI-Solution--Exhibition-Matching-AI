"""AI-BUYER-MATCH(WAVE 2C) 순수 점수화 함수 단위테스트. DB 없음.

``ai.buyer_matching``을 import하려면 저장소 루트가 sys.path에 있어야 한다. 통합 전 이 파일은
``Path(__file__).resolve().parents[2]``로 직접 보정을 시도했지만 그 경로는 저장소 루트가
아니라 ``apps/``였고(tests -> api -> apps), 그래서 이 파일은 통합 전까지 수집 단계에서
``ModuleNotFoundError: No module named 'ai'``로 깨져 있었다. 통합(MERGE STEP 17)에서
``apps/api/pyproject.toml``의 ``pythonpath``에 저장소 루트(``".."``/``".."``)를 추가했으므로
국소 sys.path 보정은 제거한다 - 경로 깊이를 손으로 세는 방식 자체가 원인이었다.
"""

from __future__ import annotations

import pytest
from ai.buyer_matching import reason_codes as rc
from ai.buyer_matching.hard_filter import hard_filter
from ai.buyer_matching.pipeline import evaluate_candidates, primary_results
from ai.buyer_matching.scoring import (
    grade_for_score,
    harmonic_mean,
    mutual_score,
    score_b2e,
    score_e2b,
)
from ai.buyer_matching.types import (
    BuyerProfile,
    ExhibitorBuyerPreferenceSignal,
    ExhibitorCandidate,
)
from ai.evaluation.buyer_matching.harness import run_evaluation
from ai.evaluation.buyer_matching.scenarios import build_scenarios


def _buyer(**overrides: object) -> BuyerProfile:
    base: dict[str, object] = {"buyer_id": "buyer-1", "verification_status": "VERIFIED"}
    base.update(overrides)
    return BuyerProfile(**base)  # type: ignore[arg-type]


def _exhibitor(**overrides: object) -> ExhibitorCandidate:
    base: dict[str, object] = {
        "exhibitor_id": "exh-1",
        "approval_status": "APPROVED",
        "participation_status": "APPROVED",
    }
    base.update(overrides)
    return ExhibitorCandidate(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# hard_filter
# ---------------------------------------------------------------------------


def test_hard_filter_passes_clean_candidate() -> None:
    buyer = _buyer(required_product_codes=("ALCOHOL.TAKJU",))
    exhibitor = _exhibitor(product_codes=("ALCOHOL.TAKJU",))

    results = hard_filter(buyer, [exhibitor])

    assert len(results) == 1
    assert results[0].passed is True
    assert results[0].failed_filters == ()


def test_hard_filter_blocks_unverified_buyer_regardless_of_exhibitor_quality() -> None:
    buyer = _buyer(verification_status="UNVERIFIED")
    exhibitor = _exhibitor()

    (result,) = hard_filter(buyer, [exhibitor])

    assert result.passed is False
    assert "BUYER_VERIFICATION" in result.failed_filters


@pytest.mark.parametrize("status", ["DRAFT", "REJECTED"])
def test_hard_filter_blocks_unapproved_exhibitor(status: str) -> None:
    buyer = _buyer()
    exhibitor = _exhibitor(approval_status=status)

    (result,) = hard_filter(buyer, [exhibitor])

    assert result.passed is False
    assert "EXHIBITOR_APPROVAL" in result.failed_filters


@pytest.mark.parametrize("status", ["APPLIED", "CANCELLED"])
def test_hard_filter_blocks_inactive_participation(status: str) -> None:
    buyer = _buyer()
    exhibitor = _exhibitor(participation_status=status)

    (result,) = hard_filter(buyer, [exhibitor])

    assert result.passed is False
    assert "PARTICIPATION_ACTIVE" in result.failed_filters


@pytest.mark.parametrize("scope", ["MATCHED_BUYER_ONLY", "MEETING_ACCEPTED", "PRIVATE"])
def test_hard_filter_blocks_post_meeting_visibility_scopes(scope: str) -> None:
    buyer = _buyer()
    exhibitor = _exhibitor(visibility_scope=scope)

    (result,) = hard_filter(buyer, [exhibitor])

    assert result.passed is False
    assert "VISIBILITY_SCOPE" in result.failed_filters


def test_hard_filter_required_product_missing_and_undeclared_is_flagged_as_unknown() -> None:
    """OEM 예시(임무 지시): 필수 기술코드가 미확인(UNKNOWN)이면 탈락하되, 정보 필요로 별도 표시한다."""

    buyer = _buyer(required_technology_codes=("CAPACITY.OEM",))
    exhibitor = _exhibitor(technology_codes=(), declared_capability_codes=())

    (result,) = hard_filter(buyer, [exhibitor])

    assert result.passed is False
    assert "REQUIRED_PRODUCT_TECH" in result.failed_filters
    assert "CAPACITY.OEM" in result.unknown_required_codes


def test_hard_filter_required_product_explicitly_declined_is_not_flagged_as_unknown() -> None:
    """업체가 이미 '없다'고 명시적으로 답한 코드는 UNKNOWN 정보-필요 목록에 넣지 않는다."""

    buyer = _buyer(required_technology_codes=("CAPACITY.OEM",))
    exhibitor = _exhibitor(technology_codes=(), declared_capability_codes=("CAPACITY.OEM",))

    (result,) = hard_filter(buyer, [exhibitor])

    assert result.passed is False
    assert "REQUIRED_PRODUCT_TECH" in result.failed_filters
    assert result.unknown_required_codes == ()


def test_hard_filter_required_region_missing_flags_info_region_unknown() -> None:
    buyer = _buyer(required_region_codes=("REGION.KR.BUSAN",))
    exhibitor = _exhibitor(supply_region_codes=())

    (result,) = hard_filter(buyer, [exhibitor])

    assert result.passed is False
    assert "REQUIRED_REGION" in result.failed_filters
    assert rc.INFO_REGION_UNKNOWN in result.info_codes


def test_hard_filter_moq_ceiling_exceeded_fails_without_info_flag() -> None:
    buyer = _buyer(moq_ceiling=100)
    exhibitor = _exhibitor(moq=200)

    (result,) = hard_filter(buyer, [exhibitor])

    assert result.passed is False
    assert "MOQ_CEILING" in result.failed_filters
    assert rc.INFO_MOQ_UNKNOWN not in result.info_codes


def test_hard_filter_moq_unknown_fails_with_info_flag() -> None:
    buyer = _buyer(moq_ceiling=100)
    exhibitor = _exhibitor(moq=None)

    (result,) = hard_filter(buyer, [exhibitor])

    assert result.passed is False
    assert "MOQ_CEILING" in result.failed_filters
    assert rc.INFO_MOQ_UNKNOWN in result.info_codes


def test_hard_filter_no_moq_requirement_passes_regardless_of_unknown_moq() -> None:
    buyer = _buyer(moq_ceiling=None)
    exhibitor = _exhibitor(moq=None)

    (result,) = hard_filter(buyer, [exhibitor])

    assert result.passed is True


@pytest.mark.parametrize(
    ("status", "should_pass"),
    [("YES", True), ("NEGOTIABLE", True), ("CONDITIONAL", True), ("NO", False), ("UNKNOWN", False)],
)
def test_hard_filter_new_trade_available_statuses(status: str, should_pass: bool) -> None:
    buyer = _buyer(require_new_trade_available=True)
    exhibitor = _exhibitor(new_trade_available=status)

    (result,) = hard_filter(buyer, [exhibitor])

    assert result.passed is should_pass
    if status == "CONDITIONAL":
        assert rc.INFO_TRADE_CONDITION_CONDITIONAL in result.info_codes


def test_hard_filter_meeting_available_required() -> None:
    buyer = _buyer(require_meeting_available=True)
    exhibitor = _exhibitor(meeting_available=False)

    (result,) = hard_filter(buyer, [exhibitor])

    assert result.passed is False
    assert "MEETING_AVAILABLE" in result.failed_filters


def test_hard_filter_preserves_input_order() -> None:
    buyer = _buyer()
    candidates = [_exhibitor(exhibitor_id=f"exh-{i}") for i in range(5)]

    results = hard_filter(buyer, candidates)

    assert [r.exhibitor_id for r in results] == [c.exhibitor_id for c in candidates]


# ---------------------------------------------------------------------------
# score_b2e
# ---------------------------------------------------------------------------


def test_score_b2e_perfect_match_scores_high() -> None:
    buyer = _buyer(
        required_product_codes=("ALCOHOL.TAKJU",),
        business_goal_codes=("BIZ_GOAL.DISTRIBUTION",),
        channel_codes=("CHANNEL.OPEN_MARKET",),
        moq_ceiling=1000,
        required_region_codes=("REGION.KR.SEOUL",),
        required_cooperation_type_codes=("TRADE.REGULAR_SUPPLY",),
    )
    exhibitor = _exhibitor(
        product_codes=("ALCOHOL.TAKJU",),
        business_goal_codes=("BIZ_GOAL.DISTRIBUTION",),
        channel_codes=("CHANNEL.OPEN_MARKET",),
        moq=500,
        supply_region_codes=("REGION.KR.SEOUL",),
        cooperation_type_codes=("TRADE.REGULAR_SUPPLY",),
        trade_readiness_score=90.0,
        data_trust_score=90.0,
    )

    result = score_b2e(buyer, exhibitor)

    assert result.score >= 80.0
    assert rc.MATCH_PRODUCT in result.reason_codes
    assert rc.MATCH_BUSINESS_GOAL in result.reason_codes
    assert rc.MATCH_CHANNEL in result.reason_codes
    assert rc.MATCH_MOQ in result.reason_codes
    assert rc.MATCH_REGION in result.reason_codes
    assert rc.MATCH_COOPERATION in result.reason_codes
    assert rc.MATCH_TRADE_READINESS in result.reason_codes


def test_score_b2e_missing_signals_are_renormalized_not_zeroed() -> None:
    """바이어가 아무 선호도 명시하지 않았으면 남은 신호(여기선 trade_readiness/data_trust)만으로
    재정규화되어야 한다 - 0점으로 깔리지 않는다.
    """

    buyer = _buyer()  # 아무 요구조건도 없음
    exhibitor = _exhibitor(trade_readiness_score=100.0, data_trust_score=100.0)

    result = score_b2e(buyer, exhibitor)

    assert result.score == pytest.approx(100.0)


def test_score_b2e_no_signal_at_all_scores_zero() -> None:
    buyer = _buyer()
    exhibitor = _exhibitor()

    result = score_b2e(buyer, exhibitor)

    assert result.score == 0.0


def test_score_b2e_moq_unknown_adds_info_code() -> None:
    buyer = _buyer(moq_ceiling=100)
    exhibitor = _exhibitor(moq=None)

    result = score_b2e(buyer, exhibitor)

    assert rc.INFO_MOQ_UNKNOWN in result.info_codes


def test_score_b2e_is_deterministic() -> None:
    buyer = _buyer(required_product_codes=("ALCOHOL.TAKJU",), moq_ceiling=500)
    exhibitor = _exhibitor(product_codes=("ALCOHOL.TAKJU",), moq=200, trade_readiness_score=70.0)

    first = score_b2e(buyer, exhibitor)
    second = score_b2e(buyer, exhibitor)

    assert first == second


# ---------------------------------------------------------------------------
# score_e2b
# ---------------------------------------------------------------------------


def test_score_e2b_none_when_no_preference_declared() -> None:
    buyer = _buyer()
    exhibitor = _exhibitor(buyer_preference=None)

    assert score_e2b(buyer, exhibitor) is None


def test_score_e2b_required_dimension_match_scores_full_credit() -> None:
    buyer = _buyer(buyer_type_code="BUYER.DISTRIBUTOR")
    preference = ExhibitorBuyerPreferenceSignal(required_buyer_type_codes=("BUYER.DISTRIBUTOR",))
    exhibitor = _exhibitor(buyer_preference=preference)

    result = score_e2b(buyer, exhibitor)

    assert result is not None
    assert result.score == pytest.approx(100.0)


def test_score_e2b_excluded_dimension_forces_zero_for_that_component() -> None:
    preference = ExhibitorBuyerPreferenceSignal(
        required_buyer_type_codes=("BUYER.DISTRIBUTOR",),
        excluded_buyer_type_codes=("BUYER.CONVENIENCE",),
        preferred_channel_codes=("CHANNEL.WHOLESALE",),
    )
    exhibitor = _exhibitor(channel_codes=("CHANNEL.WHOLESALE",), buyer_preference=preference)
    buyer_with_channel = _buyer(
        buyer_type_code="BUYER.CONVENIENCE", channel_codes=("CHANNEL.WHOLESALE",)
    )

    result = score_e2b(buyer_with_channel, exhibitor)

    assert result is not None
    # buyer_type 컴포넌트(0.20 가중치)는 0점으로 강제되지만 channel(0.20)은 살아있으므로
    # 전체 점수는 100이 아니면서도 0은 아니어야 한다.
    assert 0.0 < result.score < 100.0


def test_score_e2b_no_declared_dimensions_falls_back_to_verification_trust_only() -> None:
    """buyer_type/channel/region/cooperation_type/order_scale 차원을 하나도 선언하지
    않으면 유일하게 항상 값을 갖는 verification_trust(0.10 가중치)만 재정규화되어 그
    값 그대로가 최종 점수가 된다 - "신호 없음 = 0점"이 아니라 "가진 신호만으로 판단"이
    맞물려 작동하는지 확인한다. verification_trust에는 전용 MATCH.* 사유 코드가 없다.
    """

    preference = ExhibitorBuyerPreferenceSignal()  # 어떤 차원도 선언하지 않음
    exhibitor = _exhibitor(buyer_preference=preference)
    buyer = _buyer(verification_status="PENDING")  # trust 0.6 (types._BUYER_VERIFICATION_TRUST)

    result = score_e2b(buyer, exhibitor)

    assert result is not None
    assert result.score == pytest.approx(60.0)
    assert result.reason_codes == ()


# ---------------------------------------------------------------------------
# mutual_score / grade_for_score
# ---------------------------------------------------------------------------


def test_mutual_score_without_e2b_passes_through_b2e() -> None:
    assert mutual_score(72.5, None) == 72.5


def test_mutual_score_is_harmonic_mean_of_both() -> None:
    assert mutual_score(80.0, 80.0) == pytest.approx(80.0)
    assert mutual_score(100.0, 50.0) == harmonic_mean(100.0, 50.0)
    assert harmonic_mean(100.0, 50.0) == pytest.approx(66.67, abs=0.01)


def test_mutual_score_zero_on_either_side_is_zero() -> None:
    assert mutual_score(0.0, 90.0) == 0.0
    assert mutual_score(90.0, 0.0) == 0.0


@pytest.mark.parametrize(
    ("score", "expected_grade"),
    [(100.0, "HIGH"), (80.0, "HIGH"), (79.99, "MEDIUM"), (65.0, "MEDIUM"), (50.0, "POSSIBLE"), (49.99, "LOW"), (0.0, "LOW")],
)
def test_grade_thresholds(score: float, expected_grade: str) -> None:
    assert grade_for_score(score) == expected_grade


# ---------------------------------------------------------------------------
# pipeline.evaluate_candidates
# ---------------------------------------------------------------------------


def test_pipeline_never_scores_a_hard_filter_failure() -> None:
    buyer = _buyer(verification_status="REJECTED")
    exhibitor = _exhibitor(trade_readiness_score=100.0, data_trust_score=100.0)

    (result,) = evaluate_candidates(buyer, [exhibitor])

    assert result.hard_filter.passed is False
    assert result.b2e is None
    assert result.e2b is None
    assert result.final_score is None
    assert result.grade is None
    assert result.included_in_primary is False


def test_pipeline_sorts_by_final_score_descending() -> None:
    buyer = _buyer(required_product_codes=("ALCOHOL.TAKJU",))
    strong = _exhibitor(
        exhibitor_id="exh-strong",
        product_codes=("ALCOHOL.TAKJU",),
        trade_readiness_score=100.0,
        data_trust_score=100.0,
    )
    weak = _exhibitor(exhibitor_id="exh-weak", product_codes=("ALCOHOL.TAKJU",))

    results = evaluate_candidates(buyer, [weak, strong])

    assert [r.exhibitor_id for r in results] == ["exh-strong", "exh-weak"]


def test_pipeline_low_grade_excluded_from_primary_results() -> None:
    # product_tech만 완전 일치(가중치 0.20)하고, 그 외 명시적으로 선언한 선호(business_goal/
    # channel/cooperation_type, 합 가중치 0.40)는 전혀 겹치지 않아 0점 - 재정규화해도
    # (0.20*1.0)/(0.20+0.15+0.15+0.10) = 33.3점으로 LOW 등급이 나와야 한다.
    buyer = _buyer(
        required_product_codes=("ALCOHOL.TAKJU",),
        business_goal_codes=("BIZ_GOAL.EXPORT",),
        channel_codes=("CHANNEL.EXPORT",),
        preferred_cooperation_type_codes=("TRADE.EXPORT",),
    )
    exhibitor = _exhibitor(
        product_codes=("ALCOHOL.TAKJU",),
        business_goal_codes=("BIZ_GOAL.DISTRIBUTION",),
        channel_codes=("CHANNEL.WHOLESALE",),
        cooperation_type_codes=("TRADE.REGULAR_SUPPLY",),
    )

    results = evaluate_candidates(buyer, [exhibitor])
    primary = primary_results(results)

    assert results[0].hard_filter.passed is True
    assert results[0].final_score == pytest.approx(33.33, abs=0.01)
    assert results[0].grade == "LOW"
    assert results[0].included_in_primary is False
    assert primary == []


def test_pipeline_is_deterministic_across_repeated_calls() -> None:
    buyer = _buyer(required_product_codes=("ALCOHOL.TAKJU",), moq_ceiling=500)
    candidates = [
        _exhibitor(exhibitor_id="exh-a", product_codes=("ALCOHOL.TAKJU",), moq=100, trade_readiness_score=80.0),
        _exhibitor(exhibitor_id="exh-b", product_codes=(), approval_status="DRAFT"),
    ]

    first = evaluate_candidates(buyer, candidates)
    second = evaluate_candidates(buyer, candidates)

    assert first == second


def test_pipeline_emits_mutual_preference_reason_when_e2b_is_strong() -> None:
    buyer = _buyer(
        required_product_codes=("ALCOHOL.WINE",),
        buyer_type_code="BUYER.DISTRIBUTOR",
    )
    preference = ExhibitorBuyerPreferenceSignal(required_buyer_type_codes=("BUYER.DISTRIBUTOR",))
    exhibitor = _exhibitor(
        product_codes=("ALCOHOL.WINE",),
        trade_readiness_score=90.0,
        buyer_preference=preference,
    )

    (result,) = evaluate_candidates(buyer, [exhibitor])

    assert result.e2b is not None
    assert rc.MATCH_MUTUAL_PREFERENCE in result.reason_codes


# ---------------------------------------------------------------------------
# 평가 하네스: 10개 시나리오 + 불변식
# ---------------------------------------------------------------------------


def test_evaluation_harness_has_ten_scenarios() -> None:
    assert len(build_scenarios()) == 10
    assert len({s.id for s in build_scenarios()}) == 10  # 이름 중복 없음


def test_evaluation_harness_zero_hard_filter_violations_and_reproducible() -> None:
    report = run_evaluation()

    assert report.total_hard_filter_violations == 0
    assert report.all_reproducible is True
    assert len(report.scenario_reports) == 10


def test_evaluation_harness_unverified_buyer_scenario_blocks_all_candidates() -> None:
    report = run_evaluation()
    scenario_report = next(r for r in report.scenario_reports if r.scenario_id == "unverified_buyer")

    assert scenario_report.passed_hard_filter == 0


def test_evaluation_harness_hard_filter_violating_scenario_blocks_the_candidate() -> None:
    report = run_evaluation()
    scenario_report = next(
        r for r in report.scenario_reports if r.scenario_id == "hard_filter_violating_exhibitor"
    )

    assert scenario_report.passed_hard_filter == 0


def test_evaluation_harness_exhibitor_without_preference_has_no_e2b() -> None:
    scenario = next(s for s in build_scenarios() if s.id == "exhibitor_without_preference")

    (result,) = evaluate_candidates(scenario.buyer, scenario.candidates)

    assert result.e2b is None
    assert result.final_score == result.b2e.score
