"""publish operator-authored event-message campaign + workflow (event_message schema)

Revision ID: 0028_event_message
Revises: 0027_notification
Create Date: 2026-08-03

WAVE 2E ADMIN-NOTIFICATION. See ``app/models/event_message.py`` module docstring for the full
schema rationale (why a new ``event_message`` schema separate from ``notification``, why only
two tables, small-audience-suppression and coarse-targeting invariants).

Chained onto ``0019_search_indexing`` - one of several current heads at authoring time (this
repo has multiple concurrent WAVE 2D/2E tracks each adding their own migration on top of
``0016_kiosk_session``; see ``alembic heads``). A multi-head merge migration is needed at
integration - flagged in this track's final report, not resolved here (this track does not own
other tracks' migration files).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0028_event_message"
down_revision: str | None = "0027_notification"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_MESSAGE_TYPES = (
    "'EVENT_OPERATION_NOTICE', 'EVENT_START_REMINDER', 'PROFILE_CONFIRMATION_REMINDER', "
    "'RECOMMENDATION_READY_NOTICE', 'POST_EVENT_RESOURCE_NOTICE'"
)
_STATUSES = (
    "'DRAFT', 'PREVIEWED', 'APPROVED', 'SCHEDULED', 'PUBLISHED', 'COMPLETED', 'CANCELLED'"
)
_TARGET_SEGMENTS = (
    "'ALL_REGISTERED_USERS', 'PROFILE_UNCONFIRMED', 'RECOMMENDATION_READY', 'BUYERS', "
    "'EXHIBITOR_STAFF', 'SPECIFIC_ROLE'"
)
_TARGET_ROLE_CODES = "'VISITOR', 'BUYER', 'EXHIBITOR', 'OPERATOR', 'ADMIN'"


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS event_message")

    op.create_table(
        "event_message",
        sa.Column("event_message_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("message_type", sa.String(50), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="DRAFT"),
        sa.Column("title", sa.String(200), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("channels_json", postgresql.JSONB(), nullable=False),
        sa.Column("target_segment", sa.String(30), nullable=False),
        sa.Column("target_role_code", sa.String(30), nullable=True),
        sa.Column("destination_screen", sa.String(200), nullable=False),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("preview_target_count", sa.Integer(), nullable=True),
        sa.Column("preview_consent_excluded_count", sa.Integer(), nullable=True),
        sa.Column("preview_duplicate_warning", sa.Boolean(), nullable=True),
        sa.Column("previewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("approved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenant.tenant_id"], name="fk_event_message_tenant_id_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_event_message_tenant_event",
        ),
        sa.ForeignKeyConstraint(
            ["created_by_user_id"],
            ["profile.user_account.user_id"],
            name="fk_event_message_created_by_user_id_user_account",
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["profile.user_account.user_id"],
            name="fk_event_message_approved_by_user_id_user_account",
        ),
        sa.CheckConstraint(
            f"message_type IN ({_MESSAGE_TYPES})",
            name=op.f("ck_event_message_message_type_allowed"),
        ),
        sa.CheckConstraint(
            f"status IN ({_STATUSES})", name=op.f("ck_event_message_status_allowed")
        ),
        sa.CheckConstraint(
            f"target_segment IN ({_TARGET_SEGMENTS})",
            name=op.f("ck_event_message_target_segment_allowed"),
        ),
        sa.CheckConstraint(
            f"target_role_code IS NULL OR target_role_code IN ({_TARGET_ROLE_CODES})",
            name=op.f("ck_event_message_target_role_code_allowed"),
        ),
        sa.CheckConstraint(
            "(target_segment = 'SPECIFIC_ROLE') = (target_role_code IS NOT NULL)",
            name=op.f("ck_event_message_target_role_code_matches_segment"),
        ),
        sa.CheckConstraint(
            "destination_screen LIKE '/%' AND destination_screen NOT LIKE '//%' "
            "AND destination_screen NOT LIKE '%://%'",
            name=op.f("ck_event_message_destination_screen_is_internal_route"),
        ),
        sa.CheckConstraint(
            "row_version > 0", name=op.f("ck_event_message_row_version_positive")
        ),
        schema="event_message",
    )
    op.create_index(
        "ix_event_message_tenant_event_status",
        "event_message",
        ["tenant_id", "event_id", "status"],
        schema="event_message",
    )

    op.create_table(
        "event_message_recipient",
        sa.Column(
            "event_message_recipient_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column("event_message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recipient_user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "email_consent_excluded", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["event_message_id"],
            ["event_message.event_message.event_message_id"],
            name="fk_event_message_recipient_event_message_id_event_message",
        ),
        sa.ForeignKeyConstraint(
            ["recipient_user_id"],
            ["profile.user_account.user_id"],
            name="fk_event_message_recipient_recipient_user_id_user_account",
        ),
        sa.UniqueConstraint(
            "event_message_id",
            "recipient_user_id",
            name="uq_event_message_recipient_message_user",
        ),
        schema="event_message",
    )
    op.create_index(
        "ix_event_message_recipient_message",
        "event_message_recipient",
        ["event_message_id"],
        schema="event_message",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_event_message_recipient_message",
        table_name="event_message_recipient",
        schema="event_message",
    )
    op.drop_table("event_message_recipient", schema="event_message")
    op.drop_index(
        "ix_event_message_tenant_event_status",
        table_name="event_message",
        schema="event_message",
    )
    op.drop_table("event_message", schema="event_message")
    op.execute("DROP SCHEMA IF EXISTS event_message CASCADE")
