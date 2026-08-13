from __future__ import annotations

import base64
from datetime import date
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.auth import digest_secret
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.main import app
from app.models.core import Event
from app.models.identity import GuestSession
from app.models.profile import UserProfile, VisitSession


class _RecordingDb:
    def __init__(self, event: Event | None) -> None:
        self.event = event
        self.rows: list[object] = []
        self.commits = 0

    async def scalar(self, _statement: object) -> Event | None:
        return self.event

    def add_all(self, rows: list[object]) -> None:
        self.rows.extend(rows)

    async def commit(self) -> None:
        self.commits += 1


def _settings() -> Settings:
    return Settings(
        SECRET_KEY="guest-session-unit-test-secret",
        AUTH_TOKEN_PEPPER="guest-session-independent-pepper",
        AUTH_ENCRYPTION_KEY_B64=base64.urlsafe_b64encode(b"g" * 32).decode(),
    )


def _event(status: str = "OPEN") -> Event:
    return Event(
        event_id=uuid4(),
        tenant_id=uuid4(),
        event_code="BACKJU-2026",
        event_name="Backju 2026",
        timezone="Asia/Seoul",
        start_date=date(2026, 8, 1),
        end_date=date(2026, 8, 5),
        event_status=status,
    )


def test_session_entry_contract_is_public() -> None:
    operation = app.openapi()["paths"]["/api/v1/sessions"]["post"]
    assert operation["security"] == []
    assert operation["responses"]["201"]


def test_create_session_sets_opaque_guest_cookie_and_persists_digest() -> None:
    event = _event()
    db = _RecordingDb(event)
    settings = _settings()

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_settings] = lambda: settings
    try:
        response = TestClient(app, base_url="https://testserver").post(
            "/api/v1/sessions",
            headers={"X-Request-ID": "session-test"},
            json={
                "event_id": str(event.event_id),
                "entry_channel": "WEB",
                "device_type": "MOBILE_WEB",
                "language": "ko-KR",
            },
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 201
    assert response.json()["data"]["service_available"] is True
    assert response.json()["meta"]["request_id"] == "session-test"
    assert db.commits == 1
    guest, profile, visit = db.rows
    assert isinstance(guest, GuestSession)
    assert isinstance(profile, UserProfile)
    assert isinstance(visit, VisitSession)
    raw_token = response.cookies["__Host-meet_ai_guest"]
    assert guest.session_token_hmac == digest_secret(
        raw_token, purpose="guest-session", settings=settings
    )
    assert raw_token not in response.text
    cookie_header = response.headers["set-cookie"]
    assert "HttpOnly" in cookie_header
    assert "Secure" in cookie_header
    assert "SameSite=lax" in cookie_header


def test_session_entry_rejects_inactive_kiosk_channel() -> None:
    db = _RecordingDb(_event())

    async def fake_db():
        yield db

    app.dependency_overrides[get_db] = fake_db
    app.dependency_overrides[get_settings] = _settings
    try:
        response = TestClient(app, base_url="https://testserver").post(
            "/api/v1/sessions",
            json={"event_id": str(uuid4()), "entry_channel": "KIOSK"},
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 422
    assert db.rows == []
