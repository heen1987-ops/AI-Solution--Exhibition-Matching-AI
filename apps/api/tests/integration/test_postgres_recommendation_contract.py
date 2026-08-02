"""Live PostgreSQL catalog checks for recommendation persistence guarantees.

Set POSTGRES_TEST_DATABASE_URL to an asyncpg URL whose database has already
been migrated with ``alembic upgrade head``.  The test is intentionally
read-only and is skipped when no designated integration database is present.
"""

from __future__ import annotations

import os

import pytest
from app.core.config import SEARCH_EMBEDDING_MODEL_CONFIG_HASH_V1
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

DATABASE_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")

pytestmark = [
    pytest.mark.postgres_integration,
    pytest.mark.skipif(
        not DATABASE_URL,
        reason="POSTGRES_TEST_DATABASE_URL is not configured",
    ),
]


@pytest.mark.asyncio
async def test_live_postgres_recommendation_guarantees() -> None:
    assert DATABASE_URL is not None
    engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            head = (
                await connection.execute(
                    text("SELECT version_num FROM alembic_version")
                )
            ).scalar_one()
            dedupe_table = (
                await connection.execute(
                    text("SELECT to_regclass('interaction.client_event_dedupe')::text")
                )
            ).scalar_one()
            foreign_key = (
                await connection.execute(
                    text(
                        "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                        "WHERE conname = 'fk_client_event_dedupe_interaction_event'"
                    )
                )
            ).scalar_one()
            append_only_trigger = (
                await connection.execute(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM pg_trigger "
                        "WHERE tgname = 'trg_client_event_dedupe_append_only' "
                        "AND NOT tgisinternal)"
                    )
                )
            ).scalar_one()
            context_details_column = (
                await connection.execute(
                    text(
                        "SELECT EXISTS ("
                        "SELECT 1 FROM information_schema.columns "
                        "WHERE table_schema = 'matching' "
                        "AND table_name = 'match_result' "
                        "AND column_name = 'context_details')"
                    )
                )
            ).scalar_one()
            context_policy = (
                await connection.execute(
                    text(
                        "SELECT policy_type, status FROM matching.match_policy_version "
                        "WHERE version = 'context-rerank-v1.0'"
                    )
                )
            ).one()
            context_provenance_columns = (
                await connection.execute(
                    text(
                        "SELECT count(*) FROM information_schema.columns "
                        "WHERE table_schema = 'matching' AND table_name = 'match_result' "
                        "AND column_name IN ('context_policy_version_id', "
                        "'context_components', 'context_effective_weights', "
                        "'context_contributions', 'context_input_fingerprint', "
                        "'context_score_fingerprint')"
                    )
                )
            ).scalar_one()
            vector_contract = (
                await connection.execute(
                    text(
                        "SELECT to_regclass('ai.object_embedding')::text, "
                        "(SELECT extversion FROM pg_extension WHERE extname = 'vector'), "
                        "format_type(a.atttypid, a.atttypmod) "
                        "FROM pg_attribute a "
                        "WHERE a.attrelid = 'ai.object_embedding'::regclass "
                        "AND a.attname = 'embedding'"
                    )
                )
            ).one()
            embedding_model = (
                await connection.execute(
                    text(
                        "SELECT model_type, provider, model_name, gateway_adapter, "
                        "config_hash, status, config_json ->> 'dimensions', "
                        "config_json ->> 'distance' "
                        "FROM ai.model_version "
                        "WHERE model_version_id = "
                        "'5f2fe7ac-74d7-59c9-85d3-6b5faf2f7a4e'::uuid"
                    )
                )
            ).one()
            hnsw_index = (
                await connection.execute(
                    text(
                        "SELECT indexdef FROM pg_indexes "
                        "WHERE schemaname = 'ai' "
                        "AND indexname = 'ix_object_embedding_active_hnsw_cosine'"
                    )
                )
            ).scalar_one()
            source_invalidation_triggers = (
                (
                    await connection.execute(
                        text(
                            "SELECT tgname FROM pg_trigger "
                            "WHERE tgname IN ("
                            "'trg_embedding_source_lock_event_product', "
                            "'trg_embedding_source_lock_product', "
                            "'trg_embedding_source_lock_participation', "
                            "'trg_embedding_source_lock_exhibitor', "
                            "'trg_embedding_source_lock_recommendable', "
                            "'trg_embedding_invalidate_event_product_summary', "
                            "'trg_embedding_invalidate_product_summary', "
                            "'trg_embedding_invalidate_participation_summary', "
                            "'trg_embedding_invalidate_exhibitor_summary', "
                            "'trg_embedding_invalidate_recommendable') "
                            "AND NOT tgisinternal"
                        )
                    )
                )
                .scalars()
                .all()
            )
    finally:
        await engine.dispose()

    assert head == "0017_object_embedding"
    assert dedupe_table == "interaction.client_event_dedupe"
    assert "event_date, interaction_event_id" in foreign_key
    assert append_only_trigger is True
    assert context_details_column is True
    assert tuple(context_policy) == ("CONTEXT_RERANK", "PUBLISHED")
    assert context_provenance_columns == 6
    assert vector_contract[0] == "ai.object_embedding"
    assert vector_contract[1] is not None
    assert tuple(int(part) for part in vector_contract[1].split(".")) >= (0, 8, 0)
    assert vector_contract[2] == "vector(512)"
    assert tuple(embedding_model) == (
        "EMBEDDING",
        "OPENAI",
        "text-embedding-3-small",
        "OPENAI_DIRECT",
        SEARCH_EMBEDDING_MODEL_CONFIG_HASH_V1,
        "DEPLOYED",
        "512",
        "COSINE",
    )
    assert "USING hnsw" in hnsw_index
    assert "vector_cosine_ops" in hnsw_index
    assert "ACTIVE IS TRUE" in hnsw_index.upper()
    assert "CONTENT_TYPE = 'SUMMARY'" in hnsw_index.upper()
    assert set(source_invalidation_triggers) == {
        "trg_embedding_source_lock_event_product",
        "trg_embedding_source_lock_product",
        "trg_embedding_source_lock_participation",
        "trg_embedding_source_lock_exhibitor",
        "trg_embedding_source_lock_recommendable",
        "trg_embedding_invalidate_event_product_summary",
        "trg_embedding_invalidate_product_summary",
        "trg_embedding_invalidate_participation_summary",
        "trg_embedding_invalidate_exhibitor_summary",
        "trg_embedding_invalidate_recommendable",
    }
