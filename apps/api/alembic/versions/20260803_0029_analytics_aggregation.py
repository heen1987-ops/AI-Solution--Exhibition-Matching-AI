"""publish analytics daily/funnel metric, search-no-result, and data-quality tables

WAVE 2E / WORKER-ANALYTICS. See app/models/analytics.py's module docstring for the full
design rationale (idempotent natural-key upsert targets, small-group suppression contract,
and the explicit owned-path exception that lets this track add
apps/api/app/models/analytics.py + this migration).

The `analytics` schema itself already exists - it is created generically by
0001_create_schemas (app/db/base.py's ALL_SCHEMAS already lists SCHEMA_ANALYTICS), so this
revision only adds tables inside it.

This domain has no foreign-key dependency on any other WAVE 2C/2D/2E track's tables - only on
`exhibition.event`, published long before, and conceptually on `interaction.interaction_event`,
which this migration does not need to reference structurally (the aggregation job reads it at
runtime, not via a DB-level FK, so a partitioned table with a composite PK isn't referenced
here). It therefore sits last in the integrated linear chain
(0020_interaction_domain -> 0030_event_ingestion_failure), which has exactly one head.

Revision ID: 0029_analytics_aggregation
Revises: 0028_event_message
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0029_analytics_aggregation"
down_revision: str | None = "0028_event_message"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "analytics"


def _event_boundary_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(
        ["tenant_id", "event_id"],
        ["exhibition.event.tenant_id", "exhibition.event.event_id"],
        name=f"fk_{table}_event_boundary",
    )


def upgrade() -> None:
    op.create_table(
        "daily_metric",
        sa.Column("daily_metric_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("metric_code", sa.String(60), nullable=False),
        sa.Column(
            "dimension_code", sa.String(40), nullable=False, server_default="ALL"
        ),
        sa.Column("event_count", sa.Integer(), nullable=True),
        sa.Column("distinct_actor_count", sa.Integer(), nullable=True),
        sa.Column(
            "suppressed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("aggregation_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        _event_boundary_fk("daily_metric"),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "metric_date",
            "metric_code",
            "dimension_code",
            name=op.f("uq_daily_metric_natural_key"),
        ),
        sa.CheckConstraint(
            "(suppressed = false) OR (event_count IS NULL AND distinct_actor_count IS NULL)",
            name=op.f("ck_daily_metric_suppressed_hides_values"),
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_daily_metric_event_date_code",
        "daily_metric",
        ["tenant_id", "event_id", "metric_date", "metric_code"],
        schema=_SCHEMA,
    )

    op.create_table(
        "funnel_metric",
        sa.Column("funnel_metric_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("metric_date", sa.Date(), nullable=False),
        sa.Column("funnel_code", sa.String(10), nullable=False),
        sa.Column("step_code", sa.String(40), nullable=False),
        sa.Column("step_order", sa.Integer(), nullable=False),
        sa.Column("actor_count", sa.Integer(), nullable=True),
        sa.Column(
            "suppressed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("conversion_from_previous", sa.Numeric(9, 6), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("aggregation_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        _event_boundary_fk("funnel_metric"),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "metric_date",
            "funnel_code",
            "step_code",
            name=op.f("uq_funnel_metric_natural_key"),
        ),
        sa.CheckConstraint(
            "funnel_code IN ('WEB', 'KIOSK', 'BUYER')",
            name=op.f("ck_funnel_metric_funnel_code_allowed"),
        ),
        sa.CheckConstraint(
            "step_order > 0", name=op.f("ck_funnel_metric_step_order_positive")
        ),
        sa.CheckConstraint(
            "(suppressed = false) OR "
            "(actor_count IS NULL AND conversion_from_previous IS NULL)",
            name=op.f("ck_funnel_metric_suppressed_hides_values"),
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_funnel_metric_event_date_funnel",
        "funnel_metric",
        ["tenant_id", "event_id", "metric_date", "funnel_code"],
        schema=_SCHEMA,
    )

    op.create_table(
        "search_no_result_summary",
        sa.Column(
            "search_no_result_summary_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("summary_date", sa.Date(), nullable=False),
        sa.Column(
            "channel_code", sa.String(20), nullable=False, server_default="UNKNOWN"
        ),
        sa.Column(
            "query_norm", sa.String(200), nullable=False, server_default="UNKNOWN"
        ),
        sa.Column("occurrence_count", sa.Integer(), nullable=True),
        sa.Column("distinct_actor_count", sa.Integer(), nullable=True),
        sa.Column(
            "suppressed", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("last_occurred_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("aggregation_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        _event_boundary_fk("search_no_result_summary"),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "summary_date",
            "channel_code",
            "query_norm",
            name=op.f("uq_search_no_result_summary_natural_key"),
        ),
        sa.CheckConstraint(
            "(suppressed = false) OR "
            "(occurrence_count IS NULL AND distinct_actor_count IS NULL "
            "AND last_occurred_at IS NULL)",
            name=op.f("ck_search_no_result_summary_suppressed_hides_values"),
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_search_no_result_summary_event_date",
        "search_no_result_summary",
        ["tenant_id", "event_id", "summary_date"],
        schema=_SCHEMA,
    )

    op.create_table(
        "data_quality_snapshot",
        sa.Column(
            "data_quality_snapshot_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("check_code", sa.String(60), nullable=False),
        sa.Column("status", sa.String(10), nullable=False),
        sa.Column("metric_value", sa.Numeric(12, 6), nullable=True),
        sa.Column("threshold_value", sa.Numeric(12, 6), nullable=True),
        sa.Column("affected_count", sa.Integer(), nullable=True),
        sa.Column("details_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "computed_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("aggregation_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        _event_boundary_fk("data_quality_snapshot"),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "snapshot_date",
            "check_code",
            name=op.f("uq_data_quality_snapshot_natural_key"),
        ),
        sa.CheckConstraint(
            "status IN ('OK', 'WARN', 'FAIL')",
            name=op.f("ck_data_quality_snapshot_status_allowed"),
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_data_quality_snapshot_event_date",
        "data_quality_snapshot",
        ["tenant_id", "event_id", "snapshot_date"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("data_quality_snapshot", schema=_SCHEMA)
    op.drop_table("search_no_result_summary", schema=_SCHEMA)
    op.drop_table("funnel_metric", schema=_SCHEMA)
    op.drop_table("daily_metric", schema=_SCHEMA)
