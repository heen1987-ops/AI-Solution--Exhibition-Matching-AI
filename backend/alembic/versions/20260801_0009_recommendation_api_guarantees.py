"""add recommendation API persistence guarantees

Revision ID: 0009_recommendation_api
Revises: 0008_matching_runtime
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0009_recommendation_api"
down_revision: str | None = "0008_matching_runtime"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "match_result",
        sa.Column("context_details", postgresql.JSONB(), nullable=True),
        schema="matching",
    )
    # A non-partitioned registry is required because PostgreSQL unique indexes
    # on the event table itself must include event_date and cannot deduplicate
    # a client retry whose timestamp crosses a partition boundary.
    op.create_table(
        "client_event_dedupe",
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("client_event_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column(
            "interaction_event_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("payload_hash", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_client_event_dedupe_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["event_date", "interaction_event_id"],
            [
                "interaction.interaction_event.event_date",
                "interaction.interaction_event.interaction_event_id",
            ],
            name="fk_client_event_dedupe_interaction_event",
        ),
        schema="interaction",
    )
    op.create_index(
        "ix_client_event_dedupe_event",
        "client_event_dedupe",
        ["tenant_id", "event_id"],
        schema="interaction",
    )
    op.execute(
        "CREATE TRIGGER trg_client_event_dedupe_append_only "
        "BEFORE UPDATE OR DELETE ON interaction.client_event_dedupe "
        "FOR EACH ROW EXECUTE FUNCTION interaction.reject_interaction_event_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_client_event_dedupe_append_only "
        "ON interaction.client_event_dedupe"
    )
    op.drop_table("client_event_dedupe", schema="interaction")
    op.drop_column("match_result", "context_details", schema="matching")
