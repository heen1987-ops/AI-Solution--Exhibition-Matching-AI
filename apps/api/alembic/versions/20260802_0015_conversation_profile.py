"""publish privacy-minimized conversational profiling ledger

Revision ID: 0015_conversation_profile
Revises: 0014_explanation_lineage
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0015_conversation_profile"
down_revision: str | None = "0014_explanation_lineage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS conversation")
    op.create_table(
        "conversation_session",
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("user_type", sa.String(30), nullable=False),
        sa.Column("language", sa.String(10), nullable=False, server_default="ko"),
        sa.Column(
            "dialog_state", sa.String(40), nullable=False, server_default="COLLECT_GOAL"
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("policy_version", sa.String(100), nullable=False),
        sa.Column(
            "state_json",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "started_at",
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
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "profile_id"],
            [
                "profile.user_profile.tenant_id",
                "profile.user_profile.event_id",
                "profile.user_profile.profile_id",
            ],
            name="fk_conversation_session_profile_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["visit_session_id"], ["profile.visit_session.visit_session_id"]
        ),
        sa.CheckConstraint(
            "user_type IN ('GENERAL_VISITOR', 'BUYER')",
            name=op.f("ck_conversation_session_user_type_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'COMPLETED', 'EXPIRED', 'CANCELLED')",
            name=op.f("ck_conversation_session_status_allowed"),
        ),
        schema="conversation",
    )
    op.create_index(
        "ix_conversation_session_profile_status",
        "conversation_session",
        ["profile_id", "status", "last_activity_at"],
        schema="conversation",
    )
    op.create_table(
        "message",
        sa.Column("message_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sender_type", sa.String(20), nullable=False),
        sa.Column("masked_text", sa.String(2000), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("message_type", sa.String(20), nullable=False, server_default="TEXT"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["conversation_id"],
            ["conversation.conversation_session.conversation_id"],
        ),
        sa.CheckConstraint(
            "sender_type IN ('USER', 'ASSISTANT', 'SYSTEM')",
            name=op.f("ck_message_sender_type_allowed"),
        ),
        schema="conversation",
    )
    op.create_index(
        "ix_conversation_message_order",
        "message",
        ["conversation_id", "created_at"],
        schema="conversation",
    )
    op.create_table(
        "entity_extraction",
        sa.Column("extraction_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attribute_code", sa.String(100), nullable=False),
        sa.Column("operator_code", sa.String(40), nullable=False),
        sa.Column("value_json", postgresql.JSONB(), nullable=False),
        sa.Column("unit_code", sa.String(20), nullable=True),
        sa.Column("requirement_level", sa.String(20), nullable=False),
        sa.Column("source_text", sa.String(300), nullable=False),
        sa.Column("confidence", sa.Numeric(7, 6), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("policy_version", sa.String(100), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "applied_profile_attribute_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["message_id"], ["conversation.message.message_id"]
        ),
        sa.ForeignKeyConstraint(
            ["applied_profile_attribute_id"],
            ["profile.profile_attribute.profile_attribute_id"],
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_entity_extraction_confidence_range"),
        ),
        sa.CheckConstraint(
            "status IN ('PROPOSED', 'CONFIRMED', 'REJECTED')",
            name=op.f("ck_entity_extraction_status_allowed"),
        ),
        sa.CheckConstraint(
            "requirement_level IN ('REQUIRED', 'PREFERRED', 'ACCEPTABLE', 'EXCLUDED')",
            name=op.f("ck_entity_extraction_requirement_level_allowed"),
        ),
        schema="conversation",
    )
    op.create_index(
        "ix_entity_extraction_message",
        "entity_extraction",
        ["message_id", "status"],
        schema="conversation",
    )


def downgrade() -> None:
    op.drop_table("entity_extraction", schema="conversation")
    op.drop_table("message", schema="conversation")
    op.drop_table("conversation_session", schema="conversation")
    op.execute("DROP SCHEMA IF EXISTS conversation")
