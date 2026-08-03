from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
GUEST_ENDPOINT = ROOT / "backend/app/api/v1/endpoints/guest.py"


def test_guest_conversion_expires_session_and_clears_handoff_code() -> None:
    source = GUEST_ENDPOINT.read_text(encoding="utf-8")

    assert "guest_session.converted_user_id = context.user_id" in source
    assert "guest_session.converted_at = converted_at" in source
    assert "guest_session.entry_code = None" in source
    assert "guest_session.expires_at = converted_at" in source


def test_temporary_visit_sessions_are_detached_after_guest_conversion() -> None:
    source = GUEST_ENDPOINT.read_text(encoding="utf-8")

    assert ".where(VisitSession.guest_session_id == guest_session.guest_session_id)" in source
    assert "guest_session_id=None" in source


def test_temporary_favorites_require_active_guest_session() -> None:
    source = GUEST_ENDPOINT.read_text(encoding="utf-8")

    add_favorite_block = source.split('"/sessions/{guest_session_id}/favorites"', maxsplit=1)[1]
    assert "require_active=True" in add_favorite_block
