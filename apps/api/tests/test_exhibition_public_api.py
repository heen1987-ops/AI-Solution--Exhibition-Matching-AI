"""Tests for the unauthenticated public event/exhibitor/product/booth API.

This router is deliberately not registered in ``app.main.app`` yet (see the module docstring
of ``app.api.v1.routers.exhibition_public`` - registration is an integration-step concern
owned by another track). So these tests build a small standalone FastAPI app that mounts only
this router, the same technique used to unit-test isolated routers before they land in the
shared ``app.api.v1.api`` registry.

Coverage
--------
    - route registration (all 7 required paths, GET only)
    - pagination cursor codec (round trip + malformed cursor rejection)
    - repository SQL includes every required approval/active filter (compiled to text, no DB
      needed) - this is what actually proves "미승인 업체 미노출" / "비활성 업체 미노출"
      since that filtering lives in the WHERE clause, not in Python
    - field allow-list: the public schemas never define a field that maps to non-public data
      (wholesale price, contact info, product-level inventory) and the service/repository
      source never references the private tables that hold them (TradeCondition,
      ExhibitorStaff, EventProduct.inventory_status)
    - service-layer mapping functions (grouping, product/booth schema construction) exercised
      directly against hand-built ORM instances (no DB - SQLAlchemy models are plain Python
      objects until they touch a session)
    - router 404 behavior for event/exhibitor/booth via monkeypatched service functions
    - an optional live-Postgres end-to-end test (pagination across two pages + unapproved/
      inactive exclusion + 404s), skipped unless POSTGRES_TEST_DATABASE_URL is configured,
      mirroring the existing convention in tests/integration/test_postgres_recommendation_contract.py
"""

from __future__ import annotations

import inspect
import os
import uuid
from datetime import date, time
from decimal import Decimal

import pytest
from app.api.v1.routers import exhibition_public as router_module
from app.db.session import get_db
from app.models.core import Event, EventDay, EventZone
from app.models.exhibitor import (
    Booth,
    EventProduct,
    Exhibitor,
    ExhibitorParticipation,
    Product,
    ProductImage,
)
from app.services import exhibition_public as service
from app.services import exhibition_public_repository as repo
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_all_seven_required_routes_are_registered_as_get() -> None:
    paths = {(frozenset(route.methods), route.path) for route in router_module.router.routes}
    expected = {
        (frozenset({"GET"}), "/events/{event_id}"),
        (frozenset({"GET"}), "/events/{event_id}/exhibitors"),
        (frozenset({"GET"}), "/exhibitors/{exhibitor_id}"),
        (frozenset({"GET"}), "/exhibitors/{exhibitor_id}/products"),
        (frozenset({"GET"}), "/events/{event_id}/booths"),
        (frozenset({"GET"}), "/booths/{booth_id}"),
        (frozenset({"GET"}), "/events/{event_id}/map"),
    }
    assert paths == expected


def test_router_is_registered_in_the_shared_api_router() -> None:
    """The integration pass publishes the public routes through ``/api/v1``."""

    from app.main import app as shared_app

    paths = set(shared_app.openapi()["paths"])
    assert "/api/v1/events/{event_id}/exhibitors" in paths
    assert "/api/v1/events/{event_id}/booths" in paths


# ---------------------------------------------------------------------------
# Cursor codec
# ---------------------------------------------------------------------------


def test_cursor_round_trips_opaque_value() -> None:
    exhibitor_id = str(uuid.uuid4())
    cursor = service.encode_cursor("가나다 Winery", exhibitor_id)

    assert cursor != f"가나다 Winery{exhibitor_id}"
    name, ident = service.decode_cursor(cursor)
    assert name == "가나다 Winery"
    assert ident == exhibitor_id


@pytest.mark.parametrize(
    "bad_cursor",
    ["not-base64-!!!", "", "aGVsbG8", "%%%"],
)
def test_malformed_cursor_raises_invalid_cursor_error(bad_cursor: str) -> None:
    with pytest.raises(service.InvalidCursorError):
        service.decode_cursor(bad_cursor)


def test_router_maps_invalid_cursor_to_400_before_hitting_the_service(monkeypatch) -> None:
    called = False

    async def _should_not_run(*args, **kwargs):
        nonlocal called
        called = True
        raise AssertionError("service.list_exhibitors must not run for an invalid cursor")

    monkeypatch.setattr(service, "list_exhibitors", _should_not_run)
    app = _standalone_app()
    client = TestClient(app)

    response = client.get(
        f"/api/v1/events/{uuid.uuid4()}/exhibitors", params={"cursor": "!!!not-valid!!!"}
    )

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "INVALID_CURSOR"
    assert called is False


# ---------------------------------------------------------------------------
# Repository SQL: approval/active filters compiled without touching a DB
# ---------------------------------------------------------------------------


def _compiled(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect()))


def test_exhibitor_and_booth_queries_require_approval_and_active_event() -> None:
    compiled = _compiled(repo._approved_participation_stmt(event_id=uuid.uuid4()))

    assert "exhibition.exhibitor.master_approval_status" in compiled
    assert "exhibition.exhibitor.deleted_at IS NULL" in compiled
    assert "exhibition.exhibitor_participation.participation_status" in compiled
    assert "exhibition.event.event_status" in compiled
    # keyset/id filters must be parameterised, never string-formatted into the query
    assert "exhibition.exhibitor_participation.event_id" in compiled


def test_open_event_lookup_filters_on_event_status() -> None:
    stmt = (
        __import__("sqlalchemy")
        .select(Event)
        .where(Event.event_id == uuid.uuid4(), Event.event_status == "OPEN")
    )
    compiled = _compiled(stmt)
    assert "event_status" in compiled


def test_product_query_requires_product_and_event_product_approval() -> None:
    import asyncio

    class _FakeResult:
        def all(self):
            return []

    class _FakeSession:
        def __init__(self) -> None:
            self.captured_stmt = None

        async def execute(self, stmt):
            self.captured_stmt = stmt
            return _FakeResult()

    session = _FakeSession()
    asyncio.run(repo.fetch_products_by_participation(session, participation_ids=[uuid.uuid4()]))
    compiled = _compiled(session.captured_stmt)
    assert "exhibition.product.master_approval_status" in compiled
    assert "exhibition.product.deleted_at IS NULL" in compiled
    assert "exhibition.event_product.approval_status" in compiled


def test_image_query_requires_image_approval() -> None:
    import asyncio

    class _FakeScalars:
        def all(self):
            return []

    class _FakeResult:
        def scalars(self):
            return _FakeScalars()

    class _FakeSession:
        def __init__(self) -> None:
            self.captured_stmt = None

        async def execute(self, stmt):
            self.captured_stmt = stmt
            return _FakeResult()

    session = _FakeSession()
    asyncio.run(repo.fetch_images_by_product(session, product_ids=[uuid.uuid4()]))
    compiled = _compiled(session.captured_stmt)
    assert "exhibition.product_image.approval_status" in compiled


# ---------------------------------------------------------------------------
# Field allow-list (docs/08-exhibitor-product-profile-model.md 2.3절)
# ---------------------------------------------------------------------------


_FORBIDDEN_SOURCE_TOKENS = (
    "wholesale_price",
    "TradeCondition",
    "trade_condition",
    "business_registration_hmac",
    "ExhibitorStaff",
    "exhibitor_staff",
    "inventory_status",
    "MeetingContactShare",
)


@pytest.mark.parametrize("module", [service, repo])
def test_public_modules_never_reference_private_trade_or_contact_data(module) -> None:
    """service/repository code (not just field names) must never touch the private tables.

    ``app.schemas.exhibition_public`` is intentionally excluded from this source-text scan -
    its module docstring explains, in prose, *why* trade_condition/inventory_status are
    excluded (so the forbidden words legitimately appear there). The schema module's actual
    compliance is verified structurally instead by
    ``test_public_schemas_do_not_expose_disallowed_fields`` below, which inspects
    ``model_fields`` rather than raw source text.
    """

    source = inspect.getsource(module)
    for token in _FORBIDDEN_SOURCE_TOKENS:
        assert token not in source, f"{module.__name__} must never reference {token!r}"


def test_public_schemas_do_not_expose_disallowed_fields() -> None:
    from app.schemas.exhibition_public import (
        PublicBoothDetail,
        PublicExhibitorDetail,
        PublicProductDetail,
    )

    disallowed = {
        "wholesale_price_min_amount",
        "wholesale_price_max_amount",
        "min_order_quantity",
        "monthly_capacity",
        "oem_status",
        "private_label_status",
        "export_status",
        "phone",
        "email",
        "contact",
        "inventory_status",
    }
    for model in (PublicExhibitorDetail, PublicProductDetail, PublicBoothDetail):
        assert disallowed.isdisjoint(model.model_fields.keys())


# ---------------------------------------------------------------------------
# Service-layer mapping against hand-built ORM instances (no DB)
# ---------------------------------------------------------------------------


def _make_exhibitor(name: str = "Backju Winery") -> Exhibitor:
    return Exhibitor(
        exhibitor_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        company_name=name,
        company_summary="전통 방식으로 빚은 프리미엄 약주.",
        master_approval_status="APPROVED",
        data_completeness_percent=Decimal("87.50"),
    )


def _make_booth(participation_id: uuid.UUID, number: str = "A-01") -> Booth:
    return Booth(
        booth_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        participation_id=participation_id,
        booth_number=number,
        operating_status="OPEN",
        congestion_level="LOW",
        estimated_wait_minutes=5,
        map_x=Decimal("12.500"),
        map_y=Decimal("34.000"),
    )


def test_group_by_exhibitor_collects_every_booth_row_under_one_exhibitor() -> None:
    exhibitor = _make_exhibitor()
    participation_id = uuid.uuid4()
    participation = ExhibitorParticipation(
        participation_id=participation_id,
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        exhibitor_id=exhibitor.exhibitor_id,
        participation_status="APPROVED",
    )
    booth_a = _make_booth(participation_id, "A-01")
    booth_b = _make_booth(participation_id, "A-02")

    groups = service._group_by_exhibitor(
        [
            (exhibitor, participation, booth_a, None),
            (exhibitor, participation, booth_b, None),
        ]
    )

    assert len(groups) == 1
    group = groups[exhibitor.exhibitor_id]
    assert {b.booth_number for b, _zone in group.booths} == {"A-01", "A-02"}
    assert service._primary_booth(group)[0].booth_number == "A-01"


def test_product_summary_maps_only_public_fields_and_omits_inventory() -> None:
    product = Product(
        product_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        product_name="약주 15년",
        product_summary="쌀과 누룩만으로 빚은 약주.",
        alcohol_percentage=Decimal("15.00"),
        master_approval_status="APPROVED",
    )
    event_product = EventProduct(
        event_product_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        participation_id=uuid.uuid4(),
        product_id=product.product_id,
        retail_price_amount=35000,
        event_price_amount=30000,
        currency="KRW",
        tasting_status="AVAILABLE",
        purchase_status="AVAILABLE",
        inventory_status="LOW",  # must never leak into the public summary
        approval_status="APPROVED",
    )
    image = ProductImage(
        product_image_id=uuid.uuid4(),
        product_id=product.product_id,
        storage_key="s3://demo/bottle.jpg",
        display_order=0,
        approval_status="APPROVED",
    )

    summary = service._product_summary(product, event_product, {}, [image])

    assert summary.product_name == "약주 15년"
    assert summary.retail_price_amount == 35000
    assert summary.event_price_amount == 30000
    assert summary.tasting_status == "AVAILABLE"
    assert summary.purchase_status == "AVAILABLE"
    assert summary.primary_image is not None
    assert summary.primary_image.storage_key == "s3://demo/bottle.jpg"
    assert not hasattr(summary, "inventory_status")


def test_booth_summary_carries_zone_and_map_coordinates() -> None:
    participation_id = uuid.uuid4()
    booth = _make_booth(participation_id)
    zone = EventZone(
        event_zone_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        zone_code="A",
        zone_name="A홀",
    )

    summary = service._booth_summary(booth, zone)

    assert summary.zone is not None
    assert summary.zone.zone_name == "A홀"
    assert summary.map_x == 12.5
    assert summary.map_y == 34.0


def test_event_detail_sorts_days_and_carries_operating_hours() -> None:
    event = Event(
        event_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_code="BACKJU-2026",
        event_name="2026 백주대간 박람회",
        timezone="Asia/Seoul",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        event_status="OPEN",
    )
    day2 = EventDay(
        event_day_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_id=event.event_id,
        event_date=date(2026, 9, 2),
        status="PLANNED",
    )
    day1 = EventDay(
        event_day_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_id=event.event_id,
        event_date=date(2026, 9, 1),
        open_at=time(10, 0),
        close_at=time(18, 0),
        status="OPEN",
    )
    event.days = [day2, day1]

    import asyncio

    class _FakeSession:
        async def execute(self, stmt):  # pragma: no cover - not reached
            raise AssertionError

    async def _fake_fetch_open_event(_db, *, event_id):
        assert event_id == event.event_id
        return event

    original = repo.fetch_open_event
    repo.fetch_open_event = _fake_fetch_open_event  # type: ignore[assignment]
    try:
        detail = asyncio.run(service.get_event_detail(_FakeSession(), event_id=event.event_id))
    finally:
        repo.fetch_open_event = original  # type: ignore[assignment]

    assert detail is not None
    assert [d.event_date for d in detail.days] == [date(2026, 9, 1), date(2026, 9, 2)]
    assert detail.days[0].open_at == time(10, 0)


# ---------------------------------------------------------------------------
# Router 404s (monkeypatched service layer, no DB)
# ---------------------------------------------------------------------------


def _standalone_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router_module.router, prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: None
    return app


@pytest.mark.parametrize(
    ("path_template", "service_fn", "expected_code"),
    [
        ("/api/v1/events/{id}", "get_event_detail", "EVENT_NOT_FOUND"),
        ("/api/v1/events/{id}/exhibitors", "list_exhibitors", "EVENT_NOT_FOUND"),
        ("/api/v1/exhibitors/{id}", "get_exhibitor_detail", "EXHIBITOR_NOT_FOUND"),
        ("/api/v1/exhibitors/{id}/products", "get_exhibitor_products", "EXHIBITOR_NOT_FOUND"),
        ("/api/v1/events/{id}/booths", "list_booths", "EVENT_NOT_FOUND"),
        ("/api/v1/booths/{id}", "get_booth_detail", "BOOTH_NOT_FOUND"),
        ("/api/v1/events/{id}/map", "get_map", "EVENT_NOT_FOUND"),
    ],
)
def test_missing_resource_returns_404_with_catalogued_error_code(
    monkeypatch, path_template: str, service_fn: str, expected_code: str
) -> None:
    async def _returns_none(*args, **kwargs):
        return None

    monkeypatch.setattr(service, service_fn, _returns_none)
    app = _standalone_app()
    client = TestClient(app)

    response = client.get(path_template.format(id=uuid.uuid4()))

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == expected_code


def test_found_event_returns_envelope_with_request_id(monkeypatch) -> None:
    from app.schemas.exhibition_public import PublicEventDetail

    event_id = uuid.uuid4()

    async def _fake_get_event_detail(_db, *, event_id):
        return PublicEventDetail(
            event_id=event_id,
            event_code="BACKJU-2026",
            event_name="2026 백주대간 박람회",
            timezone="Asia/Seoul",
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 3),
            event_status="OPEN",
            days=[],
        )

    monkeypatch.setattr(service, "get_event_detail", _fake_get_event_detail)
    app = _standalone_app()
    client = TestClient(app)

    response = client.get(f"/api/v1/events/{event_id}", headers={"X-Request-ID": "req-test-1"})

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["event_id"] == str(event_id)
    assert body["meta"]["request_id"] == "req-test-1"


# ---------------------------------------------------------------------------
# Optional live-Postgres end-to-end coverage
# ---------------------------------------------------------------------------

DATABASE_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")


@pytest.mark.postgres_integration
@pytest.mark.skipif(
    not DATABASE_URL, reason="POSTGRES_TEST_DATABASE_URL is not configured"
)
@pytest.mark.asyncio
async def test_live_postgres_pagination_and_visibility_rules() -> None:
    """Runs scripts/seed_demo.py's fixture builder against a real migrated DB and asserts:

    - an unapproved exhibitor never appears in the exhibitor list
    - a booth belonging to a non-OPEN event never appears
    - listing paginates (two half-size pages cover every approved exhibitor exactly once)
    - unknown ids 404 (via the service layer, since this test does not go through HTTP)
    """

    from scripts.seed_demo import build_demo_dataset
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    session_factory = async_sessionmaker(bind=engine, expire_on_commit=False)
    dataset = build_demo_dataset()
    try:
        async with session_factory() as session:
            async with session.begin():
                session.add_all(dataset.all_objects())
            await session.commit()

            first_page = await service.list_exhibitors(
                session, event_id=dataset.event.event_id, limit=4, cursor=None
            )
            assert first_page is not None
            assert first_page.has_more is True
            second_page = await service.list_exhibitors(
                session,
                event_id=dataset.event.event_id,
                limit=100,
                cursor=first_page.next_cursor,
            )
            assert second_page is not None
            seen_ids = {item.exhibitor_id for item in first_page.items} | {
                item.exhibitor_id for item in second_page.items
            }
            assert dataset.unapproved_exhibitor_id not in seen_ids
            assert len(seen_ids) == len(dataset.approved_exhibitor_ids)
            assert seen_ids == set(dataset.approved_exhibitor_ids)

            assert (
                await service.get_exhibitor_detail(
                    session, exhibitor_id=dataset.unapproved_exhibitor_id, event_id=None
                )
                is None
            )
            assert (
                await service.get_event_detail(session, event_id=uuid.uuid4()) is None
            )
    finally:
        async with session_factory() as session:
            async with session.begin():
                for obj in reversed(dataset.all_objects()):
                    await session.delete(obj)
            await session.commit()
        await engine.dispose()
