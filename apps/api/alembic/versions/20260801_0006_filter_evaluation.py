"""create append-only hard-filter evaluations

Revision ID: 0006_filter_evaluation
Revises: 0005_exhibition
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0006_filter_evaluation"
down_revision: str | None = "0005_exhibition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_profile_version_profile_id_version_id",
        "profile_version",
        ["profile_id", "profile_version_id"],
        schema="profile",
    )

    op.create_table(
        "filter_evaluation",
        sa.Column(
            "filter_evaluation_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "profile_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("request_id", sa.String(length=100), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("filter_policy_version", sa.String(length=50), nullable=False),
        sa.Column("input_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("context_snapshot", postgresql.JSONB(), nullable=False),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("eligible_count", sa.Integer(), nullable=False),
        sa.Column("rejected_count", sa.Integer(), nullable=False),
        sa.Column(
            "evaluation_status",
            sa.String(length=20),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "candidate_count >= 0 AND eligible_count >= 0 AND rejected_count >= 0",
            name="counts_nonnegative",
        ),
        sa.CheckConstraint(
            "candidate_count = eligible_count + rejected_count",
            name="counts_balance",
        ),
        sa.CheckConstraint(
            "evaluation_status IN ('COMPLETED')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "completed_at >= started_at",
            name="time_order",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["core.tenant.tenant_id"],
            name="fk_filter_evaluation_tenant_id_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_filter_evaluation_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "profile_version_id"],
            [
                "profile.profile_version.profile_id",
                "profile.profile_version.profile_version_id",
            ],
            name="fk_filter_evaluation_profile_version",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "request_id",
            name="uq_filter_evaluation_request",
        ),
        schema="matching",
    )
    op.create_index(
        "uq_filter_evaluation_idempotency",
        "filter_evaluation",
        ["tenant_id", "event_id", "idempotency_key"],
        unique=True,
        schema="matching",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.create_index(
        "ix_filter_evaluation_profile_created",
        "filter_evaluation",
        ["profile_id", "created_at"],
        schema="matching",
    )

    op.create_table(
        "filter_result",
        sa.Column(
            "filter_result_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "filter_evaluation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("object_type", sa.String(length=20), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "recommendable_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("passed", sa.Boolean(), nullable=False),
        sa.Column("filter_code", sa.String(length=60), nullable=True),
        sa.Column("details_json", postgresql.JSONB(), nullable=False),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=False),
        sa.Column("candidate_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "(passed AND filter_code IS NULL) OR "
            "(NOT passed AND filter_code IS NOT NULL)",
            name="pass_code_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["filter_evaluation_id"],
            ["matching.filter_evaluation.filter_evaluation_id"],
            name="fk_filter_result_filter_evaluation_id_filter_evaluation",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "filter_evaluation_id",
            "object_type",
            "object_id",
            name="uq_filter_result_candidate",
        ),
        schema="matching",
    )
    op.create_index(
        "ix_filter_result_code",
        "filter_result",
        ["filter_code"],
        schema="matching",
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION matching.reject_filter_audit_mutation()
        RETURNS trigger
        LANGUAGE plpgsql
        AS $$
        BEGIN
            RAISE EXCEPTION 'hard-filter audit rows are append-only';
        END;
        $$
        """
    )
    for table_name in ("filter_evaluation", "filter_result"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_append_only
            BEFORE UPDATE OR DELETE ON matching.{table_name}
            FOR EACH ROW EXECUTE FUNCTION matching.reject_filter_audit_mutation()
            """
        )


def downgrade() -> None:
    for table_name in ("filter_result", "filter_evaluation"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only "
            f"ON matching.{table_name}"
        )
    op.execute("DROP FUNCTION IF EXISTS matching.reject_filter_audit_mutation()")

    op.drop_index(
        "ix_filter_result_code",
        table_name="filter_result",
        schema="matching",
    )
    op.drop_table("filter_result", schema="matching")
    op.drop_index(
        "ix_filter_evaluation_profile_created",
        table_name="filter_evaluation",
        schema="matching",
    )
    op.drop_index(
        "uq_filter_evaluation_idempotency",
        table_name="filter_evaluation",
        schema="matching",
    )
    op.drop_table("filter_evaluation", schema="matching")

    op.drop_constraint(
        "uq_profile_version_profile_id_version_id",
        "profile_version",
        schema="profile",
        type_="unique",
    )
