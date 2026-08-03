"""align WEB_ONLY search persistence channels and search indexes

CTR-012 follows CR-001/AIS-009. It keeps previously stored rows by converting
legacy `WEB` to `REGISTERED_WEB` and legacy `KIOSK` to `GUEST_WEB`, widens the
channel column, then recreates the CHECK constraint with WEB_ONLY channels.

It also adds the database side of the AIS-009 provider contract:
- expression GIN FTS indexes for approved exhibitor/product/search excerpt text;
- pgvector lookup and HNSW cosine indexes for semantic search.

Revision ID: 0013_search_web_only_indexes
Revises: 0012_ai_schema
Create Date: 2026-08-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0013_search_web_only_indexes"
down_revision: str | None = "0012_ai_schema"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

WEB_ONLY_CHANNEL_CHECK = (
    "channel IN ('REGISTERED_WEB', 'GUEST_WEB', 'BUYER_WEB', 'ADMIN_PREVIEW')"
)
LEGACY_CHANNEL_CHECK = "channel IN ('WEB', 'KIOSK')"


def upgrade() -> None:
    op.drop_constraint(
        op.f("ck_search_session_channel_allowed"),
        "search_session",
        schema="matching",
        type_="check",
    )
    op.alter_column(
        "search_session",
        "channel",
        schema="matching",
        existing_type=sa.String(length=10),
        type_=sa.String(length=30),
        existing_nullable=False,
    )
    op.execute(
        """
        UPDATE matching.search_session
        SET channel = CASE channel
            WHEN 'WEB' THEN 'REGISTERED_WEB'
            WHEN 'KIOSK' THEN 'GUEST_WEB'
            ELSE channel
        END
        WHERE channel IN ('WEB', 'KIOSK')
        """
    )
    op.create_check_constraint(
        op.f("ck_search_session_channel_allowed"),
        "search_session",
        WEB_ONLY_CHANNEL_CHECK,
        schema="matching",
    )

    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_exhibitor_fts_web_search
        ON exhibition.exhibitor
        USING gin (
            to_tsvector(
                'simple',
                coalesce(company_name, '') || ' ' || coalesce(company_summary, '')
            )
        )
        WHERE deleted_at IS NULL AND master_approval_status = 'APPROVED'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_product_fts_web_search
        ON exhibition.product
        USING gin (
            to_tsvector(
                'simple',
                coalesce(product_name, '') || ' ' ||
                coalesce(product_summary, '') || ' ' ||
                coalesce(production_method, '')
            )
        )
        WHERE deleted_at IS NULL AND master_approval_status = 'APPROVED'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_exhibitor_participation_fts_web_search
        ON exhibition.exhibitor_participation
        USING gin (to_tsvector('simple', coalesce(promotion_summary, '')))
        WHERE participation_status = 'APPROVED'
        """
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_embedding_document_excerpt_fts_web_search
        ON ai.embedding_document
        USING gin (to_tsvector('simple', coalesce(content_excerpt, '')))
        WHERE active AND content_excerpt IS NOT NULL
        """
    )

    op.create_index(
        "idx_embedding_vector_model_dimension_active",
        "embedding_vector",
        ["embedding_model", "embedding_dimension"],
        unique=False,
        schema="ai",
        postgresql_where=sa.text("active"),
    )
    op.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_embedding_vector_hnsw_cosine_1536_active
        ON ai.embedding_vector
        USING hnsw ((embedding::vector(1536)) vector_cosine_ops)
        WHERE active AND embedding_dimension = 1536
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ai.idx_embedding_vector_hnsw_cosine_1536_active")
    op.drop_index(
        "idx_embedding_vector_model_dimension_active",
        table_name="embedding_vector",
        schema="ai",
    )
    op.execute("DROP INDEX IF EXISTS ai.idx_embedding_document_excerpt_fts_web_search")
    op.execute(
        "DROP INDEX IF EXISTS exhibition.idx_exhibitor_participation_fts_web_search"
    )
    op.execute("DROP INDEX IF EXISTS exhibition.idx_product_fts_web_search")
    op.execute("DROP INDEX IF EXISTS exhibition.idx_exhibitor_fts_web_search")

    op.drop_constraint(
        op.f("ck_search_session_channel_allowed"),
        "search_session",
        schema="matching",
        type_="check",
    )
    op.execute(
        """
        UPDATE matching.search_session
        SET channel = CASE channel
            WHEN 'REGISTERED_WEB' THEN 'WEB'
            WHEN 'BUYER_WEB' THEN 'WEB'
            WHEN 'ADMIN_PREVIEW' THEN 'WEB'
            WHEN 'GUEST_WEB' THEN 'KIOSK'
            ELSE channel
        END
        WHERE channel IN ('REGISTERED_WEB', 'GUEST_WEB', 'BUYER_WEB', 'ADMIN_PREVIEW')
        """
    )
    op.alter_column(
        "search_session",
        "channel",
        schema="matching",
        existing_type=sa.String(length=30),
        type_=sa.String(length=10),
        existing_nullable=False,
    )
    op.create_check_constraint(
        op.f("ck_search_session_channel_allowed"),
        "search_session",
        LEGACY_CHANNEL_CHECK,
        schema="matching",
    )
