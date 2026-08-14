"""publish versioned pgvector object embeddings for hybrid catalog search

Revision ID: 0017_object_embedding
Revises: 0016_kiosk_session
Create Date: 2026-08-02
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects import postgresql

revision: str = "0017_object_embedding"
down_revision: str | None = "0016_kiosk_session"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBEDDING_DIMENSIONS = 512
MODEL_VERSION_ID = uuid.UUID("5f2fe7ac-74d7-59c9-85d3-6b5faf2f7a4e")
MODEL_VERSION = "openai-text-embedding-3-small-512-v1"
MODEL_NAME = "text-embedding-3-small"
_DEPLOYED_AT = datetime(2026, 8, 2, tzinfo=UTC)
_MODEL_CONFIG = {
    "dimensions": EMBEDDING_DIMENSIONS,
    "distance": "COSINE",
    "endpoint": "/v1/embeddings",
    "minimum_relevance": 0.35,
    "input_scope": "APPROVED_PUBLIC_CATALOG_ONLY",
}


def _json_literal(value: dict[str, object]) -> sa.sql.elements.BindParameter:
    return op.inline_literal(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        type_=sa.String(),
    )


def _seed_embedding_model() -> None:
    model_table = sa.table(
        "model_version",
        sa.column("model_version_id", postgresql.UUID(as_uuid=True)),
        sa.column("model_type", sa.String()),
        sa.column("provider", sa.String()),
        sa.column("model_name", sa.String()),
        sa.column("provider_version", sa.String()),
        sa.column("version", sa.String()),
        sa.column("gateway_adapter", sa.String()),
        sa.column("config_json", postgresql.JSONB()),
        sa.column("config_hash", sa.String()),
        sa.column("status", sa.String()),
        sa.column("deployed_at", sa.DateTime(timezone=True)),
        schema="ai",
    )
    canonical = json.dumps(
        _MODEL_CONFIG,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    op.bulk_insert(
        model_table,
        [
            {
                "model_version_id": MODEL_VERSION_ID,
                "model_type": "EMBEDDING",
                "provider": "OPENAI",
                "model_name": MODEL_NAME,
                "provider_version": None,
                "version": MODEL_VERSION,
                "gateway_adapter": "OPENAI_DIRECT",
                "config_json": _json_literal(_MODEL_CONFIG),
                "config_hash": hashlib.sha256(canonical).hexdigest(),
                "status": "DEPLOYED",
                "deployed_at": _DEPLOYED_AT,
            }
        ],
        multiinsert=False,
    )


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    op.execute(
        """
        DO $$
        DECLARE installed_version integer[];
        BEGIN
            SELECT string_to_array(extversion, '.')::integer[]
            INTO installed_version
            FROM pg_extension
            WHERE extname = 'vector';

            IF installed_version < ARRAY[0, 8, 0] THEN
                RAISE EXCEPTION
                    'pgvector 0.8.0 or newer is required for filtered iterative HNSW scans';
            END IF;
        END;
        $$
        """
    )
    _seed_embedding_model()
    op.create_table(
        "object_embedding",
        sa.Column("embedding_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendable_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("content_type", sa.String(30), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column("embedding", VECTOR(EMBEDDING_DIMENSIONS), nullable=False),
        sa.Column("model_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("language", sa.String(10), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                "exhibition.recommendable.tenant_id",
                "exhibition.recommendable.event_id",
                "exhibition.recommendable.recommendable_id",
            ],
            name="fk_object_embedding_recommendable_boundary",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["ai.model_version.model_version_id"],
            name="fk_object_embedding_model_version",
        ),
        sa.CheckConstraint(
            "content_type IN ('SUMMARY', 'TRADE', 'PRODUCT')",
            name="content_type_allowed",
        ),
        sa.CheckConstraint(
            "octet_length(content_hash) = 32",
            name="content_hash_sha256",
        ),
        sa.CheckConstraint(
            "char_length(language) BETWEEN 2 AND 10",
            name="language_length",
        ),
        sa.UniqueConstraint(
            "recommendable_id",
            "content_type",
            "content_hash",
            "model_version_id",
            "language",
            name="uq_object_embedding_content_version",
        ),
        schema="ai",
    )
    op.create_index(
        "uq_object_embedding_active_pointer",
        "object_embedding",
        [
            "tenant_id",
            "event_id",
            "recommendable_id",
            "content_type",
            "language",
        ],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("active IS TRUE"),
    )
    op.create_index(
        "ix_object_embedding_active_lookup",
        "object_embedding",
        ["tenant_id", "event_id", "model_version_id", "language", "active"],
        schema="ai",
    )
    op.create_index(
        "ix_object_embedding_active_hnsw_cosine",
        "object_embedding",
        ["embedding"],
        schema="ai",
        postgresql_using="hnsw",
        postgresql_ops={"embedding": "vector_cosine_ops"},
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_where=sa.text("active IS TRUE AND content_type = 'SUMMARY'"),
    )
    op.execute(
        f"""
        CREATE OR REPLACE FUNCTION ai.validate_object_embedding_model()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE target_type text;
                target_status text;
                target_dimensions integer;
        BEGIN
            SELECT model_type, status, (config_json ->> 'dimensions')::integer
            INTO target_type, target_status, target_dimensions
            FROM ai.model_version
            WHERE model_version_id = NEW.model_version_id;

            IF target_type IS DISTINCT FROM 'EMBEDDING' THEN
                RAISE EXCEPTION 'object embedding requires an EMBEDDING model';
            END IF;
            IF target_dimensions IS DISTINCT FROM {EMBEDDING_DIMENSIONS} THEN
                RAISE EXCEPTION 'object embedding model dimension mismatch';
            END IF;
            IF NEW.active AND target_status IS DISTINCT FROM 'DEPLOYED' THEN
                RAISE EXCEPTION 'active object embedding requires a DEPLOYED model';
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_object_embedding_validate_model
        BEFORE INSERT OR UPDATE ON ai.object_embedding
        FOR EACH ROW EXECUTE FUNCTION ai.validate_object_embedding_model()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ai.lock_catalog_embedding_sources()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended('catalog-embedding-source', 0)
            );
            RETURN NULL;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ai.deactivate_participation_catalog_embeddings(
            source_tenant_id uuid,
            source_event_id uuid,
            source_participation_id uuid
        ) RETURNS void LANGUAGE plpgsql AS $$
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended('catalog-embedding-source', 0)
            );
            UPDATE ai.object_embedding AS embedding
            SET active = false
            FROM exhibition.recommendable AS recommendable
            LEFT JOIN exhibition.event_product AS event_product
              ON event_product.tenant_id = recommendable.tenant_id
             AND event_product.event_id = recommendable.event_id
             AND event_product.event_product_id = recommendable.event_product_id
            WHERE embedding.tenant_id = source_tenant_id
              AND embedding.event_id = source_event_id
              AND embedding.recommendable_id = recommendable.recommendable_id
              AND embedding.active IS TRUE
              AND recommendable.tenant_id = source_tenant_id
              AND recommendable.event_id = source_event_id
              AND (
                  recommendable.participation_id = source_participation_id
                  OR event_product.participation_id = source_participation_id
              );
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ai.invalidate_summary_from_event_product()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                PERFORM ai.deactivate_participation_catalog_embeddings(
                    OLD.tenant_id, OLD.event_id, OLD.participation_id
                );
            END IF;
            IF TG_OP IN ('INSERT', 'UPDATE') THEN
                PERFORM ai.deactivate_participation_catalog_embeddings(
                    NEW.tenant_id, NEW.event_id, NEW.participation_id
                );
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ai.invalidate_summary_from_product()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE source_row record;
        BEGIN
            FOR source_row IN
                SELECT DISTINCT tenant_id, event_id, participation_id
                FROM exhibition.event_product
                WHERE product_id = OLD.product_id
            LOOP
                PERFORM ai.deactivate_participation_catalog_embeddings(
                    source_row.tenant_id,
                    source_row.event_id,
                    source_row.participation_id
                );
            END LOOP;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ai.invalidate_summary_from_participation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                PERFORM ai.deactivate_participation_catalog_embeddings(
                    OLD.tenant_id, OLD.event_id, OLD.participation_id
                );
            END IF;
            IF TG_OP IN ('INSERT', 'UPDATE') THEN
                PERFORM ai.deactivate_participation_catalog_embeddings(
                    NEW.tenant_id, NEW.event_id, NEW.participation_id
                );
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ai.invalidate_summary_from_exhibitor()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE source_row record;
        BEGIN
            FOR source_row IN
                SELECT tenant_id, event_id, participation_id
                FROM exhibition.exhibitor_participation
                WHERE tenant_id = OLD.tenant_id
                  AND exhibitor_id = OLD.exhibitor_id
            LOOP
                PERFORM ai.deactivate_participation_catalog_embeddings(
                    source_row.tenant_id,
                    source_row.event_id,
                    source_row.participation_id
                );
            END LOOP;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ai.invalidate_embeddings_from_recommendable()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE source_participation_id uuid;
        BEGIN
            PERFORM pg_advisory_xact_lock(
                hashtextextended('catalog-embedding-source', 0)
            );
            IF TG_OP IN ('UPDATE', 'DELETE') THEN
                UPDATE ai.object_embedding AS embedding
                SET active = false
                WHERE embedding.tenant_id = OLD.tenant_id
                  AND embedding.event_id = OLD.event_id
                  AND embedding.recommendable_id = OLD.recommendable_id
                  AND embedding.active IS TRUE;
                source_participation_id := OLD.participation_id;
                IF source_participation_id IS NULL
                   AND OLD.event_product_id IS NOT NULL THEN
                    SELECT participation_id
                    INTO source_participation_id
                    FROM exhibition.event_product
                    WHERE tenant_id = OLD.tenant_id
                      AND event_id = OLD.event_id
                      AND event_product_id = OLD.event_product_id;
                END IF;
                IF source_participation_id IS NOT NULL THEN
                    PERFORM ai.deactivate_participation_catalog_embeddings(
                        OLD.tenant_id, OLD.event_id, source_participation_id
                    );
                END IF;
            END IF;

            IF TG_OP IN ('INSERT', 'UPDATE') THEN
                UPDATE ai.object_embedding AS embedding
                SET active = false
                WHERE embedding.tenant_id = NEW.tenant_id
                  AND embedding.event_id = NEW.event_id
                  AND embedding.recommendable_id = NEW.recommendable_id
                  AND embedding.active IS TRUE;
                source_participation_id := NEW.participation_id;
                IF source_participation_id IS NULL
                   AND NEW.event_product_id IS NOT NULL THEN
                    SELECT participation_id
                    INTO source_participation_id
                    FROM exhibition.event_product
                    WHERE tenant_id = NEW.tenant_id
                      AND event_id = NEW.event_id
                      AND event_product_id = NEW.event_product_id;
                END IF;
                IF source_participation_id IS NOT NULL THEN
                    PERFORM ai.deactivate_participation_catalog_embeddings(
                        NEW.tenant_id, NEW.event_id, source_participation_id
                    );
                END IF;
            END IF;

            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_embedding_source_lock_event_product
        BEFORE INSERT OR UPDATE OR DELETE ON exhibition.event_product
        FOR EACH STATEMENT EXECUTE FUNCTION ai.lock_catalog_embedding_sources()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_embedding_source_lock_product
        BEFORE INSERT OR UPDATE OR DELETE ON exhibition.product
        FOR EACH STATEMENT EXECUTE FUNCTION ai.lock_catalog_embedding_sources()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_embedding_source_lock_participation
        BEFORE INSERT OR UPDATE OR DELETE ON exhibition.exhibitor_participation
        FOR EACH STATEMENT EXECUTE FUNCTION ai.lock_catalog_embedding_sources()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_embedding_source_lock_exhibitor
        BEFORE INSERT OR UPDATE OR DELETE ON exhibition.exhibitor
        FOR EACH STATEMENT EXECUTE FUNCTION ai.lock_catalog_embedding_sources()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_embedding_source_lock_recommendable
        BEFORE INSERT OR UPDATE OR DELETE ON exhibition.recommendable
        FOR EACH STATEMENT EXECUTE FUNCTION ai.lock_catalog_embedding_sources()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_embedding_invalidate_event_product_summary
        AFTER INSERT OR UPDATE OF tenant_id, event_id, participation_id, product_id,
            approval_status OR DELETE ON exhibition.event_product
        FOR EACH ROW EXECUTE FUNCTION ai.invalidate_summary_from_event_product()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_embedding_invalidate_product_summary
        BEFORE UPDATE OF exhibitor_id, product_name, product_summary, production_method,
            master_approval_status, deleted_at OR DELETE ON exhibition.product
        FOR EACH ROW EXECUTE FUNCTION ai.invalidate_summary_from_product()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_embedding_invalidate_participation_summary
        AFTER INSERT OR UPDATE OF tenant_id, event_id, exhibitor_id, participation_status,
            promotion_summary OR DELETE ON exhibition.exhibitor_participation
        FOR EACH ROW EXECUTE FUNCTION ai.invalidate_summary_from_participation()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_embedding_invalidate_exhibitor_summary
        BEFORE UPDATE OF tenant_id, company_name, company_summary,
            master_approval_status, deleted_at OR DELETE ON exhibition.exhibitor
        FOR EACH ROW EXECUTE FUNCTION ai.invalidate_summary_from_exhibitor()
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_embedding_invalidate_recommendable
        AFTER INSERT OR UPDATE OF tenant_id, event_id, object_type, event_product_id,
            participation_id, active OR DELETE ON exhibition.recommendable
        FOR EACH ROW EXECUTE FUNCTION ai.invalidate_embeddings_from_recommendable()
        """
    )


def downgrade() -> None:
    op.execute(
        f"""
        DO $$
        BEGIN
            IF EXISTS (
                SELECT 1 FROM ai.ai_run
                WHERE model_version_id = '{MODEL_VERSION_ID}'::uuid
            ) OR EXISTS (
                SELECT 1 FROM matching.recommendation_session
                WHERE ranking_model_version_id = '{MODEL_VERSION_ID}'::uuid
                   OR explanation_model_version_id = '{MODEL_VERSION_ID}'::uuid
            ) THEN
                RAISE EXCEPTION
                    'cannot downgrade object embeddings while runtime or audit rows reference the seeded model';
            END IF;
        END;
        $$
        """
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_embedding_invalidate_recommendable "
        "ON exhibition.recommendable"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_embedding_invalidate_exhibitor_summary "
        "ON exhibition.exhibitor"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_embedding_invalidate_participation_summary "
        "ON exhibition.exhibitor_participation"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_embedding_invalidate_product_summary "
        "ON exhibition.product"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_embedding_invalidate_event_product_summary "
        "ON exhibition.event_product"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_embedding_source_lock_recommendable "
        "ON exhibition.recommendable"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_embedding_source_lock_exhibitor "
        "ON exhibition.exhibitor"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_embedding_source_lock_participation "
        "ON exhibition.exhibitor_participation"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_embedding_source_lock_product ON exhibition.product"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_embedding_source_lock_event_product "
        "ON exhibition.event_product"
    )
    op.execute("DROP FUNCTION IF EXISTS ai.invalidate_embeddings_from_recommendable()")
    op.execute("DROP FUNCTION IF EXISTS ai.invalidate_summary_from_exhibitor()")
    op.execute("DROP FUNCTION IF EXISTS ai.invalidate_summary_from_participation()")
    op.execute("DROP FUNCTION IF EXISTS ai.invalidate_summary_from_product()")
    op.execute("DROP FUNCTION IF EXISTS ai.invalidate_summary_from_event_product()")
    op.execute(
        "DROP FUNCTION IF EXISTS ai.deactivate_participation_catalog_embeddings(uuid, uuid, uuid)"
    )
    op.execute("DROP FUNCTION IF EXISTS ai.lock_catalog_embedding_sources()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_object_embedding_validate_model "
        "ON ai.object_embedding"
    )
    op.execute("DROP FUNCTION IF EXISTS ai.validate_object_embedding_model()")
    op.drop_table("object_embedding", schema="ai")

    # Deployed model rows are immutable by contract. Temporarily remove only the
    # guarding trigger so this migration can reverse its own deterministic seed.
    op.execute("DROP TRIGGER IF EXISTS trg_model_version_immutable ON ai.model_version")
    op.execute(
        "DELETE FROM ai.model_version "
        f"WHERE model_version_id = '{MODEL_VERSION_ID}'::uuid"
    )
    op.execute(
        """
        CREATE TRIGGER trg_model_version_immutable
        BEFORE UPDATE OR DELETE ON ai.model_version
        FOR EACH ROW EXECUTE FUNCTION ai.protect_deployed_model()
        """
    )
    # The vector extension is shared infrastructure and is intentionally retained.
