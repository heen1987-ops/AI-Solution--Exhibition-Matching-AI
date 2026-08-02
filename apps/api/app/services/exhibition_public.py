"""Application service for unauthenticated public event/exhibitor/product/booth reads.

Layering: Router -> Application Service (this module) -> Repository
(``app.services.exhibition_public_repository``) -> SQLAlchemy Model. This module owns:
    - grouping raw joined rows from the repository into per-exhibitor/per-booth structures
    - mapping ORM rows to the public Pydantic response shapes in
      ``app.schemas.exhibition_public`` (the field allow-list enforcement lives there and in
      the repository's approval filters - this module must not reach past the repository for
      any column not already selected)
    - opaque keyset pagination cursors (encode/decode)

None-return convention: every "get one thing" function here returns ``None`` when the event is
not OPEN, or the exhibitor/booth is not found/approved - the router turns that into a 404. This
keeps 404 mapping (an HTTP concern) out of the service layer while still letting the router stay
thin.
"""

from __future__ import annotations

import base64
import binascii
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import EventZone
from app.models.exhibitor import Booth, Exhibitor, Product, ProductImage
from app.schemas.exhibition_public import (
    PublicBoothDetail,
    PublicBoothListResponse,
    PublicBoothSummary,
    PublicEventDay,
    PublicEventDetail,
    PublicExhibitorDetail,
    PublicExhibitorListItem,
    PublicExhibitorListResponse,
    PublicMapResponse,
    PublicProductDetail,
    PublicProductImage,
    PublicProductSummary,
    PublicZone,
)
from app.services import exhibition_public_repository as repo
from app.services.matching.ontology_support import resolve_concept_codes

_CURSOR_SEPARATOR = "\x1f"


class InvalidCursorError(ValueError):
    """Raised when a client-supplied pagination cursor cannot be decoded."""


def encode_cursor(primary: str, secondary: str) -> str:
    """Opaque keyset cursor over an (ordering_key, tiebreaker_id) pair.

    Mirrors the base64-opaque-cursor convention already established by
    ``app.api.v1.routers.recommendations._encode_rank_cursor`` - clients must treat the value
    as opaque, never parse or construct it themselves.
    """

    raw = f"{primary}{_CURSOR_SEPARATOR}{secondary}".encode()
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[str, str]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded.encode("ascii"))
        text = raw.decode("utf-8")
    except (UnicodeDecodeError, binascii.Error, ValueError) as exc:
        raise InvalidCursorError("cursor 형식이 올바르지 않습니다.") from exc
    primary, separator, secondary = text.partition(_CURSOR_SEPARATOR)
    if not separator or not secondary:
        raise InvalidCursorError("cursor 형식이 올바르지 않습니다.")
    return primary, secondary


@dataclass
class _ExhibitorGroup:
    exhibitor: Exhibitor
    participation_id: uuid.UUID
    booths: list[tuple[Booth, EventZone | None]] = field(default_factory=list)


def _group_by_exhibitor(rows) -> dict[uuid.UUID, _ExhibitorGroup]:
    groups: dict[uuid.UUID, _ExhibitorGroup] = {}
    for exhibitor, participation, booth, zone in rows:
        group = groups.get(exhibitor.exhibitor_id)
        if group is None:
            group = _ExhibitorGroup(
                exhibitor=exhibitor, participation_id=participation.participation_id
            )
            groups[exhibitor.exhibitor_id] = group
        group.booths.append((booth, zone))
    return groups


def _primary_booth(group: _ExhibitorGroup) -> tuple[Booth, EventZone | None]:
    return min(group.booths, key=lambda pair: pair[0].booth_number)


def _zone_schema_required(zone: EventZone) -> PublicZone:
    return PublicZone(
        event_zone_id=zone.event_zone_id,
        zone_code=zone.zone_code,
        zone_name=zone.zone_name,
        floor_label=zone.floor_label,
        zone_type=zone.zone_type,
        parent_zone_id=zone.parent_zone_id,
    )


def _zone_schema(zone: EventZone | None) -> PublicZone | None:
    if zone is None:
        return None
    return _zone_schema_required(zone)


def _booth_summary(booth: Booth, zone: EventZone | None) -> PublicBoothSummary:
    return PublicBoothSummary(
        booth_id=booth.booth_id,
        booth_number=booth.booth_number,
        zone=_zone_schema(zone),
        operating_status=booth.operating_status,
        congestion_level=booth.congestion_level,
        estimated_wait_minutes=booth.estimated_wait_minutes,
        map_x=float(booth.map_x) if booth.map_x is not None else None,
        map_y=float(booth.map_y) if booth.map_y is not None else None,
    )


def _booth_detail(
    booth: Booth,
    zone: EventZone | None,
    exhibitor: Exhibitor,
    products: list[PublicProductSummary],
) -> PublicBoothDetail:
    return PublicBoothDetail(
        **_booth_summary(booth, zone).model_dump(),
        exhibitor_id=exhibitor.exhibitor_id,
        company_name=exhibitor.company_name,
        company_summary=exhibitor.company_summary,
        products=products,
    )


def _image_schema(image: ProductImage | None) -> PublicProductImage | None:
    if image is None:
        return None
    return PublicProductImage(
        product_image_id=image.product_image_id,
        storage_key=image.storage_key,
        image_type=image.image_type,
        alt_text=image.alt_text,
        display_order=image.display_order,
    )


def _product_summary(
    product: Product,
    event_product,
    category_codes: dict[uuid.UUID, str],
    images: list[ProductImage],
) -> PublicProductSummary:
    primary = images[0] if images else None
    category_code = (
        category_codes.get(product.category_concept_id)
        if product.category_concept_id is not None
        else None
    )
    return PublicProductSummary(
        product_id=product.product_id,
        product_name=product.product_name,
        product_summary=product.product_summary,
        category_code=category_code,
        alcohol_percentage=(
            float(product.alcohol_percentage)
            if product.alcohol_percentage is not None
            else None
        ),
        retail_price_amount=event_product.retail_price_amount,
        event_price_amount=event_product.event_price_amount,
        currency=event_product.currency,
        tasting_status=event_product.tasting_status,
        purchase_status=event_product.purchase_status,
        primary_image=_image_schema(primary),
    )


async def _load_products_for_participations(
    db: AsyncSession,
    participation_ids: list[uuid.UUID],
    *,
    detail: bool = False,
) -> dict[uuid.UUID, list[PublicProductSummary | PublicProductDetail]]:
    """Batched product load keyed by participation id.

    Exactly three queries total no matter how many participations/products are involved
    (products+event_products, images, ontology concept codes) - see module docstrings in
    ``exhibition_public_repository`` for the N+1 rationale.
    """

    ids = list(dict.fromkeys(participation_ids))
    if not ids:
        return {}
    rows = await repo.fetch_products_by_participation(db, participation_ids=ids)
    grouped: dict[uuid.UUID, list[PublicProductSummary | PublicProductDetail]] = defaultdict(
        list
    )
    if not rows:
        return grouped

    product_ids = [product.product_id for _event_product, product in rows]
    category_ids = [
        product.category_concept_id
        for _event_product, product in rows
        if product.category_concept_id is not None
    ]
    images = await repo.fetch_images_by_product(db, product_ids=product_ids)
    category_codes = await resolve_concept_codes(db, category_ids)

    images_by_product: dict[uuid.UUID, list[ProductImage]] = defaultdict(list)
    for image in images:
        images_by_product[image.product_id].append(image)

    for event_product, product in rows:
        product_images = images_by_product.get(product.product_id, [])
        summary = _product_summary(product, event_product, category_codes, product_images)
        if detail:
            item: PublicProductSummary | PublicProductDetail = PublicProductDetail(
                **summary.model_dump(),
                images=[_image_schema(image) for image in product_images],
            )
        else:
            item = summary
        grouped[event_product.participation_id].append(item)
    return grouped


async def get_event_detail(
    db: AsyncSession, *, event_id: uuid.UUID
) -> PublicEventDetail | None:
    event = await repo.fetch_open_event(db, event_id=event_id)
    if event is None:
        return None
    days = sorted(event.days, key=lambda day: day.event_date)
    return PublicEventDetail(
        event_id=event.event_id,
        event_code=event.event_code,
        event_name=event.event_name,
        venue_name=event.venue_name,
        timezone=event.timezone,
        start_date=event.start_date,
        end_date=event.end_date,
        event_status=event.event_status,
        days=[
            PublicEventDay(
                event_date=day.event_date,
                open_at=day.open_at,
                close_at=day.close_at,
                status=day.status,
            )
            for day in days
        ],
    )


async def list_exhibitors(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    limit: int,
    cursor: str | None,
) -> PublicExhibitorListResponse | None:
    event = await repo.fetch_open_event(db, event_id=event_id)
    if event is None:
        return None

    rows = await repo.fetch_exhibitor_participation_rows(db, event_id=event_id)
    groups = _group_by_exhibitor(rows)
    ordered = sorted(
        groups.values(),
        key=lambda group: (group.exhibitor.company_name, str(group.exhibitor.exhibitor_id)),
    )

    if cursor:
        after = decode_cursor(cursor)
        ordered = [
            group
            for group in ordered
            if (group.exhibitor.company_name, str(group.exhibitor.exhibitor_id)) > after
        ]

    window = ordered[: limit + 1]
    has_more = len(window) > limit
    page = window[:limit]

    products_by_participation = await _load_products_for_participations(
        db, [group.participation_id for group in page]
    )

    items: list[PublicExhibitorListItem] = []
    for group in page:
        booth, zone = _primary_booth(group)
        products = products_by_participation.get(group.participation_id, [])
        items.append(
            PublicExhibitorListItem(
                exhibitor_id=group.exhibitor.exhibitor_id,
                company_name=group.exhibitor.company_name,
                company_summary=group.exhibitor.company_summary,
                data_quality_score=float(group.exhibitor.data_completeness_percent),
                booth=_booth_summary(booth, zone),
                product_count=len(products),
                products=products,
            )
        )

    next_cursor = None
    if has_more and page:
        last = page[-1]
        next_cursor = encode_cursor(
            last.exhibitor.company_name, str(last.exhibitor.exhibitor_id)
        )
    return PublicExhibitorListResponse(items=items, next_cursor=next_cursor, has_more=has_more)


async def get_exhibitor_detail(
    db: AsyncSession, *, exhibitor_id: uuid.UUID, event_id: uuid.UUID | None
) -> PublicExhibitorDetail | None:
    rows = await repo.fetch_exhibitor_detail_rows(
        db, exhibitor_id=exhibitor_id, event_id=event_id
    )
    if not rows:
        return None
    group = next(iter(_group_by_exhibitor(rows).values()))
    booth, zone = _primary_booth(group)
    products_by_participation = await _load_products_for_participations(
        db, [group.participation_id]
    )
    products = products_by_participation.get(group.participation_id, [])
    return PublicExhibitorDetail(
        exhibitor_id=group.exhibitor.exhibitor_id,
        company_name=group.exhibitor.company_name,
        company_summary=group.exhibitor.company_summary,
        data_quality_score=float(group.exhibitor.data_completeness_percent),
        booth=_booth_summary(booth, zone),
        product_count=len(products),
        products=products,
    )


async def get_exhibitor_products(
    db: AsyncSession, *, exhibitor_id: uuid.UUID, event_id: uuid.UUID | None
) -> list[PublicProductDetail] | None:
    rows = await repo.fetch_exhibitor_detail_rows(
        db, exhibitor_id=exhibitor_id, event_id=event_id
    )
    if not rows:
        return None
    group = next(iter(_group_by_exhibitor(rows).values()))
    products_by_participation = await _load_products_for_participations(
        db, [group.participation_id], detail=True
    )
    return list(products_by_participation.get(group.participation_id, []))


async def list_booths(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    limit: int,
    cursor: str | None,
) -> PublicBoothListResponse | None:
    event = await repo.fetch_open_event(db, event_id=event_id)
    if event is None:
        return None

    rows = list(await repo.fetch_booth_rows(db, event_id=event_id))
    ordered = sorted(rows, key=lambda row: (row[2].booth_number, str(row[2].booth_id)))

    if cursor:
        after = decode_cursor(cursor)
        ordered = [
            row for row in ordered if (row[2].booth_number, str(row[2].booth_id)) > after
        ]

    window = ordered[: limit + 1]
    has_more = len(window) > limit
    page = window[:limit]

    participation_ids = [participation.participation_id for _, participation, _, _ in page]
    products_by_participation = await _load_products_for_participations(db, participation_ids)

    items = [
        _booth_detail(
            booth,
            zone,
            exhibitor,
            products_by_participation.get(participation.participation_id, []),
        )
        for exhibitor, participation, booth, zone in page
    ]

    next_cursor = None
    if has_more and page:
        last_booth = page[-1][2]
        next_cursor = encode_cursor(last_booth.booth_number, str(last_booth.booth_id))
    return PublicBoothListResponse(items=items, next_cursor=next_cursor, has_more=has_more)


async def get_booth_detail(
    db: AsyncSession, *, booth_id: uuid.UUID
) -> PublicBoothDetail | None:
    row = await repo.fetch_booth_detail_row(db, booth_id=booth_id)
    if row is None:
        return None
    exhibitor, participation, booth, zone = row
    products_by_participation = await _load_products_for_participations(
        db, [participation.participation_id], detail=True
    )
    products = products_by_participation.get(participation.participation_id, [])
    return _booth_detail(booth, zone, exhibitor, products)


async def get_map(db: AsyncSession, *, event_id: uuid.UUID) -> PublicMapResponse | None:
    event = await repo.fetch_open_event(db, event_id=event_id)
    if event is None:
        return None
    zones = await repo.fetch_zones(db, event_id=event_id)
    rows = await repo.fetch_booth_rows(db, event_id=event_id)
    participation_ids = [participation.participation_id for _, participation, _, _ in rows]
    products_by_participation = await _load_products_for_participations(db, participation_ids)

    booths = [
        _booth_detail(
            booth,
            zone,
            exhibitor,
            products_by_participation.get(participation.participation_id, []),
        )
        for exhibitor, participation, booth, zone in rows
    ]
    return PublicMapResponse(
        event_id=event_id,
        generated_at=datetime.now(UTC),
        zones=[_zone_schema_required(zone) for zone in zones],
        booths=booths,
    )
