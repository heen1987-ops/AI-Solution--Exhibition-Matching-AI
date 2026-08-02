"""Opaque personal-link exchange, browser sessions, and administrator MFA."""

from __future__ import annotations

import json
import secrets
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Annotated
from uuid import UUID

import pyotp
from fastapi import APIRouter, Depends, Request, Response, status
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from webauthn import (
    base64url_to_bytes,
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.exceptions import (
    InvalidAuthenticationResponse,
    InvalidRegistrationResponse,
)
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.core.auth import (
    PRIVILEGED_ADMIN_ROLES,
    VerifiedPrincipal,
    _active_role_grants,
    _browser_principal,
    _fail,
    _now,
    decrypt_secret,
    decrypted_csrf_token,
    digest_secret,
    encrypt_secret,
    mfa_establishes_aal2,
    new_session_material,
    require_browser_session,
    require_csrf,
    set_session_cookie,
    visible_role_grants,
)
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.auth import (
    AuthRoleGrant,
    AuthSession,
    MfaAuthenticator,
    MfaChallenge,
    MfaRecoveryCode,
    PersonalAccessLink,
)
from app.models.consent import AuditLog
from app.models.identity import UserAccount
from app.models.integration import NotificationDelivery
from app.schemas.auth import (
    AuthError,
    AuthMagicLinkExchangeRequest,
    AuthMfaChallengeRequest,
    AuthMfaChallengeResponse,
    AuthMfaEnrollmentRequest,
    AuthMfaVerificationResponse,
    AuthMfaVerifyRequest,
    AuthPrincipal,
    AuthSessionResponse,
)
from app.schemas.auth import AuthRoleGrant as AuthRoleGrantView
from app.services.auth_rate_limit import (
    AuthLinkRateLimiter,
    AuthRateLimitUnavailable,
    get_auth_link_rate_limiter,
)

router = APIRouter(prefix="/auth")

Database = Annotated[AsyncSession, Depends(get_db)]
AuthSettings = Annotated[Settings, Depends(get_settings)]
BrowserPrincipal = Annotated[VerifiedPrincipal, Depends(require_browser_session)]
CsrfPrincipal = Annotated[VerifiedPrincipal, Depends(require_csrf)]
LinkRateLimiter = Annotated[AuthLinkRateLimiter, Depends(get_auth_link_rate_limiter)]

_AUTH_ERRORS = {
    401: {"model": AuthError},
    403: {"model": AuthError},
    429: {"model": AuthError},
}


async def _record_notification_click(
    db: AsyncSession, personal_access_link_id: UUID, clicked_at: datetime
) -> None:
    """Record the first My Event doorway click without adding a tracking token."""

    await db.execute(
        update(NotificationDelivery)
        .where(
            NotificationDelivery.personal_access_link_id == personal_access_link_id,
            NotificationDelivery.clicked_at.is_(None),
        )
        .values(clicked_at=clicked_at)
    )


def _session_response(
    verified: VerifiedPrincipal, settings: Settings
) -> AuthSessionResponse:
    session = verified.session
    if session is None:
        raise RuntimeError("browser session required")
    return AuthSessionResponse(
        session_id=session.session_id,
        state=session.state,  # type: ignore[arg-type]
        principal=verified.principal,
        csrf_token=decrypted_csrf_token(session, settings),
        idle_expires_at=session.idle_expires_at,
        absolute_expires_at=session.absolute_expires_at,
    )


def _magic_link_principal(
    session: AuthSession, grants: Sequence[AuthRoleGrantView] = ()
) -> VerifiedPrincipal:
    """Project a just-issued AAL1 session without re-entering request CSRF checks."""

    return VerifiedPrincipal(
        principal=AuthPrincipal(
            subject_type="USER",
            subject_id=session.user_id,
            tenant_id=session.tenant_id,
            event_id=session.event_id,
            role_grants=list(grants),
            authn_level="AAL1",
            amr={"magic_link"},
            authenticated_at=session.authenticated_at,
            mfa_at=None,
        ),
        session=session,
    )


async def _has_admin_grant(db: AsyncSession, user_id: UUID, event_id: UUID) -> bool:
    now = _now()
    count = await db.scalar(
        select(func.count())
        .select_from(AuthRoleGrant)
        .where(
            AuthRoleGrant.user_id == user_id,
            AuthRoleGrant.event_id == event_id,
            AuthRoleGrant.role.in_(PRIVILEGED_ADMIN_ROLES),
            AuthRoleGrant.valid_from <= now,
            or_(AuthRoleGrant.valid_until.is_(None), AuthRoleGrant.valid_until > now),
        )
    )
    return bool(count)


async def _has_mfa(db: AsyncSession, user_id: UUID) -> bool:
    count = await db.scalar(
        select(func.count())
        .select_from(MfaAuthenticator)
        .where(
            MfaAuthenticator.user_id == user_id, MfaAuthenticator.revoked_at.is_(None)
        )
    )
    return bool(count)


def _audit(
    db: AsyncSession,
    request: Request,
    *,
    session: AuthSession,
    action: str,
    resource_type: str,
    resource_id: UUID | None,
    reason_code: str,
) -> None:
    db.add(
        AuditLog(
            tenant_id=session.tenant_id,
            event_id=session.event_id,
            actor_user_id=session.user_id,
            actor_role=None,
            action_type=action,
            resource_type=resource_type,
            resource_id=resource_id,
            reason_code=reason_code,
            request_id=request.headers.get("X-Request-Id", "unknown")[:100],
        )
    )


@router.post(
    "/magic-links/exchange",
    response_model=AuthSessionResponse,
    responses={401: {"model": AuthError}},
    summary="Exchange One-Time Personal Access Link",
)
async def exchange_magic_link(
    payload: AuthMagicLinkExchangeRequest,
    request: Request,
    response: Response,
    db: Database,
    settings: AuthSettings,
    rate_limiter: LinkRateLimiter,
) -> AuthSessionResponse:
    now = _now()
    token_hmac = digest_secret(
        payload.token, purpose="personal-link", settings=settings
    )
    try:
        initial_allowed = await rate_limiter.allow_initial(request, token_hmac)
    except AuthRateLimitUnavailable:
        initial_allowed = False
    if not initial_allowed:
        raise _fail(
            request, 429, "AUTH_RATE_LIMITED", "Too many authentication attempts."
        )
    link = await db.scalar(
        select(PersonalAccessLink)
        .where(PersonalAccessLink.token_hmac == token_hmac)
        .with_for_update()
    )
    invalid = (
        link is None
        or link.consumed_at is not None
        or link.revoked_at is not None
        or now >= link.expires_at
        or (payload.event_id is not None and payload.event_id != link.event_id)
        or (payload.return_path is not None and payload.return_path != link.return_path)
    )
    if invalid:
        raise _fail(request, 401, "AUTH_LINK_INVALID", "접근 링크가 유효하지 않습니다.")
    assert link is not None
    try:
        account_allowed = await rate_limiter.allow_account(link.user_id)
    except AuthRateLimitUnavailable:
        account_allowed = False
    if not account_allowed:
        raise _fail(
            request, 429, "AUTH_RATE_LIMITED", "Too many authentication attempts."
        )
    account = await db.get(UserAccount, link.user_id)
    if (
        account is None
        or account.account_status != "ACTIVE"
        or account.deleted_at is not None
    ):
        raise _fail(request, 401, "AUTH_LINK_INVALID", "접근 링크가 유효하지 않습니다.")

    active_grants = await _active_role_grants(
        db,
        user_id=link.user_id,
        tenant_id=link.tenant_id,
        event_id=link.event_id,
        now=now,
    )
    visible_grants = visible_role_grants(active_grants, "AAL1")
    admin_grant = await _has_admin_grant(db, link.user_id, link.event_id)
    state = "AUTHENTICATED"
    if admin_grant:
        state = (
            "MFA_PENDING"
            if await _has_mfa(db, link.user_id)
            else "MFA_ENROLLMENT_REQUIRED"
        )
    raw_token, session_hmac, _csrf, csrf_hmac, csrf_enc = new_session_material(settings)
    idle_seconds = (
        settings.AUTH_SESSION_IDLE_ADMIN_SECONDS
        if admin_grant
        else settings.AUTH_SESSION_IDLE_USER_SECONDS
    )
    session = AuthSession(
        token_hmac=session_hmac,
        csrf_hmac=csrf_hmac,
        csrf_enc=csrf_enc,
        tenant_id=link.tenant_id,
        event_id=link.event_id,
        user_id=link.user_id,
        profile_id=link.profile_id,
        state=state,
        authn_level="AAL1",
        amr=["magic_link"],
        authenticated_at=now,
        idle_expires_at=now + timedelta(seconds=idle_seconds),
        absolute_expires_at=now
        + timedelta(seconds=settings.AUTH_SESSION_ABSOLUTE_SECONDS),
        last_seen_at=now,
    )
    db.add(session)
    link.consumed_at = now
    account.last_authenticated_at = now
    await _record_notification_click(db, link.personal_access_link_id, now)
    await db.flush()
    _audit(
        db,
        request,
        session=session,
        action="CREATE",
        resource_type="AUTH_SESSION",
        resource_id=session.session_id,
        reason_code="PERSONAL_LINK_EXCHANGED",
    )
    await db.commit()
    verified = _magic_link_principal(session, visible_grants)
    set_session_cookie(response, raw_token, settings)
    return _session_response(verified, settings)


@router.get(
    "/session",
    response_model=AuthSessionResponse,
    responses={401: {"model": AuthError}},
    summary="Get Verified Session Principal",
)
async def get_auth_session(
    principal: BrowserPrincipal,
    settings: AuthSettings,
) -> AuthSessionResponse:
    return _session_response(principal, settings)


@router.delete(
    "/session",
    status_code=status.HTTP_204_NO_CONTENT,
    responses=_AUTH_ERRORS,
    summary="Revoke Current Session",
)
async def delete_auth_session(
    request: Request,
    response: Response,
    principal: CsrfPrincipal,
    db: Database,
    settings: AuthSettings,
) -> None:
    assert principal.session is not None
    principal.session.revoked_at = _now()
    _audit(
        db,
        request,
        session=principal.session,
        action="DELETE",
        resource_type="AUTH_SESSION",
        resource_id=principal.session.session_id,
        reason_code="USER_LOGOUT",
    )
    await db.commit()
    response.delete_cookie(
        settings.AUTH_SESSION_COOKIE_NAME,
        path="/",
        secure=True,
        httponly=True,
        samesite="lax",
    )


async def _assert_admin_eligible(
    request: Request, db: AsyncSession, session: AuthSession
) -> None:
    if not await _has_admin_grant(db, session.user_id, session.event_id):
        raise _fail(
            request, 403, "RESOURCE_FORBIDDEN", "관리자 MFA를 등록할 권한이 없습니다."
        )


async def _active_authenticators(
    db: AsyncSession, user_id: UUID, method: str
) -> list[MfaAuthenticator]:
    return list(
        (
            await db.scalars(
                select(MfaAuthenticator).where(
                    MfaAuthenticator.user_id == user_id,
                    MfaAuthenticator.method == method,
                    MfaAuthenticator.revoked_at.is_(None),
                )
            )
        ).all()
    )


def _challenge_response(
    challenge: MfaChallenge,
    *,
    public_options: dict[str, object] | None = None,
) -> AuthMfaChallengeResponse:
    return AuthMfaChallengeResponse(
        challenge_id=challenge.challenge_id,
        purpose=challenge.purpose,  # type: ignore[arg-type]
        method=challenge.method,  # type: ignore[arg-type]
        expires_at=challenge.expires_at,
        public_options=(
            challenge.public_options if public_options is None else public_options
        ),
    )


def _totp_enrollment_material(
    *, user_id: UUID, display_name: str, settings: Settings
) -> tuple[bytes, dict[str, object], dict[str, object]]:
    """Return encrypted persistence state and one-time enrollment response state."""

    secret = pyotp.random_base32()
    persisted_options: dict[str, object] = {"display_name": display_name}
    response_options = {
        **persisted_options,
        "secret": secret,
        "otpauth_uri": pyotp.TOTP(secret).provisioning_uri(
            name=str(user_id), issuer_name=settings.AUTH_WEBAUTHN_RP_NAME
        ),
    }
    return (
        encrypt_secret(secret, purpose="totp", settings=settings),
        persisted_options,
        response_options,
    )


@router.post(
    "/mfa/enrollments",
    response_model=AuthMfaChallengeResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_AUTH_ERRORS,
    summary="Start Administrator MFA Enrollment",
)
async def start_mfa_enrollment(
    payload: AuthMfaEnrollmentRequest,
    request: Request,
    principal: CsrfPrincipal,
    db: Database,
    settings: AuthSettings,
) -> AuthMfaChallengeResponse:
    assert principal.session is not None
    session = principal.session
    await _assert_admin_eligible(request, db, session)
    now = _now()
    expires_at = now + timedelta(seconds=settings.AUTH_MFA_CHALLENGE_TTL_SECONDS)
    challenge_bytes: bytes | None = None
    secret_enc: bytes | None = None
    display_name = payload.display_name or payload.method
    if payload.method == "WEBAUTHN":
        existing = await _active_authenticators(db, session.user_id, "WEBAUTHN")
        options = generate_registration_options(
            rp_id=settings.AUTH_WEBAUTHN_RP_ID,
            rp_name=settings.AUTH_WEBAUTHN_RP_NAME,
            user_id=session.user_id.bytes,
            user_name=str(session.user_id),
            user_display_name="Meet AI administrator",
            authenticator_selection=AuthenticatorSelectionCriteria(
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.REQUIRED,
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=item.credential_id)
                for item in existing
                if item.credential_id is not None
            ],
        )
        challenge_bytes = options.challenge
        public_options = json.loads(options_to_json(options))
        public_options["display_name"] = display_name
        response_options = public_options
    else:
        secret_enc, public_options, response_options = _totp_enrollment_material(
            user_id=session.user_id,
            display_name=display_name,
            settings=settings,
        )
    challenge = MfaChallenge(
        session_id=session.session_id,
        user_id=session.user_id,
        purpose="ENROLLMENT",
        method=payload.method,
        expected_challenge=challenge_bytes,
        secret_enc=secret_enc,
        public_options=public_options,
        expires_at=expires_at,
    )
    db.add(challenge)
    await db.commit()
    return _challenge_response(challenge, public_options=response_options)


async def _rate_limit_challenges(
    request: Request, db: AsyncSession, session_id: UUID, now: datetime
) -> None:
    count = await db.scalar(
        select(func.count())
        .select_from(MfaChallenge)
        .where(
            MfaChallenge.session_id == session_id,
            MfaChallenge.created_at >= now - timedelta(minutes=5),
        )
    )
    if count is not None and count >= 5:
        raise _fail(request, 429, "AUTH_RATE_LIMITED", "인증 시도 횟수를 초과했습니다.")


@router.post(
    "/mfa/challenges",
    response_model=AuthMfaChallengeResponse,
    status_code=status.HTTP_201_CREATED,
    responses=_AUTH_ERRORS,
    summary="Start MFA or Recovery Challenge",
)
async def start_mfa_challenge(
    payload: AuthMfaChallengeRequest,
    request: Request,
    principal: CsrfPrincipal,
    db: Database,
    settings: AuthSettings,
) -> AuthMfaChallengeResponse:
    assert principal.session is not None
    session = principal.session
    await _assert_admin_eligible(request, db, session)
    now = _now()
    await _rate_limit_challenges(request, db, session.session_id, now)
    challenge_bytes: bytes | None = None
    if payload.method == "WEBAUTHN":
        authenticators = await _active_authenticators(db, session.user_id, "WEBAUTHN")
        if not authenticators:
            raise _fail(
                request, 403, "RESOURCE_FORBIDDEN", "등록된 인증 수단이 없습니다."
            )
        options = generate_authentication_options(
            rp_id=settings.AUTH_WEBAUTHN_RP_ID,
            user_verification=UserVerificationRequirement.REQUIRED,
            allow_credentials=[
                PublicKeyCredentialDescriptor(id=item.credential_id)
                for item in authenticators
                if item.credential_id is not None
            ],
        )
        challenge_bytes = options.challenge
        public_options: dict[str, object] = json.loads(options_to_json(options))
    elif payload.method == "TOTP":
        if not await _active_authenticators(db, session.user_id, "TOTP"):
            raise _fail(
                request, 403, "RESOURCE_FORBIDDEN", "등록된 인증 수단이 없습니다."
            )
        public_options = {}
    else:
        unused = await db.scalar(
            select(func.count())
            .select_from(MfaRecoveryCode)
            .where(
                MfaRecoveryCode.user_id == session.user_id,
                MfaRecoveryCode.used_at.is_(None),
            )
        )
        if not unused:
            raise _fail(
                request, 403, "RESOURCE_FORBIDDEN", "사용 가능한 복구 코드가 없습니다."
            )
        public_options = {}
    challenge = MfaChallenge(
        session_id=session.session_id,
        user_id=session.user_id,
        purpose=payload.purpose,
        method=payload.method,
        expected_challenge=challenge_bytes,
        public_options=public_options,
        expires_at=now + timedelta(seconds=settings.AUTH_MFA_CHALLENGE_TTL_SECONDS),
    )
    db.add(challenge)
    await db.commit()
    return _challenge_response(challenge)


def _proof_matches(challenge: MfaChallenge, proof: AuthMfaVerifyRequest) -> bool:
    return (
        (challenge.method == "WEBAUTHN" and proof.webauthn_response is not None)
        or (challenge.method == "TOTP" and proof.otp_code is not None)
        or (challenge.method == "RECOVERY_CODE" and proof.recovery_code is not None)
    )


async def _consume_recovery_code(
    db: AsyncSession, user_id: UUID, raw_code: str, settings: Settings, now: datetime
) -> bool:
    code_hmac = digest_secret(raw_code, purpose="recovery-code", settings=settings)
    row = await db.scalar(
        select(MfaRecoveryCode)
        .where(
            MfaRecoveryCode.user_id == user_id,
            MfaRecoveryCode.code_hmac == code_hmac,
            MfaRecoveryCode.used_at.is_(None),
        )
        .with_for_update()
    )
    if row is None:
        return False
    row.used_at = now
    return True


async def _new_recovery_codes(
    db: AsyncSession, user_id: UUID, settings: Settings
) -> list[str] | None:
    existing = await db.scalar(
        select(func.count())
        .select_from(MfaRecoveryCode)
        .where(MfaRecoveryCode.user_id == user_id)
    )
    if existing:
        return None
    raw_codes = [secrets.token_urlsafe(15) for _ in range(10)]
    db.add_all(
        [
            MfaRecoveryCode(
                user_id=user_id,
                code_hmac=digest_secret(
                    code, purpose="recovery-code", settings=settings
                ),
            )
            for code in raw_codes
        ]
    )
    return raw_codes


async def _verify_webauthn(
    db: AsyncSession,
    challenge: MfaChallenge,
    proof: dict[str, object],
    settings: Settings,
    now: datetime,
) -> bool:
    if challenge.expected_challenge is None:
        return False
    if challenge.purpose == "ENROLLMENT":
        verified = verify_registration_response(
            credential=proof,
            expected_challenge=challenge.expected_challenge,
            expected_rp_id=settings.AUTH_WEBAUTHN_RP_ID,
            expected_origin=settings.auth_webauthn_origins,
            require_user_verification=True,
        )
        if not verified.user_verified:
            return False
        db.add(
            MfaAuthenticator(
                user_id=challenge.user_id,
                method="WEBAUTHN",
                display_name=str(
                    challenge.public_options.get("display_name", "WebAuthn")
                ),
                credential_id=verified.credential_id,
                public_key=verified.credential_public_key,
                sign_count=verified.sign_count,
                transports=[],
                user_verified=True,
                verified_at=now,
                last_used_at=now,
            )
        )
        return True

    credential_id = base64url_to_bytes(str(proof.get("id") or proof.get("rawId") or ""))
    authenticator = await db.scalar(
        select(MfaAuthenticator)
        .where(
            MfaAuthenticator.user_id == challenge.user_id,
            MfaAuthenticator.credential_id == credential_id,
            MfaAuthenticator.revoked_at.is_(None),
        )
        .with_for_update()
    )
    if authenticator is None or authenticator.public_key is None:
        return False
    verified = verify_authentication_response(
        credential=proof,
        expected_challenge=challenge.expected_challenge,
        expected_rp_id=settings.AUTH_WEBAUTHN_RP_ID,
        expected_origin=settings.auth_webauthn_origins,
        credential_public_key=authenticator.public_key,
        credential_current_sign_count=authenticator.sign_count,
        require_user_verification=True,
    )
    if not verified.user_verified:
        return False
    authenticator.sign_count = verified.new_sign_count
    authenticator.last_used_at = now
    return True


async def _verify_totp(
    db: AsyncSession,
    challenge: MfaChallenge,
    otp_code: str,
    settings: Settings,
    now: datetime,
) -> bool:
    if challenge.purpose == "ENROLLMENT":
        if challenge.secret_enc is None:
            return False
        secret = decrypt_secret(
            challenge.secret_enc, purpose="totp", settings=settings
        ).decode()
        if not pyotp.TOTP(secret).verify(otp_code, valid_window=1):
            return False
        db.add(
            MfaAuthenticator(
                user_id=challenge.user_id,
                method="TOTP",
                display_name=str(challenge.public_options.get("display_name", "TOTP")),
                secret_enc=challenge.secret_enc,
                user_verified=False,
                verified_at=now,
                last_used_at=now,
            )
        )
        return True
    authenticators = await _active_authenticators(db, challenge.user_id, "TOTP")
    for authenticator in authenticators:
        if authenticator.secret_enc is None:
            continue
        secret = decrypt_secret(
            authenticator.secret_enc, purpose="totp", settings=settings
        ).decode()
        if pyotp.TOTP(secret).verify(otp_code, valid_window=1):
            authenticator.last_used_at = now
            return True
    return False


@router.post(
    "/mfa/challenges/{challenge_id}/verify",
    response_model=AuthMfaVerificationResponse,
    responses=_AUTH_ERRORS,
    summary="Verify MFA Enrollment, Step-Up, or Recovery",
)
async def verify_mfa_challenge(
    challenge_id: UUID,
    payload: AuthMfaVerifyRequest,
    request: Request,
    response: Response,
    principal: CsrfPrincipal,
    db: Database,
    settings: AuthSettings,
) -> AuthMfaVerificationResponse:
    assert principal.session is not None
    session = principal.session
    now = _now()
    challenge = await db.scalar(
        select(MfaChallenge)
        .where(
            MfaChallenge.challenge_id == challenge_id,
            MfaChallenge.session_id == session.session_id,
            MfaChallenge.user_id == session.user_id,
        )
        .with_for_update()
    )
    if (
        challenge is None
        or challenge.consumed_at is not None
        or now >= challenge.expires_at
        or challenge.attempts >= 5
        or not _proof_matches(challenge, payload)
    ):
        raise _fail(request, 401, "MFA_CHALLENGE_INVALID", "MFA 검증에 실패했습니다.")
    challenge.attempts += 1
    try:
        if challenge.method == "WEBAUTHN":
            assert payload.webauthn_response is not None
            valid = await _verify_webauthn(
                db, challenge, payload.webauthn_response, settings, now
            )
        elif challenge.method == "TOTP":
            assert payload.otp_code is not None
            valid = await _verify_totp(db, challenge, payload.otp_code, settings, now)
        else:
            assert payload.recovery_code is not None
            valid = await _consume_recovery_code(
                db, session.user_id, payload.recovery_code, settings, now
            )
    except (
        InvalidRegistrationResponse,
        InvalidAuthenticationResponse,
        ValueError,
        KeyError,
    ):
        valid = False
    if not valid:
        await db.commit()
        raise _fail(request, 401, "MFA_CHALLENGE_INVALID", "MFA 검증에 실패했습니다.")

    challenge.consumed_at = now
    recovery_codes = (
        await _new_recovery_codes(db, session.user_id, settings)
        if challenge.purpose == "ENROLLMENT"
        else None
    )
    establishes_aal2 = mfa_establishes_aal2(session.amr, challenge.method)
    raw_token, token_hmac, _csrf, csrf_hmac, csrf_enc = new_session_material(settings)
    session.token_hmac = token_hmac
    session.csrf_hmac = csrf_hmac
    session.csrf_enc = csrf_enc
    session.last_seen_at = now
    session.idle_expires_at = min(
        now + timedelta(seconds=settings.AUTH_SESSION_IDLE_ADMIN_SECONDS),
        session.absolute_expires_at,
    )
    if establishes_aal2:
        session.authn_level = "AAL2"
        session.mfa_at = now
        session.state = "AUTHENTICATED"
    else:
        session.authn_level = "AAL1"
        session.state = "MFA_PENDING"
    amr = challenge.method.lower()
    session.amr = list(dict.fromkeys([*session.amr, amr]))
    _audit(
        db,
        request,
        session=session,
        action="UPDATE",
        resource_type="MFA_CHALLENGE",
        resource_id=challenge.challenge_id,
        reason_code=("MFA_VERIFIED_AAL2" if establishes_aal2 else "MFA_VERIFIED_AAL1"),
    )
    await db.commit()
    verified = await _browser_principal(
        request, db, raw_token, settings, enforce_mutation=False
    )
    set_session_cookie(response, raw_token, settings)
    return AuthMfaVerificationResponse(
        session=_session_response(verified, settings), recovery_codes=recovery_codes
    )
