from __future__ import annotations

import base64
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from cryptography.exceptions import InvalidTag
from fastapi.testclient import TestClient
from pydantic import ValidationError
from starlette.requests import Request

from app.api.v1.routers.auth import _magic_link_principal, _totp_enrollment_material
from app.core.auth import (
    AuthException,
    _verify_browser_mutation,
    decrypt_secret,
    digest_secret,
    encrypt_secret,
    issue_personal_access_link,
    mfa_establishes_aal2,
    new_session_material,
    visible_role_grants,
)
from app.core.config import Settings
from app.db.session import get_db
from app.main import app
from app.schemas.auth import AuthMfaVerifyRequest
from app.schemas.auth import AuthRoleGrant as AuthRoleGrantView


class _RecordingDb:
    def __init__(self) -> None:
        self.rows: list[object] = []
        self.executions: list[object] = []
        self.flushes = 0

    def add(self, row: object) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        self.flushes += 1

    async def execute(self, statement: object) -> None:
        self.executions.append(statement)


def _settings() -> Settings:
    return Settings(
        SECRET_KEY="unit-test-secret-key-with-enough-entropy",
        AUTH_TOKEN_PEPPER="independent-unit-test-token-pepper",
        AUTH_ENCRYPTION_KEY_B64=base64.urlsafe_b64encode(b"e" * 32).decode(),
    )


def test_auth_contract_paths_and_security_schemes_are_published() -> None:
    spec = app.openapi()
    assert {
        "/api/v1/auth/magic-links/exchange",
        "/api/v1/auth/session",
        "/api/v1/auth/mfa/enrollments",
        "/api/v1/auth/mfa/challenges",
        "/api/v1/auth/mfa/challenges/{challenge_id}/verify",
    } <= set(spec["paths"])
    assert set(spec["components"]["securitySchemes"]) == {
        "BrowserSession",
        "BearerJWT",
        "GuestSession",
    }
    assert spec["paths"]["/api/v1/auth/magic-links/exchange"]["post"]["security"] == []
    assert spec["paths"]["/api/v1/auth/session"]["get"]["security"] == [
        {"BrowserSession": []}
    ]


def test_signed_context_headers_cannot_create_a_user_principal() -> None:
    async def fake_db():
        yield object()

    app.dependency_overrides[get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/recommendations",
            headers={
                "X-Tenant-Id": str(uuid4()),
                "X-Event-Id": str(uuid4()),
                "X-Profile-Id": str(uuid4()),
                "X-User-Id": str(uuid4()),
            },
            json={"recommendation_type": "PRODUCT"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.asyncio
async def test_personal_link_persists_only_keyed_digest() -> None:
    db = _RecordingDb()
    settings = _settings()
    row, raw_token = await issue_personal_access_link(
        db,  # type: ignore[arg-type]
        tenant_id=uuid4(),
        event_id=uuid4(),
        user_id=uuid4(),
        profile_id=uuid4(),
        return_path="/e/baekdudaegan-2026/my",
        settings=settings,
    )

    assert len(raw_token) >= 43
    assert raw_token.encode() not in row.token_hmac
    assert row.token_hmac == digest_secret(
        raw_token, purpose="personal-link", settings=settings
    )
    assert db.rows == [row]
    assert db.flushes == 1
    assert len(db.executions) == 1


@pytest.mark.asyncio
async def test_personal_link_rejects_cross_origin_return_path() -> None:
    with pytest.raises(ValueError, match="same-origin"):
        await issue_personal_access_link(
            _RecordingDb(),  # type: ignore[arg-type]
            tenant_id=uuid4(),
            event_id=uuid4(),
            user_id=uuid4(),
            profile_id=None,
            return_path="//attacker.example/steal",
            settings=_settings(),
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("return_path", [r"/safe\\evil", "/safe\nLocation: evil"])
async def test_personal_link_rejects_ambiguous_return_path(return_path: str) -> None:
    with pytest.raises(ValueError, match="same-origin"):
        await issue_personal_access_link(
            _RecordingDb(),  # type: ignore[arg-type]
            tenant_id=uuid4(),
            event_id=uuid4(),
            user_id=uuid4(),
            profile_id=None,
            return_path=return_path,
            settings=_settings(),
        )


def test_aead_ciphertext_is_randomized_and_tamper_evident() -> None:
    settings = _settings()
    first = encrypt_secret("sensitive memo", purpose="meeting", settings=settings)
    second = encrypt_secret("sensitive memo", purpose="meeting", settings=settings)

    assert first != second
    assert b"sensitive memo" not in first
    assert (
        decrypt_secret(first, purpose="meeting", settings=settings) == b"sensitive memo"
    )
    tampered = first[:-1] + bytes([first[-1] ^ 1])
    with pytest.raises(InvalidTag):
        decrypt_secret(tampered, purpose="meeting", settings=settings)


def test_session_material_contains_no_raw_persisted_secret() -> None:
    settings = _settings()
    token, token_hmac, csrf, csrf_hmac, csrf_enc = new_session_material(settings)

    assert token.encode() not in token_hmac
    assert csrf.encode() not in csrf_hmac
    assert csrf.encode() not in csrf_enc
    assert decrypt_secret(csrf_enc, purpose="csrf", settings=settings).decode() == csrf


def _request(method: str, headers: dict[str, str]) -> Request:
    return Request(
        {
            "type": "http",
            "method": method,
            "path": "/api/v1/protected",
            "headers": [
                (name.lower().encode("ascii"), value.encode("ascii"))
                for name, value in headers.items()
            ],
        }
    )


def test_browser_mutation_requires_allowlisted_origin_and_bound_csrf() -> None:
    settings = _settings()
    csrf = "session-csrf-token"
    session = SimpleNamespace(
        csrf_hmac=digest_secret(csrf, purpose="csrf", settings=settings)
    )

    with pytest.raises(AuthException) as missing_origin:
        _verify_browser_mutation(
            _request("POST", {"X-CSRF-Token": csrf}),
            session,
            settings,  # type: ignore[arg-type]
        )
    assert missing_origin.value.error.code == "CSRF_FAILED"

    with pytest.raises(AuthException) as cross_origin:
        _verify_browser_mutation(
            _request(
                "POST",
                {"Origin": "https://attacker.example", "X-CSRF-Token": csrf},
            ),
            session,  # type: ignore[arg-type]
            settings,
        )
    assert cross_origin.value.error.code == "CSRF_FAILED"

    _verify_browser_mutation(
        _request(
            "POST",
            {"Origin": "http://localhost:3001", "X-CSRF-Token": csrf},
        ),
        session,  # type: ignore[arg-type]
        settings,
    )


def test_magic_link_principal_is_aal1_without_admin_grants() -> None:
    issued_at = datetime.now(UTC)
    session = SimpleNamespace(
        user_id=uuid4(),
        tenant_id=uuid4(),
        event_id=uuid4(),
        authenticated_at=issued_at,
    )
    verified = _magic_link_principal(session)  # type: ignore[arg-type]

    assert verified.session is session
    assert verified.principal.authn_level == "AAL1"
    assert verified.principal.amr == {"magic_link"}
    assert verified.principal.role_grants == []


def test_aal1_retains_exhibitor_grant_but_hides_privileged_grants() -> None:
    tenant_id = uuid4()
    event_id = uuid4()
    grants = [
        AuthRoleGrantView(
            role="EVENT_ADMIN",
            tenant_id=tenant_id,
            event_id=event_id,
            exhibitor_id=None,
        ),
        AuthRoleGrantView(
            role="EXHIBITOR_ADMIN",
            tenant_id=tenant_id,
            event_id=event_id,
            exhibitor_id=uuid4(),
        ),
    ]

    assert [grant.role for grant in visible_role_grants(grants, "AAL1")] == [
        "EXHIBITOR_ADMIN"
    ]
    assert visible_role_grants(grants, "AAL2") == grants


def test_totp_secret_is_returned_once_but_not_persisted_in_json() -> None:
    settings = _settings()
    secret_enc, persisted_options, response_options = _totp_enrollment_material(
        user_id=uuid4(), display_name="Security key", settings=settings
    )

    assert persisted_options == {"display_name": "Security key"}
    assert "secret" not in persisted_options
    assert "otpauth_uri" not in persisted_options
    assert isinstance(response_options["secret"], str)
    assert str(response_options["otpauth_uri"]).startswith("otpauth://totp/")
    assert (
        decrypt_secret(secret_enc, purpose="totp", settings=settings).decode()
        == response_options["secret"]
    )


def test_auth_migration_backfills_only_explicit_legacy_event_scopes() -> None:
    migration = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260803_0018_auth_session_mfa.py"
    ).read_text(encoding="utf-8")

    assert "r.role_code = 'OPERATOR' AND ur.event_id IS NOT NULL" in migration
    assert "r.role_code = 'EXHIBITOR' AND ur.event_id IS NOT NULL" in migration
    assert "r.role_code = 'ADMIN'" not in migration


@pytest.mark.parametrize(
    ("amr", "method", "expected"),
    [
        (["magic_link"], "TOTP", False),
        (["password"], "TOTP", True),
        (["oidc"], "TOTP", True),
        (["magic_link"], "WEBAUTHN", True),
        (["magic_link"], "RECOVERY_CODE", True),
    ],
)
def test_mfa_factor_independence(amr: list[str], method: str, expected: bool) -> None:
    assert mfa_establishes_aal2(amr, method) is expected


def test_mfa_verify_requires_exactly_one_matching_proof() -> None:
    with pytest.raises(ValidationError):
        AuthMfaVerifyRequest()
    with pytest.raises(ValidationError):
        AuthMfaVerifyRequest(otp_code="123456", recovery_code="recovery-code-123")
    assert AuthMfaVerifyRequest(otp_code="123456").otp_code == "123456"


def test_deployment_requires_independent_auth_keys() -> None:
    encoded = base64.urlsafe_b64encode(b"k" * 32).decode()
    with pytest.raises(ValidationError, match="AUTH_TOKEN_PEPPER"):
        Settings(
            ENV="production",
            SECRET_KEY="production-secret",
            SITE_CONTEXT_SECRET="site-context-secret",
            AUTH_ENCRYPTION_KEY_B64=encoded,
        )


def test_deployment_rejects_local_auth_origins() -> None:
    encoded = base64.urlsafe_b64encode(b"k" * 32).decode()
    with pytest.raises(ValidationError, match="AUTH_BROWSER_ORIGINS"):
        Settings(
            ENV="production",
            SECRET_KEY="production-secret",
            SITE_CONTEXT_SECRET="site-context-secret",
            AUTH_TOKEN_PEPPER="independent-production-pepper",
            AUTH_ENCRYPTION_KEY_B64=encoded,
        )
