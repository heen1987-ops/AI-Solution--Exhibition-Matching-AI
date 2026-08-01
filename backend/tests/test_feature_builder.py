from __future__ import annotations

import uuid
from decimal import Decimal

from app.services.matching.feature_builder import (
    BuyerCandidateFacts,
    BuyerProfileFacts,
    ConsumerCandidateFacts,
    ConsumerProfileFacts,
    build_buyer_components,
    build_consumer_components,
)


def test_consumer_price_within_range_scores_one() -> None:
    candidate = ConsumerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset(),
        event_price_amount=40_000,
    )
    profile = ConsumerProfileFacts(
        required_category_concept_ids=frozenset(),
        price_min=20_000,
        price_max=50_000,
    )

    components = build_consumer_components(candidate, profile)

    assert components["price"] == Decimal(1)


def test_consumer_price_above_max_decays_but_stays_bounded() -> None:
    candidate = ConsumerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset(),
        event_price_amount=100_000,
    )
    profile = ConsumerProfileFacts(
        required_category_concept_ids=frozenset(), price_min=None, price_max=50_000
    )

    components = build_consumer_components(candidate, profile)

    assert Decimal(0) <= components["price"] < Decimal(1)


def test_consumer_price_is_none_when_user_has_no_price_requirement() -> None:
    candidate = ConsumerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset(),
        event_price_amount=40_000,
    )
    profile = ConsumerProfileFacts(
        required_category_concept_ids=frozenset(), price_min=None, price_max=None
    )

    components = build_consumer_components(candidate, profile)

    assert components["price"] is None


def test_consumer_category_match_requires_overlap() -> None:
    shared = uuid.uuid4()
    candidate = ConsumerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset({shared, uuid.uuid4()}),
        event_price_amount=None,
    )
    profile = ConsumerProfileFacts(
        required_category_concept_ids=frozenset({shared}),
        price_min=None,
        price_max=None,
    )

    components = build_consumer_components(candidate, profile)

    assert components["category"] == Decimal(1)


def test_consumer_category_mismatch_scores_zero_not_none() -> None:
    candidate = ConsumerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset({uuid.uuid4()}),
        event_price_amount=None,
    )
    profile = ConsumerProfileFacts(
        required_category_concept_ids=frozenset({uuid.uuid4()}),
        price_min=None,
        price_max=None,
    )

    components = build_consumer_components(candidate, profile)

    # 명시적 불일치는 "정보 없음"(None)과 달리 실제 0점 신호여야 한다
    # (docs/11-13-scoring-implementation.md 구현 범위 3번).
    assert components["category"] == Decimal(0)


def test_unimplemented_consumer_components_are_none_not_fabricated() -> None:
    candidate = ConsumerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset(),
        event_price_amount=None,
    )
    profile = ConsumerProfileFacts(
        required_category_concept_ids=frozenset(), price_min=None, price_max=None
    )

    components = build_consumer_components(candidate, profile)

    for component in (
        "goal",
        "sensory",
        "alcohol",
        "service",
        "usage",
        "behavior",
        "trust",
    ):
        assert components[component] is None


def test_buyer_moq_within_capacity_passes() -> None:
    candidate = BuyerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset(),
        wholesale_price_amount=None,
        min_order_quantity=100,
    )
    profile = BuyerProfileFacts(
        required_category_concept_ids=frozenset(),
        target_price_max=None,
        max_order_quantity=300,
    )

    components = build_buyer_components(candidate, profile)

    assert components["moq"] == Decimal(1)


def test_buyer_moq_exceeding_capacity_scores_zero() -> None:
    candidate = BuyerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset(),
        wholesale_price_amount=None,
        min_order_quantity=500,
    )
    profile = BuyerProfileFacts(
        required_category_concept_ids=frozenset(),
        target_price_max=None,
        max_order_quantity=100,
    )

    components = build_buyer_components(candidate, profile)

    assert components["moq"] == Decimal(0)
