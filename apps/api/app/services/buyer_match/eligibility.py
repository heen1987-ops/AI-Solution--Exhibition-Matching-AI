"""바이어 매칭 하드필터 (합격하지 못한 업체는 결과에 절대 나타나지 않는다).

``CandidateRow``는 DB에서 뽑아낸 값 그대로를 담는 순수 데이터 구조이고, ``hard_filter``는
부작용 없는 순수 함수다 - orchestrator가 DB I/O를 담당하고, 이 모듈은 판정 로직만 담당한다
(단위 테스트가 DB 없이도 하드필터 규칙을 검증할 수 있도록 하기 위한 의도적 분리).

값을 모르면 "통과"로 단정하지 않는다는 원칙
--------------------------------------------
바이어가 특정 조건(OEM 가능 여부, 가격대 등)을 명시적으로 요구했는데 업체 쪽 데이터가 아예
없거나 명시적으로 UNKNOWN이면, 이 필터는 그 후보를 통과시키지 않는다(AGENTS.md 불변조건:
"AI는 원문에 없는 값을 단정하지 않는다"를 매칭 이전 단계에도 동일하게 적용한 것 - 데이터가
없다는 사실 자체를 "조건을 만족한다"는 뜻으로 바꿔치기하지 않는다).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

_POSITIVE_TRADE_STATUSES = frozenset({"YES", "NEGOTIABLE"})


@dataclass(frozen=True)
class CandidateRow:
    """하드필터·점수산정에 필요한 후보 1건의 원시 데이터."""

    exhibitor_id: uuid.UUID
    participation_id: uuid.UUID
    category_codes: frozenset[str] = frozenset()
    region_code: str | None = None
    has_trade_condition: bool = False
    oem_status: str | None = None
    private_label_status: str | None = None
    export_status: str | None = None
    min_order_quantity: int | None = None
    max_order_quantity: int | None = None
    wholesale_price_min: int | None = None
    wholesale_price_max: int | None = None
    profile_approved: bool = False


@dataclass(frozen=True)
class BuyerCriteria:
    """바이어가 이번 실행에 적용한 유효 필터(요청 필터 + BuyerNeed 보강값)."""

    categories: frozenset[str] = frozenset()
    channels: frozenset[str] = frozenset()
    regions: frozenset[str] = frozenset()
    price_min: int | None = None
    price_max: int | None = None
    monthly_units_min: int | None = None
    monthly_units_max: int | None = None
    oem_required: bool | None = None
    private_label_required: bool | None = None
    export_required: bool | None = None

    def to_json(self) -> dict:
        return {
            "categories": sorted(self.categories),
            "channels": sorted(self.channels),
            "regions": sorted(self.regions),
            "price_min": self.price_min,
            "price_max": self.price_max,
            "monthly_units_min": self.monthly_units_min,
            "monthly_units_max": self.monthly_units_max,
            "oem_required": self.oem_required,
            "private_label_required": self.private_label_required,
            "export_required": self.export_required,
        }


@dataclass(frozen=True)
class HardFilterOutcome:
    passed: bool
    reason: str | None = None


def hard_filter(candidate: CandidateRow, criteria: BuyerCriteria) -> HardFilterOutcome:
    """바이어가 명시한 조건 중 하나라도 어기면(또는 판정 불가면) 탈락시킨다."""

    if criteria.regions and candidate.region_code not in criteria.regions:
        return HardFilterOutcome(False, "REGION_NOT_MATCHED")

    if criteria.categories and not (candidate.category_codes & criteria.categories):
        return HardFilterOutcome(False, "CATEGORY_NOT_MATCHED")

    if criteria.oem_required and candidate.oem_status not in _POSITIVE_TRADE_STATUSES:
        return HardFilterOutcome(False, "OEM_NOT_AVAILABLE")

    if (
        criteria.private_label_required
        and candidate.private_label_status not in _POSITIVE_TRADE_STATUSES
    ):
        return HardFilterOutcome(False, "PRIVATE_LABEL_NOT_AVAILABLE")

    if criteria.export_required and candidate.export_status not in _POSITIVE_TRADE_STATUSES:
        return HardFilterOutcome(False, "EXPORT_NOT_AVAILABLE")

    if criteria.price_min is not None or criteria.price_max is not None:
        if candidate.wholesale_price_min is None and candidate.wholesale_price_max is None:
            return HardFilterOutcome(False, "PRICE_UNKNOWN")
        cand_min = (
            candidate.wholesale_price_min
            if candidate.wholesale_price_min is not None
            else candidate.wholesale_price_max
        )
        cand_max = (
            candidate.wholesale_price_max
            if candidate.wholesale_price_max is not None
            else candidate.wholesale_price_min
        )
        req_min = criteria.price_min if criteria.price_min is not None else 0
        req_max = criteria.price_max if criteria.price_max is not None else cand_max
        if cand_max < req_min or cand_min > req_max:
            return HardFilterOutcome(False, "PRICE_RANGE_NOT_MATCHED")

    if criteria.monthly_units_min is not None or criteria.monthly_units_max is not None:
        if candidate.min_order_quantity is None and candidate.max_order_quantity is None:
            return HardFilterOutcome(False, "ORDER_SCALE_UNKNOWN")
        cand_min = (
            candidate.min_order_quantity
            if candidate.min_order_quantity is not None
            else candidate.max_order_quantity
        )
        cand_max = (
            candidate.max_order_quantity
            if candidate.max_order_quantity is not None
            else candidate.min_order_quantity
        )
        req_min = criteria.monthly_units_min if criteria.monthly_units_min is not None else 0
        req_max = (
            criteria.monthly_units_max
            if criteria.monthly_units_max is not None
            else cand_max
        )
        if cand_max < req_min or cand_min > req_max:
            return HardFilterOutcome(False, "ORDER_SCALE_NOT_MATCHED")

    return HardFilterOutcome(True)
