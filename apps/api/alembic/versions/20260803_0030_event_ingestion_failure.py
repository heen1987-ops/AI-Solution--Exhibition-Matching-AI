"""publish interaction.event_ingestion_failure (WAVE 2E, BACKEND-EVENT-COLLECTION)

The observability ledger for *rejected* client event submissions. It is declared by
``app/models/interaction_event.py::EventIngestionFailure`` but was created by no migration
anywhere - a grep of the WAVE 2C/2D/2E branch's fully compiled ``alembic upgrade head --sql``
returned zero occurrences of the table name. This revision closes that gap; the ORM-vs-
migration parity test in ``tests/test_alembic_orm_parity.py`` keeps it closed.

Deliberate absence of foreign keys
----------------------------------
``tenant_id``/``event_id``/``client_event_id`` carry NO referential constraint, matching the
model. A rejected submission may claim a tenant/event that does not exist at all (malformed
client, replay, fuzzing) - that is precisely the class of input this ledger exists to record,
so an FK here would turn the failures we want to observe into a second, unrelated FK violation
and lose the row.

The ``interaction`` schema already exists (0001_create_schemas, and every earlier interaction
revision), so this migration creates no schema.

Revision ID: 0030_event_ingestion_failure
Revises: 0029_analytics_aggregation
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0030_event_ingestion_failure"
down_revision: str | None = "0029_analytics_aggregation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "interaction"

# Literal copies of app/models/interaction_event.py's constants. A migration is a historical
# record of the schema at the moment it was applied, so it must not import values that a later
# edit to the model file could change underneath it (same convention as every other revision).
_SOURCES = ("WEB", "KIOSK", "UNKNOWN")
_REASON_CODES = (
    "SCHEMA_ERROR",
    "UNKNOWN_EVENT_TYPE",
    "KIOSK_IDENTITY_FIELD_FORBIDDEN",
    "TIMESTAMP_OUT_OF_RANGE",
    "IDEMPOTENCY_CONFLICT",
    "PERSIST_FAILED",
)


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "event_ingestion_failure",
        sa.Column(
            "event_ingestion_failure_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source", sa.String(10), nullable=False, server_default="UNKNOWN"),
        sa.Column("client_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("event_type", sa.String(60), nullable=True),
        sa.Column("reason_code", sa.String(40), nullable=False),
        sa.Column("detail", sa.String(300), nullable=True),
        sa.Column("request_id", sa.String(80), nullable=True),
        sa.Column("claimed_occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            f"source IN ({_in_list(_SOURCES)})",
            name="ck_event_ingestion_failure_source_allowed",
        ),
        sa.CheckConstraint(
            f"reason_code IN ({_in_list(_REASON_CODES)})",
            name="ck_event_ingestion_failure_reason_code_allowed",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_event_ingestion_failure_tenant_time",
        "event_ingestion_failure",
        ["tenant_id", "received_at"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_event_ingestion_failure_reason_time",
        "event_ingestion_failure",
        ["reason_code", "received_at"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_event_ingestion_failure_reason_time",
        table_name="event_ingestion_failure",
        schema=_SCHEMA,
    )
    op.drop_index(
        "ix_event_ingestion_failure_tenant_time",
        table_name="event_ingestion_failure",
        schema=_SCHEMA,
    )
    op.drop_table("event_ingestion_failure", schema=_SCHEMA)
