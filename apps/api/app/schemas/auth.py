"""Frozen CONTRACT-006 authentication request and response schemas."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

AuthRole = Literal["EVENT_ADMIN", "DATA_REVIEWER", "EXHIBITOR_ADMIN"]
AuthMethod = Literal[
    "magic_link", "password", "oidc", "webauthn", "totp", "recovery_code", "service_jwt"
]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AuthError(StrictModel):
    code: Literal[
        "AUTH_REQUIRED",
        "AUTH_LINK_INVALID",
        "SESSION_EXPIRED",
        "TOKEN_INVALID",
        "PRINCIPAL_CONFLICT",
        "RESOURCE_FORBIDDEN",
        "SCOPE_FORBIDDEN",
        "MFA_REQUIRED",
        "MFA_FRESHNESS_REQUIRED",
        "MFA_CHALLENGE_INVALID",
        "CSRF_FAILED",
        "AUTH_RATE_LIMITED",
    ]
    message: Annotated[str, Field(max_length=300)]
    request_id: Annotated[str, Field(max_length=100)]


class AuthMagicLinkExchangeRequest(StrictModel):
    token: Annotated[str, Field(min_length=22, max_length=2048)]
    event_id: UUID | None = None
    return_path: Annotated[str, Field(pattern=r"^/[^/].*$", max_length=500)] | None = (
        None
    )


class AuthRoleGrant(StrictModel):
    role: AuthRole
    tenant_id: UUID
    event_id: UUID | None
    exhibitor_id: UUID | None


class AuthPrincipal(StrictModel):
    subject_type: Literal["USER", "SERVICE"]
    subject_id: UUID
    tenant_id: UUID
    event_id: UUID | None
    role_grants: Annotated[list[AuthRoleGrant], Field(max_length=50)]
    authn_level: Literal["AAL1", "AAL2"]
    amr: set[AuthMethod]
    authenticated_at: datetime
    mfa_at: datetime | None


class AuthSessionResponse(StrictModel):
    session_id: UUID
    state: Literal["AUTHENTICATED", "MFA_PENDING", "MFA_ENROLLMENT_REQUIRED"]
    principal: AuthPrincipal
    csrf_token: Annotated[str, Field(min_length=32, max_length=512)]
    idle_expires_at: datetime
    absolute_expires_at: datetime


class AuthMfaEnrollmentRequest(StrictModel):
    method: Literal["WEBAUTHN", "TOTP"]
    display_name: Annotated[str, Field(min_length=1, max_length=80)] | None = None


class AuthMfaChallengeRequest(StrictModel):
    purpose: Literal["LOGIN", "STEP_UP", "RECOVERY"]
    method: Literal["WEBAUTHN", "TOTP", "RECOVERY_CODE"]


class AuthMfaChallengeResponse(StrictModel):
    challenge_id: UUID
    purpose: Literal["ENROLLMENT", "LOGIN", "STEP_UP", "RECOVERY"]
    method: Literal["WEBAUTHN", "TOTP", "RECOVERY_CODE"]
    expires_at: datetime
    public_options: dict[str, object]


class AuthMfaVerifyRequest(StrictModel):
    otp_code: Annotated[str, Field(pattern=r"^[0-9]{6,10}$")] | None = None
    recovery_code: Annotated[str, Field(min_length=12, max_length=128)] | None = None
    webauthn_response: dict[str, object] | None = None

    @model_validator(mode="after")
    def exactly_one_proof(self) -> AuthMfaVerifyRequest:
        supplied = sum(
            value is not None
            for value in (self.otp_code, self.recovery_code, self.webauthn_response)
        )
        if supplied != 1:
            raise ValueError("exactly one MFA proof is required")
        return self


class AuthMfaVerificationResponse(StrictModel):
    session: AuthSessionResponse
    recovery_codes: Annotated[list[str], Field(min_length=10, max_length=10)] | None
