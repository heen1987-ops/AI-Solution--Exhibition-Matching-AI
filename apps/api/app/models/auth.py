"""Server-managed browser authentication and administrator MFA persistence."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_EXHIBITION, SCHEMA_IDENTITY, SCHEMA_PROFILE, Base
from app.models.common import new_uuid7


class PersonalAccessLink(Base):
    """Opaque, single-use link. Only its keyed digest is persisted."""

    __tablename__ = "personal_access_link"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_personal_access_link_event_boundary",
        ),
        Index("ix_personal_access_link_expiry", "expires_at"),
        {"schema": SCHEMA_IDENTITY},
    )

    personal_access_link_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    token_hmac: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_profile.profile_id"),
        nullable=True,
    )
    recommendation_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matching.recommendation_session.recommendation_session_id"),
        nullable=True,
    )
    return_path: Mapped[str] = mapped_column(String(500), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuthRoleGrant(Base):
    """Explicit event-scoped application role used by the verified principal."""

    __tablename__ = "auth_role_grant"
    __table_args__ = (
        CheckConstraint(
            "role IN ('EVENT_ADMIN', 'DATA_REVIEWER', 'EXHIBITOR_ADMIN')",
            name="auth_role_grant_role_allowed",
        ),
        CheckConstraint(
            "(role IN ('EVENT_ADMIN', 'DATA_REVIEWER') AND event_id IS NOT NULL "
            "AND exhibitor_id IS NULL) OR (role = 'EXHIBITOR_ADMIN' "
            "AND event_id IS NOT NULL AND exhibitor_id IS NOT NULL)",
            name="auth_role_grant_scope_consistent",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_auth_role_grant_event_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            [
                f"{SCHEMA_EXHIBITION}.exhibitor.tenant_id",
                f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id",
            ],
            name="fk_auth_role_grant_exhibitor_boundary",
        ),
        Index(
            "uq_auth_role_grant_active",
            "tenant_id",
            "event_id",
            "user_id",
            "role",
            "exhibitor_id",
            unique=True,
            postgresql_where=text("valid_until IS NULL"),
            postgresql_nulls_not_distinct=True,
        ),
        Index("ix_auth_role_grant_user", "user_id", "event_id"),
        {"schema": SCHEMA_PROFILE},
    )

    auth_role_grant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(30), nullable=False)
    exhibitor_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    granted_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True))
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class AuthSession(Base):
    """Revocable browser session whose raw credential exists only in the cookie."""

    __tablename__ = "auth_session"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_auth_session_event_boundary",
        ),
        CheckConstraint(
            "state IN ('AUTHENTICATED', 'MFA_PENDING', 'MFA_ENROLLMENT_REQUIRED')",
            name="auth_session_state_allowed",
        ),
        CheckConstraint("authn_level IN ('AAL1', 'AAL2')", name="authn_level_allowed"),
        Index("ix_auth_session_user_active", "user_id", "revoked_at"),
        Index("ix_auth_session_expiry", "idle_expires_at", "absolute_expires_at"),
        {"schema": SCHEMA_IDENTITY},
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    token_hmac: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    csrf_hmac: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    csrf_enc: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA_PROFILE}.user_profile.profile_id")
    )
    state: Mapped[str] = mapped_column(String(30), nullable=False)
    authn_level: Mapped[str] = mapped_column(String(10), nullable=False)
    amr: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    authenticated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    mfa_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    idle_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    absolute_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MfaAuthenticator(Base):
    """Verified WebAuthn or TOTP authenticator; sensitive material is encrypted."""

    __tablename__ = "mfa_authenticator"
    __table_args__ = (
        CheckConstraint("method IN ('WEBAUTHN', 'TOTP')", name="mfa_method_allowed"),
        CheckConstraint(
            "(method = 'WEBAUTHN' AND credential_id IS NOT NULL AND public_key IS NOT NULL "
            "AND secret_enc IS NULL) OR (method = 'TOTP' AND secret_enc IS NOT NULL "
            "AND credential_id IS NULL AND public_key IS NULL)",
            name="mfa_authenticator_material_consistent",
        ),
        Index(
            "uq_mfa_authenticator_credential_active",
            "credential_id",
            unique=True,
            postgresql_where=text("credential_id IS NOT NULL AND revoked_at IS NULL"),
        ),
        Index("ix_mfa_authenticator_user_active", "user_id", "revoked_at"),
        {"schema": SCHEMA_IDENTITY},
    )

    authenticator_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
    )
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(80))
    credential_id: Mapped[bytes | None] = mapped_column(LargeBinary)
    public_key: Mapped[bytes | None] = mapped_column(LargeBinary)
    sign_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    transports: Mapped[list[str] | None] = mapped_column(JSONB)
    user_verified: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    verified_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MfaChallenge(Base):
    """Short-lived, session- and purpose-bound ceremony state."""

    __tablename__ = "mfa_challenge"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('ENROLLMENT', 'LOGIN', 'STEP_UP', 'RECOVERY')",
            name="mfa_challenge_purpose_allowed",
        ),
        CheckConstraint(
            "method IN ('WEBAUTHN', 'TOTP', 'RECOVERY_CODE')",
            name="mfa_challenge_method_allowed",
        ),
        Index("ix_mfa_challenge_session_expiry", "session_id", "expires_at"),
        {"schema": SCHEMA_IDENTITY},
    )

    challenge_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_IDENTITY}.auth_session.session_id"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
    )
    purpose: Mapped[str] = mapped_column(String(20), nullable=False)
    method: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_challenge: Mapped[bytes | None] = mapped_column(LargeBinary)
    secret_enc: Mapped[bytes | None] = mapped_column(LargeBinary)
    public_options: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MfaRecoveryCode(Base):
    """Single-use recovery code represented only by a keyed digest."""

    __tablename__ = "mfa_recovery_code"
    __table_args__ = (
        UniqueConstraint("user_id", "code_hmac", name="uq_mfa_recovery_code_digest"),
        Index("ix_mfa_recovery_code_user_unused", "user_id", "used_at"),
        {"schema": SCHEMA_IDENTITY},
    )

    recovery_code_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
    )
    code_hmac: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
