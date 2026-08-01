"""Live PostgreSQL catalog checks for recommendation persistence guarantees.

Set POSTGRES_TEST_DATABASE_URL to an asyncpg URL whose database has already
been migrated with ``alembic upgrade head``.  The test is intentionally
read-only and is skipped when no designated integration database is present.
"""

from __future__ import annotations

import os

import pytest
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
    finally:
        await engine.dispose()

    assert head == "0010_context_rerank"
    assert dedupe_table == "interaction.client_event_dedupe"
    assert "event_date, interaction_event_id" in foreign_key
    assert append_only_trigger is True
    assert context_details_column is True
    assert tuple(context_policy) == ("CONTEXT_RERANK", "PUBLISHED")
    assert context_provenance_columns == 6
