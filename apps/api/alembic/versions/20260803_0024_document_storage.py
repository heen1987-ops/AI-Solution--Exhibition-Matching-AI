"""publish exhibitor document upload/version/processing-job/access-log tables (document schema)

Revision ID: 0024_document_storage
Revises: 0023_buyer_match
Create Date: 2026-08-02

BACKEND-DOCUMENT (WAVE 2D). See app/models/document.py module docstring for the full schema
rationale (why a new "document" schema, why SourceDocument/DocumentFile are split, why
document_access_log has no FK to the document it audits).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0024_document_storage"
down_revision: str | None = "0023_buyer_match"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS document")

    op.create_table(
        "source_document",
        sa.Column("document_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exhibitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_type", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="UPLOADED"),
        sa.Column("current_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("published_file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("original_filename", sa.String(255), nullable=True),
        sa.Column("mime_type", sa.String(150), nullable=True),
        sa.Column("size_bytes", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_source_document_tenant_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"], ["core.tenant.tenant_id"], name="fk_source_document_tenant"
        ),
        sa.ForeignKeyConstraint(
            ["exhibitor_id"],
            ["exhibition.exhibitor.exhibitor_id"],
            name="fk_source_document_exhibitor",
        ),
        sa.CheckConstraint(
            "document_type IN ('CATALOG', 'CERTIFICATE', 'PRICE_LIST', 'COMPANY_PROFILE', "
            "'PRODUCT_SPEC', 'OTHER')",
            name=op.f("ck_source_document_document_type_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('UPLOADED', 'PROCESSING', 'PROCESSED', 'PROCESSING_FAILED')",
            name=op.f("ck_source_document_status_allowed"),
        ),
        sa.CheckConstraint(
            "size_bytes IS NULL OR size_bytes > 0", name=op.f("ck_source_document_size_bytes_positive")
        ),
        schema="document",
    )
    op.create_index(
        "ix_source_document_exhibitor",
        "source_document",
        ["exhibitor_id", "document_type"],
        schema="document",
    )
    op.create_index(
        "ix_source_document_exhibitor_hash",
        "source_document",
        ["exhibitor_id", "content_hash"],
        schema="document",
    )

    op.create_table(
        "document_file",
        sa.Column("file_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(500), nullable=False),
        sa.Column("original_filename", sa.String(255), nullable=False),
        sa.Column("declared_extension", sa.String(20), nullable=False),
        sa.Column("mime_type", sa.String(150), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("uploaded_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "uploaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.source_document.document_id"],
            name="fk_document_file_document",
        ),
        sa.UniqueConstraint(
            "document_id", "version_no", name=op.f("uq_document_file_document_version")
        ),
        sa.CheckConstraint("version_no > 0", name=op.f("ck_document_file_version_no_positive")),
        sa.CheckConstraint("size_bytes > 0", name=op.f("ck_document_file_size_bytes_positive")),
        schema="document",
    )
    op.create_index(
        "ix_document_file_content_hash", "document_file", ["content_hash"], schema="document"
    )

    op.create_table(
        "document_processing_job",
        sa.Column("processing_job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["document.source_document.document_id"],
            name="fk_document_processing_job_document",
        ),
        sa.ForeignKeyConstraint(
            ["file_id"], ["document.document_file.file_id"], name="fk_document_processing_job_file"
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')",
            name=op.f("ck_document_processing_job_status_allowed"),
        ),
        schema="document",
    )
    op.create_index(
        "ix_document_processing_job_document",
        "document_processing_job",
        ["document_id", "status"],
        schema="document",
    )

    op.create_table(
        "document_access_log",
        sa.Column("access_log_id", postgresql.UUID(as_uuid=True), primary_key=True),
        # document_id/file_id intentionally have no FK - see app/models/document.py module
        # docstring decision 3 (audit trail must survive hard-deletion of the audited document).
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("file_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exhibitor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("action", sa.String(30), nullable=False),
        sa.Column("detail_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.CheckConstraint(
            "action IN ('UPLOAD', 'DOWNLOAD_TOKEN_ISSUED', 'DOWNLOAD', 'DELETE', "
            "'DELETE_BLOCKED', 'PROCESS_REQUESTED')",
            name=op.f("ck_document_access_log_action_allowed"),
        ),
        schema="document",
    )
    op.create_index(
        "ix_document_access_log_document_created",
        "document_access_log",
        ["document_id", "created_at"],
        schema="document",
    )


def downgrade() -> None:
    op.drop_table("document_access_log", schema="document")
    op.drop_table("document_processing_job", schema="document")
    op.drop_table("document_file", schema="document")
    op.drop_table("source_document", schema="document")
    op.execute("DROP SCHEMA IF EXISTS document")
