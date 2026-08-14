"""Verified principals, opaque credentials, CSRF, RBAC, and crypto helpers.

Raw browser credentials and personal-link tokens are never persisted. Browser
requests use the server session cookie; service callers may use short-lived
asymmetrically signed JWTs. Raw identity headers are deliberately ignored.
"""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal
from uuid import UUID

import jwt
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from fastapi import Depends, Header, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import AuthRoleGrant as AuthRoleGrantRecord
from app.models.auth import AuthSession, PersonalAccessLink
from app.models.identity import GuestSession, UserAccount
from app.schemas.auth import AuthError, AuthPrincipal, AuthRoleGrant

SESSION_COOKIE = "__Host-meet_ai_session"
CSRF_HEADER = "X-CSRF-Token"
PRIVILEGED_ADMIN_ROLES = frozenset({"EVENT_ADMIN", "DATA_REVIEWER"})


class AuthException(Exception):
    def __init__(
        self, status_code: int, code: str, message: str, request_id: str = "unknown"
    ):
        self.status_code = status_code
        self.error = AuthError(code=code, message=message, request_id=request_id)  # type: ignore[arg-type]
        super().__init__(code)


async def auth_exception_handler(_request: Request, exc: AuthException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code, content=exc.error.model_dump(mode="json")
    )


def _request_id(request: Request) -> str:
    return request.headers.get("X-Request-Id", "unknown")[:100]


def _fail(request: Request, status_code: int, code: str, message: str) -> AuthException:
    return AuthException(status_code, code, message, _request_id(request))


def digest_secret(secret: str | bytes, *, purpose: str, settings: Settings) -> bytes:
    raw = secret.encode("utf-8") if isinstance(secret, str) else secret
    return hmac.digest(
        settings.auth_token_pepper, purpose.encode("ascii") + b"\0" + raw, "sha256"
    )


def encrypt_secret(value: str | bytes, *, purpose: str, settings: Settings) -> bytes:
    raw = value.encode("utf-8") if isinstance(value, str) else value
    nonce = secrets.token_bytes(12)
    ciphertext = AESGCM(settings.auth_encryption_key).encrypt(
        nonce, raw, purpose.encode("ascii")
    )
    return b"MEETAI1" + nonce + ciphertext


def decrypt_secret(value: bytes, *, purpose: str, settings: Settings) -> bytes:
    if not value.startswith(b"MEETAI1") or len(value) < 36:
        raise ValueError("unsupported encrypted value")
    return AESGCM(settings.auth_encryption_key).decrypt(
        value[7:19], value[19:], purpose.encode("ascii")
    )


def _now() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class VerifiedPrincipal:
    principal: AuthPrincipal
    session: AuthSession | None
    service_scopes: frozenset[str] = frozenset()

    @property
    def user_id(self) -> UUID:
        return self.principal.subject_id

    def has_role(
        self,
        role: str,
        *,
        tenant_id: UUID | None = None,
        event_id: UUID | None = None,
        exhibitor_id: UUID | None = None,
    ) -> bool:
        for grant in self.principal.role_grants:
            if grant.role != role:
                continue
            if tenant_id is not None and grant.tenant_id != tenant_id:
                continue
            if event_id is not None and grant.event_id != event_id:
                continue
            if exhibitor_id is not None and grant.exhibitor_id != exhibitor_id:
                continue
            return True
        return False


@dataclass(frozen=True, slots=True)
class VerifiedGuest:
    guest_session_id: UUID
    tenant_id: UUID
    event_id: UUID


async def _active_role_grants(
    db: AsyncSession,
    *,
    user_id: UUID,
    tenant_id: UUID,
    event_id: UUID | None,
    now: datetime,
) -> list[AuthRoleGrant]:
    query = select(AuthRoleGrantRecord).where(
        AuthRoleGrantRecord.user_id == user_id,
        AuthRoleGrantRecord.tenant_id == tenant_id,
        AuthRoleGrantRecord.valid_from <= now,
        or_(
            AuthRoleGrantRecord.valid_until.is_(None),
            AuthRoleGrantRecord.valid_until > now,
        ),
    )
    if event_id is not None:
        query = query.where(AuthRoleGrantRecord.event_id == event_id)
    rows = (await db.scalars(query)).all()
    return [
        AuthRoleGrant(
            role=row.role,  # type: ignore[arg-type]
            tenant_id=row.tenant_id,
            event_id=row.event_id,
            exhibitor_id=row.exhibitor_id,
        )
        for row in rows
    ]


def visible_role_grants(
    grants: list[AuthRoleGrant], authn_level: str
) -> list[AuthRoleGrant]:
    """Hide privileged operator grants until MFA while retaining exhibitor scope."""

    if authn_level == "AAL2":
        return grants
    return [grant for grant in grants if grant.role not in PRIVILEGED_ADMIN_ROLES]


async def _browser_principal(
    request: Request,
    db: AsyncSession,
    token: str,
    settings: Settings,
    *,
    enforce_mutation: bool = True,
) -> VerifiedPrincipal:
    now = _now()
    token_hmac = digest_secret(token, purpose="browser-session", settings=settings)
    session = await db.scalar(
        select(AuthSession).where(AuthSession.token_hmac == token_hmac)
    )
    if session is None:
        raise _fail(request, 401, "AUTH_REQUIRED", "인증이 필요합니다.")
    if (
        session.revoked_at is not None
        or now >= session.absolute_expires_at
        or now >= session.idle_expires_at
    ):
        if session.revoked_at is None:
            session.revoked_at = now
            await db.commit()
        raise _fail(request, 401, "SESSION_EXPIRED", "세션이 만료되었습니다.")
    account = await db.get(UserAccount, session.user_id)
    if (
        account is None
        or account.account_status != "ACTIVE"
        or account.deleted_at is not None
    ):
        raise _fail(request, 401, "AUTH_REQUIRED", "인증이 필요합니다.")

    if enforce_mutation:
        _verify_browser_mutation(request, session, settings)

    grants = visible_role_grants(
        await _active_role_grants(
            db,
            user_id=session.user_id,
            tenant_id=session.tenant_id,
            event_id=session.event_id,
            now=now,
        ),
        session.authn_level,
    )
    idle_seconds = (
        settings.AUTH_SESSION_IDLE_ADMIN_SECONDS
        if grants or session.state != "AUTHENTICATED"
        else settings.AUTH_SESSION_IDLE_USER_SECONDS
    )
    next_idle = min(now + timedelta(seconds=idle_seconds), session.absolute_expires_at)
    if (now - session.last_seen_at).total_seconds() >= 60:
        session.last_seen_at = now
        session.idle_expires_at = next_idle
        await db.commit()

    return VerifiedPrincipal(
        principal=AuthPrincipal(
            subject_type="USER",
            subject_id=session.user_id,
            tenant_id=session.tenant_id,
            event_id=session.event_id,
            role_grants=grants,
            authn_level=session.authn_level,  # type: ignore[arg-type]
            amr=set(session.amr),
            authenticated_at=session.authenticated_at,
            mfa_at=session.mfa_at,
        ),
        session=session,
    )


def _verify_browser_mutation(
    request: Request, session: AuthSession, settings: Settings
) -> None:
    """Require a session-bound token and an allowlisted Origin on unsafe methods."""

    if request.method.upper() in {"GET", "HEAD", "OPTIONS"}:
        return
    origin = request.headers.get("Origin")
    if not origin or origin not in settings.auth_browser_origins:
        raise _fail(request, 403, "CSRF_FAILED", "요청 출처를 확인할 수 없습니다.")
    supplied = request.headers.get(CSRF_HEADER)
    if not supplied or not hmac.compare_digest(
        session.csrf_hmac,
        digest_secret(supplied, purpose="csrf", settings=settings),
    ):
        raise _fail(request, 403, "CSRF_FAILED", "CSRF 검증에 실패했습니다.")


async def _jwt_principal(
    request: Request, db: AsyncSession, token: str, settings: Settings
) -> VerifiedPrincipal:
    key_setting = settings.AUTH_JWT_PUBLIC_KEY_PEM
    if key_setting is None:
        raise _fail(request, 401, "TOKEN_INVALID", "토큰이 유효하지 않습니다.")
    try:
        claims = jwt.decode(
            token,
            key_setting.get_secret_value(),
            algorithms=["RS256"],
            audience=settings.AUTH_JWT_AUDIENCE,
            issuer=settings.AUTH_JWT_ISSUER,
            options={"require": ["iss", "aud", "sub", "iat", "nbf", "exp", "jti"]},
        )
        issued = datetime.fromtimestamp(int(claims["iat"]), UTC)
        expires = datetime.fromtimestamp(int(claims["exp"]), UTC)
        if expires - issued > timedelta(minutes=10):
            raise ValueError("JWT lifetime exceeds contract")
        subject_id = UUID(str(claims["sub"]))
        tenant_id = UUID(str(claims["tenant_id"]))
        event_id = UUID(str(claims["event_id"])) if claims.get("event_id") else None
        subject_type: Literal["USER", "SERVICE"] = claims.get("subject_type", "SERVICE")
        if subject_type not in {"USER", "SERVICE"}:
            raise ValueError("subject type")
    except (jwt.PyJWTError, KeyError, TypeError, ValueError):
        raise _fail(
            request, 401, "TOKEN_INVALID", "토큰이 유효하지 않습니다."
        ) from None

    if subject_type == "USER":
        account = await db.get(UserAccount, subject_id)
        if (
            account is None
            or account.account_status != "ACTIVE"
            or account.deleted_at is not None
        ):
            raise _fail(request, 401, "TOKEN_INVALID", "User account is not active.")
        grants = visible_role_grants(
            await _active_role_grants(
                db,
                user_id=subject_id,
                tenant_id=tenant_id,
                event_id=event_id,
                now=_now(),
            ),
            str(claims.get("aal", "AAL1")),
        )
    else:
        grants = []
    return VerifiedPrincipal(
        principal=AuthPrincipal(
            subject_type=subject_type,
            subject_id=subject_id,
            tenant_id=tenant_id,
            event_id=event_id,
            role_grants=grants,
            authn_level=claims.get("aal", "AAL1"),
            amr={"service_jwt"}
            if subject_type == "SERVICE"
            else set(claims.get("amr", [])),
            authenticated_at=issued,
            mfa_at=(
                datetime.fromtimestamp(int(claims["mfa_at"]), UTC)
                if claims.get("mfa_at")
                else None
            ),
        ),
        session=None,
        service_scopes=frozenset(str(item) for item in claims.get("scope", "").split()),
    )


async def get_verified_principal(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VerifiedPrincipal:
    cookie = request.cookies.get(settings.AUTH_SESSION_COOKIE_NAME)
    authorization = request.headers.get("Authorization")
    bearer = None
    if authorization:
        scheme, _, credential = authorization.partition(" ")
        if scheme.lower() != "bearer" or not credential:
            raise _fail(request, 401, "TOKEN_INVALID", "토큰이 유효하지 않습니다.")
        bearer = credential
    if cookie and bearer:
        raise _fail(
            request, 401, "PRINCIPAL_CONFLICT", "하나의 인증 수단만 사용해야 합니다."
        )
    if cookie:
        return await _browser_principal(request, db, cookie, settings)
    if bearer:
        return await _jwt_principal(request, db, bearer, settings)
    raise _fail(request, 401, "AUTH_REQUIRED", "인증이 필요합니다.")


async def get_verified_subject(
    request: Request,
    db: Annotated[AsyncSession, Depends(get_db)],
    settings: Annotated[Settings, Depends(get_settings)],
) -> VerifiedPrincipal | VerifiedGuest:
    """Resolve either an authenticated principal or a separate guest cookie."""

    has_authenticated_credential = bool(
        request.cookies.get(settings.AUTH_SESSION_COOKIE_NAME)
        or request.headers.get("Authorization")
    )
    guest_token = request.cookies.get("__Host-meet_ai_guest")
    if has_authenticated_credential and guest_token:
        raise _fail(
            request,
            401,
            "PRINCIPAL_CONFLICT",
            "인증 세션과 게스트 세션을 동시에 사용할 수 없습니다.",
        )
    if has_authenticated_credential:
        return await get_verified_principal(request, db, settings)
    if not guest_token:
        raise _fail(
            request, 401, "AUTH_REQUIRED", "인증 세션 또는 게스트 세션이 필요합니다."
        )
    token_hmac = digest_secret(guest_token, purpose="guest-session", settings=settings)
    guest = await db.scalar(
        select(GuestSession).where(GuestSession.session_token_hmac == token_hmac)
    )
    now = _now()
    if guest is None or now >= guest.expires_at or guest.converted_at is not None:
        raise _fail(request, 401, "SESSION_EXPIRED", "게스트 세션이 만료되었습니다.")
    return VerifiedGuest(
        guest_session_id=guest.guest_session_id,
        tenant_id=guest.tenant_id,
        event_id=guest.event_id,
    )


async def require_browser_session(
    request: Request,
    principal: Annotated[VerifiedPrincipal, Depends(get_verified_principal)],
) -> VerifiedPrincipal:
    if principal.session is None:
        raise _fail(request, 403, "RESOURCE_FORBIDDEN", "브라우저 세션이 필요합니다.")
    return principal


async def require_csrf(
    request: Request,
    principal: Annotated[VerifiedPrincipal, Depends(require_browser_session)],
    settings: Annotated[Settings, Depends(get_settings)],
    x_csrf_token: Annotated[str | None, Header(alias=CSRF_HEADER)] = None,
) -> VerifiedPrincipal:
    assert principal.session is not None
    if not x_csrf_token or not hmac.compare_digest(
        principal.session.csrf_hmac,
        digest_secret(x_csrf_token, purpose="csrf", settings=settings),
    ):
        raise _fail(request, 403, "CSRF_FAILED", "CSRF 검증에 실패했습니다.")
    return principal


def require_roles(*roles: str, fresh_mfa: bool = False):
    async def dependency(
        request: Request,
        principal: Annotated[VerifiedPrincipal, Depends(get_verified_principal)],
        settings: Annotated[Settings, Depends(get_settings)],
    ) -> VerifiedPrincipal:
        matching_grants = [
            grant for grant in principal.principal.role_grants if grant.role in roles
        ]
        needs_aal2 = (
            fresh_mfa
            or bool(principal.session and principal.session.state != "AUTHENTICATED")
            or any(grant.role in PRIVILEGED_ADMIN_ROLES for grant in matching_grants)
        )
        if needs_aal2 and principal.principal.authn_level != "AAL2":
            raise _fail(request, 403, "MFA_REQUIRED", "관리자 다중 인증이 필요합니다.")
        if not matching_grants:
            raise _fail(
                request, 403, "RESOURCE_FORBIDDEN", "자원에 접근할 권한이 없습니다."
            )
        if fresh_mfa:
            mfa_at = principal.principal.mfa_at
            if mfa_at is None or _now() - mfa_at > timedelta(
                seconds=settings.AUTH_MFA_FRESHNESS_SECONDS
            ):
                raise _fail(
                    request,
                    403,
                    "MFA_FRESHNESS_REQUIRED",
                    "최근 다중 인증이 필요합니다.",
                )
        return principal

    return dependency


async def issue_personal_access_link(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
    user_id: UUID,
    profile_id: UUID | None,
    recommendation_session_id: UUID | None = None,
    return_path: str,
    settings: Settings | None = None,
) -> tuple[PersonalAccessLink, str]:
    """Internal adapter entrypoint for Alimtalk/email personal-link issuance."""

    if (
        not return_path.startswith("/")
        or return_path.startswith("//")
        or "\\" in return_path
        or any(ord(character) < 32 for character in return_path)
    ):
        raise ValueError("return_path must be same-origin and relative")
    settings = settings or get_settings()
    now = _now()
    await db.execute(
        update(PersonalAccessLink)
        .where(
            PersonalAccessLink.tenant_id == tenant_id,
            PersonalAccessLink.event_id == event_id,
            PersonalAccessLink.user_id == user_id,
            PersonalAccessLink.return_path == return_path,
            PersonalAccessLink.consumed_at.is_(None),
            PersonalAccessLink.revoked_at.is_(None),
            PersonalAccessLink.expires_at > now,
        )
        .values(revoked_at=now)
    )
    raw_token = secrets.token_urlsafe(32)
    row = PersonalAccessLink(
        token_hmac=digest_secret(raw_token, purpose="personal-link", settings=settings),
        tenant_id=tenant_id,
        event_id=event_id,
        user_id=user_id,
        profile_id=profile_id,
        recommendation_session_id=recommendation_session_id,
        return_path=return_path,
        expires_at=now + timedelta(seconds=settings.AUTH_MAGIC_LINK_TTL_SECONDS),
    )
    db.add(row)
    await db.flush()
    return row, raw_token


def decrypted_csrf_token(session: AuthSession, settings: Settings) -> str:
    return decrypt_secret(session.csrf_enc, purpose="csrf", settings=settings).decode(
        "utf-8"
    )


def new_session_material(settings: Settings) -> tuple[str, bytes, str, bytes, bytes]:
    token = secrets.token_urlsafe(32)
    csrf = secrets.token_urlsafe(32)
    return (
        token,
        digest_secret(token, purpose="browser-session", settings=settings),
        csrf,
        digest_secret(csrf, purpose="csrf", settings=settings),
        encrypt_secret(csrf, purpose="csrf", settings=settings),
    )


def set_session_cookie(response, token: str, settings: Settings) -> None:
    response.set_cookie(
        key=settings.AUTH_SESSION_COOKIE_NAME,
        value=token,
        max_age=settings.AUTH_SESSION_ABSOLUTE_SECONDS,
        secure=True,
        httponly=True,
        samesite="lax",
        path="/",
    )


def mfa_establishes_aal2(session_amr: list[str], method: str) -> bool:
    """Apply CONTRACT-006 factor-independence rules deterministically."""

    if method in {"WEBAUTHN", "RECOVERY_CODE"}:
        return True
    return method == "TOTP" and any(
        primary in {"password", "oidc"} for primary in session_amr
    )
