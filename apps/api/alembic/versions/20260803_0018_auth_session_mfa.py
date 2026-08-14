"""add opaque personal links, server sessions, scoped RBAC, and MFA

Revision ID: 0018_auth_session_mfa
Revises: 0017_object_embedding
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_auth_session_mfa"
down_revision: str | None = "0017_object_embedding"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "auth_role_grant",
        _uuid("auth_role_grant_id"),
        _uuid("tenant_id"),
        _uuid("event_id"),
        _uuid("user_id"),
        sa.Column("role", sa.String(30), nullable=False),
        _uuid("exhibitor_id", nullable=True),
        _uuid("granted_by", nullable=True),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("auth_role_grant_id"),
        sa.ForeignKeyConstraint(["user_id"], ["profile.user_account.user_id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_auth_role_grant_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            ["exhibition.exhibitor.tenant_id", "exhibition.exhibitor.exhibitor_id"],
            name="fk_auth_role_grant_exhibitor_boundary",
        ),
        sa.CheckConstraint(
            "role IN ('EVENT_ADMIN', 'DATA_REVIEWER', 'EXHIBITOR_ADMIN')",
            name="auth_role_grant_role_allowed",
        ),
        sa.CheckConstraint(
            "(role IN ('EVENT_ADMIN', 'DATA_REVIEWER') AND event_id IS NOT NULL "
            "AND exhibitor_id IS NULL) OR (role = 'EXHIBITOR_ADMIN' "
            "AND event_id IS NOT NULL AND exhibitor_id IS NOT NULL)",
            name="auth_role_grant_scope_consistent",
        ),
        schema="profile",
    )
    op.create_index(
        "uq_auth_role_grant_active",
        "auth_role_grant",
        ["tenant_id", "event_id", "user_id", "role", "exhibitor_id"],
        unique=True,
        schema="profile",
        postgresql_where=sa.text("valid_until IS NULL"),
        postgresql_nulls_not_distinct=True,
    )
    op.create_index(
        "ix_auth_role_grant_user",
        "auth_role_grant",
        ["user_id", "event_id"],
        schema="profile",
    )
    op.execute(
        """
        INSERT INTO profile.auth_role_grant (
            auth_role_grant_id,
            tenant_id,
            event_id,
            user_id,
            role,
            exhibitor_id,
            granted_by,
            valid_from,
            valid_until,
            created_at
        )
        SELECT
            ur.user_role_id,
            ur.tenant_id,
            ur.event_id,
            ur.user_id,
            CASE
                WHEN r.role_code = 'OPERATOR' THEN 'EVENT_ADMIN'
                WHEN r.role_code = 'EXHIBITOR' THEN 'EXHIBITOR_ADMIN'
            END,
            ur.exhibitor_id,
            ur.granted_by,
            ur.valid_from,
            ur.valid_until,
            ur.created_at
        FROM profile.user_role AS ur
        JOIN profile.role AS r ON r.role_id = ur.role_id
        WHERE ur.valid_until IS NULL
          AND (
              (r.role_code = 'OPERATOR' AND ur.event_id IS NOT NULL
                  AND ur.exhibitor_id IS NULL)
              OR
              (r.role_code = 'EXHIBITOR' AND ur.event_id IS NOT NULL
                  AND ur.exhibitor_id IS NOT NULL)
          )
        """
    )

    op.create_table(
        "personal_access_link",
        _uuid("personal_access_link_id"),
        sa.Column("token_hmac", sa.LargeBinary(), nullable=False),
        _uuid("tenant_id"),
        _uuid("event_id"),
        _uuid("user_id"),
        _uuid("profile_id", nullable=True),
        _uuid("recommendation_session_id", nullable=True),
        sa.Column("return_path", sa.String(500), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("personal_access_link_id"),
        sa.UniqueConstraint("token_hmac"),
        sa.ForeignKeyConstraint(["user_id"], ["profile.user_account.user_id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.user_profile.profile_id"]),
        sa.ForeignKeyConstraint(
            ["recommendation_session_id"],
            ["matching.recommendation_session.recommendation_session_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_personal_access_link_event_boundary",
        ),
        schema="identity",
    )
    op.create_index(
        "ix_personal_access_link_expiry",
        "personal_access_link",
        ["expires_at"],
        schema="identity",
    )

    op.create_table(
        "auth_session",
        _uuid("session_id"),
        sa.Column("token_hmac", sa.LargeBinary(), nullable=False),
        sa.Column("csrf_hmac", sa.LargeBinary(), nullable=False),
        sa.Column("csrf_enc", sa.LargeBinary(), nullable=False),
        _uuid("tenant_id"),
        _uuid("event_id"),
        _uuid("user_id"),
        _uuid("profile_id", nullable=True),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("authn_level", sa.String(10), nullable=False),
        sa.Column("amr", postgresql.JSONB(), nullable=False),
        sa.Column("authenticated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("mfa_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("idle_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("absolute_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("session_id"),
        sa.UniqueConstraint("token_hmac"),
        sa.ForeignKeyConstraint(["user_id"], ["profile.user_account.user_id"]),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.user_profile.profile_id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_auth_session_event_boundary",
        ),
        sa.CheckConstraint(
            "state IN ('AUTHENTICATED', 'MFA_PENDING', 'MFA_ENROLLMENT_REQUIRED')",
            name="auth_session_state_allowed",
        ),
        sa.CheckConstraint(
            "authn_level IN ('AAL1', 'AAL2')", name="authn_level_allowed"
        ),
        schema="identity",
    )
    op.create_index(
        "ix_auth_session_user_active",
        "auth_session",
        ["user_id", "revoked_at"],
        schema="identity",
    )
    op.create_index(
        "ix_auth_session_expiry",
        "auth_session",
        ["idle_expires_at", "absolute_expires_at"],
        schema="identity",
    )

    op.create_table(
        "mfa_authenticator",
        _uuid("authenticator_id"),
        _uuid("user_id"),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("display_name", sa.String(80), nullable=True),
        sa.Column("credential_id", sa.LargeBinary(), nullable=True),
        sa.Column("public_key", sa.LargeBinary(), nullable=True),
        sa.Column("sign_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("transports", postgresql.JSONB(), nullable=True),
        sa.Column(
            "user_verified", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("secret_enc", sa.LargeBinary(), nullable=True),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("authenticator_id"),
        sa.ForeignKeyConstraint(["user_id"], ["profile.user_account.user_id"]),
        sa.CheckConstraint("method IN ('WEBAUTHN', 'TOTP')", name="mfa_method_allowed"),
        sa.CheckConstraint(
            "(method = 'WEBAUTHN' AND credential_id IS NOT NULL AND public_key IS NOT NULL "
            "AND secret_enc IS NULL) OR (method = 'TOTP' AND secret_enc IS NOT NULL "
            "AND credential_id IS NULL AND public_key IS NULL)",
            name="mfa_authenticator_material_consistent",
        ),
        schema="identity",
    )
    op.create_index(
        "uq_mfa_authenticator_credential_active",
        "mfa_authenticator",
        ["credential_id"],
        unique=True,
        schema="identity",
        postgresql_where=sa.text("credential_id IS NOT NULL AND revoked_at IS NULL"),
    )
    op.create_index(
        "ix_mfa_authenticator_user_active",
        "mfa_authenticator",
        ["user_id", "revoked_at"],
        schema="identity",
    )

    op.create_table(
        "mfa_challenge",
        _uuid("challenge_id"),
        _uuid("session_id"),
        _uuid("user_id"),
        sa.Column("purpose", sa.String(20), nullable=False),
        sa.Column("method", sa.String(20), nullable=False),
        sa.Column("expected_challenge", sa.LargeBinary(), nullable=True),
        sa.Column("secret_enc", sa.LargeBinary(), nullable=True),
        sa.Column("public_options", postgresql.JSONB(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("challenge_id"),
        sa.ForeignKeyConstraint(["session_id"], ["identity.auth_session.session_id"]),
        sa.ForeignKeyConstraint(["user_id"], ["profile.user_account.user_id"]),
        sa.CheckConstraint(
            "purpose IN ('ENROLLMENT', 'LOGIN', 'STEP_UP', 'RECOVERY')",
            name="mfa_challenge_purpose_allowed",
        ),
        sa.CheckConstraint(
            "method IN ('WEBAUTHN', 'TOTP', 'RECOVERY_CODE')",
            name="mfa_challenge_method_allowed",
        ),
        schema="identity",
    )
    op.create_index(
        "ix_mfa_challenge_session_expiry",
        "mfa_challenge",
        ["session_id", "expires_at"],
        schema="identity",
    )

    op.create_table(
        "mfa_recovery_code",
        _uuid("recovery_code_id"),
        _uuid("user_id"),
        sa.Column("code_hmac", sa.LargeBinary(), nullable=False),
        sa.Column("used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("recovery_code_id"),
        sa.ForeignKeyConstraint(["user_id"], ["profile.user_account.user_id"]),
        sa.UniqueConstraint("user_id", "code_hmac", name="uq_mfa_recovery_code_digest"),
        schema="identity",
    )
    op.create_index(
        "ix_mfa_recovery_code_user_unused",
        "mfa_recovery_code",
        ["user_id", "used_at"],
        schema="identity",
    )


def downgrade() -> None:
    op.drop_table("mfa_recovery_code", schema="identity")
    op.drop_table("mfa_challenge", schema="identity")
    op.drop_table("mfa_authenticator", schema="identity")
    op.drop_table("auth_session", schema="identity")
    op.drop_table("personal_access_link", schema="identity")
    op.drop_table("auth_role_grant", schema="profile")
