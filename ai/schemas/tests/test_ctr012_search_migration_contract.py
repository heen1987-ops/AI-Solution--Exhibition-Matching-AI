"""CTR-012 regression tests for WEB_ONLY search persistence and index migration."""

from __future__ import annotations

import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND_DIR = _REPO_ROOT / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

from app.models.search import SEARCH_CHANNELS, SearchSession
from app.services.matching.search_pipeline_contract import (
    KEYWORD_SEARCH_CONTRACT,
    VECTOR_SEARCH_CONTRACT,
)

MIGRATION = (
    _BACKEND_DIR
    / "alembic"
    / "versions"
    / "20260803_0013_search_web_only_indexes.py"
)


def test_search_session_model_accepts_web_only_channel_values() -> None:
    assert SEARCH_CHANNELS == (
        "REGISTERED_WEB",
        "GUEST_WEB",
        "BUYER_WEB",
        "ADMIN_PREVIEW",
    )
    assert SearchSession.__table__.c.channel.type.length == 30


def test_ctr012_migration_backfills_legacy_channels_without_delete() -> None:
    migration_text = MIGRATION.read_text(encoding="utf-8")

    assert "WHEN 'WEB' THEN 'REGISTERED_WEB'" in migration_text
    assert "WHEN 'KIOSK' THEN 'GUEST_WEB'" in migration_text
    assert "DELETE FROM matching.search_session" not in migration_text
    assert "REGISTERED_WEB" in migration_text
    assert "ADMIN_PREVIEW" in migration_text


def test_ctr012_migration_contains_fts_and_vector_index_strategy() -> None:
    migration_text = MIGRATION.read_text(encoding="utf-8")

    assert "USING gin" in migration_text
    assert "to_tsvector" in migration_text
    assert "idx_exhibitor_fts_web_search" in migration_text
    assert "idx_product_fts_web_search" in migration_text
    assert "idx_embedding_document_excerpt_fts_web_search" in migration_text
    assert "USING hnsw" in migration_text
    assert "embedding::vector(1536)" in migration_text
    assert "embedding_dimension = 1536" in migration_text
    assert "vector_cosine_ops" in migration_text


def test_ais009_contract_no_longer_marks_db_indexes_as_missing() -> None:
    assert "FTS_INDEX_MISSING" not in KEYWORD_SEARCH_CONTRACT.unavailable_readiness.reason_codes
    assert (
        "VECTOR_ANN_INDEX_MISSING"
        not in VECTOR_SEARCH_CONTRACT.unavailable_readiness.reason_codes
    )
    assert any(
        "0013_search_web_only_indexes" in item
        for item in KEYWORD_SEARCH_CONTRACT.required_db_objects
    )
    assert any(
        "0013_search_web_only_indexes" in item
        for item in VECTOR_SEARCH_CONTRACT.required_db_objects
    )
