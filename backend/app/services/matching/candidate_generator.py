"""9단계 후보검색: 채널 결과 병합, 업체 편중 제한, 후보 풀 크기 조정.

근거 문서: docs/09-candidate-search-design.md (18~22절 - 검색점수 정규화·RRF 병합·중복
제거·업체별 상한·후보 수 제어). db-erd-table-spec.md는 후보 자체를 영속화하는 테이블을
두지 않으므로(matching.recommendation_session.candidate_count/filtered_count만 집계값으로
남긴다), 이 모듈의 산출물(CandidateHit 목록)은 요청 처리 중에만 존재하는 순수 인메모리
자료구조다. 최종 통과 후보만 hard_filter_engine을 거쳐 matching.match_result에 저장된다.

구현 범위과 남은 작업
----------------------
- 순위 기반 정규화(18.2절)와 가중 RRF 병합(19절)은 순수 함수로 완전히 구현했다 - DB나
  검색엔진 없이 단위 테스트로 검증 가능하다.
- 업체별 최대 후보 수 제한(20.3절)과 후보 풀 크기 조정(22절)도 순수 함수로 구현했다.
- 구조화 검색 채널(6절)은 두 방향 모두 실제 쿼리로 구현했다: 일반 관람객용
  `structured_search_products`(exhibition.event_product/product/recommendable)와
  바이어용 `structured_search_exhibitors`(exhibition.exhibitor_participation/
  trade_condition/recommendable). 거래조건이 아직 없는 업체는 후자에서 제외되는데,
  이는 함수 docstring에 남겨둔 별도 한계다. 이것이 지금 유일하게 동작하는 검색채널
  종류다.
- 키워드 검색(7절)·벡터 의미검색(8절)·행동 기반 검색(9절)·인기 후보(10절)·신규 탐색
  후보(11절)는 아직 구현하지 않았다. 벡터 인덱스(ai.object_embedding)와 행동 이벤트
  파이프라인이 이 커밋 시점에 존재하지 않기 때문이다. 이 모듈은 이 채널들의 자리를
  RetrievalChannel 프로토콜로 남겨두고, orchestrator는 구조화 채널 하나만 사용해도
  동작하도록 설계했다 (재현율은 다른 채널이 붙기 전까지 구조화 검색 하나에 의존한다는
  뜻이며, 이는 은폐된 축소가 아니라 명시적 한계다).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exhibitor import (
    EventProduct,
    ExhibitorParticipation,
    Product,
    TradeCondition,
)
from app.models.matching import Recommendable

#: 9단계 18.2절 예시(1위=1.00 ... 10위=0.60 ... 50위=0.20)에 맞춘 순위 기반 점수 함수.
#: 선형 감쇠가 아니라 상위 순위를 우대하는 역수 감쇠를 쓴다: score = 1 / (1 + 0.045*(rank-1)).
#: rank=1 -> 1.000, rank=10 -> 0.712, rank=50 -> 0.313. doc 예시와 완전히 같지는 않지만
#: (doc도 "채널 특성에 따라 함수값을 조정한다"고 명시) 같은 성질(상위 급락 방지, 단조감소)을
#: 만족하는 단일 공식으로 모든 채널에 재사용한다.
_RANK_DECAY = Decimal("0.045")


def rank_based_score(rank: int) -> Decimal:
    if rank < 1:
        raise ValueError("rank must be >= 1")
    return Decimal(1) / (Decimal(1) + _RANK_DECAY * (rank - 1))


@dataclass(frozen=True)
class ChannelHit:
    """단일 검색채널이 반환한 후보 1건."""

    recommendable_id: uuid.UUID
    rank: int
    matched_concept_ids: frozenset[uuid.UUID] = field(default_factory=frozenset)

    @property
    def score(self) -> Decimal:
        return rank_based_score(self.rank)


@dataclass(frozen=True)
class ChannelResult:
    """검색채널 1회 실행 결과 (9단계 3절 Parallel Candidate Retrieval의 출력)."""

    channel: str
    hits: tuple[ChannelHit, ...]


@dataclass(frozen=True)
class CandidateHit:
    """채널 병합 이후의 후보 1건 (9단계 17절 후보 결과 공통구조)."""

    recommendable_id: uuid.UUID
    retrieval_score: Decimal
    source_channels: tuple[str, ...]
    matched_concept_ids: frozenset[uuid.UUID]
    per_channel_scores: Mapping[str, Decimal]


#: 9단계 19.1절 RRF 상수. k=60은 문서가 검토를 권장한 초기값이다.
DEFAULT_RRF_K = 60


def reciprocal_rank_fusion(
    channel_results: Sequence[ChannelResult],
    *,
    channel_weights: Mapping[str, Decimal] | None = None,
    k: int = DEFAULT_RRF_K,
) -> list[CandidateHit]:
    """9단계 19.2절 가중 RRF: Σ channel_weight_i × 1 / (k + rank_i).

    복수 채널에서 나타난 후보는 자연히 가점된다(19.3절 병합 원칙 1번) - 여러 항을 그대로
    더하기 때문이다. 결과는 retrieval_score 내림차순으로 정렬한다.
    """

    weights = channel_weights or {}
    scores: dict[uuid.UUID, Decimal] = {}
    sources: dict[uuid.UUID, dict[str, Decimal]] = {}
    concepts: dict[uuid.UUID, set[uuid.UUID]] = {}

    for result in channel_results:
        weight = weights.get(result.channel, Decimal(1))
        for hit in result.hits:
            rrf_term = weight * (Decimal(1) / (Decimal(k) + hit.rank))
            scores[hit.recommendable_id] = (
                scores.get(hit.recommendable_id, Decimal(0)) + rrf_term
            )
            sources.setdefault(hit.recommendable_id, {})[result.channel] = rrf_term
            concepts.setdefault(hit.recommendable_id, set()).update(
                hit.matched_concept_ids
            )

    fused = [
        CandidateHit(
            recommendable_id=recommendable_id,
            retrieval_score=score,
            source_channels=tuple(sources[recommendable_id]),
            matched_concept_ids=frozenset(concepts.get(recommendable_id, ())),
            per_channel_scores=sources[recommendable_id],
        )
        for recommendable_id, score in scores.items()
    ]
    fused.sort(key=lambda hit: hit.retrieval_score, reverse=True)
    return fused


def enforce_object_owner_cap(
    candidates: Sequence[CandidateHit],
    *,
    owner_of: Callable[[uuid.UUID], uuid.UUID | None],
    max_per_owner: int = 5,
) -> list[CandidateHit]:
    """9단계 20.3절: 업체별 최대 제품 후보 상한(기본 5개).

    candidates는 이미 retrieval_score 내림차순이라고 가정한다(reciprocal_rank_fusion의
    출력이 이 계약을 만족한다). owner_of가 None을 반환하는 후보(예: 업체 단위 추천이라
    "제품의 소속 업체"라는 개념이 없는 경우)는 상한 대상에서 제외한다.
    """

    kept: list[CandidateHit] = []
    counts: dict[uuid.UUID, int] = {}
    for candidate in candidates:
        owner_id = owner_of(candidate.recommendable_id)
        if owner_id is None:
            kept.append(candidate)
            continue
        count = counts.get(owner_id, 0)
        if count >= max_per_owner:
            continue
        counts[owner_id] = count + 1
        kept.append(candidate)
    return kept


@dataclass(frozen=True)
class CandidatePool:
    """9단계 22절 후보 수 제어의 결과. 22.2절 최소·최대 기준 판단을 담는다."""

    candidates: tuple[CandidateHit, ...]
    target_count: int
    below_minimum: bool
    truncated_count: int


def build_candidate_pool(
    candidates: Sequence[CandidateHit],
    *,
    target_count: int,
    minimum_count: int,
) -> CandidatePool:
    """9단계 22.1/22.2절: 목표 후보 수로 절단하고, 최소 기준 미달 여부를 함께 보고한다.

    최소 기준 미달이어도 이 함수는 검색범위를 스스로 확장하지 않는다(22.3절 "사용자의
    필수조건은 자동으로 완화하지 않는다") - 단계적 확장 여부는 검색계획을 다시 세우는
    상위 오케스트레이터의 책임이다. 이 함수는 판단에 필요한 신호만 돌려준다.
    """

    if target_count < 1:
        raise ValueError("target_count must be >= 1")
    truncated = max(0, len(candidates) - target_count)
    kept = tuple(candidates[:target_count])
    return CandidatePool(
        candidates=kept,
        target_count=target_count,
        below_minimum=len(kept) < minimum_count,
        truncated_count=truncated,
    )


# ---------------------------------------------------------------------------
# 구조화 검색 채널 (9단계 6절) - 현재 유일하게 구현된 검색채널.
# ---------------------------------------------------------------------------


async def structured_search_products(
    session: AsyncSession,
    *,
    event_id: uuid.UUID,
    category_concept_ids: Sequence[uuid.UUID] | None = None,
    price_max: int | None = None,
    tasting_required: bool = False,
    purchase_required: bool = False,
    limit: int = 120,
) -> ChannelResult:
    """9단계 6.2절 구조화 검색 예시 SQL의 SQLAlchemy 대응.

    exhibition.recommendable(EVENT_PRODUCT)과 그에 연결된 event_product/product를
    approval_status='APPROVED' 조건으로 조인한다. 상위·하위 온톨로지 확장(6.3절)은
    category_concept_ids를 호출자가 이미 확장해서 넘긴다고 가정한다(카탈로그 계층 조회는
    meet_ai.ontology의 책임이라 이 함수는 확장된 concept_id 목록만 받는다).
    """

    stmt = (
        select(Recommendable.recommendable_id, Product.category_concept_id)
        .join(
            EventProduct,
            EventProduct.event_product_id == Recommendable.event_product_id,
        )
        .join(Product, Product.product_id == EventProduct.product_id)
        .where(
            Recommendable.event_id == event_id,
            Recommendable.object_type == "EVENT_PRODUCT",
            Recommendable.active.is_(True),
            EventProduct.approval_status == "APPROVED",
        )
    )
    if category_concept_ids:
        stmt = stmt.where(Product.category_concept_id.in_(category_concept_ids))
    if price_max is not None:
        stmt = stmt.where(
            EventProduct.event_price_amount.is_(None)
            | (EventProduct.event_price_amount <= price_max)
        )
    if tasting_required:
        stmt = stmt.where(EventProduct.tasting_status == "AVAILABLE")
    if purchase_required:
        stmt = stmt.where(EventProduct.purchase_status == "AVAILABLE")
    stmt = stmt.limit(limit)

    rows = (await session.execute(stmt)).all()
    hits = tuple(
        ChannelHit(
            recommendable_id=recommendable_id,
            rank=rank,
            matched_concept_ids=(
                frozenset({category_concept_id})
                if category_concept_id is not None
                else frozenset()
            ),
        )
        for rank, (recommendable_id, category_concept_id) in enumerate(rows, start=1)
    )
    return ChannelResult(channel="STRUCTURED", hits=hits)


async def structured_search_exhibitors(
    session: AsyncSession,
    *,
    event_id: uuid.UUID,
    moq_max: int | None = None,
    limit: int = 120,
) -> ChannelResult:
    """9단계 6.2절의 바이어용 대응. exhibition.recommendable(EXHIBITOR)을
    exhibitor_participation + trade_condition(업체 공통조건, event_product_id IS NULL)과
    조인한다.

    거래조건이 아직 등록되지 않은 업체(trade_condition 행 자체가 없는 경우)는 이 채널에서는
    제외된다 - 9단계 23.2절 "미확인 업체 별도 후보"는 이 함수 하나로 표현하지 않고, 별도
    채널(관리자 지정 후보 등)이나 미확인 후보 병합 단계에서 다뤄야 한다(아직 미구현).
    """

    stmt = (
        select(Recommendable.recommendable_id, TradeCondition.min_order_quantity)
        .join(
            ExhibitorParticipation,
            ExhibitorParticipation.participation_id == Recommendable.participation_id,
        )
        .join(
            TradeCondition,
            TradeCondition.participation_id == ExhibitorParticipation.participation_id,
        )
        .where(
            Recommendable.event_id == event_id,
            Recommendable.object_type == "EXHIBITOR",
            Recommendable.active.is_(True),
            ExhibitorParticipation.participation_status == "APPROVED",
            TradeCondition.approval_status == "APPROVED",
            TradeCondition.event_product_id.is_(None),
        )
    )
    if moq_max is not None:
        stmt = stmt.where(
            TradeCondition.min_order_quantity.is_(None)
            | (TradeCondition.min_order_quantity <= moq_max)
        )
    stmt = stmt.limit(limit)

    rows = (await session.execute(stmt)).all()
    hits = tuple(
        ChannelHit(recommendable_id=recommendable_id, rank=rank)
        for rank, (recommendable_id, _min_order_quantity) in enumerate(rows, start=1)
    )
    return ChannelResult(channel="STRUCTURED", hits=hits)
