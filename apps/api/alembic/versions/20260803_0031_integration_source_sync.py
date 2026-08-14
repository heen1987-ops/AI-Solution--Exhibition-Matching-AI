"""publish integration.source_system / external_reference / sync_job / sync_row_error /
idempotency_record

Why this revision exists (drift discovered during the WAVE 2C/2D/2E merge)
--------------------------------------------------------------------------
``app/models/integration.py`` has declared these five tables since the external-data
integration work landed, and ``app/services/excel_import.py`` and the imports/webhooks
routers write to them - but NO migration on EITHER codebase ever created them. The gap was
invisible because ``alembic/env.py`` used to import a hand-maintained module tuple that
omitted ``integration``, so autogenerate never saw the models, and the only test that would
have caught it (``tests/integration/test_postgres_recommendation_contract.py``) is skipped
unless ``POSTGRES_TEST_DATABASE_URL`` is set.

``tests/test_alembic_orm_parity.py`` (added in the same merge) now asserts that every ORM
table has a creating migration, so this class of drift cannot recur silently.

The DDL below is transcribed from ``app/models/integration.py``'s declarations, including the
constraint names that ``app/db/base.py``'s NAMING_CONVENTION derives (``op.create_table``
attaches to a plain MetaData without that convention, so every name is spelled out - the same
approach 20260801144653_profile_domain and 0020_interaction_domain take).

The ``integration`` schema already exists (0001_create_schemas; 0019_notification_outbox also
creates tables in it), so this migration creates no schema.

Revision ID: 0031_integration_source_sync
Revises: 0030_event_ingestion_failure
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0031_integration_source_sync"
down_revision: str | None = "0030_event_ingestion_failure"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "integration"

# Literal copies of app/models/integration.py's constants - a migration records the schema as
# it was applied and must not follow later edits to the model file.
_SYNC_TYPES = ("CSV", "API", "WEBHOOK")
_OBJECT_TYPES = ("VISITOR", "EXHIBITOR", "PRODUCT")
_SYNC_STATUSES = ("SYNCED", "FAILED", "CONFLICT")
_JOB_TYPES = ("VISITOR_IMPORT", "EXHIBITOR_IMPORT", "PRODUCT_IMPORT", "WEBHOOK_INGEST")
_JOB_STATUSES = ("PENDING", "RUNNING", "COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED")
_RETRY_STATUSES = ("PENDING", "RETRIED", "IGNORED")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "source_system",
        sa.Column("source_system_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("system_code", sa.String(50), nullable=False),
        sa.Column("system_name", sa.String(200), nullable=False),
        sa.Column("sync_type", sa.String(20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("source_system_id", name="pk_source_system"),
        sa.UniqueConstraint("tenant_id", "system_code", name="uq_source_system_tenant_code"),
        sa.CheckConstraint(
            f"sync_type IN ({_in_list(_SYNC_TYPES)})",
            name="ck_source_system_sync_type_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["core.tenant.tenant_id"],
            name="fk_source_system_tenant_id_tenant",
        ),
        schema=_SCHEMA,
    )

    op.create_table(
        "external_reference",
        sa.Column("external_reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_system_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_type", sa.String(30), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=False),
        # Polymorphic target (object_type decides the table), so no FK - same pattern as
        # exhibition SupplyProfileAttribute.object_id.
        sa.Column("internal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "last_synced_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("source_payload_hash", sa.LargeBinary(), nullable=True),
        sa.Column("sync_status", sa.String(20), nullable=False, server_default="SYNCED"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("external_reference_id", name="pk_external_reference"),
        sa.UniqueConstraint(
            "source_system_id",
            "object_type",
            "external_id",
            name="uq_external_reference_source_object",
        ),
        sa.CheckConstraint(
            f"object_type IN ({_in_list(_OBJECT_TYPES)})",
            name="ck_external_reference_object_type_allowed",
        ),
        sa.CheckConstraint(
            f"sync_status IN ({_in_list(_SYNC_STATUSES)})",
            name="ck_external_reference_sync_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["source_system_id"],
            [f"{_SCHEMA}.source_system.source_system_id"],
            name="fk_external_reference_source_system_id_source_system",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_external_reference_internal_id",
        "external_reference",
        ["object_type", "internal_id"],
        schema=_SCHEMA,
    )

    op.create_table(
        "sync_job",
        sa.Column("sync_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_system_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("job_type", sa.String(30), nullable=False),
        sa.Column("file_checksum", sa.String(128), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="PENDING"),
        sa.Column("total_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        # No FK: service-to-service (webhook) jobs have no profile.user_account row.
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("sync_job_id", name="pk_sync_job"),
        sa.CheckConstraint(
            f"job_type IN ({_in_list(_JOB_TYPES)})", name="ck_sync_job_job_type_allowed"
        ),
        sa.CheckConstraint(
            f"status IN ({_in_list(_JOB_STATUSES)})", name="ck_sync_job_status_allowed"
        ),
        sa.CheckConstraint("total_rows >= 0", name="ck_sync_job_total_rows_nonneg"),
        sa.CheckConstraint("success_rows >= 0", name="ck_sync_job_success_rows_nonneg"),
        sa.CheckConstraint("failed_rows >= 0", name="ck_sync_job_failed_rows_nonneg"),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenant.tenant_id"], name="fk_sync_job_tenant_id_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["source_system_id"],
            [f"{_SCHEMA}.source_system.source_system_id"],
            name="fk_sync_job_source_system_id_source_system",
        ),
        schema=_SCHEMA,
    )

    op.create_table(
        "sync_row_error",
        sa.Column("sync_row_error_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sync_job_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=False),
        # Application-constructed, masked message only - never the raw exception text.
        sa.Column("error_message", sa.Text(), nullable=False),
        sa.Column("raw_row_json", postgresql.JSONB(), nullable=True),
        sa.Column("retry_status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("sync_row_error_id", name="pk_sync_row_error"),
        sa.CheckConstraint("row_number >= 0", name="ck_sync_row_error_row_number_nonneg"),
        sa.CheckConstraint(
            f"retry_status IN ({_in_list(_RETRY_STATUSES)})",
            name="ck_sync_row_error_retry_status_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["sync_job_id"],
            [f"{_SCHEMA}.sync_job.sync_job_id"],
            name="fk_sync_row_error_sync_job_id_sync_job",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_sync_row_error_job", "sync_row_error", ["sync_job_id"], schema=_SCHEMA
    )

    op.create_table(
        "idempotency_record",
        sa.Column("idempotency_record_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("principal_fingerprint", sa.LargeBinary(), nullable=False),
        sa.Column("method", sa.String(10), nullable=False),
        sa.Column("route", sa.String(200), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("request_hash", sa.LargeBinary(), nullable=True),
        sa.Column("response_status", sa.Integer(), nullable=True),
        sa.Column("response_reference", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("idempotency_record_id", name="pk_idempotency_record"),
        sa.UniqueConstraint(
            "tenant_id",
            "principal_fingerprint",
            "method",
            "route",
            "idempotency_key",
            name="uq_idempotency_record_scope",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["core.tenant.tenant_id"],
            name="fk_idempotency_record_tenant_id_tenant",
        ),
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("idempotency_record", schema=_SCHEMA)
    op.drop_index("ix_sync_row_error_job", table_name="sync_row_error", schema=_SCHEMA)
    op.drop_table("sync_row_error", schema=_SCHEMA)
    op.drop_table("sync_job", schema=_SCHEMA)
    op.drop_index(
        "ix_external_reference_internal_id", table_name="external_reference", schema=_SCHEMA
    )
    op.drop_table("external_reference", schema=_SCHEMA)
    op.drop_table("source_system", schema=_SCHEMA)
