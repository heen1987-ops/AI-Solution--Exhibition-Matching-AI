"""AIS-006 유닛 테스트 - `SearchProvider` Protocol + `MockSearchProvider`.

배치 위치에 대한 메모: 이 테스트가 다루는 대상(`search_provider.py`)은
`backend/app/services/matching/`에 있지만, 그 디렉터리 안의 다른 파일(candidate_generator
등)은 이번 디스패치에서 "읽기 전용"으로 지정돼 새 테스트 파일조차 그 옆에 두지 않았다.
`backend/tests/**`·루트 `tests/**`는 QA_SECURITY 전속 경로라 그쪽에도 둘 수 없다. 그래서
이번 디스패치의 다른 산출물(AIS-005 스키마 테스트)과 함께 `ai/schemas/tests/`(AI_SEARCH
소유, `.harness/locks.yaml`상 `ai/**` 전체)에 둔다 - QA_SECURITY가 Wave 2 하드닝 때
`backend/tests/test_search_provider.py`로 복제·이관해도 무방하다(HANDOFF 참고).

실행: `python -m pytest ai/schemas/tests/test_search_provider_protocol.py -v`
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

_BACKEND_DIR = Path(__file__).resolve().parents[3] / "backend"
sys.path.insert(0, str(_BACKEND_DIR))

from app.services.matching.search_provider import (
    CandidateCombiner,
    MockSearchProvider,
    ReciprocalRankFusionCombiner,
    SearchCandidate,
    SearchProvider,
    SearchQuery,
    SearchScoreBreakdown,
    StructuredSearchProvider,
)

EVENT_ID = uuid.uuid4()
CONCEPT_A = uuid.uuid4()
CONCEPT_B = uuid.uuid4()


def _candidate(rank: int, *, provider: str = "MOCK") -> SearchCandidate:
    return SearchCandidate(
        recommendable_id=uuid.uuid4(),
        rank=rank,
        source_provider=provider,
        matched_concept_ids=frozenset({CONCEPT_A}),
    )


def _query(**overrides: object) -> SearchQuery:
    payload: dict[str, object] = {
        "event_id": EVENT_ID,
        "target_type": "EVENT_PRODUCT",
        "raw_text": "달지 않은 막걸리",
        "required_concept_ids": frozenset({CONCEPT_A}),
        "preferred_concept_ids": frozenset({CONCEPT_B}),
    }
    payload.update(overrides)
    return SearchQuery(**payload)  # type: ignore[arg-type]


def test_mock_provider_satisfies_search_provider_protocol() -> None:
    mock = MockSearchProvider(canned_results=[_candidate(1), _candidate(2)])
    assert isinstance(mock, SearchProvider)


@pytest.mark.asyncio
async def test_mock_provider_returns_canned_results_in_order() -> None:
    candidates = [_candidate(1), _candidate(2), _candidate(3)]
    mock = MockSearchProvider(canned_results=candidates)

    result = await mock.search(_query(), limit=10)

    assert result == candidates
    assert [c.rank for c in result] == [1, 2, 3]


@pytest.mark.asyncio
async def test_mock_provider_respects_limit() -> None:
    candidates = [_candidate(i) for i in range(1, 6)]
    mock = MockSearchProvider(canned_results=candidates)

    result = await mock.search(_query(), limit=2)

    assert len(result) == 2
    assert result == candidates[:2]


@pytest.mark.asyncio
async def test_mock_provider_rejects_non_positive_limit() -> None:
    mock = MockSearchProvider(canned_results=[_candidate(1)])
    with pytest.raises(ValueError):
        await mock.search(_query(), limit=0)


@pytest.mark.asyncio
async def test_mock_provider_records_call_count_and_received_query() -> None:
    mock = MockSearchProvider(canned_results=[])
    query = _query(raw_text="친환경 포장재")

    await mock.search(query, limit=5)
    await mock.search(query, limit=5)

    assert mock.call_count == 2
    assert mock.received_queries == [query, query]


def test_search_query_is_frozen_dataclass() -> None:
    query = _query()
    with pytest.raises(AttributeError):
        query.event_id = uuid.uuid4()  # type: ignore[misc]


def test_search_candidate_default_score_breakdown_is_none() -> None:
    candidate = _candidate(1)
    assert candidate.score_breakdown is None


def test_score_breakdown_shape_holds_all_wave2_component_fields() -> None:
    """§11.6 - 값은 아직 계산하지 않지만(전부 None/기본값 가능) 모양은 고정돼 있어야
    한다."""

    breakdown = SearchScoreBreakdown(
        structured_score=0.9,
        keyword_score=0.4,
        semantic_score=0.8,
        data_quality_score=1.0,
        availability_score=0.5,
        final_score=0.72,
        reason_codes=("CONCEPT_MATCH", "IN_STOCK"),
    )
    assert breakdown.final_score == 0.72
    assert breakdown.reason_codes == ("CONCEPT_MATCH", "IN_STOCK")


def test_score_breakdown_all_fields_optional() -> None:
    breakdown = SearchScoreBreakdown()
    assert breakdown.structured_score is None
    assert breakdown.final_score is None
    assert breakdown.reason_codes == ()


def test_rrf_combiner_satisfies_candidate_combiner_protocol() -> None:
    combiner = ReciprocalRankFusionCombiner()
    assert isinstance(combiner, CandidateCombiner)


def test_rrf_combiner_merges_duplicate_candidates_across_channels() -> None:
    shared_id = uuid.uuid4()
    keyword_only_id = uuid.uuid4()
    semantic_only_id = uuid.uuid4()
    combiner = ReciprocalRankFusionCombiner(
        channel_weights={"KEYWORD": "1.0", "VECTOR": "1.0"}
    )

    result = combiner.combine(
        {
            "KEYWORD": [
                SearchCandidate(
                    recommendable_id=shared_id,
                    rank=1,
                    source_provider="KEYWORD",
                ),
                SearchCandidate(
                    recommendable_id=keyword_only_id,
                    rank=2,
                    source_provider="KEYWORD",
                ),
            ],
            "VECTOR": [
                SearchCandidate(
                    recommendable_id=shared_id,
                    rank=2,
                    source_provider="VECTOR",
                ),
                SearchCandidate(
                    recommendable_id=semantic_only_id,
                    rank=1,
                    source_provider="VECTOR",
                ),
            ],
        }
    )

    assert result[0].recommendable_id == shared_id
    assert result[0].rank == 1
    assert result[0].source_provider == "KEYWORD+VECTOR"
    assert result[0].score_breakdown is not None
    assert result[0].score_breakdown.reason_codes == (
        "RETRIEVED_BY_KEYWORD",
        "RETRIEVED_BY_VECTOR",
    )


def test_rrf_combiner_rejects_invalid_k() -> None:
    with pytest.raises(ValueError):
        ReciprocalRankFusionCombiner(k=0).combine({})


def test_structured_search_provider_satisfies_search_provider_protocol() -> None:
    provider = StructuredSearchProvider(session=object())  # type: ignore[arg-type]
    assert isinstance(provider, SearchProvider)


def test_structured_filters_default_empty_mapping() -> None:
    query = _query()
    assert dict(query.structured_filters) == {}


def test_structured_filters_can_carry_channel_specific_values() -> None:
    query = _query(structured_filters={"price_max": 50000, "tasting_required": True})
    assert query.structured_filters["price_max"] == 50000
