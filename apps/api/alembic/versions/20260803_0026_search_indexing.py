"""publish search-index document/job/cache-invalidation tables (BACKEND-INDEXING, WAVE 2D)

Revision ID: 0026_search_indexing
Revises: 0025_extraction_review
Create Date: 2026-08-02

See app/models/indexing.py module docstring for the full schema rationale (why a new
"indexing" schema instead of reusing "ai", why search_document has no hard FK to
document.published_content_version, why REMOVED is a status flag rather than a hard delete).

Chosen parent revision
----------------------
Chains onto 0025_extraction_review, which creates document.published_content_version -
the table this track's service layer (app/services/indexing/service.py) reads. The chain
0020_interaction_domain -> 0030_event_ingestion_failure is strictly linear and has exactly
one head; the parallel-development branches this migration was originally authored against
were rechained during integration.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0026_search_indexing"
down_revision: str | None = "0025_extraction_review"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "indexing"


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS "indexing"')

    op.create_table(
        "search_document",
        sa.Column("search_document_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        # 검색 문서의 grain은 (tenant, event, exhibitor, tier)다. event_id가 NULL이거나
        # 유니크 키에서 빠지면 같은 업체를 행사 B로 재생성할 때 행사 A의 행을 덮어써
        # 행사 A의 검색 결과에서 그 업체가 사라진다.
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exhibitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tier", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("content_json", postgresql.JSONB(), nullable=False),
        sa.Column("search_text", sa.Text(), nullable=False),
        sa.Column("content_hash", sa.String(71), nullable=False),
        sa.Column("source_version_ids", postgresql.JSONB(), nullable=True),
        sa.Column(
            "generated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            ["exhibition.exhibitor.tenant_id", "exhibition.exhibitor.exhibitor_id"],
            name="fk_search_document_exhibitor_boundary",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "exhibitor_id",
            "tier",
            name=op.f("uq_search_document_exhibitor_tier"),
        ),
        sa.CheckConstraint(
            "tier IN ('PUBLIC', 'VERIFIED_BUYER')", name=op.f("ck_search_document_tier_allowed")
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'REMOVED')", name=op.f("ck_search_document_status_allowed")
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_search_document_event_tier_status",
        "search_document",
        ["tenant_id", "event_id", "tier", "status"],
        schema=_SCHEMA,
    )

    op.create_table(
        "indexing_job",
        sa.Column("indexing_job_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exhibitor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("trigger", sa.String(30), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("requested_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("source_reference", postgresql.JSONB(), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "trigger IN ('APPROVE', 'PUBLISH', 'UNPUBLISH', 'VISIBILITY_CHANGE', "
            "'DOCUMENT_DELETE', 'MANUAL')",
            name=op.f("ck_indexing_job_trigger_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'RUNNING', 'COMPLETED', 'FAILED')",
            name=op.f("ck_indexing_job_status_allowed"),
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_indexing_job_exhibitor_created",
        "indexing_job",
        ["exhibitor_id", "created_at"],
        schema=_SCHEMA,
    )

    op.create_table(
        "cache_invalidation_event",
        sa.Column("cache_invalidation_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("exhibitor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("cache_scope", sa.String(30), nullable=False),
        sa.Column("reason", sa.String(30), nullable=False),
        sa.Column("indexing_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["indexing_job_id"],
            [f"{_SCHEMA}.indexing_job.indexing_job_id"],
            name="fk_cache_invalidation_event_indexing_job",
        ),
        sa.CheckConstraint(
            "cache_scope IN ('EXHIBITOR_DETAIL', 'SEARCH', 'RECOMMENDATION', 'BUYER_MATCH', "
            "'SEMANTIC_INDEX')",
            name=op.f("ck_cache_invalidation_event_cache_scope_allowed"),
        ),
        sa.CheckConstraint(
            "reason IN ('APPROVE', 'PUBLISH', 'UNPUBLISH', 'VISIBILITY_CHANGE', "
            "'DOCUMENT_DELETE', 'MANUAL')",
            name=op.f("ck_cache_invalidation_event_reason_allowed"),
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_cache_invalidation_event_scope_created",
        "cache_invalidation_event",
        ["cache_scope", "created_at"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("cache_invalidation_event", schema=_SCHEMA)
    op.drop_table("indexing_job", schema=_SCHEMA)
    op.drop_table("search_document", schema=_SCHEMA)
    op.execute('DROP SCHEMA IF EXISTS "indexing"')
