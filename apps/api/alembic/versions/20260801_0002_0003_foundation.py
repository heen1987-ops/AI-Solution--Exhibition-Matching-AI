"""create tenant, event, identity, consent, privacy, and audit foundations

Revision ID: 0003_foundation
Revises: 0002_ontology
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_foundation"
down_revision: str | None = "0002_ontology"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid(name: str, *, nullable: bool = False, primary_key: bool = False) -> sa.Column:
    return sa.Column(
        name,
        postgresql.UUID(as_uuid=True),
        nullable=nullable if not primary_key else False,
        primary_key=primary_key,
    )


def _created_at() -> sa.Column:
    return sa.Column(
        "created_at",
        sa.DateTime(timezone=True),
        nullable=False,
        server_default=sa.text("now()"),
    )


def upgrade() -> None:
    # Supports a lossless API code cache beside the canonical concept UUID.
    op.create_unique_constraint(
        "uq_ontology_concept_id_code",
        "concept",
        ["concept_id", "concept_code"],
        schema="ontology",
    )

    op.create_table(
        "tenant",
        _uuid("tenant_id", primary_key=True),
        sa.Column("tenant_code", sa.String(50), nullable=False),
        sa.Column("tenant_name", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        _created_at(),
        sa.UniqueConstraint("tenant_code", name="uq_tenant_tenant_code"),
        sa.CheckConstraint("status IN ('ACTIVE', 'SUSPENDED')", name="status_allowed"),
        schema="core",
    )

    op.create_table(
        "event",
        _uuid("event_id", primary_key=True),
        _uuid("tenant_id"),
        sa.Column("event_code", sa.String(50), nullable=False),
        sa.Column("event_name", sa.String(200), nullable=False),
        sa.Column("venue_name", sa.String(200), nullable=True),
        sa.Column(
            "timezone", sa.String(50), nullable=False, server_default="Asia/Seoul"
        ),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column(
            "event_status", sa.String(20), nullable=False, server_default="PREPARING"
        ),
        _uuid("current_taxonomy_version_id", nullable=True),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenant.tenant_id"], name="fk_event_tenant_id_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["current_taxonomy_version_id"],
            ["ontology.taxonomy_version.taxonomy_version_id"],
            name="fk_event_current_taxonomy_version_id_taxonomy_version",
        ),
        sa.UniqueConstraint("tenant_id", "event_code", name="uq_event_tenant_code"),
        sa.UniqueConstraint(
            "tenant_id", "event_id", name="uq_event_tenant_id_event_id"
        ),
        sa.CheckConstraint("start_date <= end_date", name="start_date_before_end_date"),
        sa.CheckConstraint(
            "event_status IN ('PREPARING', 'OPEN', 'CLOSED')",
            name="event_status_allowed",
        ),
        schema="exhibition",
    )

    op.create_table(
        "event_day",
        _uuid("event_day_id", primary_key=True),
        _uuid("tenant_id"),
        _uuid("event_id"),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("open_at", sa.Time(timezone=True), nullable=True),
        sa.Column("close_at", sa.Time(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PLANNED"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_event_day_event_boundary",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("event_id", "event_date", name="uq_event_day_event_date"),
        sa.CheckConstraint(
            "status IN ('PLANNED', 'OPEN', 'CLOSED')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "open_at IS NULL OR close_at IS NULL OR open_at < close_at",
            name="operating_hours_order",
        ),
        schema="exhibition",
    )

    op.create_table(
        "event_zone",
        _uuid("event_zone_id", primary_key=True),
        _uuid("tenant_id"),
        _uuid("event_id"),
        sa.Column("zone_code", sa.String(50), nullable=False),
        sa.Column("zone_name", sa.String(200), nullable=False),
        sa.Column("floor_label", sa.String(50), nullable=True),
        sa.Column("coordinate_x", sa.Numeric(10, 3), nullable=True),
        sa.Column("coordinate_y", sa.Numeric(10, 3), nullable=True),
        _uuid("parent_zone_id", nullable=True),
        sa.Column("zone_type", sa.String(50), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_event_zone_event_boundary",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "parent_zone_id"],
            [
                "exhibition.event_zone.tenant_id",
                "exhibition.event_zone.event_id",
                "exhibition.event_zone.event_zone_id",
            ],
            name="fk_event_zone_parent_same_event",
        ),
        sa.UniqueConstraint(
            "tenant_id", "event_id", "zone_code", name="uq_event_zone_code"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "event_zone_id",
            name="uq_event_zone_boundary_id",
        ),
        schema="exhibition",
    )

    op.create_table(
        "user_account",
        _uuid("user_id", primary_key=True),
        sa.Column("authentication_state", sa.String(30), nullable=False),
        sa.Column(
            "account_status", sa.String(20), nullable=False, server_default="ACTIVE"
        ),
        sa.Column(
            "default_language", sa.String(10), nullable=False, server_default="ko-KR"
        ),
        sa.Column(
            "timezone", sa.String(50), nullable=False, server_default="Asia/Seoul"
        ),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "authentication_state IN ('PHONE_VERIFIED', 'ACCOUNT_AUTHENTICATED')",
            name="authentication_state_allowed",
        ),
        sa.CheckConstraint(
            "account_status IN ('ACTIVE', 'SUSPENDED', 'WITHDRAWN')",
            name="account_status_allowed",
        ),
        schema="profile",
    )

    op.create_table(
        "user_identity",
        _uuid("identity_id", primary_key=True),
        _uuid("user_id"),
        sa.Column("name_enc", sa.LargeBinary(), nullable=True),
        sa.Column("phone_enc", sa.LargeBinary(), nullable=True),
        sa.Column("phone_hmac", sa.LargeBinary(), nullable=True),
        sa.Column("email_enc", sa.LargeBinary(), nullable=True),
        sa.Column("email_hmac", sa.LargeBinary(), nullable=True),
        sa.Column("phone_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("email_verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retention_expires_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["profile.user_account.user_id"],
            name="fk_user_identity_user_id_user_account",
        ),
        sa.UniqueConstraint("user_id", name="uq_user_identity_user_id"),
        schema="identity",
    )
    op.create_index(
        "uq_user_identity_phone_hmac",
        "user_identity",
        ["phone_hmac"],
        unique=True,
        schema="identity",
        postgresql_where=sa.text("phone_hmac IS NOT NULL"),
    )
    op.create_index(
        "ix_user_identity_retention_expires_at",
        "user_identity",
        ["retention_expires_at"],
        schema="identity",
    )

    op.create_table(
        "authentication_method",
        _uuid("authentication_method_id", primary_key=True),
        _uuid("user_id"),
        sa.Column("method_type", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(100), nullable=True),
        sa.Column("provider_subject_hmac", sa.LargeBinary(), nullable=True),
        sa.Column("last_authenticated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["profile.user_account.user_id"],
            name="fk_authentication_method_user_id_user_account",
        ),
        sa.CheckConstraint(
            "method_type IN ('PHONE_OTP', 'EMAIL', 'SOCIAL')",
            name="method_type_allowed",
        ),
        schema="identity",
    )
    op.create_index(
        "ix_authentication_method_user_id",
        "authentication_method",
        ["user_id"],
        schema="identity",
    )

    op.create_table(
        "role",
        _uuid("role_id", primary_key=True),
        sa.Column("role_code", sa.String(30), nullable=False),
        sa.Column("role_name", sa.String(100), nullable=True),
        _created_at(),
        sa.UniqueConstraint("role_code", name="uq_role_role_code"),
        sa.CheckConstraint(
            "role_code IN ('VISITOR', 'BUYER', 'EXHIBITOR', 'OPERATOR', 'ADMIN')",
            name="role_code_allowed",
        ),
        schema="profile",
    )

    op.create_table(
        "user_role",
        _uuid("user_role_id", primary_key=True),
        _uuid("tenant_id"),
        _uuid("event_id", nullable=True),
        _uuid("user_id"),
        _uuid("role_id"),
        _uuid("exhibitor_id", nullable=True),
        sa.Column(
            "valid_from",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        _uuid("granted_by", nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_user_role_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenant.tenant_id"], name="fk_user_role_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["profile.user_account.user_id"],
            name="fk_user_role_user_id_user_account",
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["profile.role.role_id"], name="fk_user_role_role_id_role"
        ),
        schema="profile",
    )
    op.create_index(
        "uq_user_role_active_assignment",
        "user_role",
        ["tenant_id", "event_id", "user_id", "role_id", "exhibitor_id"],
        unique=True,
        schema="profile",
        postgresql_where=sa.text("valid_until IS NULL"),
        postgresql_nulls_not_distinct=True,
    )

    op.create_table(
        "guest_session",
        _uuid("guest_session_id", primary_key=True),
        _uuid("tenant_id"),
        _uuid("event_id"),
        sa.Column("session_token_hmac", sa.LargeBinary(), nullable=False),
        sa.Column("entry_channel", sa.String(20), nullable=False),
        sa.Column("entry_code", sa.String(100), nullable=True),
        sa.Column("device_type", sa.String(30), nullable=True),
        sa.Column("language", sa.String(10), nullable=True, server_default="ko-KR"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        _uuid("converted_user_id", nullable=True),
        sa.Column("converted_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_guest_session_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["converted_user_id"],
            ["profile.user_account.user_id"],
            name="fk_guest_session_converted_user_id_user_account",
        ),
        sa.UniqueConstraint(
            "session_token_hmac", name="uq_guest_session_session_token_hmac"
        ),
        sa.CheckConstraint(
            "entry_channel IN ('QR', 'WEB', 'KIOSK')",
            name="entry_channel_allowed",
        ),
        schema="profile",
    )

    _create_consent_and_privacy_tables()


def _create_consent_and_privacy_tables() -> None:
    op.create_table(
        "consent_policy",
        _uuid("consent_policy_id", primary_key=True),
        _uuid("tenant_id"),
        _uuid("event_id", nullable=True),
        sa.Column("purpose", sa.String(50), nullable=False),
        sa.Column("document_version", sa.String(50), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("required_for", sa.String(50), nullable=True),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("content_hash", sa.LargeBinary(), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenant.tenant_id"], name="fk_consent_policy_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_consent_policy_event_boundary",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "purpose",
            "document_version",
            name="uq_consent_policy_tenant_event_purpose_version",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint(
            "effective_until IS NULL OR effective_from <= effective_until",
            name="effective_period_order",
        ),
        schema="profile",
    )

    op.create_table(
        "user_consent",
        _uuid("consent_id", primary_key=True),
        _uuid("tenant_id"),
        _uuid("event_id", nullable=True),
        _uuid("user_id", nullable=True),
        _uuid("guest_session_id", nullable=True),
        _uuid("consent_policy_id"),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("source_channel", sa.String(20), nullable=True),
        sa.Column("ip_hmac", sa.LargeBinary(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenant.tenant_id"], name="fk_user_consent_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_user_consent_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["profile.user_account.user_id"], name="fk_user_consent_user"
        ),
        sa.ForeignKeyConstraint(
            ["guest_session_id"],
            ["profile.guest_session.guest_session_id"],
            name="fk_user_consent_guest",
        ),
        sa.ForeignKeyConstraint(
            ["consent_policy_id"],
            ["profile.consent_policy.consent_policy_id"],
            name="fk_user_consent_policy",
        ),
        sa.CheckConstraint(
            "num_nonnulls(user_id, guest_session_id) = 1",
            name="exactly_one_owner",
        ),
        sa.CheckConstraint(
            "source_channel IS NULL OR source_channel IN ('WEB', 'QR', 'KIOSK')",
            name="source_channel_allowed",
        ),
        schema="profile",
    )
    op.create_index(
        "ix_user_consent_policy_id",
        "user_consent",
        ["consent_policy_id"],
        schema="profile",
    )

    op.create_table(
        "privacy_request",
        _uuid("privacy_request_id", primary_key=True),
        _uuid("tenant_id"),
        _uuid("user_id"),
        sa.Column("request_type", sa.String(30), nullable=False),
        sa.Column("scope_json", postgresql.JSONB(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="RECEIVED"),
        sa.Column("rejection_reason_code", sa.String(50), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenant.tenant_id"], name="fk_privacy_request_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["profile.user_account.user_id"],
            name="fk_privacy_request_user",
        ),
        sa.CheckConstraint(
            "request_type IN ('ACCESS', 'EXPORT', 'CORRECT', 'DELETE', 'WITHDRAW')",
            name="request_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('RECEIVED', 'VERIFYING', 'PROCESSING', 'COMPLETED', 'REJECTED')",
            name="status_allowed",
        ),
        schema="privacy",
    )

    op.create_table(
        "retention_policy",
        _uuid("retention_policy_id", primary_key=True),
        _uuid("tenant_id"),
        sa.Column("data_category", sa.String(100), nullable=False),
        sa.Column("purpose", sa.String(100), nullable=False),
        sa.Column("start_point_code", sa.String(50), nullable=False),
        sa.Column("retention_period_days", sa.Integer(), nullable=False),
        sa.Column("disposal_method", sa.String(50), nullable=False),
        sa.Column("legal_hold_exception", sa.Text(), nullable=True),
        sa.Column("policy_version", sa.String(50), nullable=False),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenant.tenant_id"], name="fk_retention_policy_tenant"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "data_category",
            "purpose",
            "policy_version",
            name="uq_retention_policy_tenant_category_purpose_version",
        ),
        sa.CheckConstraint(
            "retention_period_days >= 0",
            name="retention_period_days_nonneg",
        ),
        schema="privacy",
    )

    op.create_table(
        "deletion_job",
        _uuid("deletion_job_id", primary_key=True),
        _uuid("tenant_id"),
        _uuid("privacy_request_id", nullable=True),
        _uuid("retention_policy_id", nullable=True),
        sa.Column("target_table", sa.String(200), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("anonymization_result", postgresql.JSONB(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        _created_at(),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenant.tenant_id"], name="fk_deletion_job_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["privacy_request_id"],
            ["privacy.privacy_request.privacy_request_id"],
            name="fk_deletion_job_privacy_request",
        ),
        sa.ForeignKeyConstraint(
            ["retention_policy_id"],
            ["privacy.retention_policy.retention_policy_id"],
            name="fk_deletion_job_retention_policy",
        ),
        sa.CheckConstraint(
            "num_nonnulls(privacy_request_id, retention_policy_id) >= 1",
            name="at_least_one_cause",
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED')",
            name="status_allowed",
        ),
        sa.CheckConstraint("retry_count >= 0", name="retry_count_nonneg"),
        schema="privacy",
    )

    op.create_table(
        "audit_log",
        _uuid("audit_log_id", primary_key=True),
        _uuid("tenant_id", nullable=True),
        _uuid("event_id", nullable=True),
        _uuid("actor_user_id", nullable=True),
        sa.Column("actor_role", sa.String(30), nullable=True),
        sa.Column("action_type", sa.String(20), nullable=False),
        sa.Column("resource_type", sa.String(100), nullable=False),
        _uuid("resource_id", nullable=True),
        sa.Column("before_hash", sa.LargeBinary(), nullable=True),
        sa.Column("after_hash", sa.LargeBinary(), nullable=True),
        sa.Column("reason_code", sa.String(50), nullable=True),
        sa.Column("request_id", sa.String(100), nullable=True),
        sa.Column("ip_hmac", sa.LargeBinary(), nullable=True),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenant.tenant_id"], name="fk_audit_log_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_audit_log_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["actor_user_id"],
            ["profile.user_account.user_id"],
            name="fk_audit_log_actor_user",
        ),
        sa.CheckConstraint(
            "action_type IN ('VIEW', 'CREATE', 'UPDATE', 'DELETE', 'EXPORT', 'APPROVE')",
            name="action_type_allowed",
        ),
        sa.CheckConstraint(
            "actor_role IS NULL OR actor_role IN "
            "('VISITOR', 'BUYER', 'EXHIBITOR', 'OPERATOR', 'ADMIN')",
            name="actor_role_allowed",
        ),
        schema="audit",
    )
    op.create_index(
        "ix_audit_log_tenant_event_occurred_at",
        "audit_log",
        ["tenant_id", "event_id", "occurred_at"],
        schema="audit",
    )
    op.create_index(
        "ix_audit_log_resource",
        "audit_log",
        ["resource_type", "resource_id"],
        schema="audit",
    )


def downgrade() -> None:
    for schema, table in (
        ("audit", "audit_log"),
        ("privacy", "deletion_job"),
        ("privacy", "retention_policy"),
        ("privacy", "privacy_request"),
        ("profile", "user_consent"),
        ("profile", "consent_policy"),
        ("profile", "guest_session"),
        ("profile", "user_role"),
        ("profile", "role"),
        ("identity", "authentication_method"),
        ("identity", "user_identity"),
        ("profile", "user_account"),
        ("exhibition", "event_zone"),
        ("exhibition", "event_day"),
        ("exhibition", "event"),
        ("core", "tenant"),
    ):
        op.drop_table(table, schema=schema)
    op.drop_constraint(
        "uq_ontology_concept_id_code", "concept", schema="ontology", type_="unique"
    )
