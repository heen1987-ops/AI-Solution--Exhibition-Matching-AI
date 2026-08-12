"""Tests for BACKEND-016 (QR check-in API).

No live Postgres is assumed reachable in this environment, so these tests follow the project's
established convention (see test_favorites_api.py, test_object_embeddings.py's fake session):

  - the service layer (app/services/checkin/service.py) is exercised directly against a
    self-contained FakeAsyncSession that queues db.scalar()/db.get() results, records
    db.execute() calls (for the advisory lock), and can simulate a race via IntegrityError on
    commit,
  - the router (app/api/v1/routers/checkin.py) is exercised through a real
    fastapi.testclient.TestClient with app.dependency_overrides for get_db and
    app.api.v1.routers.profile.get_current_subject.

Covers every behavior named in this track's task spec:
    1. successful check-in (new row, 201, duplicate=False)
    2. duplicate-within-window returns the existing record with duplicate=True (never an error)
    3. expired / revoked / wrong-event QR token all reject as INVALID_QR
    4. CLOSED booth is rejected (BOOTH_CLOSED), PAUSED is not
    5. Idempotency-Key replay returns the same result without double-inserting
    6. cross-tenant/cross-event isolation (a booth from another tenant/event is INVALID_QR)
    7. both an authenticated user and an anonymous guest can check in
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api.v1.routers.checkin import build_checkin_router
from app.api.v1.routers.profile import CurrentSubject, get_current_subject
from app.core.auth import AuthException, auth_exception_handler, digest_secret
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.checkin import CheckIn
from app.models.exhibitor import Booth, BoothQr
from app.models.integration import IdempotencyRecord
from app.services.checkin.service import (
    QR_TOKEN_PURPOSE,
    BoothClosedError,
    InvalidQrError,
    VisitSessionNotFoundError,
    submit_check_in,
)

TENANT = uuid.uuid4()
EVENT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()
OTHER_EVENT = uuid.uuid4()


def _settings() -> Settings:
    return Settings(
        SECRET_KEY="checkin-unit-test-secret",
        AUTH_TOKEN_PEPPER="checkin-unit-test-pepper",
        AUTH_ENCRYPTION_KEY_B64=base64.urlsafe_b64encode(b"k" * 32).decode(),
    )


SETTINGS = _settings()
NOW = datetime(2026, 10, 9, 5, 31, 12, tzinfo=UTC)


def _booth(
    *,
    booth_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID = TENANT,
    event_id: uuid.UUID = EVENT,
    operating_status: str = "OPEN",
) -> Booth:
    return Booth(
        booth_id=booth_id or uuid.uuid4(),
        tenant_id=tenant_id,
        event_id=event_id,
        participation_id=uuid.uuid4(),
        booth_number="A-01",
        operating_status=operating_status,
    )


def _booth_qr(
    *,
    booth_id: uuid.UUID,
    raw_token: str = "raw-qr-token",
    status: str = "ACTIVE",
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
    key_version: int = 1,
) -> BoothQr:
    return BoothQr(
        booth_qr_id=uuid.uuid4(),
        booth_id=booth_id,
        token_hmac=digest_secret(raw_token, purpose=QR_TOKEN_PURPOSE, settings=SETTINGS),
        status=status,
        valid_from=valid_from,
        valid_until=valid_until,
        key_version=key_version,
    )


def _check_in(
    *,
    check_in_id: uuid.UUID | None = None,
    visit_session_id: uuid.UUID | None = None,
    booth_id: uuid.UUID | None = None,
    activities: list[str] | None = None,
    checked_in_at: datetime | None = None,
) -> CheckIn:
    return CheckIn(
        check_in_id=check_in_id or uuid.uuid4(),
        tenant_id=TENANT,
        event_id=EVENT,
        visit_session_id=visit_session_id or uuid.uuid4(),
        booth_id=booth_id or uuid.uuid4(),
        check_in_method="QR",
        activities=activities or ["TASTING"],
        checked_in_at=checked_in_at or NOW,
        received_at=NOW,
    )


# ---------------------------------------------------------------------------
# Self-contained fake AsyncSession (see module docstring for rationale/precedent).
# ---------------------------------------------------------------------------


class FakeAsyncSession:
    def __init__(self) -> None:
        self.scalar_queue: list[Any] = []
        self.get_queue: list[Any] = []
        self.executed: list[Any] = []
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self.refreshed: list[Any] = []
        self.raise_integrity_error_on_next_commit = False

    async def scalar(self, _stmt: Any) -> Any:
        if not self.scalar_queue:
            raise AssertionError(
                "FakeAsyncSession.scalar called with an empty queue - under-provisioned test"
            )
        return self.scalar_queue.pop(0)

    async def get(self, _model: Any, _pk: Any) -> Any:
        if not self.get_queue:
            raise AssertionError(
                "FakeAsyncSession.get called with an empty queue - under-provisioned test"
            )
        return self.get_queue.pop(0)

    async def execute(self, stmt: Any) -> Any:
        self.executed.append(stmt)
        return []

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, CheckIn) and obj.check_in_id is None:
            obj.check_in_id = uuid.uuid4()

    async def flush(self) -> None:
        self.flushes += 1
        for obj in self.added:
            if isinstance(obj, CheckIn) and obj.check_in_id is None:
                obj.check_in_id = uuid.uuid4()

    async def commit(self) -> None:
        if self.raise_integrity_error_on_next_commit:
            self.raise_integrity_error_on_next_commit = False
            raise IntegrityError("INSERT", {}, Exception("duplicate key value"))
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, obj: Any) -> None:
        self.refreshed.append(obj)


# ---------------------------------------------------------------------------
# submit_check_in: the full service-layer orchestration.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_check_in_creates_a_new_row_when_none_exists() -> None:
    session = FakeAsyncSession()
    booth = _booth()
    booth_qr = _booth_qr(booth_id=booth.booth_id)
    visit_session_id = uuid.uuid4()
    session.scalar_queue = [visit_session_id, booth_qr, None]  # visit, qr, no recent dup
    session.get_queue = [booth]

    check_in, duplicate = await submit_check_in(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        qr_token="raw-qr-token",
        activities=["TASTING", "PURCHASE"],
        match_result_id=None,
        client_event_id=uuid.uuid4(),
        occurred_at=NOW,
        idempotency_key=None,
        settings=SETTINGS,
        now=NOW,
    )

    assert duplicate is False
    assert check_in.booth_id == booth.booth_id
    assert check_in.visit_session_id == visit_session_id
    assert check_in.activities == ["TASTING", "PURCHASE"]
    assert check_in.qr_id == booth_qr.booth_qr_id
    assert check_in.qr_key_version == booth_qr.key_version
    assert session.commits == 1
    assert any(pending is check_in for pending in session.added)
    # The advisory lock was taken before the dedupe query.
    assert any("pg_advisory_xact_lock" in str(stmt) for stmt in session.executed)


@pytest.mark.asyncio
async def test_submit_check_in_duplicate_within_window_returns_existing_row_not_an_error() -> (
    None
):
    session = FakeAsyncSession()
    booth = _booth()
    booth_qr = _booth_qr(booth_id=booth.booth_id)
    visit_session_id = uuid.uuid4()
    existing = _check_in(
        visit_session_id=visit_session_id,
        booth_id=booth.booth_id,
        checked_in_at=NOW - timedelta(minutes=2),
    )
    session.scalar_queue = [visit_session_id, booth_qr, existing]
    session.get_queue = [booth]

    check_in, duplicate = await submit_check_in(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        qr_token="raw-qr-token",
        activities=["PURCHASE"],  # different from existing - must not be merged in
        match_result_id=None,
        client_event_id=None,
        occurred_at=NOW,
        idempotency_key=None,
        settings=SETTINGS,
        now=NOW,
    )

    assert duplicate is True
    assert check_in is existing
    assert check_in.activities == ["TASTING"]  # the existing row's own activities, unchanged
    assert session.added == []  # no new CheckIn inserted
    assert session.commits == 0  # no idempotency key -> nothing to persist


@pytest.mark.asyncio
async def test_submit_check_in_rejects_unknown_qr_token() -> None:
    session = FakeAsyncSession()
    visit_session_id = uuid.uuid4()
    session.scalar_queue = [visit_session_id, None]  # visit found, qr lookup misses

    with pytest.raises(InvalidQrError):
        await submit_check_in(
            session,
            tenant_id=TENANT,
            event_id=EVENT,
            user_id=uuid.uuid4(),
            guest_session_id=None,
            qr_token="not-a-real-token",
            activities=["TASTING"],
            match_result_id=None,
            client_event_id=None,
            occurred_at=NOW,
            idempotency_key=None,
            settings=SETTINGS,
            now=NOW,
        )
    assert session.added == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_submit_check_in_rejects_expired_qr_token() -> None:
    session = FakeAsyncSession()
    booth = _booth()
    booth_qr = _booth_qr(
        booth_id=booth.booth_id,
        valid_from=NOW - timedelta(hours=2),
        valid_until=NOW - timedelta(hours=1),  # expired before `now`
    )
    session.scalar_queue = [uuid.uuid4(), booth_qr]

    with pytest.raises(InvalidQrError):
        await submit_check_in(
            session,
            tenant_id=TENANT,
            event_id=EVENT,
            user_id=uuid.uuid4(),
            guest_session_id=None,
            qr_token="raw-qr-token",
            activities=["TASTING"],
            match_result_id=None,
            client_event_id=None,
            occurred_at=NOW,
            idempotency_key=None,
            settings=SETTINGS,
            now=NOW,
        )


@pytest.mark.asyncio
async def test_submit_check_in_rejects_revoked_qr_token() -> None:
    session = FakeAsyncSession()
    booth = _booth()
    booth_qr = _booth_qr(booth_id=booth.booth_id, status="REVOKED")
    session.scalar_queue = [uuid.uuid4(), booth_qr]

    with pytest.raises(InvalidQrError):
        await submit_check_in(
            session,
            tenant_id=TENANT,
            event_id=EVENT,
            user_id=uuid.uuid4(),
            guest_session_id=None,
            qr_token="raw-qr-token",
            activities=["TASTING"],
            match_result_id=None,
            client_event_id=None,
            occurred_at=NOW,
            idempotency_key=None,
            settings=SETTINGS,
            now=NOW,
        )


@pytest.mark.asyncio
async def test_submit_check_in_rejects_qr_from_a_different_tenant_or_event() -> None:
    """Cross-tenant/cross-event isolation: a valid, active QR whose booth belongs to a
    different tenant/event than the caller's own subject must be rejected exactly like an
    unknown token - never disclosing that the booth exists elsewhere."""

    session = FakeAsyncSession()
    foreign_booth = _booth(tenant_id=OTHER_TENANT, event_id=OTHER_EVENT)
    booth_qr = _booth_qr(booth_id=foreign_booth.booth_id)
    session.scalar_queue = [uuid.uuid4(), booth_qr]
    session.get_queue = [foreign_booth]

    with pytest.raises(InvalidQrError):
        await submit_check_in(
            session,
            tenant_id=TENANT,
            event_id=EVENT,
            user_id=uuid.uuid4(),
            guest_session_id=None,
            qr_token="raw-qr-token",
            activities=["TASTING"],
            match_result_id=None,
            client_event_id=None,
            occurred_at=NOW,
            idempotency_key=None,
            settings=SETTINGS,
            now=NOW,
        )


@pytest.mark.asyncio
async def test_submit_check_in_rejects_a_closed_booth() -> None:
    session = FakeAsyncSession()
    booth = _booth(operating_status="CLOSED")
    booth_qr = _booth_qr(booth_id=booth.booth_id)
    session.scalar_queue = [uuid.uuid4(), booth_qr]
    session.get_queue = [booth]

    with pytest.raises(BoothClosedError):
        await submit_check_in(
            session,
            tenant_id=TENANT,
            event_id=EVENT,
            user_id=uuid.uuid4(),
            guest_session_id=None,
            qr_token="raw-qr-token",
            activities=["TASTING"],
            match_result_id=None,
            client_event_id=None,
            occurred_at=NOW,
            idempotency_key=None,
            settings=SETTINGS,
            now=NOW,
        )
    # Never took the advisory lock or touched the CheckIn table for a rejected booth.
    assert session.executed == []
    assert session.added == []


@pytest.mark.asyncio
async def test_submit_check_in_allows_a_paused_booth() -> None:
    """Only CLOSED rejects - PAUSED (busy but still operating) does not."""

    session = FakeAsyncSession()
    booth = _booth(operating_status="PAUSED")
    booth_qr = _booth_qr(booth_id=booth.booth_id)
    session.scalar_queue = [uuid.uuid4(), booth_qr, None]
    session.get_queue = [booth]

    check_in, duplicate = await submit_check_in(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        qr_token="raw-qr-token",
        activities=["TASTING"],
        match_result_id=None,
        client_event_id=None,
        occurred_at=NOW,
        idempotency_key=None,
        settings=SETTINGS,
        now=NOW,
    )
    assert duplicate is False
    assert check_in.booth_id == booth.booth_id


@pytest.mark.asyncio
async def test_submit_check_in_raises_when_no_active_visit_session() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [None]  # resolve_active_visit_session_id finds nothing

    with pytest.raises(VisitSessionNotFoundError):
        await submit_check_in(
            session,
            tenant_id=TENANT,
            event_id=EVENT,
            user_id=uuid.uuid4(),
            guest_session_id=None,
            qr_token="raw-qr-token",
            activities=["TASTING"],
            match_result_id=None,
            client_event_id=None,
            occurred_at=NOW,
            idempotency_key=None,
            settings=SETTINGS,
            now=NOW,
        )


@pytest.mark.asyncio
async def test_submit_check_in_works_for_an_anonymous_guest_owner() -> None:
    session = FakeAsyncSession()
    booth = _booth()
    booth_qr = _booth_qr(booth_id=booth.booth_id)
    session.scalar_queue = [uuid.uuid4(), booth_qr, None]
    session.get_queue = [booth]

    check_in, duplicate = await submit_check_in(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=None,
        guest_session_id=uuid.uuid4(),
        qr_token="raw-qr-token",
        activities=["INFO_CHECK"],
        match_result_id=None,
        client_event_id=None,
        occurred_at=NOW,
        idempotency_key=None,
        settings=SETTINGS,
        now=NOW,
    )
    assert duplicate is False
    assert check_in.activities == ["INFO_CHECK"]


# ---------------------------------------------------------------------------
# Idempotency-Key replay.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_check_in_idempotency_key_replay_returns_prior_result_without_reinserting() -> (
    None
):
    session = FakeAsyncSession()
    prior = _check_in()
    record = IdempotencyRecord(
        tenant_id=TENANT,
        principal_fingerprint=b"irrelevant-in-this-fake",
        method="POST",
        route="/check-ins",
        idempotency_key="replayed-key",
        response_status=201,
        response_reference=prior.check_in_id,
    )
    session.scalar_queue = [record]  # idempotency lookup hits immediately
    session.get_queue = [prior]  # replay resolves the CheckIn by response_reference

    check_in, duplicate = await submit_check_in(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        qr_token="raw-qr-token",
        activities=["TASTING"],
        match_result_id=None,
        client_event_id=None,
        occurred_at=NOW,
        idempotency_key="replayed-key",
        settings=SETTINGS,
        now=NOW,
    )

    assert check_in is prior
    assert duplicate is False  # response_status=201 on the original -> not a duplicate
    # Replay short-circuits before ever touching visit-session/QR/booth resolution or the DB.
    assert session.added == []
    assert session.commits == 0
    assert session.executed == []


@pytest.mark.asyncio
async def test_submit_check_in_idempotency_key_replay_reconstructs_duplicate_flag() -> None:
    session = FakeAsyncSession()
    prior = _check_in()
    record = IdempotencyRecord(
        tenant_id=TENANT,
        principal_fingerprint=b"irrelevant-in-this-fake",
        method="POST",
        route="/check-ins",
        idempotency_key="replayed-key",
        response_status=200,  # the original request was itself a dedupe-window duplicate
        response_reference=prior.check_in_id,
    )
    session.scalar_queue = [record]
    session.get_queue = [prior]

    _result, duplicate = await submit_check_in(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        qr_token="raw-qr-token",
        activities=["TASTING"],
        match_result_id=None,
        client_event_id=None,
        occurred_at=NOW,
        idempotency_key="replayed-key",
        settings=SETTINGS,
        now=NOW,
    )
    assert duplicate is True


@pytest.mark.asyncio
async def test_submit_check_in_new_creation_records_an_idempotency_row() -> None:
    session = FakeAsyncSession()
    booth = _booth()
    booth_qr = _booth_qr(booth_id=booth.booth_id)
    session.scalar_queue = [None, uuid.uuid4(), booth_qr, None]  # no prior key, visit, qr, dup
    session.get_queue = [booth]

    check_in, duplicate = await submit_check_in(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        qr_token="raw-qr-token",
        activities=["TASTING"],
        match_result_id=None,
        client_event_id=None,
        occurred_at=NOW,
        idempotency_key="fresh-key",
        settings=SETTINGS,
        now=NOW,
    )

    assert duplicate is False
    idempotency_rows = [row for row in session.added if isinstance(row, IdempotencyRecord)]
    assert len(idempotency_rows) == 1
    assert idempotency_rows[0].response_reference == check_in.check_in_id
    assert idempotency_rows[0].response_status == 201
    assert idempotency_rows[0].idempotency_key == "fresh-key"


@pytest.mark.asyncio
async def test_submit_check_in_race_window_falls_back_to_the_row_that_won_never_a_raw_500() -> (
    None
):
    """Two concurrent replays of the same offline-queued request: our idempotency pre-check
    sees nothing, but a concurrent request's insert (or its own idempotency_record row) commits
    first, and our own commit hits IntegrityError. This must resolve to the winning row, not an
    unhandled exception."""

    session = FakeAsyncSession()
    booth = _booth()
    booth_qr = _booth_qr(booth_id=booth.booth_id)
    winner = _check_in()
    winning_record = IdempotencyRecord(
        tenant_id=TENANT,
        principal_fingerprint=b"irrelevant-in-this-fake",
        method="POST",
        route="/check-ins",
        idempotency_key="racy-key",
        response_status=201,
        response_reference=winner.check_in_id,
    )
    session.scalar_queue = [
        None,  # pre-check: no idempotency record yet
        uuid.uuid4(),  # visit session
        booth_qr,  # qr lookup
        None,  # no recent duplicate
        winning_record,  # post-conflict idempotency re-lookup
    ]
    session.get_queue = [booth, winner]  # booth resolution, then replay's CheckIn lookup
    session.raise_integrity_error_on_next_commit = True

    check_in, duplicate = await submit_check_in(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        qr_token="raw-qr-token",
        activities=["TASTING"],
        match_result_id=None,
        client_event_id=None,
        occurred_at=NOW,
        idempotency_key="racy-key",
        settings=SETTINGS,
        now=NOW,
    )

    assert check_in is winner
    assert duplicate is False
    assert session.rollbacks == 1


# ---------------------------------------------------------------------------
# Router-level tests: TestClient + dependency_overrides.
# ---------------------------------------------------------------------------


def _build_app(session: FakeAsyncSession, subject: CurrentSubject) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(build_checkin_router())
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_subject] = lambda: subject
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    return app


def _auth_subject(user_id: uuid.UUID | None = None) -> CurrentSubject:
    return CurrentSubject(
        tenant_id=TENANT, event_id=EVENT, user_id=user_id or uuid.uuid4(), guest_session_id=None
    )


def _guest_subject(guest_session_id: uuid.UUID | None = None) -> CurrentSubject:
    return CurrentSubject(
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=None,
        guest_session_id=guest_session_id or uuid.uuid4(),
    )


def _request_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "qr_token": "raw-qr-token",
        "activities": ["TASTING"],
        "occurred_at": NOW.isoformat(),
    }
    body.update(overrides)
    return body


def test_router_creates_a_new_check_in_for_an_authenticated_user() -> None:
    session = FakeAsyncSession()
    booth = _booth()
    booth_qr = _booth_qr(booth_id=booth.booth_id)
    session.scalar_queue = [uuid.uuid4(), booth_qr, None]
    session.get_queue = [booth]
    app = _build_app(session, _auth_subject())

    with TestClient(app) as client:
        response = client.post("/check-ins", json=_request_body())

    assert response.status_code == 201
    body = response.json()
    assert body["duplicate"] is False
    assert body["booth_id"] == str(booth.booth_id)
    assert body["activities"] == ["TASTING"]


def test_router_creates_a_new_check_in_for_an_anonymous_guest() -> None:
    session = FakeAsyncSession()
    booth = _booth()
    booth_qr = _booth_qr(booth_id=booth.booth_id)
    session.scalar_queue = [uuid.uuid4(), booth_qr, None]
    session.get_queue = [booth]
    app = _build_app(session, _guest_subject())

    with TestClient(app) as client:
        response = client.post("/check-ins", json=_request_body(activities=["MEETING"]))

    assert response.status_code == 201
    assert response.json()["duplicate"] is False


def test_router_duplicate_within_window_returns_200_not_an_error() -> None:
    session = FakeAsyncSession()
    booth = _booth()
    booth_qr = _booth_qr(booth_id=booth.booth_id)
    existing = _check_in(booth_id=booth.booth_id, checked_in_at=NOW - timedelta(minutes=1))
    session.scalar_queue = [uuid.uuid4(), booth_qr, existing]
    session.get_queue = [booth]
    app = _build_app(session, _auth_subject())

    with TestClient(app) as client:
        response = client.post("/check-ins", json=_request_body())

    assert response.status_code == 200
    body = response.json()
    assert body["duplicate"] is True
    assert body["check_in_id"] == str(existing.check_in_id)


def test_router_invalid_qr_token_returns_422_with_invalid_qr_code() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [uuid.uuid4(), None]  # visit found, qr lookup misses
    app = _build_app(session, _auth_subject())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/check-ins", json=_request_body(qr_token="bogus"))

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "INVALID_QR"


def test_router_closed_booth_returns_409_with_booth_closed_code() -> None:
    session = FakeAsyncSession()
    booth = _booth(operating_status="CLOSED")
    booth_qr = _booth_qr(booth_id=booth.booth_id)
    session.scalar_queue = [uuid.uuid4(), booth_qr]
    session.get_queue = [booth]
    app = _build_app(session, _auth_subject())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/check-ins", json=_request_body())

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "BOOTH_CLOSED"


def test_router_no_active_visit_session_returns_404() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [None]
    app = _build_app(session, _auth_subject())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/check-ins", json=_request_body())

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "VISIT_SESSION_NOT_FOUND"


def test_router_idempotency_key_header_is_forwarded_and_replay_avoids_double_insert() -> None:
    session = FakeAsyncSession()
    prior = _check_in()
    record = IdempotencyRecord(
        tenant_id=TENANT,
        principal_fingerprint=b"irrelevant-in-this-fake",
        method="POST",
        route="/check-ins",
        idempotency_key="header-key",
        response_status=201,
        response_reference=prior.check_in_id,
    )
    session.scalar_queue = [record]
    session.get_queue = [prior]
    app = _build_app(session, _auth_subject())

    with TestClient(app) as client:
        response = client.post(
            "/check-ins",
            json=_request_body(),
            headers={"Idempotency-Key": "header-key"},
        )

    assert response.status_code == 201
    assert response.json()["check_in_id"] == str(prior.check_in_id)
    assert session.added == []  # no new row inserted on replay


def test_router_rejects_empty_activities_at_schema_layer() -> None:
    session = FakeAsyncSession()
    app = _build_app(session, _auth_subject())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/check-ins", json=_request_body(activities=[]))

    assert response.status_code == 422
    assert session.scalar_queue == []  # never touched the DB


def test_router_requires_a_subject_dependency() -> None:
    """No subject override -> the real get_current_subject dependency runs, which itself
    depends on get_verified_subject. Without a session/guest cookie that raises 401 - the
    router takes no identity from client-supplied headers (same precedent as
    test_favorites_api.py::test_router_requires_a_subject_dependency)."""

    session = FakeAsyncSession()
    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(build_checkin_router())
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_settings] = lambda: SETTINGS

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/check-ins", json=_request_body())

    assert response.status_code == 401
