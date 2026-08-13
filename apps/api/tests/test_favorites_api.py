"""Tests for BACKEND-009 (favorites API).

No live Postgres is assumed reachable in this environment, so these tests follow the
project's established convention (see test_notification_api.py, test_analytics_notification_
privacy.py's FakeAsyncSession):

  - statement builders (app/services/favorite/service.py) are compiled and their WHERE
    clauses asserted as text (postgresql dialect, matching test_favorite_model.py),
  - the service functions are exercised directly against a self-contained FakeAsyncSession
    that queues db.scalar()/db.execute() results and can simulate a partial-unique race via
    IntegrityError on commit,
  - the router (app/api/v1/routers/favorites.py) is exercised through a real
    fastapi.testclient.TestClient with app.dependency_overrides for get_db and
    app.api.v1.routers.profile.get_current_subject.

Covers every behavior named in this track's task spec:
    1. create (authenticated + anonymous guest)
    2. duplicate create is idempotent, never a raw 500
    3. list only the caller's own active favorites (cross-owner denied)
    4. soft-delete
    5. delete-not-yours is denied (404, not-found semantics)
    6. delete-already-deleted is a clean no-op (404)
    7. invalid object_type / unresolvable object_id are rejected cleanly (422), never 500
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api.v1.routers.favorites import build_favorites_router
from app.api.v1.routers.profile import CurrentSubject, get_current_subject
from app.core.auth import AuthException, auth_exception_handler
from app.db.session import get_db
from app.models.favorite import Favorite
from app.services.favorite.service import (
    InvalidMatchResultError,
    active_favorite_for_target_stmt,
    create_favorite,
    list_favorites,
    list_favorites_stmt,
    own_favorite_stmt,
    resolve_recommendable_id,
    soft_delete_favorite,
)

TENANT = uuid.uuid4()
EVENT = uuid.uuid4()


# ---------------------------------------------------------------------------
# Self-contained fake AsyncSession (see module docstring for rationale/precedent).
# ---------------------------------------------------------------------------


class _Rows:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def __iter__(self):
        return iter(self._rows)


class FakeAsyncSession:
    def __init__(self) -> None:
        self.scalar_queue: list[Any] = []
        self.execute_queue: list[list[Any]] = []
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.refreshed: list[Any] = []
        self.raise_integrity_error_on_next_commit = False

    async def scalar(self, _stmt: Any) -> Any:
        if not self.scalar_queue:
            raise AssertionError(
                "FakeAsyncSession.scalar called with an empty queue - under-provisioned test"
            )
        return self.scalar_queue.pop(0)

    async def execute(self, _stmt: Any) -> _Rows:
        if not self.execute_queue:
            raise AssertionError(
                "FakeAsyncSession.execute called with an empty queue - under-provisioned test"
            )
        return _Rows(self.execute_queue.pop(0))

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        if self.raise_integrity_error_on_next_commit:
            self.raise_integrity_error_on_next_commit = False
            raise IntegrityError("INSERT", {}, Exception("duplicate key value"))
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, obj: Any) -> None:
        self.refreshed.append(obj)
        if getattr(obj, "favorite_id", None) is None:
            obj.favorite_id = uuid.uuid4()
        if getattr(obj, "created_at", None) is None:
            obj.created_at = datetime.now(UTC)


def _favorite(
    *,
    favorite_id: uuid.UUID | None = None,
    user_id: uuid.UUID | None = None,
    guest_session_id: uuid.UUID | None = None,
    recommendable_id: uuid.UUID | None = None,
    source: str = "SEARCH",
    match_result_id: uuid.UUID | None = None,
    created_at: datetime | None = None,
    deleted_at: datetime | None = None,
) -> Favorite:
    return Favorite(
        favorite_id=favorite_id or uuid.uuid4(),
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=user_id,
        guest_session_id=guest_session_id,
        recommendable_id=recommendable_id or uuid.uuid4(),
        source=source,
        match_result_id=match_result_id,
        created_at=created_at or datetime.now(UTC),
        deleted_at=deleted_at,
    )


# ---------------------------------------------------------------------------
# Statement builders: compile and assert the WHERE clauses.
# ---------------------------------------------------------------------------


def _compiled(stmt: Any) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def test_active_favorite_for_target_stmt_scopes_to_user_owner_and_active_rows() -> None:
    user_id = uuid.uuid4()
    recommendable_id = uuid.uuid4()
    sql = _compiled(
        active_favorite_for_target_stmt(
            tenant_id=TENANT,
            event_id=EVENT,
            user_id=user_id,
            guest_session_id=None,
            recommendable_id=recommendable_id,
        )
    )
    stripped = sql.replace("-", "")
    assert "favorite.user_id =" in sql
    assert "favorite.guest_session_id =" not in sql
    assert "favorite.deleted_at IS NULL" in sql
    assert user_id.hex in stripped
    assert recommendable_id.hex in stripped


def test_active_favorite_for_target_stmt_scopes_to_guest_owner() -> None:
    guest_session_id = uuid.uuid4()
    sql = _compiled(
        active_favorite_for_target_stmt(
            tenant_id=TENANT,
            event_id=EVENT,
            user_id=None,
            guest_session_id=guest_session_id,
            recommendable_id=uuid.uuid4(),
        )
    )
    assert "favorite.guest_session_id =" in sql
    assert guest_session_id.hex in sql.replace("-", "")


def test_own_favorite_stmt_requires_both_id_and_owner_match() -> None:
    user_id = uuid.uuid4()
    favorite_id = uuid.uuid4()
    sql = _compiled(
        own_favorite_stmt(
            tenant_id=TENANT,
            event_id=EVENT,
            user_id=user_id,
            guest_session_id=None,
            favorite_id=favorite_id,
        )
    )
    stripped = sql.replace("-", "")
    assert favorite_id.hex in stripped
    assert user_id.hex in stripped
    assert "favorite.favorite_id =" in sql
    assert "favorite.user_id =" in sql


def test_list_favorites_stmt_filters_active_own_rows_and_orders_newest_first() -> None:
    user_id = uuid.uuid4()
    sql = _compiled(
        list_favorites_stmt(
            tenant_id=TENANT,
            event_id=EVENT,
            user_id=user_id,
            guest_session_id=None,
            limit=20,
            before=None,
        )
    )
    assert "favorite.deleted_at IS NULL" in sql
    assert "favorite.user_id =" in sql
    assert "ORDER BY interaction.favorite.created_at DESC" in sql
    assert "LIMIT" in sql


def test_list_favorites_stmt_applies_before_cursor() -> None:
    before = datetime(2026, 8, 13, tzinfo=UTC)
    sql = _compiled(
        list_favorites_stmt(
            tenant_id=TENANT,
            event_id=EVENT,
            user_id=uuid.uuid4(),
            guest_session_id=None,
            limit=20,
            before=before,
        )
    )
    assert "favorite.created_at <" in sql


def test_owner_clause_rejects_neither_user_nor_guest() -> None:
    with pytest.raises(ValueError):
        _compiled(
            active_favorite_for_target_stmt(
                tenant_id=TENANT,
                event_id=EVENT,
                user_id=None,
                guest_session_id=None,
                recommendable_id=uuid.uuid4(),
            )
        )


# ---------------------------------------------------------------------------
# resolve_recommendable_id
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_resolve_recommendable_id_booth_is_a_single_direct_lookup() -> None:
    session = FakeAsyncSession()
    recommendable_id = uuid.uuid4()
    session.scalar_queue = [recommendable_id]

    result = await resolve_recommendable_id(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        object_type="BOOTH",
        object_id=uuid.uuid4(),
    )

    assert result == recommendable_id


@pytest.mark.asyncio
async def test_resolve_recommendable_id_exhibitor_is_a_two_step_lookup() -> None:
    session = FakeAsyncSession()
    participation_id = uuid.uuid4()
    recommendable_id = uuid.uuid4()
    session.scalar_queue = [participation_id, recommendable_id]

    result = await resolve_recommendable_id(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        object_type="EXHIBITOR",
        object_id=uuid.uuid4(),
    )

    assert result == recommendable_id


@pytest.mark.asyncio
async def test_resolve_recommendable_id_exhibitor_short_circuits_when_no_participation() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [None]  # no matching ExhibitorParticipation

    result = await resolve_recommendable_id(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        object_type="EXHIBITOR",
        object_id=uuid.uuid4(),
    )

    assert result is None
    assert session.scalar_queue == []  # the second lookup was never issued


@pytest.mark.asyncio
async def test_resolve_recommendable_id_returns_none_when_target_does_not_exist() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [None]

    result = await resolve_recommendable_id(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        object_type="PROGRAM",
        object_id=uuid.uuid4(),
    )

    assert result is None


# ---------------------------------------------------------------------------
# create_favorite: idempotent create, never a raw 500.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_favorite_inserts_when_none_exists() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [None]  # no existing active favorite
    recommendable_id = uuid.uuid4()
    user_id = uuid.uuid4()

    favorite, created = await create_favorite(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=user_id,
        guest_session_id=None,
        recommendable_id=recommendable_id,
        source="SEARCH",
        match_result_id=None,
    )

    assert created is True
    assert favorite.favorite_id is not None
    assert favorite.created_at is not None
    assert session.commits == 1
    assert session.added == [favorite]


@pytest.mark.asyncio
async def test_create_favorite_pre_check_returns_existing_row_not_a_duplicate_insert() -> None:
    session = FakeAsyncSession()
    existing = _favorite(user_id=uuid.uuid4())
    session.scalar_queue = [existing]  # pre-check finds an active row already

    favorite, created = await create_favorite(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=existing.user_id,
        guest_session_id=None,
        recommendable_id=existing.recommendable_id,
        source="SEARCH",
        match_result_id=None,
    )

    assert created is False
    assert favorite is existing
    assert session.commits == 0
    assert session.added == []  # no duplicate insert attempted


@pytest.mark.asyncio
async def test_create_favorite_race_window_falls_back_to_the_row_that_won_never_a_raw_500() -> (
    None
):
    """Two concurrent requests: our pre-check sees nothing, but the unique index rejects our
    insert because the other request committed first. This must resolve to the winning row,
    not an unhandled IntegrityError."""

    session = FakeAsyncSession()
    winner = _favorite(user_id=uuid.uuid4())
    session.scalar_queue = [None, winner]  # pre-check: none; post-conflict re-query: winner
    session.raise_integrity_error_on_next_commit = True

    favorite, created = await create_favorite(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=winner.user_id,
        guest_session_id=None,
        recommendable_id=winner.recommendable_id,
        source="SEARCH",
        match_result_id=None,
    )

    assert created is False
    assert favorite is winner
    assert session.rollbacks == 1


@pytest.mark.asyncio
async def test_create_favorite_rejects_invalid_match_result_id_cleanly() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [None, None]  # no existing favorite, then match_result lookup misses

    with pytest.raises(InvalidMatchResultError):
        await create_favorite(
            session,
            tenant_id=TENANT,
            event_id=EVENT,
            user_id=uuid.uuid4(),
            guest_session_id=None,
            recommendable_id=uuid.uuid4(),
            source="RECOMMENDATION",
            match_result_id=uuid.uuid4(),
        )
    assert session.commits == 0
    assert session.added == []


@pytest.mark.asyncio
async def test_create_favorite_works_for_an_anonymous_guest_owner() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [None]
    guest_session_id = uuid.uuid4()

    favorite, created = await create_favorite(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=None,
        guest_session_id=guest_session_id,
        recommendable_id=uuid.uuid4(),
        source="SEARCH",
        match_result_id=None,
    )

    assert created is True
    assert favorite.guest_session_id == guest_session_id
    assert favorite.user_id is None


# ---------------------------------------------------------------------------
# list_favorites: own rows only, target resolved back from Recommendable joins.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_favorites_resolves_each_object_type_from_the_joined_row() -> None:
    session = FakeAsyncSession()
    booth_fav = _favorite()
    booth_id = uuid.uuid4()
    product_fav = _favorite()
    product_id = uuid.uuid4()
    exhibitor_fav = _favorite()
    exhibitor_id = uuid.uuid4()
    program_fav = _favorite()
    program_id = uuid.uuid4()
    session.execute_queue = [
        [
            (booth_fav, "BOOTH", booth_id, None, None, None),
            (product_fav, "EVENT_PRODUCT", None, None, product_id, None),
            (exhibitor_fav, "EXHIBITOR", None, None, None, exhibitor_id),
            (program_fav, "PROGRAM", None, program_id, None, None),
        ]
    ]

    items = await list_favorites(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        limit=20,
    )

    by_type = {item.object_type: item.object_id for item in items}
    assert by_type == {
        "BOOTH": booth_id,
        "PRODUCT": product_id,
        "EXHIBITOR": exhibitor_id,
        "PROGRAM": program_id,
    }


# ---------------------------------------------------------------------------
# soft_delete_favorite
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_soft_delete_favorite_sets_deleted_at() -> None:
    session = FakeAsyncSession()
    favorite = _favorite(user_id=uuid.uuid4())
    session.scalar_queue = [favorite]
    now = datetime.now(UTC)

    deleted = await soft_delete_favorite(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=favorite.user_id,
        guest_session_id=None,
        favorite_id=favorite.favorite_id,
        now=now,
    )

    assert deleted is True
    assert favorite.deleted_at == now
    assert session.commits == 1


@pytest.mark.asyncio
async def test_soft_delete_favorite_not_yours_is_denied() -> None:
    """own_favorite_stmt's WHERE clause is the enforcement - a different owner's query never
    matches the row, so the fake session's queue simulates that with None."""

    session = FakeAsyncSession()
    session.scalar_queue = [None]

    deleted = await soft_delete_favorite(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        favorite_id=uuid.uuid4(),
        now=datetime.now(UTC),
    )

    assert deleted is False
    assert session.commits == 0


@pytest.mark.asyncio
async def test_soft_delete_favorite_already_deleted_is_a_clean_no_op() -> None:
    session = FakeAsyncSession()
    favorite = _favorite(user_id=uuid.uuid4(), deleted_at=datetime.now(UTC))
    session.scalar_queue = [favorite]

    deleted = await soft_delete_favorite(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=favorite.user_id,
        guest_session_id=None,
        favorite_id=favorite.favorite_id,
        now=datetime.now(UTC),
    )

    assert deleted is False
    assert session.commits == 0


# ---------------------------------------------------------------------------
# Router-level tests: TestClient + dependency_overrides.
# ---------------------------------------------------------------------------


def _build_app(session: FakeAsyncSession, subject: CurrentSubject) -> FastAPI:
    app = FastAPI()
    app.include_router(build_favorites_router())
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_subject] = lambda: subject
    return app


def _auth_subject(user_id: uuid.UUID | None = None) -> CurrentSubject:
    return CurrentSubject(
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=user_id or uuid.uuid4(),
        guest_session_id=None,
    )


def _guest_subject(guest_session_id: uuid.UUID | None = None) -> CurrentSubject:
    return CurrentSubject(
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=None,
        guest_session_id=guest_session_id or uuid.uuid4(),
    )


def test_router_create_favorite_authenticated_user() -> None:
    session = FakeAsyncSession()
    recommendable_id = uuid.uuid4()
    session.scalar_queue = [recommendable_id, None]  # resolve target, then no existing favorite
    subject = _auth_subject()
    app = _build_app(session, subject)

    with TestClient(app) as client:
        response = client.post(
            "/me/favorites",
            json={"object_type": "BOOTH", "object_id": str(uuid.uuid4())},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["object_type"] == "BOOTH"
    assert body["source"] == "SEARCH"


def test_router_create_favorite_anonymous_guest() -> None:
    session = FakeAsyncSession()
    recommendable_id = uuid.uuid4()
    session.scalar_queue = [recommendable_id, None]
    subject = _guest_subject()
    app = _build_app(session, subject)

    with TestClient(app) as client:
        response = client.post(
            "/me/favorites",
            json={"object_type": "PROGRAM", "object_id": str(uuid.uuid4())},
        )

    assert response.status_code == 201
    assert session.added[0].guest_session_id == subject.guest_session_id
    assert session.added[0].user_id is None


def test_router_create_favorite_is_idempotent_not_500() -> None:
    session = FakeAsyncSession()
    recommendable_id = uuid.uuid4()
    subject = _auth_subject()
    existing = _favorite(user_id=subject.user_id, recommendable_id=recommendable_id)
    session.scalar_queue = [recommendable_id, existing]  # resolve target, then existing found
    app = _build_app(session, subject)

    with TestClient(app) as client:
        response = client.post(
            "/me/favorites",
            json={"object_type": "BOOTH", "object_id": str(uuid.uuid4())},
        )

    assert response.status_code == 201
    assert response.json()["favorite_id"] == str(existing.favorite_id)
    assert session.commits == 0  # no duplicate insert


def test_router_create_favorite_rejects_unresolvable_object_id_with_422() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [None]  # target does not resolve
    app = _build_app(session, _auth_subject())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/me/favorites",
            json={"object_type": "BOOTH", "object_id": str(uuid.uuid4())},
        )

    assert response.status_code == 422
    assert response.json()["detail"] == "FAVORITE_TARGET_NOT_FOUND"


def test_router_create_favorite_rejects_unknown_object_type_at_schema_layer() -> None:
    """object_type is a Literal - FastAPI/Pydantic reject an unknown value with 422 before the
    service layer is ever reached (same stronger-guarantee pattern as
    test_notification_api.py::test_router_patch_preferences_rejects_unknown_notification_type
    _at_schema_layer)."""

    session = FakeAsyncSession()
    app = _build_app(session, _auth_subject())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/me/favorites",
            json={"object_type": "NOT_A_TYPE", "object_id": str(uuid.uuid4())},
        )

    assert response.status_code == 422
    assert session.scalar_queue == []  # never touched the DB


def test_router_list_only_returns_the_callers_own_favorites() -> None:
    session = FakeAsyncSession()
    owner = uuid.uuid4()
    fav = _favorite(user_id=owner)
    booth_id = uuid.uuid4()
    session.execute_queue = [[(fav, "BOOTH", booth_id, None, None, None)]]
    app = _build_app(session, _auth_subject(user_id=owner))

    with TestClient(app) as client:
        response = client.get("/me/favorites")

    assert response.status_code == 200
    body = response.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["favorite_id"] == str(fav.favorite_id)
    assert body["items"][0]["object_id"] == str(booth_id)


def test_router_list_empty_for_a_different_owner() -> None:
    session = FakeAsyncSession()
    session.execute_queue = [[]]
    app = _build_app(session, _auth_subject())

    with TestClient(app) as client:
        response = client.get("/me/favorites")

    assert response.status_code == 200
    assert response.json()["items"] == []


def test_router_delete_soft_deletes_own_favorite() -> None:
    session = FakeAsyncSession()
    subject = _auth_subject()
    favorite = _favorite(user_id=subject.user_id)
    session.scalar_queue = [favorite]
    app = _build_app(session, subject)

    with TestClient(app) as client:
        response = client.delete(f"/me/favorites/{favorite.favorite_id}")

    assert response.status_code == 204
    assert favorite.deleted_at is not None


def test_router_delete_not_yours_is_404() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [None]  # own_favorite_stmt matches nothing for this caller
    app = _build_app(session, _auth_subject())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.delete(f"/me/favorites/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["detail"] == "FAVORITE_NOT_FOUND"


def test_router_delete_already_deleted_is_404() -> None:
    session = FakeAsyncSession()
    subject = _auth_subject()
    favorite = _favorite(user_id=subject.user_id, deleted_at=datetime.now(UTC))
    session.scalar_queue = [favorite]
    app = _build_app(session, subject)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.delete(f"/me/favorites/{favorite.favorite_id}")

    assert response.status_code == 404


def test_router_requires_a_subject_dependency() -> None:
    """No subject override -> the real get_current_subject dependency runs, which itself
    depends on get_verified_subject. Without a session/guest cookie that raises 401 - the
    router takes no identity from client-supplied headers."""

    session = FakeAsyncSession()
    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(build_favorites_router())
    app.dependency_overrides[get_db] = lambda: session

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/me/favorites")

    assert response.status_code == 401


def test_router_is_registered_in_the_shared_api_router() -> None:
    """The integration pass publishes /me/favorites through /api/v1 (same guard pattern as
    test_exhibition_public_api.py::test_router_is_registered_in_the_shared_api_router)."""

    from app.main import app as shared_app

    paths = set(shared_app.openapi()["paths"])
    assert "/api/v1/me/favorites" in paths
    assert "/api/v1/me/favorites/{favorite_id}" in paths
