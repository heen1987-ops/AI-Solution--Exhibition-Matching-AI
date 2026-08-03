"""AIS-009 tests for keyword/vector provider and BAC-008 pipeline contracts."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

from app.services.matching.search_pipeline_contract import (
    BAC008_SEARCH_PIPELINE,
    DEFAULT_PROVIDER_READINESS,
    KEYWORD_SEARCH_CONTRACT,
    VECTOR_SEARCH_CONTRACT,
    enabled_provider_names,
    fallback_reason_for_recovery,
    provider_order_for_channel,
    unavailable_fallback_reasons,
)


def test_keyword_contract_fixes_fts_fields_and_score_component() -> None:
    assert KEYWORD_SEARCH_CONTRACT.provider_name == "KEYWORD"
    assert KEYWORD_SEARCH_CONTRACT.score_component == "keyword_score"
    assert "ts_rank_cd" in KEYWORD_SEARCH_CONTRACT.rank_normalization
    assert any(
        "exhibition.product.product_name" in field
        for field in KEYWORD_SEARCH_CONTRACT.target_fields_by_type["EVENT_PRODUCT"]
    )
    assert any(
        "exhibition.exhibitor.company_name" in field
        for field in KEYWORD_SEARCH_CONTRACT.target_fields_by_type["EXHIBITOR"]
    )
    assert KEYWORD_SEARCH_CONTRACT.unavailable_readiness.fallback_reason == "NO_RESULT"


def test_vector_contract_requires_embedding_data_and_query_adapter() -> None:
    assert VECTOR_SEARCH_CONTRACT.provider_name == "VECTOR"
    assert VECTOR_SEARCH_CONTRACT.score_component == "semantic_score"
    assert "cosine distance" in VECTOR_SEARCH_CONTRACT.rank_normalization
    assert any(
        "ai.embedding_vector" in db_object
        for db_object in VECTOR_SEARCH_CONTRACT.required_db_objects
    )
    assert "QUERY_EMBEDDING_ADAPTER_MISSING" in (
        VECTOR_SEARCH_CONTRACT.unavailable_readiness.reason_codes
    )
    assert (
        VECTOR_SEARCH_CONTRACT.unavailable_readiness.fallback_reason
        == "AI_SERVICE_UNAVAILABLE"
    )


def test_default_readiness_keeps_only_structured_provider_enabled() -> None:
    assert enabled_provider_names() == ("STRUCTURED",)
    assert DEFAULT_PROVIDER_READINESS["KEYWORD"].available is False
    assert DEFAULT_PROVIDER_READINESS["VECTOR"].available is False
    assert unavailable_fallback_reasons() == ("AI_SERVICE_UNAVAILABLE", "NO_RESULT")


def test_bac008_pipeline_order_connects_providers_recovery_and_persistence() -> None:
    names = [step.name for step in BAC008_SEARCH_PIPELINE]
    assert names == [
        "validate_actor",
        "interpret_intent",
        "build_search_query",
        "run_available_providers",
        "combine_candidates",
        "decide_recovery",
        "persist_search",
        "respond",
    ]


def test_provider_order_is_web_only_and_includes_fallback_for_guest_web() -> None:
    assert provider_order_for_channel("GUEST_WEB") == (
        "STRUCTURED",
        "KEYWORD",
        "VECTOR",
        "POPULAR",
    )
    assert "KIOSK" not in provider_order_for_channel("REGISTERED_WEB")


def test_recovery_action_maps_to_search_query_fallback_reason() -> None:
    assert fallback_reason_for_recovery("NONE") is None
    assert fallback_reason_for_recovery("CLARIFY") == "NO_RESULT"
    assert (
        fallback_reason_for_recovery("POPULAR_FALLBACK", provider_unavailable=True)
        == "AI_SERVICE_UNAVAILABLE"
    )
