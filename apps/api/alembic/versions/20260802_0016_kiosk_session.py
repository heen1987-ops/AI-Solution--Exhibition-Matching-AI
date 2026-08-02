"""publish anonymous kiosk session and QR handoff audit tables

Revision ID: 0016_kiosk_session
Revises: 0015_conversation_profile
Create Date: 2026-08-02

This revision was promoted during the integration pass after confirming that
``0015_conversation_profile`` was the repository's single published head.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0016_kiosk_session"
down_revision: str | None = "0015_conversation_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS kiosk")
    op.create_table(
        "kiosk_session",
        sa.Column("session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kiosk_id", sa.String(80), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_activity_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_kiosk_session_event_boundary",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'HANDED_OFF', 'TIMED_OUT', 'CLOSED')",
            name=op.f("ck_kiosk_session_status_allowed"),
        ),
        schema="kiosk",
    )
    op.create_index(
        "ix_kiosk_session_kiosk_status_expiry",
        "kiosk_session",
        ["kiosk_id", "status", "expires_at"],
        schema="kiosk",
    )
    op.create_table(
        "kiosk_qr_handoff",
        sa.Column("handoff_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("kiosk_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("selected_result_ids", postgresql.JSONB(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["kiosk_session_id"], ["kiosk.kiosk_session.session_id"]
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_kiosk_qr_handoff_event_boundary",
        ),
        sa.UniqueConstraint(
            "token_hash", name=op.f("uq_kiosk_qr_handoff_token_hash")
        ),
        schema="kiosk",
    )

    # No name/phone/email/password column exists on either table above. This is a schema
    # invariant, not a migration-time check - see tests/test_kiosk_api.py and
    # app/models/kiosk.py's module docstring for the enforcement side.


def downgrade() -> None:
    op.drop_table("kiosk_qr_handoff", schema="kiosk")
    op.drop_table("kiosk_session", schema="kiosk")
    op.execute("DROP SCHEMA IF EXISTS kiosk")
