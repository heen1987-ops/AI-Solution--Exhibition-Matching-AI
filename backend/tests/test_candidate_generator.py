from __future__ import annotations

import uuid
from decimal import Decimal

from app.services.matching.candidate_generator import (
    CandidateHit,
    ChannelHit,
    ChannelResult,
    build_candidate_pool,
    enforce_object_owner_cap,
    rank_based_score,
    reciprocal_rank_fusion,
)


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


def test_rank_based_score_is_monotonically_decreasing() -> None:
    scores = [rank_based_score(rank) for rank in (1, 2, 5, 10, 50)]

    assert scores == sorted(scores, reverse=True)
    assert scores[0] == Decimal(1)


def test_reciprocal_rank_fusion_rewards_candidates_found_by_multiple_channels() -> None:
    only_structured = _uuid()
    both_channels = _uuid()

    structured = ChannelResult(
        channel="STRUCTURED",
        hits=(
            ChannelHit(recommendable_id=only_structured, rank=1),
            ChannelHit(recommendable_id=both_channels, rank=2),
        ),
    )
    vector = ChannelResult(
        channel="VECTOR",
        hits=(ChannelHit(recommendable_id=both_channels, rank=1),),
    )

    fused = reciprocal_rank_fusion([structured, vector])
    fused_by_id = {hit.recommendable_id: hit for hit in fused}

    # 9단계 19.3절: 복수 채널에서 나온 후보가 단일 채널 1위 후보보다 우선해야 한다.
    assert fused[0].recommendable_id == both_channels
    assert fused_by_id[both_channels].source_channels == ("STRUCTURED", "VECTOR")
    assert fused_by_id[only_structured].source_channels == ("STRUCTURED",)


def test_reciprocal_rank_fusion_applies_channel_weights() -> None:
    candidate = _uuid()
    structured = ChannelResult(
        channel="STRUCTURED", hits=(ChannelHit(recommendable_id=candidate, rank=1),)
    )

    unweighted = reciprocal_rank_fusion([structured])[0]
    downweighted = reciprocal_rank_fusion(
        [structured], channel_weights={"STRUCTURED": Decimal("0.5")}
    )[0]

    assert downweighted.retrieval_score == unweighted.retrieval_score * Decimal("0.5")


def test_enforce_object_owner_cap_keeps_highest_scored_first() -> None:
    exhibitor_a = _uuid()
    products = [_uuid() for _ in range(7)]
    owners = {product: exhibitor_a for product in products}

    candidates = [
        CandidateHit(
            recommendable_id=product,
            retrieval_score=Decimal(1) - Decimal(index) / 100,
            source_channels=("STRUCTURED",),
            matched_concept_ids=frozenset(),
            per_channel_scores={},
        )
        for index, product in enumerate(products)
    ]

    capped = enforce_object_owner_cap(
        candidates, owner_of=lambda rid: owners[rid], max_per_owner=5
    )

    assert len(capped) == 5
    assert [c.recommendable_id for c in capped] == products[:5]


def test_enforce_object_owner_cap_ignores_candidates_without_an_owner() -> None:
    candidate = CandidateHit(
        recommendable_id=_uuid(),
        retrieval_score=Decimal(1),
        source_channels=("STRUCTURED",),
        matched_concept_ids=frozenset(),
        per_channel_scores={},
    )

    capped = enforce_object_owner_cap(
        [candidate], owner_of=lambda _rid: None, max_per_owner=0
    )

    assert capped == [candidate]


def test_build_candidate_pool_truncates_and_flags_below_minimum() -> None:
    candidates = [
        CandidateHit(
            recommendable_id=_uuid(),
            retrieval_score=Decimal(1),
            source_channels=("STRUCTURED",),
            matched_concept_ids=frozenset(),
            per_channel_scores={},
        )
        for _ in range(3)
    ]

    pool = build_candidate_pool(candidates, target_count=2, minimum_count=10)

    assert len(pool.candidates) == 2
    assert pool.truncated_count == 1
    assert pool.below_minimum is True
