"""AIS-008 tests for no-result and low-confidence recovery decisions."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

from app.services.matching.search_recovery import (
    SearchRecoveryInput,
    decide_search_recovery,
)


def _input(**overrides: object) -> SearchRecoveryInput:
    payload: dict[str, object] = {
        "channel": "GUEST_WEB",
        "query_type": "FREE_TEXT",
        "result_count": 5,
        "confidence": 0.8,
    }
    payload.update(overrides)
    return SearchRecoveryInput(**payload)  # type: ignore[arg-type]


def test_healthy_result_set_needs_no_recovery() -> None:
    decision = decide_search_recovery(_input())
    assert decision.action == "NONE"
    assert decision.reason_codes == ()


def test_low_confidence_asks_for_clarification_without_pii() -> None:
    decision = decide_search_recovery(_input(result_count=0, confidence=0.2))
    assert decision.action == "CLARIFY"
    assert decision.meta_code == "SEARCH_NO_RESULT"
    assert decision.clarification_question is not None
    assert "전화" not in decision.clarification_question
    assert "이메일" not in decision.clarification_question


def test_strict_required_concepts_no_result_broadens_before_popular_fallback() -> None:
    decision = decide_search_recovery(
        _input(result_count=0, required_concept_count=2, confidence=0.8)
    )
    assert decision.action == "BROADEN_CONCEPTS"
    assert decision.reason_codes == ("STRICT_CONCEPTS_NO_RESULT",)


def test_ontology_gap_free_text_uses_popular_keyword_fallback() -> None:
    decision = decide_search_recovery(
        _input(
            result_count=0,
            confidence=0.8,
            unmapped_term_count=1,
            has_raw_text=True,
        )
    )
    assert decision.action == "POPULAR_FALLBACK"
    assert decision.reason_codes == ("ONTOLOGY_GAP_KEYWORD_FALLBACK",)


def test_category_no_result_uses_category_fallback() -> None:
    decision = decide_search_recovery(
        _input(query_type="CATEGORY", result_count=0, confidence=0.8)
    )
    assert decision.action == "CATEGORY_FALLBACK"


def test_low_recall_nonempty_result_broadens() -> None:
    decision = decide_search_recovery(_input(result_count=1, confidence=0.8))
    assert decision.action == "BROADEN_CONCEPTS"
    assert decision.meta_code is None


def test_invalid_counts_are_rejected() -> None:
    with pytest.raises(ValueError):
        decide_search_recovery(_input(result_count=-1))


def test_invalid_confidence_is_rejected() -> None:
    with pytest.raises(ValueError):
        decide_search_recovery(_input(confidence=1.1))
