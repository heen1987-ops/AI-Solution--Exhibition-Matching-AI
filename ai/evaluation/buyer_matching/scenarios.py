"""ai/buyer_matching 평가 시나리오 10종.

임무 지시가 요구한 10개 시나리오를 그대로 다룬다: online distribution buyer, OEM-seeking
buyer, small-order buyer, region-required, export-seeking, exhibitor-with-preference,
exhibitor-without-preference, MOQ-unknown exhibitor, hard-filter-violating exhibitor,
unverified buyer.

여기 쓰인 모든 온톨로지 코드값(ALCOHOL.*/BIZ_GOAL.*/BUYER.*/CHANNEL.*/TRADE.*/REGION.*/
CAPACITY.*)은 ``src/meet_ai/ontology/catalog.v1.json``에 실재하는 코드다(DECISION-004) -
``harness.assert_scenario_codes_in_catalog``가 이를 카탈로그와 대조해 검증한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai.buyer_matching.types import (
    BuyerProfile,
    ExhibitorBuyerPreferenceSignal,
    ExhibitorCandidate,
)


@dataclass(frozen=True)
class Scenario:
    id: str
    note: str
    buyer: BuyerProfile
    candidates: tuple[ExhibitorCandidate, ...]


def _base_exhibitor(exhibitor_id: str, **overrides: object) -> ExhibitorCandidate:
    base: dict[str, object] = {
        "exhibitor_id": exhibitor_id,
        "approval_status": "APPROVED",
        "participation_status": "APPROVED",
        "visibility_scope": "PUBLIC",
    }
    base.update(overrides)
    return ExhibitorCandidate(**base)  # type: ignore[arg-type]


def _base_buyer(buyer_id: str, **overrides: object) -> BuyerProfile:
    base: dict[str, object] = {"buyer_id": buyer_id, "verification_status": "VERIFIED"}
    base.update(overrides)
    return BuyerProfile(**base)  # type: ignore[arg-type]


def build_scenarios() -> tuple[Scenario, ...]:
    return (
        _online_distribution_buyer(),
        _oem_seeking_buyer(),
        _small_order_buyer(),
        _region_required_buyer(),
        _export_seeking_buyer(),
        _exhibitor_with_preference(),
        _exhibitor_without_preference(),
        _moq_unknown_exhibitor(),
        _hard_filter_violating_exhibitor(),
        _unverified_buyer(),
    )


def _online_distribution_buyer() -> Scenario:
    buyer = _base_buyer(
        "buyer-online-distribution",
        required_product_codes=("ALCOHOL.TAKJU",),
        preferred_product_codes=("ALCOHOL.YAKJU",),
        channel_codes=("CHANNEL.OPEN_MARKET", "CHANNEL.OWN_MALL"),
        business_goal_codes=("BIZ_GOAL.DISTRIBUTION",),
        preferred_cooperation_type_codes=("TRADE.REGULAR_SUPPLY",),
        moq_ceiling=1000,
    )
    exhibitor = _base_exhibitor(
        "exh-online-distribution",
        product_codes=("ALCOHOL.TAKJU",),
        channel_codes=("CHANNEL.OPEN_MARKET",),
        business_goal_codes=("BIZ_GOAL.DISTRIBUTION",),
        cooperation_type_codes=("TRADE.REGULAR_SUPPLY",),
        moq=500,
        monthly_capacity=20000,
        trade_readiness_score=85.0,
        data_trust_score=90.0,
    )
    return Scenario(
        id="online_distribution_buyer",
        note="온라인몰 유통을 원하는 바이어가 탁주 생산업체와 매칭된다 (제품/채널/사업목적/거래유형 모두 일치).",
        buyer=buyer,
        candidates=(exhibitor,),
    )


def _oem_seeking_buyer() -> Scenario:
    buyer = _base_buyer(
        "buyer-oem-seeking",
        required_technology_codes=("CAPACITY.OEM",),
        business_goal_codes=("BIZ_GOAL.OEM",),
        required_cooperation_type_codes=("TRADE.OEM",),
    )
    exhibitor = _base_exhibitor(
        "exh-oem-capable",
        technology_codes=("CAPACITY.OEM",),
        declared_capability_codes=("CAPACITY.OEM", "TRADE.OEM"),
        business_goal_codes=("BIZ_GOAL.OEM",),
        cooperation_type_codes=("TRADE.OEM",),
        trade_readiness_score=75.0,
    )
    return Scenario(
        id="oem_seeking_buyer",
        note="OEM 생산을 원하는 바이어 - 업체가 CAPACITY.OEM/TRADE.OEM을 명시적으로 보유선언.",
        buyer=buyer,
        candidates=(exhibitor,),
    )


def _small_order_buyer() -> Scenario:
    buyer = _base_buyer(
        "buyer-small-order",
        required_product_codes=("ALCOHOL.SOJU_DISTILLED",),
        moq_ceiling=100,
        monthly_order_min=50,
        monthly_order_max=200,
    )
    exhibitor = _base_exhibitor(
        "exh-small-batch",
        product_codes=("ALCOHOL.SOJU_DISTILLED",),
        technology_codes=("CAPACITY.SMALL_BATCH",),
        moq=80,
        monthly_capacity=5000,
        trade_readiness_score=60.0,
    )
    return Scenario(
        id="small_order_buyer",
        note="소량 주문 바이어 - MOQ 상한(100) 이내(80)이고 월 물량 범위가 생산역량 안에 든다.",
        buyer=buyer,
        candidates=(exhibitor,),
    )


def _region_required_buyer() -> Scenario:
    buyer = _base_buyer(
        "buyer-region-required",
        required_product_codes=("ALCOHOL.TAKJU",),
        required_region_codes=("REGION.KR.BUSAN",),
    )
    matching = _base_exhibitor(
        "exh-busan-supply",
        product_codes=("ALCOHOL.TAKJU",),
        supply_region_codes=("REGION.KR.BUSAN", "REGION.KR.GYEONGNAM"),
        trade_readiness_score=70.0,
    )
    non_matching = _base_exhibitor(
        "exh-seoul-only-supply",
        product_codes=("ALCOHOL.TAKJU",),
        supply_region_codes=("REGION.KR.SEOUL",),
    )
    return Scenario(
        id="region_required_buyer",
        note="필수 공급지역(부산) 조건 - 부산을 포함하는 업체만 통과, 서울만 공급하는 업체는 하드필터 탈락.",
        buyer=buyer,
        candidates=(matching, non_matching),
    )


def _export_seeking_buyer() -> Scenario:
    buyer = _base_buyer(
        "buyer-export-seeking",
        required_product_codes=("ALCOHOL.DISTILLED",),
        business_goal_codes=("BIZ_GOAL.EXPORT",),
        channel_codes=("CHANNEL.EXPORT",),
        required_cooperation_type_codes=("TRADE.EXPORT",),
    )
    exhibitor = _base_exhibitor(
        "exh-export-ready",
        product_codes=("ALCOHOL.DISTILLED",),
        technology_codes=("CAPACITY.EXPORT",),
        declared_capability_codes=("TRADE.EXPORT",),
        business_goal_codes=("BIZ_GOAL.EXPORT",),
        channel_codes=("CHANNEL.EXPORT",),
        cooperation_type_codes=("TRADE.EXPORT",),
        new_trade_available="YES",
        trade_readiness_score=95.0,
    )
    return Scenario(
        id="export_seeking_buyer",
        note="수출 상담을 원하는 바이어 - 업체가 수출 채널/거래유형/사업목적을 모두 갖춤.",
        buyer=buyer,
        candidates=(exhibitor,),
    )


def _exhibitor_with_preference() -> Scenario:
    buyer = _base_buyer(
        "buyer-matches-preference",
        required_product_codes=("ALCOHOL.WINE",),
        buyer_type_code="BUYER.DISTRIBUTOR",
        channel_codes=("CHANNEL.WHOLESALE",),
        monthly_order_min=200,
        monthly_order_max=500,
    )
    preference = ExhibitorBuyerPreferenceSignal(
        required_buyer_type_codes=("BUYER.DISTRIBUTOR",),
        preferred_channel_codes=("CHANNEL.WHOLESALE",),
        volume_min=100,
        volume_max=1000,
    )
    exhibitor = _base_exhibitor(
        "exh-declares-preference",
        product_codes=("ALCOHOL.WINE",),
        channel_codes=("CHANNEL.WHOLESALE",),
        trade_readiness_score=80.0,
        buyer_preference=preference,
    )
    return Scenario(
        id="exhibitor_with_preference",
        note="업체가 희망 바이어 프로파일을 선언 - e2b가 계산되고 상호선호(MUTUAL_PREFERENCE)가 붙어야 한다.",
        buyer=buyer,
        candidates=(exhibitor,),
    )


def _exhibitor_without_preference() -> Scenario:
    buyer = _base_buyer(
        "buyer-no-preference-declared",
        required_product_codes=("ALCOHOL.WINE",),
    )
    exhibitor = _base_exhibitor(
        "exh-no-preference",
        product_codes=("ALCOHOL.WINE",),
        trade_readiness_score=70.0,
        buyer_preference=None,
    )
    return Scenario(
        id="exhibitor_without_preference",
        note="업체가 희망 바이어 프로파일을 선언하지 않음 - e2b는 None이어야 하고 final_score == b2e.score.",
        buyer=buyer,
        candidates=(exhibitor,),
    )


def _moq_unknown_exhibitor() -> Scenario:
    buyer = _base_buyer(
        "buyer-moq-strict",
        required_product_codes=("ALCOHOL.TAKJU",),
        moq_ceiling=500,
    )
    exhibitor = _base_exhibitor(
        "exh-moq-unknown",
        product_codes=("ALCOHOL.TAKJU",),
        moq=None,  # 미확인 - MOQ 상한 조건이 있는데 업체 MOQ가 없으면 통과시키지 않는다.
    )
    return Scenario(
        id="moq_unknown_exhibitor",
        note="바이어가 MOQ 상한을 요구하는데 업체 MOQ가 미확인 - 하드필터 탈락 + INFO.MOQ_UNKNOWN 플래그.",
        buyer=buyer,
        candidates=(exhibitor,),
    )


def _hard_filter_violating_exhibitor() -> Scenario:
    buyer = _base_buyer(
        "buyer-strict-requirements",
        required_product_codes=("ALCOHOL.TAKJU",),
        required_technology_codes=("CAPACITY.OEM",),
        required_region_codes=("REGION.KR.SEOUL",),
        required_cooperation_type_codes=("TRADE.OEM",),
        require_new_trade_available=True,
        require_meeting_available=True,
    )
    exhibitor = _base_exhibitor(
        "exh-multi-violation",
        approval_status="DRAFT",  # 미승인 - 공개 전
        participation_status="CANCELLED",  # 참가 비활성
        visibility_scope="PRIVATE",  # 아직 공개범위 밖
        product_codes=(),  # ALCOHOL.TAKJU 미보유
        technology_codes=(),  # CAPACITY.OEM 미확인(UNKNOWN, declared에도 없음)
        cooperation_type_codes=(),
        supply_region_codes=(),  # 지역 미확인
        moq=None,
        new_trade_available="NO",
        meeting_available=False,
    )
    return Scenario(
        id="hard_filter_violating_exhibitor",
        note="사실상 모든 하드필터를 동시에 위반하는 업체 - passed는 False, 점수는 전혀 계산되지 않아야 한다.",
        buyer=buyer,
        candidates=(exhibitor,),
    )


def _unverified_buyer() -> Scenario:
    buyer = _base_buyer(
        "buyer-unverified",
        verification_status="UNVERIFIED",
        required_product_codes=("ALCOHOL.TAKJU",),
    )
    exhibitor = _base_exhibitor(
        "exh-otherwise-perfect",
        product_codes=("ALCOHOL.TAKJU",),
        channel_codes=("CHANNEL.OPEN_MARKET",),
        trade_readiness_score=95.0,
        data_trust_score=95.0,
    )
    return Scenario(
        id="unverified_buyer",
        note="다른 모든 조건이 완벽해도 바이어 검증상태(UNVERIFIED)가 매칭을 허용하지 않으면 하드필터에서 탈락해야 한다.",
        buyer=buyer,
        candidates=(exhibitor,),
    )
