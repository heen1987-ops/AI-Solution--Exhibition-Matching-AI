from __future__ import annotations

import uuid
from decimal import Decimal

from app.services.matching.feature_builder import (
    BuyerCandidateFacts,
    BuyerProfileFacts,
    ConsumerCandidateFacts,
    ConsumerProfileFacts,
    ExhibitorCandidateFacts,
    ExhibitorProfileFacts,
    build_buyer_components,
    build_consumer_components,
    build_exhibitor_components,
    component_of_attribute_code,
    group_concept_ids_by_component,
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
    """service/behavior/trust는 concept 교집합이 아니라 각각 다른 데이터(EventProduct
    상태값, 행동 이벤트 집계, 데이터 신뢰도 모델)가 필요해 아직 미구현이다(모듈
    docstring 참고) - 후보 사실관계에 아무것도 없어도 항상 None이어야 한다."""

    candidate = ConsumerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset(),
        event_price_amount=None,
    )
    profile = ConsumerProfileFacts(
        required_category_concept_ids=frozenset(), price_min=None, price_max=None
    )

    components = build_consumer_components(candidate, profile)

    for component in ("service", "behavior", "trust"):
        assert components[component] is None


def test_component_of_attribute_code_maps_known_prefixes() -> None:
    assert component_of_attribute_code("TASTE.DRY") == "sensory"
    assert component_of_attribute_code("AROMA.FRUIT") == "sensory"
    assert component_of_attribute_code("ALCOHOL_LEVEL.HIGH") == "alcohol"
    assert component_of_attribute_code("USE.GIFT") == "usage"
    assert component_of_attribute_code("GOAL.TASTING") == "goal"
    assert component_of_attribute_code("BIZ_GOAL.EXPORT") == "business_goal"
    assert component_of_attribute_code("CHANNEL.HORECA") == "channel"
    assert component_of_attribute_code("REGION.KR.SEOUL") == "region"


def test_component_of_attribute_code_returns_none_for_unmapped_prefix() -> None:
    assert component_of_attribute_code("PRICE_BAND.K20_TO_K50") is None


def test_group_concept_ids_by_component_buckets_and_drops_unmapped() -> None:
    dry, fruit, gift, unmapped = (
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
        uuid.uuid4(),
    )

    grouped = group_concept_ids_by_component(
        [
            ("TASTE.DRY", dry),
            ("AROMA.FRUIT", fruit),
            ("USE.GIFT", gift),
            ("PRICE_BAND.K20_TO_K50", unmapped),
        ]
    )

    assert grouped["sensory"] == frozenset({dry, fruit})
    assert grouped["usage"] == frozenset({gift})
    assert "price_band" not in grouped


def test_consumer_sensory_component_matches_via_concept_overlap() -> None:
    dry = uuid.uuid4()
    candidate = ConsumerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset(),
        event_price_amount=None,
        concept_ids_by_component={"sensory": frozenset({dry})},
    )
    profile = ConsumerProfileFacts(
        required_category_concept_ids=frozenset(),
        price_min=None,
        price_max=None,
        required_concept_ids_by_component={"sensory": frozenset({dry})},
    )

    components = build_consumer_components(candidate, profile)

    assert components["sensory"] == Decimal(1)


def test_consumer_sensory_component_scores_zero_on_mismatch() -> None:
    candidate = ConsumerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset(),
        event_price_amount=None,
        concept_ids_by_component={"sensory": frozenset({uuid.uuid4()})},
    )
    profile = ConsumerProfileFacts(
        required_category_concept_ids=frozenset(),
        price_min=None,
        price_max=None,
        required_concept_ids_by_component={"sensory": frozenset({uuid.uuid4()})},
    )

    components = build_consumer_components(candidate, profile)

    assert components["sensory"] == Decimal(0)


def test_buyer_channel_and_region_components_match_via_concept_overlap() -> None:
    horeca, seoul = uuid.uuid4(), uuid.uuid4()
    candidate = BuyerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset(),
        wholesale_price_amount=None,
        min_order_quantity=None,
        concept_ids_by_component={
            "channel": frozenset({horeca}),
            "region": frozenset({seoul}),
        },
    )
    profile = BuyerProfileFacts(
        required_category_concept_ids=frozenset(),
        target_price_max=None,
        max_order_quantity=None,
        required_concept_ids_by_component={
            "channel": frozenset({horeca}),
            "region": frozenset({seoul}),
        },
    )

    components = build_buyer_components(candidate, profile)

    assert components["channel"] == Decimal(1)
    assert components["region"] == Decimal(1)


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


def test_buyer_capacity_sufficient_when_available_meets_request() -> None:
    candidate = BuyerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset(),
        wholesale_price_amount=None,
        min_order_quantity=None,
        available_capacity=1_000,
    )
    profile = BuyerProfileFacts(
        required_category_concept_ids=frozenset(),
        target_price_max=None,
        max_order_quantity=None,
        requested_monthly_units=500,
    )

    components = build_buyer_components(candidate, profile)

    assert components["capacity"] == Decimal(1)


def test_buyer_capacity_insufficient_scores_zero_not_none() -> None:
    candidate = BuyerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset(),
        wholesale_price_amount=None,
        min_order_quantity=None,
        available_capacity=100,
    )
    profile = BuyerProfileFacts(
        required_category_concept_ids=frozenset(),
        target_price_max=None,
        max_order_quantity=None,
        requested_monthly_units=500,
    )

    components = build_buyer_components(candidate, profile)

    assert components["capacity"] == Decimal(0)


def test_buyer_capacity_is_none_when_data_missing() -> None:
    candidate = BuyerCandidateFacts(
        recommendable_id=uuid.uuid4(),
        category_concept_ids=frozenset(),
        wholesale_price_amount=None,
        min_order_quantity=None,
    )
    profile = BuyerProfileFacts(
        required_category_concept_ids=frozenset(),
        target_price_max=None,
        max_order_quantity=None,
    )

    components = build_buyer_components(candidate, profile)

    assert components["capacity"] is None


def test_exhibitor_buyer_type_matches_when_buyer_fits_preference() -> None:
    bottle_shop = uuid.uuid4()
    candidate = ExhibitorCandidateFacts(
        recommendable_id=uuid.uuid4(),
        monthly_capacity=None,
        preference_concept_ids_by_component={"buyer_type": frozenset({bottle_shop})},
    )
    profile = ExhibitorProfileFacts(
        requested_monthly_units=None,
        buyer_concept_ids_by_component={"buyer_type": frozenset({bottle_shop})},
    )

    components = build_exhibitor_components(candidate, profile)

    assert components["buyer_type"] == Decimal(1)


def test_exhibitor_buyer_type_scores_zero_on_mismatch() -> None:
    candidate = ExhibitorCandidateFacts(
        recommendable_id=uuid.uuid4(),
        monthly_capacity=None,
        preference_concept_ids_by_component={"buyer_type": frozenset({uuid.uuid4()})},
    )
    profile = ExhibitorProfileFacts(
        requested_monthly_units=None,
        buyer_concept_ids_by_component={"buyer_type": frozenset({uuid.uuid4()})},
    )

    components = build_exhibitor_components(candidate, profile)

    assert components["buyer_type"] == Decimal(0)


def test_exhibitor_buyer_type_is_none_when_exhibitor_has_no_preference() -> None:
    """업체가 이 차원에 선호가 없으면(exhibition.buyer_preference에 행이 없으면)
    "정보 없음"이지 불일치(0)가 아니다."""

    candidate = ExhibitorCandidateFacts(
        recommendable_id=uuid.uuid4(), monthly_capacity=None
    )
    profile = ExhibitorProfileFacts(
        requested_monthly_units=None,
        buyer_concept_ids_by_component={"buyer_type": frozenset({uuid.uuid4()})},
    )

    components = build_exhibitor_components(candidate, profile)

    assert components["buyer_type"] is None
