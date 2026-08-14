"""add informational notification delivery and transactional outbox

Revision ID: 0019_notification_outbox
Revises: 0018_auth_session_mfa
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0019_notification_outbox"
down_revision: str | None = "0018_auth_session_mfa"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _uuid(name: str, *, nullable: bool = False) -> sa.Column:
    return sa.Column(name, postgresql.UUID(as_uuid=True), nullable=nullable)


def upgrade() -> None:
    op.create_table(
        "notification_delivery",
        _uuid("notification_delivery_id"),
        _uuid("tenant_id"),
        _uuid("event_id"),
        _uuid("user_id"),
        _uuid("recommendation_session_id", nullable=True),
        _uuid("personal_access_link_id"),
        sa.Column("notification_type", sa.String(40), nullable=False),
        sa.Column(
            "message_class",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'INFORMATIONAL'"),
        ),
        sa.Column("template_code", sa.String(100), nullable=False),
        sa.Column(
            "template_parameters",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("access_url_enc", sa.LargeBinary(), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'QUEUED'"),
        ),
        sa.Column(
            "queued_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("clicked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("notification_delivery_id"),
        sa.ForeignKeyConstraint(["user_id"], ["profile.user_account.user_id"]),
        sa.ForeignKeyConstraint(
            ["recommendation_session_id"],
            ["matching.recommendation_session.recommendation_session_id"],
        ),
        sa.ForeignKeyConstraint(
            ["personal_access_link_id"],
            ["identity.personal_access_link.personal_access_link_id"],
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_notification_delivery_event_boundary",
        ),
        sa.UniqueConstraint(
            "tenant_id", "dedupe_key", name="uq_notification_delivery_dedupe"
        ),
        sa.UniqueConstraint(
            "personal_access_link_id",
            name="uq_notification_delivery_personal_access_link_id",
        ),
        sa.CheckConstraint(
            "notification_type IN ('REGISTRATION_COMPLETED', 'RECOMMENDATION_READY', "
            "'EVENT_EVE_REMINDER', 'MEETING_STATUS_CHANGED', 'MEETING_IMMINENT', "
            "'POST_EVENT_SUMMARY')",
            name="notification_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('QUEUED', 'PROCESSING', 'SENT', 'DELIVERED', 'FAILED')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "message_class = 'INFORMATIONAL'",
            name="message_class_informational",
        ),
        schema="integration",
    )
    op.create_index(
        "ix_notification_delivery_dispatch",
        "notification_delivery",
        ["status", "queued_at"],
        schema="integration",
    )
    op.create_index(
        "ix_notification_delivery_user_event",
        "notification_delivery",
        ["user_id", "event_id", "queued_at"],
        schema="integration",
    )

    op.create_table(
        "notification_attempt",
        _uuid("notification_attempt_id"),
        _uuid("notification_delivery_id"),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("channel", sa.String(30), nullable=False),
        sa.Column("provider_code", sa.String(60), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("provider_message_id", sa.String(200), nullable=True),
        sa.Column("failure_code", sa.String(100), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("failed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("notification_attempt_id"),
        sa.ForeignKeyConstraint(
            ["notification_delivery_id"],
            ["integration.notification_delivery.notification_delivery_id"],
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "notification_delivery_id",
            "sequence",
            name="uq_notification_attempt_sequence",
        ),
        sa.CheckConstraint(
            "channel IN ('KAKAO_ALIMTALK', 'SMS', 'EMAIL')",
            name="channel_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('SENT', 'DELIVERED', 'FAILED', 'SKIPPED')",
            name="status_allowed",
        ),
        sa.CheckConstraint("sequence > 0", name="sequence_positive"),
        schema="integration",
    )
    op.create_index(
        "ix_notification_attempt_delivery",
        "notification_attempt",
        ["notification_delivery_id", "sequence"],
        schema="integration",
    )

    op.create_table(
        "outbox_event",
        _uuid("outbox_event_id"),
        _uuid("tenant_id"),
        _uuid("event_id", nullable=True),
        sa.Column("aggregate_type", sa.String(60), nullable=False),
        _uuid("aggregate_id"),
        sa.Column("event_type", sa.String(100), nullable=False),
        sa.Column("schema_version", sa.String(30), nullable=False),
        sa.Column("payload", postgresql.JSONB(), nullable=False),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'PENDING'"),
        ),
        sa.Column(
            "attempt_count", sa.Integer(), nullable=False, server_default=sa.text("0")
        ),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("outbox_event_id"),
        sa.ForeignKeyConstraint(["tenant_id"], ["core.tenant.tenant_id"]),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_outbox_event_event_boundary",
        ),
        sa.UniqueConstraint("tenant_id", "dedupe_key", name="uq_outbox_event_dedupe"),
        sa.CheckConstraint(
            "status IN ('PENDING', 'PROCESSING', 'PUBLISHED', 'FAILED')",
            name="status_allowed",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        schema="integration",
    )
    op.create_index(
        "ix_outbox_event_claim",
        "outbox_event",
        ["status", "next_attempt_at", "created_at"],
        schema="integration",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_outbox_event_claim", table_name="outbox_event", schema="integration"
    )
    op.drop_table("outbox_event", schema="integration")
    op.drop_index(
        "ix_notification_attempt_delivery",
        table_name="notification_attempt",
        schema="integration",
    )
    op.drop_table("notification_attempt", schema="integration")
    op.drop_index(
        "ix_notification_delivery_user_event",
        table_name="notification_delivery",
        schema="integration",
    )
    op.drop_index(
        "ix_notification_delivery_dispatch",
        table_name="notification_delivery",
        schema="integration",
    )
    op.drop_table("notification_delivery", schema="integration")
