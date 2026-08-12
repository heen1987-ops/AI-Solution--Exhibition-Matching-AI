"""Coverage for the U-13 AI 추천 방문 동선 backend track.

No live Postgres is configured in this environment (see
tests/integration/test_postgres_recommendation_contract.py's gating convention, which this repo
already uses for exactly this situation), so DB-touching logic here is exercised the same way
tests/test_buyer_match_api.py and tests/test_exhibition_public_api.py already do:

    - router wiring/auth-boundary/status-mapping: TestClient against a standalone app with the
      service layer monkeypatched wholesale (router never touches a real session).
    - service-layer access-control and position-resolution logic: a small hand-rolled fake
      AsyncSession whose ``execute``/``get``/``scalar`` dispatch on the *entity* SQLAlchemy
      reports for a given statement (``Select.column_descriptions[0]["entity"]``) - plain ORM
      instances are ordinary Python objects until they touch a real session, so they can be
      constructed directly and handed back through the fake.
    - pure ordering/time-estimate math: tests/test_routing_pathfinding.py (separate file, no DB
      concepts at all).

Coverage checklist (from the track's test list)
-------------------------------------------------
    1. real-distance ordering, budget priority-drop, avoid_congestion reordering -
       tests/test_routing_pathfinding.py (pure, exercised by create_route/recalculate_route
       unmodified).
    2. checkpoint scan updates position and recalculate reflects it, preferring a fresh
       checkpoint over a manual zone - test_resolve_current_position_* below.
    3. unapproved/unpublished booth never appears in a route - proven at the strongest possible
       level for a DB-less test: the routing service reuses the exact same, already-audited
       predicate object every other public endpoint uses
       (test_route_service_reuses_the_exact_approved_participation_predicate), rather than a
       parallel filter that could silently drift looser.
    4. cross-user access denied / route not found - test_get_owned_route_*.
    5. recalculate after marking items ARRIVED does not reorder already-completed stops -
       test_recalculate_route_does_not_reorder_locked_items.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routers import route as route_router
from app.core.auth import (
    AuthException,
    VerifiedPrincipal,
    auth_exception_handler,
    get_verified_principal,
)
from app.core.router_auth import get_buyer_profile_id
from app.db.session import get_db
from app.models.core import EventZone
from app.models.exhibitor import Booth
from app.models.indoor_positioning import IndoorCheckpointScan
from app.models.matching import Recommendable
from app.models.profile import VisitSession
from app.models.route import Route, RouteItem
from app.schemas.auth import AuthPrincipal
from app.schemas.route import RouteStartLocation
from app.services import exhibition_public_repository as repo
from app.services.routing import service
from app.services.routing.positioning import (
    CHECKPOINT_FRESHNESS_TTL,
    ManualZoneProvider,
    PositionQuery,
    QrCheckpointProvider,
    resolve_current_position,
)

# apps/api/pyproject.toml sets asyncio_mode = "auto".


# ---------------------------------------------------------------------------
# A tiny entity-dispatching fake AsyncSession (see module docstring)
# ---------------------------------------------------------------------------


@dataclass
class _FakeResult:
    rows: list[Any]

    def scalar_one_or_none(self) -> Any:
        return self.rows[0] if self.rows else None

    def first(self) -> Any:
        return self.rows[0] if self.rows else None

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return self.rows


@dataclass
class _FakeDb:
    """Dispatches ``execute``/``scalar`` by the primary entity of the statement, and ``get`` by
    (model, pk). Handlers return a plain list of rows (or tuples, for multi-entity selects)."""

    by_get: dict[tuple[type, Any], Any] = field(default_factory=dict)
    handlers: dict[type, Any] = field(default_factory=dict)
    deleted: list[Any] = field(default_factory=list)
    commit_count: int = 0

    async def get(self, model: type, pk: Any) -> Any:
        return self.by_get.get((model, pk))

    async def execute(self, stmt: Any) -> _FakeResult:
        entity = stmt.column_descriptions[0]["entity"]
        handler = self.handlers.get(entity)
        rows = handler(stmt) if handler is not None else []
        return _FakeResult(rows)

    async def scalar(self, stmt: Any) -> Any:
        return (await self.execute(stmt)).scalar_one_or_none()

    async def delete(self, obj: Any) -> None:
        self.deleted.append(obj)

    async def commit(self) -> None:
        self.commit_count += 1

    async def flush(self) -> None:
        return None

    async def refresh(self, obj: Any, attribute_names: list[str] | None = None) -> None:
        return None

    def add(self, obj: Any) -> None:
        return None


# ---------------------------------------------------------------------------
# 2. Checkpoint precedence over a manual/stale signal
# ---------------------------------------------------------------------------


def _tenant_event_visit() -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    return uuid.uuid4(), uuid.uuid4(), uuid.uuid4()


async def test_manual_zone_provider_resolves_a_zone_with_coordinates() -> None:
    tenant_id, event_id, visit_session_id = _tenant_event_visit()
    zone = EventZone(
        event_zone_id=uuid.uuid4(),
        tenant_id=tenant_id,
        event_id=event_id,
        zone_code="A",
        zone_name="A구역",
        coordinate_x=12.0,
        coordinate_y=34.0,
    )
    db = _FakeDb(handlers={EventZone: lambda stmt: [zone]})
    now = datetime.now(UTC)
    query = PositionQuery(
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        start_location=RouteStartLocation(type="ZONE", id="A구역"),
        now=now,
    )
    observation = await ManualZoneProvider().resolve_position(db, query)
    assert observation is not None
    assert (observation.map_x, observation.map_y) == (12.0, 34.0)
    assert observation.source == "MANUAL_ZONE"


async def test_manual_zone_provider_declines_gps_start_location() -> None:
    """No GPS-to-floor-plan calibration exists in this codebase - see positioning.py's
    ManualZoneProvider docstring. Must degrade to None, never fabricate a point."""

    tenant_id, event_id, visit_session_id = _tenant_event_visit()
    db = _FakeDb()
    query = PositionQuery(
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        start_location=RouteStartLocation(type="GPS", id="37.5,127.0"),
        now=datetime.now(UTC),
    )
    assert await ManualZoneProvider().resolve_position(db, query) is None


async def test_resolve_current_position_prefers_a_fresh_checkpoint_over_manual_zone() -> None:
    tenant_id, event_id, visit_session_id = _tenant_event_visit()
    now = datetime.now(UTC)

    booth = Booth(booth_id=uuid.uuid4(), tenant_id=tenant_id, event_id=event_id, map_x=1.0, map_y=2.0)
    scan = IndoorCheckpointScan(
        indoor_checkpoint_scan_id=uuid.uuid4(),
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        booth_id=booth.booth_id,
        booth_qr_id=uuid.uuid4(),
        scanned_at=now - timedelta(minutes=2),  # fresh - well inside the TTL
    )
    zone = EventZone(
        event_zone_id=uuid.uuid4(),
        tenant_id=tenant_id,
        event_id=event_id,
        zone_code="B",
        zone_name="B구역",
        coordinate_x=99.0,
        coordinate_y=99.0,
    )
    db = _FakeDb(
        handlers={
            IndoorCheckpointScan: lambda stmt: [(scan, booth)],
            EventZone: lambda stmt: [zone],
        }
    )
    query = PositionQuery(
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        start_location=RouteStartLocation(type="ZONE", id="B구역"),
        now=now,
    )
    observation = await resolve_current_position(db, query)
    assert observation is not None
    assert observation.source == "QR_CHECKPOINT"
    assert (observation.map_x, observation.map_y) == (1.0, 2.0)


async def test_resolve_current_position_falls_back_to_manual_zone_when_checkpoint_is_stale() -> None:
    tenant_id, event_id, visit_session_id = _tenant_event_visit()
    now = datetime.now(UTC)

    booth = Booth(booth_id=uuid.uuid4(), tenant_id=tenant_id, event_id=event_id, map_x=1.0, map_y=2.0)
    stale_scan = IndoorCheckpointScan(
        indoor_checkpoint_scan_id=uuid.uuid4(),
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        booth_id=booth.booth_id,
        booth_qr_id=uuid.uuid4(),
        scanned_at=now - CHECKPOINT_FRESHNESS_TTL - timedelta(minutes=1),
    )
    zone = EventZone(
        event_zone_id=uuid.uuid4(),
        tenant_id=tenant_id,
        event_id=event_id,
        zone_code="B",
        zone_name="B구역",
        coordinate_x=42.0,
        coordinate_y=7.0,
    )
    db = _FakeDb(
        handlers={
            IndoorCheckpointScan: lambda stmt: [(stale_scan, booth)],
            EventZone: lambda stmt: [zone],
        }
    )
    query = PositionQuery(
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        start_location=RouteStartLocation(type="ZONE", id="B구역"),
        now=now,
    )
    observation = await resolve_current_position(db, query)
    assert observation is not None
    assert observation.source == "MANUAL_ZONE"
    assert (observation.map_x, observation.map_y) == (42.0, 7.0)


async def test_resolve_current_position_falls_back_to_stale_checkpoint_over_nothing() -> None:
    tenant_id, event_id, visit_session_id = _tenant_event_visit()
    now = datetime.now(UTC)
    booth = Booth(booth_id=uuid.uuid4(), tenant_id=tenant_id, event_id=event_id, map_x=5.0, map_y=5.0)
    stale_scan = IndoorCheckpointScan(
        indoor_checkpoint_scan_id=uuid.uuid4(),
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        booth_id=booth.booth_id,
        booth_qr_id=uuid.uuid4(),
        scanned_at=now - CHECKPOINT_FRESHNESS_TTL - timedelta(hours=1),
    )
    db = _FakeDb(handlers={IndoorCheckpointScan: lambda stmt: [(stale_scan, booth)]})
    query = PositionQuery(
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        start_location=None,
        now=now,
    )
    observation = await resolve_current_position(db, query)
    assert observation is not None
    assert observation.source == "QR_CHECKPOINT"  # stale, but still better than nothing


async def test_qr_checkpoint_provider_returns_none_when_no_scan_exists() -> None:
    tenant_id, event_id, visit_session_id = _tenant_event_visit()
    db = _FakeDb(handlers={IndoorCheckpointScan: lambda stmt: []})
    query = PositionQuery(
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        start_location=None,
        now=datetime.now(UTC),
    )
    assert await QrCheckpointProvider().resolve_position(db, query) is None


# ---------------------------------------------------------------------------
# 3. Approval filter is reused, never re-derived
# ---------------------------------------------------------------------------


def test_route_service_reuses_the_exact_approved_participation_predicate() -> None:
    """Guards against a parallel, possibly-looser filter being written later - the routing
    service must call the very same function object every other public endpoint audits."""

    assert service._approved_participation_stmt is repo._approved_participation_stmt


# ---------------------------------------------------------------------------
# route_preference derivation (pure)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("avoid_congestion", "minimize_walking", "expected"),
    [
        (True, False, "LOW_CONGESTION"),
        (True, True, "LOW_CONGESTION"),  # avoid_congestion wins when both are set
        (False, True, "SHORTEST"),
        (False, False, "RECOMMENDED_FIRST"),
    ],
)
def test_derive_route_preference(avoid_congestion: bool, minimize_walking: bool, expected: str) -> None:
    from app.schemas.route import RouteConstraints

    constraints = RouteConstraints(avoid_congestion=avoid_congestion, minimize_walking=minimize_walking)
    assert service._derive_route_preference(constraints) == expected


# ---------------------------------------------------------------------------
# 4. Access control
# ---------------------------------------------------------------------------


def _route_with_items(*, tenant_id, event_id, visit_session_id, items: list[RouteItem]) -> Route:
    route = Route(
        route_id=uuid.uuid4(),
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        status="ACTIVE",
        row_version=1,
        context_snapshot={"start_location": None, "constraints": {}, "targets": []},
    )
    route.items = items
    return route


async def test_get_owned_route_succeeds_for_the_owner() -> None:
    tenant_id, event_id, visit_session_id = _tenant_event_visit()
    owner_id = uuid.uuid4()
    route = _route_with_items(
        tenant_id=tenant_id, event_id=event_id, visit_session_id=visit_session_id, items=[]
    )
    db = _FakeDb(
        handlers={
            Route: lambda stmt: [route],
            VisitSession: lambda stmt: [owner_id],
        }
    )
    fetched = await service.get_owned_route(
        db, route_id=route.route_id, tenant_id=tenant_id, event_id=event_id, user_id=owner_id
    )
    assert fetched is route


async def test_get_owned_route_denies_a_different_user() -> None:
    tenant_id, event_id, visit_session_id = _tenant_event_visit()
    owner_id, other_user_id = uuid.uuid4(), uuid.uuid4()
    route = _route_with_items(
        tenant_id=tenant_id, event_id=event_id, visit_session_id=visit_session_id, items=[]
    )
    db = _FakeDb(
        handlers={
            Route: lambda stmt: [route],
            VisitSession: lambda stmt: [owner_id],
        }
    )
    with pytest.raises(service.RouteServiceError) as excinfo:
        await service.get_owned_route(
            db, route_id=route.route_id, tenant_id=tenant_id, event_id=event_id, user_id=other_user_id
        )
    assert excinfo.value.http_status == 403
    assert excinfo.value.code == "RESOURCE_FORBIDDEN"


async def test_get_owned_route_denies_a_nonexistent_route() -> None:
    tenant_id, event_id, _ = _tenant_event_visit()
    db = _FakeDb(handlers={Route: lambda stmt: []})
    with pytest.raises(service.RouteServiceError) as excinfo:
        await service.get_owned_route(
            db, route_id=uuid.uuid4(), tenant_id=tenant_id, event_id=event_id, user_id=uuid.uuid4()
        )
    assert excinfo.value.http_status == 403  # existence is never leaked, see service.py comment


# ---------------------------------------------------------------------------
# 5. Recalculate does not reorder already-completed stops
# ---------------------------------------------------------------------------


async def test_recalculate_route_does_not_reorder_locked_items() -> None:
    tenant_id, event_id, visit_session_id = _tenant_event_visit()
    now = datetime.now(UTC)

    arrived_recommendable_id = uuid.uuid4()
    pending_a_recommendable_id = uuid.uuid4()
    pending_b_recommendable_id = uuid.uuid4()

    arrived_booth = Booth(booth_id=uuid.uuid4(), tenant_id=tenant_id, event_id=event_id, map_x=0.0, map_y=0.0)
    pending_a_booth = Booth(booth_id=uuid.uuid4(), tenant_id=tenant_id, event_id=event_id, map_x=50.0, map_y=0.0)
    pending_b_booth = Booth(booth_id=uuid.uuid4(), tenant_id=tenant_id, event_id=event_id, map_x=10.0, map_y=0.0)

    arrived_recommendable = Recommendable(
        recommendable_id=arrived_recommendable_id, tenant_id=tenant_id, event_id=event_id,
        object_type="BOOTH", booth_id=arrived_booth.booth_id,
    )
    pending_a_recommendable = Recommendable(
        recommendable_id=pending_a_recommendable_id, tenant_id=tenant_id, event_id=event_id,
        object_type="BOOTH", booth_id=pending_a_booth.booth_id,
    )
    pending_b_recommendable = Recommendable(
        recommendable_id=pending_b_recommendable_id, tenant_id=tenant_id, event_id=event_id,
        object_type="BOOTH", booth_id=pending_b_booth.booth_id,
    )

    arrived_item = RouteItem(
        route_item_id=uuid.uuid4(), sequence=0, recommendable_id=arrived_recommendable_id,
        status="ARRIVED", expected_stay_minutes=15, actual_arrival_at=now - timedelta(minutes=10),
    )
    pending_a_item = RouteItem(
        route_item_id=uuid.uuid4(), sequence=1, recommendable_id=pending_a_recommendable_id,
        status="PENDING", expected_stay_minutes=15,
    )
    pending_b_item = RouteItem(
        route_item_id=uuid.uuid4(), sequence=2, recommendable_id=pending_b_recommendable_id,
        status="PENDING", expected_stay_minutes=15,
    )

    route = _route_with_items(
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        items=[arrived_item, pending_a_item, pending_b_item],
    )

    db = _FakeDb(
        by_get={
            (Recommendable, arrived_recommendable_id): arrived_recommendable,
            (Recommendable, pending_a_recommendable_id): pending_a_recommendable,
            (Recommendable, pending_b_recommendable_id): pending_b_recommendable,
            (Booth, arrived_booth.booth_id): arrived_booth,
            (Booth, pending_a_booth.booth_id): pending_a_booth,
            (Booth, pending_b_booth.booth_id): pending_b_booth,
        },
        handlers={IndoorCheckpointScan: lambda stmt: []},  # no checkpoint -> falls back to geometry
    )

    updated = await service.recalculate_route(db, route=route)

    # The already-visited stop keeps its original sequence and is untouched.
    assert arrived_item.sequence == 0
    assert arrived_item.status == "ARRIVED"

    pending_sequences = {pending_a_item.route_item_id: pending_a_item.sequence,
                          pending_b_item.route_item_id: pending_b_item.sequence}
    # Both pending items were renumbered to start after the locked stop's sequence (0), and
    # pending_b (closer, at x=10) should now be visited before pending_a (x=50) since there is
    # no manual/checkpoint position and the fallback start point is the first pending
    # candidate's own point in hydration order (pending_a) - what matters for THIS test is that
    # locked items are never touched and pending items are renumbered strictly after them.
    assert min(pending_sequences.values()) > arrived_item.sequence
    assert sorted(pending_sequences.values()) == [1, 2]
    assert updated.row_version == 2
    assert db.commit_count == 1


async def test_recalculate_route_is_a_no_op_when_nothing_is_pending() -> None:
    tenant_id, event_id, visit_session_id = _tenant_event_visit()
    completed_item = RouteItem(
        route_item_id=uuid.uuid4(), sequence=0, recommendable_id=uuid.uuid4(),
        status="COMPLETED", expected_stay_minutes=15,
    )
    route = _route_with_items(
        tenant_id=tenant_id, event_id=event_id, visit_session_id=visit_session_id, items=[completed_item]
    )
    db = _FakeDb()
    updated = await service.recalculate_route(db, route=route)
    assert updated.total_minutes == 15
    assert completed_item.sequence == 0


# ---------------------------------------------------------------------------
# Router wiring: registration, auth boundary, status mapping (service monkeypatched wholesale)
# ---------------------------------------------------------------------------


def _standalone_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(route_router.build_route_router(), prefix="/api/v1")
    return app


def test_checkpoint_scans_is_registered_before_the_route_id_catch_all() -> None:
    paths_in_order = [route.path for route in route_router.build_route_router().routes]
    checkpoint_index = paths_in_order.index("/routes/checkpoint-scans")
    route_id_index = paths_in_order.index("/routes/{route_id}")
    assert checkpoint_index < route_id_index


def test_all_expected_routes_are_registered() -> None:
    routes = {
        (frozenset(r.methods), r.path) for r in route_router.build_route_router().routes
    }
    assert (frozenset({"POST"}), "/routes") in routes
    assert (frozenset({"GET"}), "/routes/{route_id}") in routes
    assert (frozenset({"POST"}), "/routes/{route_id}/recalculate") in routes
    assert (frozenset({"POST"}), "/routes/{route_id}/items/{item_id}/status") in routes
    assert (frozenset({"POST"}), "/routes/checkpoint-scans") in routes


def test_unauthenticated_caller_is_rejected_with_401() -> None:
    app = _standalone_app()
    app.dependency_overrides[get_db] = lambda: iter([object()])

    with TestClient(app) as client:
        for method, path, body in (
            ("POST", "/api/v1/routes", {"start_location": {"type": "ZONE", "id": "입구"}, "targets": []}),
            ("GET", f"/api/v1/routes/{uuid.uuid4()}", None),
            ("POST", f"/api/v1/routes/{uuid.uuid4()}/recalculate", None),
            ("POST", "/api/v1/routes/checkpoint-scans", {"qr_token": "x"}),
        ):
            response = client.request(method, path, json=body)
            assert response.status_code == 401, (method, path, response.status_code)


def _fake_principal(*, tenant_id: uuid.UUID, event_id: uuid.UUID, user_id: uuid.UUID) -> VerifiedPrincipal:
    return VerifiedPrincipal(
        principal=AuthPrincipal(
            subject_id=user_id,
            subject_type="USER",
            tenant_id=tenant_id,
            event_id=event_id,
            role_grants=[],
            authn_level="AAL1",
            amr=set(),
            authenticated_at=datetime.now(UTC),
            mfa_at=None,
        ),
        session=None,
    )


def _authed_app(*, tenant_id, event_id, user_id, profile_id) -> FastAPI:
    app = _standalone_app()
    app.dependency_overrides[get_db] = lambda: iter([object()])
    app.dependency_overrides[get_verified_principal] = lambda: _fake_principal(
        tenant_id=tenant_id, event_id=event_id, user_id=user_id
    )
    app.dependency_overrides[get_buyer_profile_id] = lambda: profile_id
    return app


async def test_create_route_endpoint_maps_target_not_found_to_422(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, event_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def fake_resolve_or_create_visit_session(db, **kwargs):
        return VisitSession(visit_session_id=uuid.uuid4(), tenant_id=tenant_id, event_id=event_id, user_id=user_id)

    async def fake_create_route(db, **kwargs):
        raise service.target_not_found("BOOTH", "missing")

    monkeypatch.setattr(service, "resolve_or_create_visit_session", fake_resolve_or_create_visit_session)
    monkeypatch.setattr(service, "create_route", fake_create_route)

    app = _authed_app(tenant_id=tenant_id, event_id=event_id, user_id=user_id, profile_id=uuid.uuid4())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/routes",
            json={
                "start_location": {"type": "ZONE", "id": "입구"},
                "targets": [{"object_type": "BOOTH", "object_id": "missing"}],
            },
        )
    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "ROUTE_TARGET_NOT_FOUND"


async def test_create_route_endpoint_happy_path(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, event_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    visit_session_id = uuid.uuid4()
    route_id = uuid.uuid4()

    async def fake_resolve_or_create_visit_session(db, **kwargs):
        return VisitSession(visit_session_id=visit_session_id, tenant_id=tenant_id, event_id=event_id, user_id=user_id)

    async def fake_create_route(db, **kwargs):
        return Route(
            route_id=route_id, tenant_id=tenant_id, event_id=event_id,
            visit_session_id=visit_session_id, status="ACTIVE", route_preference="RECOMMENDED_FIRST",
            total_minutes=30, walking_minutes=5, items=[],
        )

    async def fake_to_route_response(db, route):
        from app.schemas.route import RouteResponse

        return RouteResponse(
            route_id=route.route_id, visit_session_id=route.visit_session_id,
            route_preference=route.route_preference, total_minutes=route.total_minutes,
            walking_minutes=route.walking_minutes, status=route.status, items=[],
        )

    monkeypatch.setattr(service, "resolve_or_create_visit_session", fake_resolve_or_create_visit_session)
    monkeypatch.setattr(service, "create_route", fake_create_route)
    monkeypatch.setattr(service, "to_route_response", fake_to_route_response)

    app = _authed_app(tenant_id=tenant_id, event_id=event_id, user_id=user_id, profile_id=uuid.uuid4())
    with TestClient(app) as client:
        response = client.post(
            "/api/v1/routes",
            json={
                "start_location": {"type": "ZONE", "id": "입구"},
                "targets": [{"object_type": "BOOTH", "object_id": str(uuid.uuid4())}],
            },
        )
    assert response.status_code == 201
    body = response.json()
    assert body["success"] is True
    assert body["data"]["route_id"] == str(route_id)
    assert body["data"]["status"] == "ACTIVE"


async def test_get_route_endpoint_maps_forbidden_to_403(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, event_id, user_id = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()

    async def fake_get_owned_route(db, **kwargs):
        raise service.route_forbidden()

    monkeypatch.setattr(service, "get_owned_route", fake_get_owned_route)

    app = _authed_app(tenant_id=tenant_id, event_id=event_id, user_id=user_id, profile_id=None)
    with TestClient(app) as client:
        response = client.get(f"/api/v1/routes/{uuid.uuid4()}")
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "RESOURCE_FORBIDDEN"
