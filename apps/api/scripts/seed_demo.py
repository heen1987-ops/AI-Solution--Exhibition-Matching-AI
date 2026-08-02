"""Minimal demo/test fixture data for the public exhibition catalog API.

Builds: 1 event, 12 exhibitors (8 APPROVED + 4 not-approved), 28 products (>= 24), 12 booths
(OPEN/PAUSED/CLOSED mixed), each product tagged with an ontology 주종(ALCOHOL.*) concept.

Two ways to use this module
----------------------------
1. As a script against a real, already-migrated database::

       DATABASE_URL=postgresql+asyncpg://... python -m scripts.seed_demo

   (or ``python scripts/seed_demo.py`` from ``apps/api`` with ``DATABASE_URL`` exported).

2. As an importable fixture builder from tests::

       from scripts.seed_demo import build_demo_dataset
       dataset = build_demo_dataset()
       session.add_all(dataset.all_objects())

``build_demo_dataset()`` never touches a database - it only constructs plain SQLAlchemy model
instances in memory (safe to call without DB connectivity, which is why this module could be
authored and reviewed even though this task could not run a live DB - see task instructions).

Ontology dependency
--------------------
``Product.category_concept_id``/``category_taxonomy_version_id`` reference
``ontology.concept_revision(taxonomy_version_id, concept_id)`` via a composite FK (no hardcoded
enum, per project rule). This script resolves those ids the same deterministic way
``app/api/v1/routers/profile.py`` already does for profile attributes: ``stable_uuid("concept",
code)`` / ``stable_uuid("taxonomy-version", catalog.version)`` from
``meet_ai.ontology.catalog``. Inserting against a real database will still fail with a FK
violation if the ontology catalog itself has not been seeded into ``ontology.concept`` /
``ontology.concept_revision`` yet (via ``meet-ai-ontology`` or the ontology migration's seed
step) - that is expected and mirrors the note already in ``profile.py``, not a bug in this
script.
"""

from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import dataclass, field
from datetime import date, time
from decimal import Decimal

from meet_ai.ontology.catalog import load_catalog, stable_uuid

from app.models.core import Event, EventDay, EventZone, Tenant
from app.models.exhibitor import (
    Booth,
    EventProduct,
    Exhibitor,
    ExhibitorParticipation,
    Product,
    ProductImage,
)

# db-erd 12.5/12.7절 "주종" 개념 코드 - 6단계 온톨로지 카탈로그(catalog.v1.json)에 이미
# 존재하는 ALCOHOL.* 코드를 그대로 쓴다(하드코딩 enum 금지 원칙 - 코드값 자체는 카탈로그가
# 정의한 것을 그대로 참조만 한다).
_CATEGORY_CODES: tuple[str, ...] = (
    "ALCOHOL.TAKJU",
    "ALCOHOL.YAKJU",
    "ALCOHOL.CHEONGJU",
    "ALCOHOL.SOJU_DISTILLED",
    "ALCOHOL.FRUIT_WINE",
    "ALCOHOL.LIQUEUR",
    "ALCOHOL.BEER",
)

_BOOTH_STATUS_CYCLE: tuple[str, ...] = ("OPEN", "OPEN", "PAUSED", "CLOSED")
_APPROVED_EXHIBITOR_COUNT = 8
_UNAPPROVED_STATUSES: tuple[str, ...] = ("DRAFT", "DRAFT", "REJECTED", "REJECTED")
_PRODUCTS_PER_APPROVED_EXHIBITOR = 3
_PRODUCTS_PER_UNAPPROVED_EXHIBITOR = 1


def _category_ids(index: int) -> tuple[uuid.UUID, uuid.UUID]:
    catalog = load_catalog()
    code = _CATEGORY_CODES[index % len(_CATEGORY_CODES)]
    return stable_uuid("taxonomy-version", catalog.version), stable_uuid("concept", code)


@dataclass
class DemoDataset:
    tenant: Tenant
    event: Event
    event_days: list[EventDay] = field(default_factory=list)
    zones: list[EventZone] = field(default_factory=list)
    exhibitors: list[Exhibitor] = field(default_factory=list)
    participations: list[ExhibitorParticipation] = field(default_factory=list)
    booths: list[Booth] = field(default_factory=list)
    products: list[Product] = field(default_factory=list)
    event_products: list[EventProduct] = field(default_factory=list)
    product_images: list[ProductImage] = field(default_factory=list)

    @property
    def approved_exhibitor_ids(self) -> list[uuid.UUID]:
        return [
            exhibitor.exhibitor_id
            for exhibitor in self.exhibitors
            if exhibitor.master_approval_status == "APPROVED"
        ]

    @property
    def unapproved_exhibitor_ids(self) -> list[uuid.UUID]:
        return [
            exhibitor.exhibitor_id
            for exhibitor in self.exhibitors
            if exhibitor.master_approval_status != "APPROVED"
        ]

    @property
    def unapproved_exhibitor_id(self) -> uuid.UUID:
        return self.unapproved_exhibitor_ids[0]

    def all_objects(self) -> list[object]:
        """FK-safe insertion order (parents before children).

        SQLAlchemy's unit-of-work also topo-sorts INSERTs on flush regardless of list order,
        but keeping this explicit makes the fixture readable and keeps the matching delete-time
        cleanup in tests straightforward.
        """

        return [
            self.tenant,
            self.event,
            *self.event_days,
            *self.zones,
            *self.exhibitors,
            *self.participations,
            *self.booths,
            *self.products,
            *self.event_products,
            *self.product_images,
        ]


def build_demo_dataset() -> DemoDataset:
    tenant = Tenant(
        tenant_id=uuid.uuid4(),
        tenant_code=f"DEMO-{uuid.uuid4().hex[:8]}",
        tenant_name="백주대간 데모 주최사",
    )
    event = Event(
        event_id=uuid.uuid4(),
        tenant_id=tenant.tenant_id,
        event_code=f"BACKJU-DEMO-{uuid.uuid4().hex[:8]}",
        event_name="2026 백주대간 박람회 (데모)",
        venue_name="데모 컨벤션센터",
        timezone="Asia/Seoul",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        event_status="OPEN",
    )
    event_days = [
        EventDay(
            event_day_id=uuid.uuid4(),
            tenant_id=tenant.tenant_id,
            event_id=event.event_id,
            event_date=date(2026, 9, day),
            open_at=time(10, 0),
            close_at=time(18, 0),
            status="OPEN" if day == 1 else "PLANNED",
        )
        for day in (1, 2, 3)
    ]
    zones = [
        EventZone(
            event_zone_id=uuid.uuid4(),
            tenant_id=tenant.tenant_id,
            event_id=event.event_id,
            zone_code=code,
            zone_name=name,
            floor_label="1F",
            zone_type="HALL",
        )
        for code, name in (("A", "A홀"), ("B", "B홀"), ("C", "C홀"))
    ]

    dataset = DemoDataset(tenant=tenant, event=event, event_days=event_days, zones=zones)

    booth_number = 1
    exhibitor_index = 0

    def _add_exhibitor(
        *, approved: bool, master_status: str, booth_status: str
    ) -> None:
        nonlocal booth_number, exhibitor_index
        exhibitor_index += 1
        exhibitor = Exhibitor(
            exhibitor_id=uuid.uuid4(),
            tenant_id=tenant.tenant_id,
            company_name=f"데모양조장 {exhibitor_index:02d}",
            company_summary=f"{exhibitor_index}번째 데모 업체의 전통주 소개.",
            master_approval_status=master_status,
            data_completeness_percent=Decimal("80.00"),
        )
        participation = ExhibitorParticipation(
            participation_id=uuid.uuid4(),
            tenant_id=tenant.tenant_id,
            event_id=event.event_id,
            exhibitor_id=exhibitor.exhibitor_id,
            participation_status="APPROVED" if approved else "APPLIED",
            promotion_summary="데모 프로모션",
        )
        zone = zones[exhibitor_index % len(zones)]
        booth = Booth(
            booth_id=uuid.uuid4(),
            tenant_id=tenant.tenant_id,
            event_id=event.event_id,
            participation_id=participation.participation_id,
            zone_id=zone.event_zone_id,
            booth_number=f"{zone.zone_code}-{booth_number:02d}",
            map_x=Decimal(f"{10 + exhibitor_index * 5}.000"),
            map_y=Decimal(f"{20 + exhibitor_index * 3}.000"),
            operating_status=booth_status,
            congestion_level="LOW",
            estimated_wait_minutes=0 if booth_status != "OPEN" else 5,
        )
        booth_number += 1

        dataset.exhibitors.append(exhibitor)
        dataset.participations.append(participation)
        dataset.booths.append(booth)

        product_count = (
            _PRODUCTS_PER_APPROVED_EXHIBITOR
            if approved
            else _PRODUCTS_PER_UNAPPROVED_EXHIBITOR
        )
        for product_seq in range(product_count):
            taxonomy_version_id, category_concept_id = _category_ids(
                exhibitor_index + product_seq
            )
            product = Product(
                product_id=uuid.uuid4(),
                exhibitor_id=exhibitor.exhibitor_id,
                product_name=f"{exhibitor.company_name} 대표주 {product_seq + 1}",
                product_summary="쌀과 누룩으로 정성껏 빚은 프리미엄 전통주.",
                category_taxonomy_version_id=taxonomy_version_id,
                category_concept_id=category_concept_id,
                alcohol_percentage=Decimal(f"{12 + product_seq}.00"),
                master_approval_status="APPROVED",
            )
            # 마지막 승인 업체의 마지막 제품 하나만 event_product 승인 대기 상태로 남겨
            # "제품은 있지만 아직 공개되지 않는" 경우를 재현한다 (product_attribute/event_product
            # 승인 필터가 exhibitor 승인과 별개로 동작함을 시드 데이터로도 보여준다).
            is_last_product_of_last_approved = (
                approved
                and exhibitor_index == _APPROVED_EXHIBITOR_COUNT
                and product_seq == product_count - 1
            )
            event_product = EventProduct(
                event_product_id=uuid.uuid4(),
                tenant_id=tenant.tenant_id,
                event_id=event.event_id,
                participation_id=participation.participation_id,
                product_id=product.product_id,
                retail_price_amount=25000 + product_seq * 5000,
                event_price_amount=22000 + product_seq * 5000,
                currency="KRW",
                tasting_status="AVAILABLE",
                purchase_status="AVAILABLE",
                inventory_status="UNKNOWN",  # 08 2.3절: 재고는 상담수락 이후 공개정보 - 공개
                # API가 절대 읽지 않는 필드지만, 시드 데이터는 그래도 현실적인 값을 채운다.
                approval_status=(
                    "DRAFT" if is_last_product_of_last_approved else "APPROVED"
                ),
            )
            image_approved = ProductImage(
                product_image_id=uuid.uuid4(),
                product_id=product.product_id,
                storage_key=f"demo/{product.product_id}/main.jpg",
                image_type="MAIN",
                display_order=0,
                alt_text=f"{product.product_name} 대표 이미지",
                approval_status="APPROVED",
            )
            image_pending = ProductImage(
                product_image_id=uuid.uuid4(),
                product_id=product.product_id,
                storage_key=f"demo/{product.product_id}/pending.jpg",
                image_type="DETAIL",
                display_order=1,
                alt_text=f"{product.product_name} 검수 대기 이미지",
                approval_status="PENDING",  # 공개 API가 절대 노출하면 안 되는 값
            )

            dataset.products.append(product)
            dataset.event_products.append(event_product)
            dataset.product_images.append(image_approved)
            dataset.product_images.append(image_pending)

    for booth_status in _BOOTH_STATUS_CYCLE:
        for _ in range(_APPROVED_EXHIBITOR_COUNT // len(_BOOTH_STATUS_CYCLE)):
            _add_exhibitor(approved=True, master_status="APPROVED", booth_status=booth_status)

    for master_status, booth_status in zip(
        _UNAPPROVED_STATUSES, _BOOTH_STATUS_CYCLE, strict=True
    ):
        _add_exhibitor(approved=False, master_status=master_status, booth_status=booth_status)

    assert len(dataset.exhibitors) == 12
    assert len(dataset.approved_exhibitor_ids) == _APPROVED_EXHIBITOR_COUNT
    assert len(dataset.unapproved_exhibitor_ids) == 4
    assert len(dataset.booths) == 12
    assert len(dataset.products) >= 24
    return dataset


async def seed(session) -> DemoDataset:  # session: AsyncSession, typed loosely to avoid a
    # hard sqlalchemy.ext.asyncio import for callers that only want build_demo_dataset().
    dataset = build_demo_dataset()
    async with session.begin():
        session.add_all(dataset.all_objects())
    return dataset


async def main() -> None:
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        raise SystemExit(
            "DATABASE_URL is not set - point it at a migrated (alembic upgrade head) "
            "Postgres database before running this script."
        )
    engine = create_async_engine(database_url)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    try:
        async with session_factory() as session:
            dataset = await seed(session)
        print(
            "Seeded demo dataset: "
            f"event={dataset.event.event_id} "
            f"exhibitors={len(dataset.exhibitors)} "
            f"(approved={len(dataset.approved_exhibitor_ids)}) "
            f"booths={len(dataset.booths)} "
            f"products={len(dataset.products)}"
        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
