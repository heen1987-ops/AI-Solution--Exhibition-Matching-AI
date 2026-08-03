"""하이브리드 검색 Provider 인터페이스와 기본 구현 (AIS-006/AIS-007/AIS-009).

근거: `.harness/backlog.yaml` AIS-006 acceptance, `docs/redesign-v2/common/C-4-search-recommendation-engine.md`
§1(RRF vs 가중합 레이어 분리 최종 결정)·§2(`GUEST_WEB_SEARCH_SCORE_V1`)·§3(신규 검색 채널:
키워드 FTS·벡터·자연어 의도 추출), `.harness/contracts/domain-model.md` §7(object_type
4종)·§8(matching 정책)·§12(자연어 검색 채널 3종).

이 모듈이 정의하는 것
----------------------
1. `SearchProvider` - 채널 하나(구조화/키워드/벡터)가 구현해야 할 최소 계약
   (`async def search(query, limit) -> list[SearchCandidate]`).
2. `SearchQuery`/`SearchCandidate` DTO - Provider 입출력 자료구조.
3. `SearchScoreBreakdown` - §11.6 점수 결과 인터페이스(구조화/키워드/의미/데이터품질/
   부스가용성/최종 점수 + reason_codes).
4. `ReciprocalRankFusionCombiner` - 여러 Provider 결과를 기존
   `candidate_generator.reciprocal_rank_fusion`으로 병합하는 기본 구현.
5. `StructuredSearchProvider` - 현재 실제로 동작하는 구조화 검색 채널 어댑터.
6. `MockSearchProvider` - 테스트 더블. 실제 검색채널 없이 이 Protocol에 의존하는 상위
   코드(오케스트레이터 등)를 단위 테스트하기 위한 것으로, Wave 2 구현체가 상속하는
   기반 클래스가 아니다.

이번 Wave에 구현하지 않는 것
---------------------------
- `KeywordSearchProvider` - PostgreSQL FTS 채널(C-4 §3). AIS-009가
  `search_pipeline_contract.py`에 대상 필드·rank normalization·unavailable fallback을
  고정했지만, 실제 GIN/tsvector migration과 SQL provider는 후속 CONTRACTS/BACKEND 작업이다.
- `VectorSearchProvider` - pgvector 코사인 유사도 채널(C-4 §3). `ai.embedding_document`/
  `ai.embedding_vector` 테이블은 생겼지만 query embedding 생성 어댑터, ANN index,
  활성 embedding 데이터 availability는 아직 후속 작업이다. AIS-009는 이 조건이 충족될
  때까지 `AI_SERVICE_UNAVAILABLE` 또는 `NO_RESULT` fallback으로 내려가는 계약만 고정한다.
- `HybridSearchService` - 위 세 Provider(또는 그 부분집합)를 호출하고 `CandidateCombiner`로
  합쳐 최종 `SearchCandidate` 목록을 만들고 `matching.search_*` 테이블에 저장하는 조합
  지점. 이것은 BAC-008 검색 API 파사드에서 연결한다.

`reciprocal_rank_fusion`(candidate_generator.py)과의 관계 - 대체가 아니라 감싸는 관계
----------------------------------------------------------------------------------------
`candidate_generator.py`를 읽고 확인한 내용 그대로 문서화한다(추측이 아니다):

- 그 파일은 이미 `ChannelHit`/`ChannelResult`(단일 채널 결과)와 `CandidateHit`(병합
  이후 결과), 그리고 여러 `ChannelResult`를 받아 가중 RRF로 합치는 순수 함수
  `reciprocal_rank_fusion(channel_results, *, channel_weights=None, k=60)`을 이미
  완전히 구현해 두었다(9단계 19절 근거). `structured_search_products`/
  `structured_search_exhibitors`가 현재 유일하게 동작하는 채널이며 각각 하나의
  `ChannelResult`를 만든다.
- 이 파일의 `SearchProvider.search()`가 반환하는 `list[SearchCandidate]`는
  `ChannelHit`와 형태가 다르다(더 상위 계층 DTO - `source_provider`/
  `score_breakdown` 등 hybrid 검색 전용 필드를 더 가진다). Wave 2가 실제로 여러
  `SearchProvider`(구조화/키워드/벡터)를 만들면, `CandidateCombiner`의 구현체는
  각 Provider의 `SearchCandidate` 목록을 `ChannelHit`/`ChannelResult`로 변환하고
  **기존 `reciprocal_rank_fusion`을 그대로 호출**한 뒤, 그 결과(`CandidateHit`)를 다시
  `SearchCandidate`로 되돌리는 얇은 어댑터가 되어야 한다. AIS-007의
  `ReciprocalRankFusionCombiner`가 이 역할을 수행한다 - RRF 순위 융합 수식을 이 파일에
  다시 구현하지 않는다(C-4 §1 "RRF는 1단계 후보 검색 책임, 가중합은 2단계 점수 계산
  책임 - 서로 다른 레이어라 공존"과 정확히 같은 경계).

target_type
-----------
`.harness/contracts/domain-model.md` §7의 `exhibition.recommendable.object_type IN
('BOOTH','EVENT_PRODUCT','EXHIBITOR','PROGRAM')` 4종 그대로 사용한다(`ai/schemas/
query_output.py`의 `TargetType`과 동일한 리터럴 - 두 파일은 서로 import하지 않는다.
`ai/`는 별도 배포 산출물이 아닌 아티팩트 디렉터리라 백엔드 런타임 코드가 거기 의존성을
갖지 않도록 값만 맞춰 중복 선언한다).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal, Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.matching.candidate_generator import (
    ChannelHit,
    ChannelResult,
    reciprocal_rank_fusion,
    structured_search_exhibitors,
    structured_search_products,
)

TargetType = Literal["BOOTH", "EVENT_PRODUCT", "EXHIBITOR", "PROGRAM"]
SearchChannel = Literal["REGISTERED_WEB", "GUEST_WEB", "BUYER_WEB", "ADMIN_PREVIEW"]
ProviderName = Literal["STRUCTURED", "KEYWORD", "VECTOR", "POPULAR"]


@dataclass(frozen=True)
class SearchQuery:
    """SearchProvider 입력 - 이미 온톨로지 코드가 concept_id(UUID)로 해석된 이후 형태.

    `ai/schemas/query_output.QueryInterpretation`(AIS-005, concept_code 문자열 기반)을
    이 DTO로 변환하는 것은 이 파일의 책임이 아니다 - 그 변환은 상위 오케스트레이션
    계층(Wave 2)이 온톨로지 조회로 code -> concept_id를 해석한 뒤 수행한다. 이 파일은
    "해석이 끝난 뒤의 검색 입력"만 정의한다.
    """

    event_id: uuid.UUID
    target_type: TargetType
    channel: SearchChannel = "GUEST_WEB"
    raw_text: str | None = None
    required_concept_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    preferred_concept_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    excluded_concept_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    #: 채널별 구조화 필터 통과용(예: price_max/moq_max/tasting_required 등 - 기존
    #: structured_search_products/exhibitors의 키워드 인자와 같은 값을 실어 나른다).
    #: 이 파일이 그 필터들을 전부 알 필요는 없으므로 제네릭 매핑으로 둔다.
    structured_filters: Mapping[str, object] = field(default_factory=dict)
    locale: str = "ko-KR"


@dataclass(frozen=True)
class SearchScoreBreakdown:
    """§11.6 점수 결과 인터페이스 - 모양만 정의(값 계산은 Wave 2).

    `GUEST_WEB_SEARCH_SCORE_V1`(0.45 Semantic + 0.30 Keyword + 0.15 Structured +
    0.05 Data Quality + 0.05 Availability)과 웹의 `CONSUMER_SCORE_V1`/`BUYER_SCORE_V1`
    양쪽 모두 이 필드들로 표현 가능해야 한다는 전제로 이름을 붙였다.
    구조화 검색(structured)·키워드(FTS)·의미(벡터) 세 채널 점수를 각각 필드로 분리해
    두는 이유는 이후 가중합 계산이 "컴포넌트별로 없는 신호는 제외하고 남은 가중치를
    재정규화한다"(`src/meet_ai/scoring/engine.py` 모듈 docstring 원칙)를 그대로 따를 수
    있게 하기 위해서다.
    """

    structured_score: float | None = None
    keyword_score: float | None = None
    semantic_score: float | None = None
    data_quality_score: float | None = None
    availability_score: float | None = None
    final_score: float | None = None
    reason_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class SearchCandidate:
    """SearchProvider.search()가 반환하는 후보 1건."""

    recommendable_id: uuid.UUID
    rank: int
    source_provider: str
    matched_concept_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)
    score_breakdown: SearchScoreBreakdown | None = None


@runtime_checkable
class SearchProvider(Protocol):
    """채널 하나(구조화/키워드/벡터)가 만족해야 할 최소 계약.

    Wave 2가 구현할 `StructuredSearchProvider`/`KeywordSearchProvider`/
    `VectorSearchProvider`는 전부 이 Protocol을 만족해야 한다 - 상속이 아니라 구조적
    타이핑(duck typing)으로 검사한다(`@runtime_checkable`로 `isinstance()` 검사도
    가능하게 해 둔다 - `tests` 참고).
    """

    async def search(self, query: SearchQuery, limit: int) -> list[SearchCandidate]:
        """query에 맞는 후보를 이 채널 기준 순위(rank, 1부터 시작)로 최대 limit개 반환."""
        ...


@runtime_checkable
class CandidateCombiner(Protocol):
    """여러 SearchProvider의 결과를 하나로 합치는 단계의 인터페이스.

    `ReciprocalRankFusionCombiner`가 기본 구현이다. Protocol은 테스트 더블이나 실험용
    조합기가 같은 모양을 유지하도록 둔다.
    """

    def combine(
        self, provider_results: Mapping[str, Sequence[SearchCandidate]]
    ) -> list[SearchCandidate]:
        ...


def _as_decimal_map(
    values: Mapping[str, Decimal | float | int | str] | None,
) -> dict[str, Decimal] | None:
    if values is None:
        return None
    return {key: Decimal(str(value)) for key, value in values.items()}


def _score_from_channel_hit(hit: ChannelHit) -> SearchScoreBreakdown:
    score = float(hit.score)
    return SearchScoreBreakdown(
        structured_score=score,
        final_score=score,
        reason_codes=("STRUCTURED_MATCH",),
    )


@dataclass(frozen=True)
class ReciprocalRankFusionCombiner:
    """SearchCandidate 목록을 기존 RRF 구현으로 병합하는 기본 combiner."""

    channel_weights: Mapping[str, Decimal | float | int | str] | None = None
    k: int = 60

    def combine(
        self, provider_results: Mapping[str, Sequence[SearchCandidate]]
    ) -> list[SearchCandidate]:
        if self.k < 1:
            raise ValueError("k must be >= 1")

        channel_results: list[ChannelResult] = []
        for provider_name, candidates in provider_results.items():
            hits = tuple(
                ChannelHit(
                    recommendable_id=candidate.recommendable_id,
                    rank=candidate.rank,
                    matched_concept_ids=candidate.matched_concept_ids,
                )
                for candidate in candidates
            )
            if hits:
                channel_results.append(ChannelResult(channel=provider_name, hits=hits))

        fused = reciprocal_rank_fusion(
            channel_results,
            channel_weights=_as_decimal_map(self.channel_weights),
            k=self.k,
        )
        return [
            SearchCandidate(
                recommendable_id=candidate.recommendable_id,
                rank=rank,
                source_provider="+".join(candidate.source_channels),
                matched_concept_ids=candidate.matched_concept_ids,
                score_breakdown=SearchScoreBreakdown(
                    final_score=float(candidate.retrieval_score),
                    reason_codes=tuple(
                        f"RETRIEVED_BY_{channel}"
                        for channel in candidate.source_channels
                    ),
                ),
            )
            for rank, candidate in enumerate(fused, start=1)
        ]


def _filter_bool(filters: Mapping[str, object], key: str) -> bool:
    return bool(filters.get(key, False))


def _filter_int(filters: Mapping[str, object], key: str) -> int | None:
    value = filters.get(key)
    if value is None:
        return None
    if isinstance(value, bool):
        raise TypeError(f"{key} must be an integer")
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} must be an integer") from exc


@dataclass(frozen=True)
class StructuredSearchProvider:
    """기존 SQL 구조화 검색 함수를 SearchProvider 계약으로 감싸는 어댑터."""

    session: AsyncSession
    provider_name: ProviderName = "STRUCTURED"

    async def search(self, query: SearchQuery, limit: int) -> list[SearchCandidate]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        filters = query.structured_filters
        if query.target_type == "EVENT_PRODUCT":
            channel_result = await structured_search_products(
                self.session,
                event_id=query.event_id,
                category_concept_ids=tuple(
                    query.required_concept_ids or query.preferred_concept_ids
                ),
                price_max=_filter_int(filters, "price_max"),
                tasting_required=_filter_bool(filters, "tasting_required"),
                purchase_required=_filter_bool(filters, "purchase_required"),
                limit=limit,
            )
        elif query.target_type == "EXHIBITOR":
            channel_result = await structured_search_exhibitors(
                self.session,
                event_id=query.event_id,
                moq_max=_filter_int(filters, "moq_max"),
                limit=limit,
            )
        else:
            return []

        return [
            SearchCandidate(
                recommendable_id=hit.recommendable_id,
                rank=hit.rank,
                source_provider=self.provider_name,
                matched_concept_ids=hit.matched_concept_ids,
                score_breakdown=_score_from_channel_hit(hit),
            )
            for hit in channel_result.hits
        ]


@dataclass
class MockSearchProvider:
    """테스트 전용 - 사전에 준비한 결과를 그대로 돌려주는 SearchProvider 구현체.

    Wave 2의 실제 Provider들이 상속하는 기반 클래스가 아니다(이 클래스는 순수 테스트
    더블). `SearchQuery`는 기록만 하고 실제로는 사용하지 않는다 - 상위 코드가 올바른
    query를 넘기는지 검증하고 싶다면 `received_queries`를 확인한다.
    """

    canned_results: Sequence[SearchCandidate] = field(default_factory=tuple)
    provider_name: str = "MOCK"
    call_count: int = field(default=0, init=False)
    received_queries: list[SearchQuery] = field(default_factory=list, init=False)

    async def search(self, query: SearchQuery, limit: int) -> list[SearchCandidate]:
        if limit < 1:
            raise ValueError("limit must be >= 1")
        self.call_count += 1
        self.received_queries.append(query)
        return list(self.canned_results[:limit])
