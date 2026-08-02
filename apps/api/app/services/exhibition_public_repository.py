"""Repository layer for unauthenticated public event/exhibitor/product/booth reads.

Layering: Router -> Application Service (``app.services.exhibition_public``) -> Repository
(this module) -> SQLAlchemy Model. This module only knows how to run SQL and return ORM
rows/objects; it never builds a Pydantic response and never enforces HTTP-level concerns
(404s, pagination cursors as opaque strings, etc.) - that is the service layer's job.

N+1 avoidance
-------------
Every "list" query here fetches its rows with a bounded number of round trips regardless of
how many exhibitors/products/booths match:
    - exhibitor/booth listings use a single joined SELECT (exhibitor+participation+booth+zone
      in one statement) instead of one query per exhibitor.
    - products and product images are fetched in a second/third batch query keyed by
      ``IN (...)`` lists built from the first query's results, not per-row.
    - ontology concept codes are resolved with one batched lookup
      (``app.services.matching.ontology_support.resolve_concept_codes``).
So a page of ``limit`` exhibitors costs a small constant number of queries, not O(limit).

Approval/visibility filters (applied everywhere in this module, never left to callers)
---------------------------------------------------------------------------------------
    - ``Exhibitor.master_approval_status == 'APPROVED'`` and ``Exhibitor.deleted_at IS NULL``
    - ``ExhibitorParticipation.participation_status == 'APPROVED'``
    - ``Event.event_status == 'OPEN'`` (PROJECT_SCOPE "활성 행사만 기본 조회")
    - ``Product.master_approval_status == 'APPROVED'`` and ``Product.deleted_at IS NULL``
    - ``EventProduct.approval_status == 'APPROVED'``
    - ``ProductImage.approval_status == 'APPROVED'``
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import Row, and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.core import Event, EventZone
from app.models.exhibitor import (
    Booth,
    EventProduct,
    Exhibitor,
    ExhibitorParticipation,
    Product,
    ProductImage,
)

# Bounded fan-out cap for a single "browse everything for this event" fetch. The exhibition
# domain is explicitly small-scale (PROJECT_SCOPE.md excludes data-warehouse-scale concerns),
# so grouping/pagination happens in Python after one capped SQL round trip rather than trying
# to keyset-paginate a multi-table join in SQL.
_MAX_PARTICIPATION_ROWS = 2000
_MAX_PRODUCT_ROWS = 5000
_MAX_IMAGE_ROWS = 10000


async def fetch_open_event(db: AsyncSession, *, event_id: uuid.UUID) -> Event | None:
    """returns the event only if it is OPEN (활성 행사만 기본 조회), with its operating days."""

    stmt = (
        select(Event)
        .options(selectinload(Event.days))
        .where(Event.event_id == event_id, Event.event_status == "OPEN")
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def fetch_zones(db: AsyncSession, *, event_id: uuid.UUID) -> list[EventZone]:
    stmt = select(EventZone).where(EventZone.event_id == event_id).order_by(EventZone.zone_code)
    return list((await db.execute(stmt)).scalars().all())


def _approved_participation_stmt(
    *,
    event_id: uuid.UUID | None = None,
    exhibitor_id: uuid.UUID | None = None,
    booth_id: uuid.UUID | None = None,
):
    stmt = (
        select(Exhibitor, ExhibitorParticipation, Booth, EventZone)
        .join(
            ExhibitorParticipation,
            ExhibitorParticipation.exhibitor_id == Exhibitor.exhibitor_id,
        )
        .join(Event, Event.event_id == ExhibitorParticipation.event_id)
        .join(
            Booth,
            and_(
                Booth.participation_id == ExhibitorParticipation.participation_id,
                Booth.event_id == ExhibitorParticipation.event_id,
            ),
        )
        .outerjoin(EventZone, EventZone.event_zone_id == Booth.zone_id)
        .where(
            Exhibitor.master_approval_status == "APPROVED",
            Exhibitor.deleted_at.is_(None),
            ExhibitorParticipation.participation_status == "APPROVED",
            Event.event_status == "OPEN",
        )
    )
    if event_id is not None:
        stmt = stmt.where(ExhibitorParticipation.event_id == event_id)
    if exhibitor_id is not None:
        stmt = stmt.where(Exhibitor.exhibitor_id == exhibitor_id)
    if booth_id is not None:
        stmt = stmt.where(Booth.booth_id == booth_id)
    return stmt


async def fetch_exhibitor_participation_rows(
    db: AsyncSession, *, event_id: uuid.UUID
) -> Sequence[Row]:
    """One joined SELECT for every approved (exhibitor, participation, booth, zone) in an
    OPEN event. Capped, not paginated here — the service layer paginates in Python after
    grouping rows by exhibitor (an exhibitor may have more than one booth row)."""

    stmt = _approved_participation_stmt(event_id=event_id).order_by(
        Exhibitor.company_name, Exhibitor.exhibitor_id, Booth.booth_number
    ).limit(_MAX_PARTICIPATION_ROWS)
    return (await db.execute(stmt)).all()


async def fetch_exhibitor_detail_rows(
    db: AsyncSession, *, exhibitor_id: uuid.UUID, event_id: uuid.UUID | None
) -> Sequence[Row]:
    stmt = _approved_participation_stmt(
        exhibitor_id=exhibitor_id, event_id=event_id
    ).order_by(Booth.booth_number).limit(100)
    return (await db.execute(stmt)).all()


async def fetch_booth_detail_row(db: AsyncSession, *, booth_id: uuid.UUID) -> Row | None:
    stmt = _approved_participation_stmt(booth_id=booth_id).limit(1)
    return (await db.execute(stmt)).first()


async def fetch_booth_rows(db: AsyncSession, *, event_id: uuid.UUID) -> Sequence[Row]:
    stmt = _approved_participation_stmt(event_id=event_id).order_by(
        Booth.booth_number, Booth.booth_id
    ).limit(_MAX_PARTICIPATION_ROWS)
    return (await db.execute(stmt)).all()


async def fetch_products_by_participation(
    db: AsyncSession, *, participation_ids: Sequence[uuid.UUID]
) -> Sequence[Row]:
    """Batched (Product, EventProduct) rows for a set of participations.

    Called once per request with every participation id needed, never once per exhibitor -
    this is the piece that keeps exhibitor-list/booth-list endpoints at O(1) product queries.
    """

    if not participation_ids:
        return []
    stmt = (
        select(EventProduct, Product)
        .join(
            Product,
            and_(
                Product.product_id == EventProduct.product_id,
                Product.master_approval_status == "APPROVED",
                Product.deleted_at.is_(None),
            ),
        )
        .where(
            EventProduct.participation_id.in_(participation_ids),
            EventProduct.approval_status == "APPROVED",
        )
        .order_by(Product.product_name)
        .limit(_MAX_PRODUCT_ROWS)
    )
    return (await db.execute(stmt)).all()


async def fetch_images_by_product(
    db: AsyncSession, *, product_ids: Sequence[uuid.UUID]
) -> Sequence[ProductImage]:
    if not product_ids:
        return []
    stmt = (
        select(ProductImage)
        .where(
            ProductImage.product_id.in_(product_ids),
            ProductImage.approval_status == "APPROVED",
        )
        .order_by(ProductImage.product_id, ProductImage.display_order)
        .limit(_MAX_IMAGE_ROWS)
    )
    return (await db.execute(stmt)).scalars().all()
