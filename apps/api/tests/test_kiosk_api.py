"""Kiosk session/QR-handoff coverage (BACKEND-006).

Covers: session creation, expiry determination, QR handoff issuance/verification, expired-QR
rejection, and the "no personal data column" schema invariant (both on the request contract and
on the durable DB tables in app/models/kiosk.py).

Redis (the live session cache) and Postgres (the durable audit trail) are both faked here on
purpose - every HTTP-level test overrides both `get_kiosk_store` and `get_db` so this suite runs
without either service, matching every other router test in this package (see
test_recommendation_api.py's dependency_overrides pattern).
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from app.api.v1.routers import kiosk as kiosk_router
from app.db.session import get_db
from app.main import app
from app.models.kiosk import (
    KioskQrHandoff,
    KioskSession,
    compute_session_expiry,
    is_session_expired,
)
from app.schemas.exhibition_public import PublicBoothDetail
from app.schemas.kiosk import KioskSessionCreateRequest
from app.schemas.search import SearchResult
from app.services import kiosk as kiosk_service
from app.services.kiosk import (
    KioskHandoffRecord,
    KioskSessionRecord,
    create_handoff_record,
    get_kiosk_store,
    issue_handoff_token,
    verify_handoff_token,
)
from fastapi.testclient import TestClient

_EXHIBITOR_ID = uuid.UUID("11111111-1111-4111-8111-111111111111")
_BOOTH_ID = uuid.UUID("22222222-2222-4222-8222-222222222222")
_CANNED_RESULT_ID = f"exhibitor:{_EXHIBITOR_ID}:booth:{_BOOTH_ID}"


# ---------------------------------------------------------------------------
# 1. Schema invariant: no personal data columns/fields anywhere in the kiosk contract.
# ---------------------------------------------------------------------------


def test_kiosk_contract_has_no_personal_identity_fields() -> None:
    fields = set(KioskSessionCreateRequest.model_fields)
    forbidden = {"user_id", "name", "phone", "email", "profile_id", "password"}
    assert fields.isdisjoint(forbidden)


_FORBIDDEN_COLUMN_SUBSTRINGS = (
    "name",
    "phone",
    "email",
    "ssn",
    "password",
    "address",
    "birth",
    "signup",
)


def test_kiosk_db_tables_have_no_personal_data_columns() -> None:
    session_columns = set(KioskSession.__table__.columns.keys())
    handoff_columns = set(KioskQrHandoff.__table__.columns.keys())

    for column_name in session_columns | handoff_columns:
        lowered = column_name.lower()
        assert not any(bad in lowered for bad in _FORBIDDEN_COLUMN_SUBSTRINGS), (
            column_name
        )

    # The fields this task explicitly requires (last_activity_at + TTL) actually exist.
    assert {"last_activity_at", "expires_at", "status"} <= session_columns
    assert {"expires_at", "claimed_at", "token_hash"} <= handoff_columns


def test_kiosk_session_status_is_constrained_to_the_documented_lifecycle() -> None:
    check_constraints = {
        constraint.sqltext.text
        for constraint in KioskSession.__table__.constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    }
    assert any("ACTIVE" in text and "TIMED_OUT" in text for text in check_constraints)


# ---------------------------------------------------------------------------
# 2. Expiration determination - the backend's entire §24 responsibility: compute the
#    deadline from last-activity + TTL, and check whether "now" has passed it. No timer.
# ---------------------------------------------------------------------------


def test_session_expiry_is_last_activity_plus_timeout() -> None:
    reference = datetime(2026, 8, 2, 10, 0, 0, tzinfo=UTC)

    assert compute_session_expiry(reference, 90) == reference + timedelta(seconds=90)
    assert compute_session_expiry(reference, 60) == reference + timedelta(seconds=60)


def test_session_expiry_check_is_an_inclusive_boundary_comparison() -> None:
    expires_at = datetime(2026, 8, 2, 10, 1, 30, tzinfo=UTC)

    assert is_session_expired(expires_at, now=expires_at) is True
    assert (
        is_session_expired(expires_at, now=expires_at - timedelta(seconds=1)) is False
    )
    assert is_session_expired(expires_at, now=expires_at + timedelta(seconds=1)) is True


# ---------------------------------------------------------------------------
# 3. QR handoff: signed with app/core/security.py's shared HMAC utility, keeps the actual
#    selection server-side, round-trips, and rejects tampering/expiry.
# ---------------------------------------------------------------------------


def test_handoff_token_is_signed_through_core_security_hmac(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[bytes] = []
    original = kiosk_service.compute_webhook_signature

    def spy(payload: bytes, *, secret: str) -> str:
        calls.append(payload)
        return original(payload, secret=secret)

    monkeypatch.setattr(kiosk_service, "compute_webhook_signature", spy)

    issue_handoff_token(
        handoff_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        secret="test-secret",
    )

    assert calls, (
        "issue_handoff_token must sign through core.security.compute_webhook_signature"
    )


def test_handoff_token_is_signed_expires_and_keeps_selection_server_side() -> None:
    now = datetime.now(UTC)
    session = KioskSessionRecord(
        session_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        kiosk_id="kiosk-a01",
        language="ko",
        created_at=now,
        last_activity_at=now,
        expires_at=now + timedelta(seconds=90),
        last_result_ids=["exhibitor:private-selection"],
    )
    record, token, _ = create_handoff_record(
        session=session,
        selected_result_ids=["exhibitor:private-selection"],
        expiration_minutes=30,
        secret="test-secret",
        guest_web_base_url="https://example.test",
    )

    assert "private-selection" not in token
    assert record.selected_result_ids == ["exhibitor:private-selection"]
    payload = verify_handoff_token(token, secret="test-secret", now=now)
    assert payload["handoff_id"] == str(record.handoff_id)
    assert set(payload) == {"handoff_id", "event_id", "expires_at"}

    version, encoded, signature = token.split(".", 2)
    replacement = "0" if signature[0] != "0" else "1"
    tampered = f"{version}.{encoded}.{replacement}{signature[1:]}"
    with pytest.raises(ValueError, match="signature"):
        verify_handoff_token(tampered, secret="test-secret", now=now)
    with pytest.raises(ValueError, match="expired"):
        verify_handoff_token(token, secret="test-secret", now=record.expires_at)


def test_qr_token_signed_with_a_different_secret_is_rejected() -> None:
    token = issue_handoff_token(
        handoff_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        expires_at=datetime.now(UTC) + timedelta(minutes=5),
        secret="secret-a",
    )

    with pytest.raises(ValueError, match="signature"):
        verify_handoff_token(token, secret="secret-b")


# ---------------------------------------------------------------------------
# 4. HTTP-level session lifecycle (dependency-overridden Redis + Postgres fakes - no live
#    infra required).
# ---------------------------------------------------------------------------


class _FakeKioskStore:
    def __init__(self) -> None:
        self.sessions: dict[uuid.UUID, KioskSessionRecord] = {}
        self.handoffs: dict[uuid.UUID, KioskHandoffRecord] = {}

    async def save_session(self, record: KioskSessionRecord, ttl_seconds: int) -> None:
        assert 60 <= ttl_seconds <= 120
        self.sessions[record.session_id] = record

    async def get_session(self, session_id: uuid.UUID) -> KioskSessionRecord | None:
        return self.sessions.get(session_id)

    async def delete_session(self, session_id: uuid.UUID) -> None:
        self.sessions.pop(session_id, None)

    async def save_handoff(self, record: KioskHandoffRecord, ttl_seconds: int) -> None:
        assert ttl_seconds > 0
        self.handoffs[record.handoff_id] = record

    async def get_handoff(self, handoff_id: uuid.UUID) -> KioskHandoffRecord | None:
        return self.handoffs.get(handoff_id)


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _FakeDb:
    """Enough of AsyncSession for the kiosk router's best-effort audit writes."""

    def __init__(self, *, tenant_id: uuid.UUID | None) -> None:
        self.tenant_id = tenant_id
        self.rows: dict[tuple[type, uuid.UUID], Any] = {}
        self.commits = 0
        self.rollbacks = 0

    async def execute(self, statement: Any) -> _ScalarResult:
        del statement
        return _ScalarResult(self.tenant_id)

    def add(self, row: Any) -> None:
        pk = getattr(row, "session_id", None) or getattr(row, "handoff_id", None)
        self.rows[(type(row), pk)] = row

    async def get(self, model: type, pk: uuid.UUID) -> Any:
        return self.rows.get((model, pk))

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1


async def _fake_search_approved_catalog(
    db: Any,
    *,
    event_id: uuid.UUID,
    query: str,
    category_codes: list[str],
    limit: int,
    language: str,
    semantic_scorer: Any,
) -> list[SearchResult]:
    del db, event_id, query, category_codes, limit, semantic_scorer
    assert language == "ko"
    return [
        SearchResult(
            result_id=_CANNED_RESULT_ID,
            rank=1,
            exhibitor_id=_EXHIBITOR_ID,
            booth_id=_BOOTH_ID,
            name="테스트 다국어 안내 솔루션",
            booth_number="A-01",
            reason="검색어와 관련된 승인 업체예요.",
            operating_status="OPEN",
        )
    ]


def _install_overrides(store: _FakeKioskStore, db: _FakeDb) -> None:
    app.dependency_overrides[get_kiosk_store] = lambda: store

    async def _db_dependency():
        yield db

    app.dependency_overrides[get_db] = _db_dependency


def _clear_overrides() -> None:
    app.dependency_overrides.pop(get_kiosk_store, None)
    app.dependency_overrides.pop(get_db, None)


def test_kiosk_config_and_session_routes_are_available_without_identity() -> None:
    store = _FakeKioskStore()
    db = _FakeDb(tenant_id=uuid.uuid4())
    _install_overrides(store, db)
    try:
        client = TestClient(app)
        config_response = client.get("/api/v1/kiosk/config/kiosk-a01")
        assert config_response.status_code == 200
        config = config_response.json()["data"]
        assert config["session_timeout_seconds"] == 90
        assert config["supported_languages"] == ["ko", "en", "ja", "zh"]

        session_response = client.post(
            "/api/v1/kiosk/sessions",
            json={"kiosk_id": "kiosk-a01", "language": "ko"},
        )
        assert session_response.status_code == 201
        data = session_response.json()["data"]
        assert data["kiosk_id"] == "kiosk-a01"
        assert "user_id" not in data
        assert "phone" not in data
        session_id = uuid.UUID(data["session_id"])
        assert session_id in store.sessions

        # A durable, no-PII audit row was written alongside the Redis write.
        audit_row = db.rows[(KioskSession, session_id)]
        assert audit_row.status == "ACTIVE"
    finally:
        _clear_overrides()


def test_create_session_search_and_handoff_flow_persists_a_no_pii_audit_trail(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = _FakeKioskStore()
    db = _FakeDb(tenant_id=uuid.uuid4())
    monkeypatch.setattr(
        kiosk_router, "search_approved_catalog", _fake_search_approved_catalog
    )

    async def _fake_booth_detail(db: Any, **kwargs: Any) -> PublicBoothDetail:
        del db
        assert kwargs["booth_id"] == _BOOTH_ID
        return PublicBoothDetail(
            booth_id=_BOOTH_ID,
            booth_number="A-01",
            operating_status="OPEN",
            congestion_level="LOW",
            exhibitor_id=_EXHIBITOR_ID,
            company_name="테스트 다국어 안내 솔루션",
        )

    monkeypatch.setattr(kiosk_router, "get_booth_detail", _fake_booth_detail)
    _install_overrides(store, db)
    client = TestClient(app)

    try:
        create_response = client.post(
            "/api/v1/kiosk/sessions", json={"kiosk_id": "kiosk_a01", "language": "ko"}
        )
        assert create_response.status_code == 201
        session_id = uuid.UUID(create_response.json()["data"]["session_id"])

        search_response = client.post(
            f"/api/v1/kiosk/sessions/{session_id}/search",
            json={"query": "다국어 AI 안내", "category_codes": [], "limit": 5},
        )
        assert search_response.status_code == 200
        results = search_response.json()["data"]["results"]
        assert [item["result_id"] for item in results] == [_CANNED_RESULT_ID]

        handoff_response = client.post(
            f"/api/v1/kiosk/sessions/{session_id}/handoff",
            json={"selected_result_ids": [_CANNED_RESULT_ID]},
        )
        assert handoff_response.status_code == 200
        handoff_data = handoff_response.json()["data"]
        assert handoff_data["token"]
        assert "token=" in handoff_data["handoff_url"]

        # QR handoff resets the shared kiosk for the next visitor ...
        assert session_id not in store.sessions
        # ... and marks the durable audit row HANDED_OFF rather than deleting it.
        assert db.rows[(KioskSession, session_id)].status == "HANDED_OFF"
        handoff_id = uuid.UUID(handoff_data["handoff_id"])
        assert db.rows[(KioskQrHandoff, handoff_id)].kiosk_session_id == session_id
        assert db.rows[(KioskQrHandoff, handoff_id)].selected_result_ids == [
            _CANNED_RESULT_ID
        ]

        resolve_response = client.post(
            "/api/v1/kiosk/handoffs/resolve",
            json={"token": handoff_data["token"]},
        )
        assert resolve_response.status_code == 200
        resolved = resolve_response.json()["data"]
        assert resolved["handoff_id"] == str(handoff_id)
        assert resolved["selected_results"][0]["company_name"] == (
            "테스트 다국어 안내 솔루션"
        )
        assert db.rows[(KioskQrHandoff, handoff_id)].claimed_at is not None
    finally:
        _clear_overrides()


def test_search_on_an_expired_session_is_rejected() -> None:
    store = _FakeKioskStore()
    db = _FakeDb(tenant_id=uuid.uuid4())
    now = datetime.now(UTC)
    session_id = uuid.uuid4()
    store.sessions[session_id] = KioskSessionRecord(
        session_id=session_id,
        event_id=uuid.uuid4(),
        kiosk_id="kiosk_a01",
        language="ko",
        created_at=now - timedelta(minutes=5),
        last_activity_at=now - timedelta(minutes=3),
        expires_at=now - timedelta(minutes=1),
    )
    _install_overrides(store, db)

    try:
        response = TestClient(app).post(
            f"/api/v1/kiosk/sessions/{session_id}/search",
            json={"query": "만료 세션", "category_codes": [], "limit": 5},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 410
    assert response.json()["detail"]["code"] == "KIOSK_SESSION_EXPIRED"


def test_handoff_rejects_a_selection_outside_the_current_search_results() -> None:
    store = _FakeKioskStore()
    db = _FakeDb(tenant_id=uuid.uuid4())
    now = datetime.now(UTC)
    session_id = uuid.uuid4()
    store.sessions[session_id] = KioskSessionRecord(
        session_id=session_id,
        event_id=uuid.uuid4(),
        kiosk_id="kiosk_a01",
        language="ko",
        created_at=now,
        last_activity_at=now,
        expires_at=now + timedelta(seconds=90),
        last_result_ids=[_CANNED_RESULT_ID],
    )
    _install_overrides(store, db)

    try:
        response = TestClient(app).post(
            f"/api/v1/kiosk/sessions/{session_id}/handoff",
            json={"selected_result_ids": ["exhibitor:not-in-results:booth:none"]},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "KIOSK_HANDOFF_SELECTION_INVALID"


def test_close_marks_the_durable_session_row_closed_and_clears_the_live_cache() -> None:
    store = _FakeKioskStore()
    db = _FakeDb(tenant_id=uuid.uuid4())
    now = datetime.now(UTC)
    session_id = uuid.uuid4()
    store.sessions[session_id] = KioskSessionRecord(
        session_id=session_id,
        event_id=uuid.uuid4(),
        kiosk_id="kiosk_a01",
        language="ko",
        created_at=now,
        last_activity_at=now,
        expires_at=now + timedelta(seconds=90),
    )
    db.rows[(KioskSession, session_id)] = KioskSession(
        session_id=session_id,
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        kiosk_id="kiosk_a01",
        language="ko",
        status="ACTIVE",
        created_at=now,
        last_activity_at=now,
        expires_at=now + timedelta(seconds=90),
    )
    _install_overrides(store, db)

    try:
        response = TestClient(app).post(f"/api/v1/kiosk/sessions/{session_id}/close")
    finally:
        _clear_overrides()

    assert response.status_code == 200
    assert response.json()["data"] == {"session_id": str(session_id), "closed": True}
    assert session_id not in store.sessions
    closed_row = db.rows[(KioskSession, session_id)]
    assert closed_row.status == "CLOSED"
    assert closed_row.closed_at is not None


def test_public_search_and_kiosk_paths_are_in_openapi() -> None:
    paths = set(app.openapi()["paths"])
    expected = {
        "/api/v1/events/{event_id}/exhibitors",
        "/api/v1/exhibitors/{exhibitor_id}",
        "/api/v1/exhibitors/{exhibitor_id}/products",
        "/api/v1/booths/{booth_id}",
        "/api/v1/events/{event_id}/map",
        "/api/v1/search",
        "/api/v1/search/{search_session_id}",
        "/api/v1/kiosk/config/{kiosk_id}",
        "/api/v1/kiosk/sessions",
        "/api/v1/kiosk/sessions/{session_id}/search",
        "/api/v1/kiosk/sessions/{session_id}/handoff",
        "/api/v1/kiosk/handoffs/resolve",
        "/api/v1/kiosk/sessions/{session_id}/close",
    }
    assert expected <= paths
