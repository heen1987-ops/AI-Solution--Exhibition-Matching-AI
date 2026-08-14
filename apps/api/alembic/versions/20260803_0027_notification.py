"""publish notification preferences/templates/rules, notifications, and delivery/attempt
lineage (BACKEND-NOTIFICATION, WAVE 2E)

Revision ID: 0027_notification
Revises: 0026_search_indexing
Create Date: 2026-08-03

See ``app/models/notification.py`` module docstring for the full schema rationale (dedup key,
why relevant_version is a free string, why notification_type is a closed CHECK enum). This
migration publishes the six ``notification.*`` tables that module declares.

Schema creation: ``app/db/base.py``'s ``ALL_SCHEMAS`` lists ``SCHEMA_NOTIFICATION``, so a
build from base creates the namespace at ``0001_create_schemas``. That is not enough for a
database already stamped past 0001, so this migration issues its own
``CREATE SCHEMA IF NOT EXISTS "notification"`` as the first statement of ``upgrade()`` -
the same self-sufficiency its siblings 0024_document_storage, 0026_search_indexing and
0028_event_message already had.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0027_notification"
down_revision: str | None = "0026_search_indexing"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NOTIFICATION_TYPES = (
    "MEETING_ACCEPTED",
    "MEETING_TIME_PROPOSED",
    "CONTENT_REVIEW_REQUESTED",
    "CONTENT_REVIEW_RESULT",
    "RECOMMENDATION_READY",
    "EVENT_DAY_REMINDER",
    "OPERATOR_NOTICE",
)
_NOTIFICATION_TYPES_SQL = ", ".join(f"'{value}'" for value in _NOTIFICATION_TYPES)
_CHANNELS_SQL = "'IN_APP', 'EMAIL'"
_DELIVERY_STATUSES_SQL = "'PENDING', 'SENT', 'FAILED', 'SKIPPED'"
_ATTEMPT_STATUSES_SQL = "'SUCCESS', 'FAILED'"


def upgrade() -> None:
    # 0001_create_schemas가 ALL_SCHEMAS를 순회해 만들지만, 그것은 base부터 새로 빌드하는
    # 데이터베이스에만 해당한다. 이미 0001 이후로 stamp된 데이터베이스에는 아무 도움이 되지
    # 않으므로, 형제 마이그레이션(0024/0026/0028)과 동일하게 스스로 스키마를 만든다.
    op.execute('CREATE SCHEMA IF NOT EXISTS "notification"')

    op.create_table(
        "notification_preferences",
        sa.Column("notification_preference_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("email_enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["core.tenant.tenant_id"],
            name="fk_notification_preferences_tenant_id_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["profile.user_account.user_id"],
            name="fk_notification_preferences_user_id_user_account",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "user_id",
            "notification_type",
            name="uq_notification_preferences_user_type",
        ),
        sa.CheckConstraint(
            f"notification_type IN ({_NOTIFICATION_TYPES_SQL})",
            name=op.f("ck_notification_preferences_notification_type_allowed"),
        ),
        schema="notification",
    )

    op.create_table(
        "notification_templates",
        sa.Column("notification_template_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("title_template", sa.Text(), nullable=False),
        sa.Column("body_template", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["core.tenant.tenant_id"],
            name="fk_notification_templates_tenant_id_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "notification_type",
            "channel",
            name="uq_notification_templates_scope",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint(
            f"notification_type IN ({_NOTIFICATION_TYPES_SQL})",
            name=op.f("ck_notification_templates_notification_type_allowed"),
        ),
        sa.CheckConstraint(
            f"channel IN ({_CHANNELS_SQL})",
            name=op.f("ck_notification_templates_channel_allowed"),
        ),
        schema="notification",
    )

    op.create_table(
        "notification_rules",
        sa.Column("notification_rule_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("business_event_code", sa.String(100), nullable=False),
        sa.Column("frequency_cap_per_recipient_per_day", sa.SmallInteger(), nullable=True),
        sa.Column("is_operational", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["core.tenant.tenant_id"],
            name="fk_notification_rules_tenant_id_tenant",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "notification_type",
            "business_event_code",
            name="uq_notification_rules_scope",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint(
            f"notification_type IN ({_NOTIFICATION_TYPES_SQL})",
            name=op.f("ck_notification_rules_notification_type_allowed"),
        ),
        sa.CheckConstraint(
            "frequency_cap_per_recipient_per_day IS NULL "
            "OR frequency_cap_per_recipient_per_day > 0",
            name=op.f("ck_notification_rules_frequency_cap_positive"),
        ),
        schema="notification",
    )

    op.create_table(
        "notifications",
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("notification_type", sa.String(50), nullable=False),
        sa.Column("object_type", sa.String(50), nullable=True),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("relevant_version", sa.String(50), nullable=True),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("data_json", postgresql.JSONB(), nullable=True),
        sa.Column("source_business_event_code", sa.String(100), nullable=True),
        sa.Column("is_operational", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("read_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["core.tenant.tenant_id"],
            name="fk_notifications_tenant_id_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["profile.user_account.user_id"],
            name="fk_notifications_recipient_user_id_user_account",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_notifications_tenant_event",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "notification_type",
            "recipient_user_id",
            "object_id",
            "relevant_version",
            name="uq_notifications_dedup_key",
            postgresql_nulls_not_distinct=True,
        ),
        sa.CheckConstraint(
            f"notification_type IN ({_NOTIFICATION_TYPES_SQL})",
            name=op.f("ck_notifications_notification_type_allowed"),
        ),
        schema="notification",
    )
    op.create_index(
        "ix_notifications_recipient_created",
        "notifications",
        ["tenant_id", "recipient_user_id", "created_at"],
        schema="notification",
    )
    op.create_index(
        "ix_notifications_recipient_unread",
        "notifications",
        ["tenant_id", "recipient_user_id", "read_at"],
        schema="notification",
    )

    op.create_table(
        "notification_deliveries",
        sa.Column("notification_delivery_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("notification_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("channel", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("skipped_reason", sa.String(50), nullable=True),
        sa.Column("failure_reason", sa.Text(), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["notification_id"],
            ["notification.notifications.notification_id"],
            name="fk_notification_deliveries_notification_id_notifications",
        ),
        sa.UniqueConstraint(
            "notification_id", "channel", name="uq_notification_deliveries_notification_channel"
        ),
        sa.CheckConstraint(
            f"channel IN ({_CHANNELS_SQL})",
            name=op.f("ck_notification_deliveries_channel_allowed"),
        ),
        sa.CheckConstraint(
            f"status IN ({_DELIVERY_STATUSES_SQL})",
            name=op.f("ck_notification_deliveries_status_allowed"),
        ),
        schema="notification",
    )

    op.create_table(
        "notification_delivery_attempts",
        sa.Column(
            "notification_delivery_attempt_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column("notification_delivery_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "attempted_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["notification_delivery_id"],
            ["notification.notification_deliveries.notification_delivery_id"],
            # Kept under Postgres's 63-char identifier limit (the ORM model's own naming
            # convention would auto-hash-truncate this same FK to fit - see
            # app/models/notification.py's NotificationDeliveryAttempt.notification_delivery_id
            # - but a hand-specified `name=` here is not auto-truncated, so it must be short by
            # construction).
            name="fk_notification_delivery_attempts_delivery_id_deliveries",
        ),
        sa.UniqueConstraint(
            "notification_delivery_id",
            "attempt_number",
            name="uq_notification_delivery_attempts_number",
        ),
        sa.CheckConstraint(
            "attempt_number > 0",
            name=op.f("ck_notification_delivery_attempts_attempt_number_positive"),
        ),
        sa.CheckConstraint(
            f"status IN ({_ATTEMPT_STATUSES_SQL})",
            name=op.f("ck_notification_delivery_attempts_status_allowed"),
        ),
        schema="notification",
    )
    op.create_index(
        "ix_notification_delivery_attempts_delivery",
        "notification_delivery_attempts",
        ["notification_delivery_id", "attempt_number"],
        schema="notification",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_notification_delivery_attempts_delivery",
        table_name="notification_delivery_attempts",
        schema="notification",
    )
    op.drop_table("notification_delivery_attempts", schema="notification")
    op.drop_table("notification_deliveries", schema="notification")
    op.drop_index(
        "ix_notifications_recipient_unread", table_name="notifications", schema="notification"
    )
    op.drop_index(
        "ix_notifications_recipient_created", table_name="notifications", schema="notification"
    )
    op.drop_table("notifications", schema="notification")
    op.drop_table("notification_rules", schema="notification")
    op.drop_table("notification_templates", schema="notification")
    op.drop_table("notification_preferences", schema="notification")
    op.execute('DROP SCHEMA IF EXISTS "notification"')
