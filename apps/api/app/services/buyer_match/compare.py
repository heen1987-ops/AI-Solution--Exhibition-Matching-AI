"""``POST /buyer/compare`` 비교 뷰 구성.

``build_compare_row``는 이미 로드된 값들로부터 뷰를 조립하는 순수 함수이고,
``load_compare_rows``만 실제 DB I/O를 수행한다 - 순수 함수는 DB 없이 단위 테스트할 수 있다
(특히 "UNKNOWN을 정확히 표시하는지" 검증에 이 분리가 중요하다).

승인되지 않은 업체 데이터는 노출하지 않는다는 원칙
----------------------------------------------------
``exhibitor.master_approval_status != 'APPROVED'`` 이거나 해당 행사 참가 상태가
``APPROVED``가 아니면, 그 업체는 비교 결과에서 모든 필드가 ``known=False``인
"available=False" 행으로만 나타난다(회사명조차 노출하지 않는다 - AGENTS.md 불변조건
"승인되지 않은 업체 데이터는 검색/추천 결과에 노출하지 않는다"를 비교 API에도 동일하게
적용). 존재하지 않는 exhibitor_id도 동일하게 처리해 존재 여부를 굳이 구분해서 노출하지
않는다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exhibitor import (
    Exhibitor,
    ExhibitorParticipation,
    Product,
    SupplyCapability,
    TradeCondition,
)
from app.models.meeting import AvailabilitySlot
from app.models.ontology_refs import concept

MAX_COMPARE_EXHIBITORS = 4


@dataclass(frozen=True)
class CompareFieldData:
    known: bool
    value: Any = None


_UNKNOWN = CompareFieldData(False)


@dataclass(frozen=True)
class CompareRow:
    exhibitor_id: uuid.UUID
    available: bool
    company_name: str | None
    product_tech: CompareFieldData
    channel: CompareFieldData
    order_scale: CompareFieldData
    region: CompareFieldData
    oem: CompareFieldData
    private_label: CompareFieldData
    export: CompareFieldData
    meeting_availability: CompareFieldData


def build_compare_row(
    *,
    exhibitor_id: uuid.UUID,
    exhibitor: Exhibitor | None,
    region_code: str | None,
    participation: ExhibitorParticipation | None,
    trade_condition: TradeCondition | None,
    supply_capability: SupplyCapability | None,
    product_names: list[str],
    has_open_slot: bool | None,
) -> CompareRow:
    approved = (
        exhibitor is not None
        and exhibitor.master_approval_status == "APPROVED"
        and participation is not None
        and participation.participation_status == "APPROVED"
    )
    if not approved:
        return CompareRow(
            exhibitor_id=exhibitor_id,
            available=False,
            company_name=None,
            product_tech=_UNKNOWN,
            channel=_UNKNOWN,
            order_scale=_UNKNOWN,
            region=_UNKNOWN,
            oem=_UNKNOWN,
            private_label=_UNKNOWN,
            export=_UNKNOWN,
            meeting_availability=_UNKNOWN,
        )

    assert exhibitor is not None  # narrows type for the branch above

    product_tech = (
        CompareFieldData(True, product_names) if product_names else _UNKNOWN
    )
    channel = (
        CompareFieldData(True, supply_capability.logistics_methods)
        if supply_capability is not None and supply_capability.logistics_methods
        else _UNKNOWN
    )
    order_scale = (
        CompareFieldData(
            True,
            {
                "min": trade_condition.min_order_quantity,
                "max": trade_condition.max_order_quantity,
            },
        )
        if trade_condition is not None
        and (
            trade_condition.min_order_quantity is not None
            or trade_condition.max_order_quantity is not None
        )
        else _UNKNOWN
    )
    region = CompareFieldData(True, region_code) if region_code else _UNKNOWN
    oem = (
        CompareFieldData(True, trade_condition.oem_status)
        if trade_condition is not None
        else _UNKNOWN
    )
    private_label = (
        CompareFieldData(True, trade_condition.private_label_status)
        if trade_condition is not None
        else _UNKNOWN
    )
    export = (
        CompareFieldData(True, trade_condition.export_status)
        if trade_condition is not None
        else _UNKNOWN
    )
    meeting_availability = (
        CompareFieldData(True, has_open_slot) if has_open_slot is not None else _UNKNOWN
    )

    return CompareRow(
        exhibitor_id=exhibitor_id,
        available=True,
        company_name=exhibitor.company_name,
        product_tech=product_tech,
        channel=channel,
        order_scale=order_scale,
        region=region,
        oem=oem,
        private_label=private_label,
        export=export,
        meeting_availability=meeting_availability,
    )


async def load_compare_rows(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    exhibitor_ids: list[uuid.UUID],
) -> list[CompareRow]:
    rows_out: list[CompareRow] = []
    for exhibitor_id in exhibitor_ids:
        exhibitor = await db.get(Exhibitor, exhibitor_id)
        if exhibitor is None or exhibitor.tenant_id != tenant_id or exhibitor.deleted_at is not None:
            rows_out.append(
                build_compare_row(
                    exhibitor_id=exhibitor_id,
                    exhibitor=None,
                    region_code=None,
                    participation=None,
                    trade_condition=None,
                    supply_capability=None,
                    product_names=[],
                    has_open_slot=None,
                )
            )
            continue

        region_code: str | None = None
        if exhibitor.region_concept_id is not None:
            region_code = (
                await db.execute(
                    select(concept.c.concept_code).where(
                        concept.c.concept_id == exhibitor.region_concept_id
                    )
                )
            ).scalar_one_or_none()

        participation = (
            await db.execute(
                select(ExhibitorParticipation).where(
                    ExhibitorParticipation.exhibitor_id == exhibitor_id,
                    ExhibitorParticipation.event_id == event_id,
                )
            )
        ).scalar_one_or_none()

        trade_condition: TradeCondition | None = None
        has_open_slot: bool | None = None
        if participation is not None:
            trade_condition = (
                await db.execute(
                    select(TradeCondition).where(
                        TradeCondition.participation_id == participation.participation_id,
                        TradeCondition.event_product_id.is_(None),
                        TradeCondition.approval_status == "APPROVED",
                    )
                )
            ).scalars().first()
            has_open_slot = bool(
                (
                    await db.execute(
                        select(AvailabilitySlot.availability_slot_id).where(
                            AvailabilitySlot.participation_id
                            == participation.participation_id,
                            AvailabilitySlot.status == "OPEN",
                            AvailabilitySlot.reserved_count < AvailabilitySlot.capacity,
                        ).limit(1)
                    )
                ).scalar_one_or_none()
            )

        supply_capability = (
            await db.execute(
                select(SupplyCapability).where(
                    SupplyCapability.exhibitor_id == exhibitor_id,
                    SupplyCapability.product_id.is_(None),
                )
            )
        ).scalars().first()

        product_names = list(
            (
                await db.execute(
                    select(Product.product_name).where(
                        Product.exhibitor_id == exhibitor_id,
                        Product.master_approval_status == "APPROVED",
                        Product.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
        )

        rows_out.append(
            build_compare_row(
                exhibitor_id=exhibitor_id,
                exhibitor=exhibitor,
                region_code=region_code,
                participation=participation,
                trade_condition=trade_condition,
                supply_capability=supply_capability,
                product_names=product_names,
                has_open_slot=has_open_slot,
            )
        )
    return rows_out
