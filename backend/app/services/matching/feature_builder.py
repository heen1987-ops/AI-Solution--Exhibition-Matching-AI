"""Feature Builder: 후보 특징을 meet_ai.scoring 구성요소 코드로 변환한다.

근거 문서: docs/11-13-scoring-implementation.md "다음 구현 순서" 3번 - "후보 특징을 본
계산 코어의 구성요소 코드로 변환하는 Feature Builder를 연결한다". 이 모듈이 그 연결부다.
출력 dict의 키는 meet_ai.scoring.CONSUMER_SCORE_V1/BUYER_SCORE_V1의 weights 키와 정확히
일치해야 하며(불일치 시 calculate_directional_score가 ScoreValidationError를 낸다), 값은
전부 [0, 1] 구간이거나 None(정보 없음)이다.

구현 범위와 남은 작업
----------------------
현재 채워지는 구성요소:
    - CONSUMER_SCORE_V1: category, price
    - BUYER_SCORE_V1: product, price, moq
    - EXHIBITOR_SCORE_V1 (양면 적합도의 업체->바이어 방향): order_volume

`component_confidence()`는 calculate_reciprocal_score가 요구하는 buyer_confidence/
exhibitor_confidence(선택값이 아니라 필수 Number)를 만들기 위한 임시 대리지표다 - 실제
데이터 신뢰도 모델(08단계 16절)이 아직 연결되지 않아, 채워진 구성요소 비율로 대신한다.
근거 데이터가 늘어나면 이 함수를 실제 신뢰도 계산으로 교체해야 한다.

None으로 남기는 구성요소(goal/sensory/alcohol/service/usage/behavior/trust, business_goal/
channel/capacity/region/cooperation/meeting)는 각각 프로파일 목적·관능 프로파일·행동
이벤트 집계·거래조건 정규화·데이터 신뢰도 산정이 필요한데, 이 커밋 시점에는 그 데이터를
읽어올 조회 계층이 아직 없다. meet_ai.scoring.calculate_directional_score는 None을
"정보 없음"으로 처리해 가중치 분모에서 제외하므로(11~13단계 구현 기록 "구현 범위" 2번),
이 모듈이 값을 지어내는 것보다 정직하게 None을 반환하는 편이 계산 계약에 맞다.
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class ConsumerCandidateFacts:
    """일반 관람객 점수 계산에 쓰는, 이미 조회된 후보 사실관계."""

    recommendable_id: uuid.UUID
    category_concept_ids: frozenset[uuid.UUID]
    event_price_amount: int | None


@dataclass(frozen=True)
class ConsumerProfileFacts:
    """9단계 검색 요청 객체·07단계 프로파일에서 뽑아낸, 이미 해석된 사용자 요구."""

    required_category_concept_ids: frozenset[uuid.UUID]
    price_min: int | None
    price_max: int | None


@dataclass(frozen=True)
class BuyerCandidateFacts:
    """바이어 점수 계산에 쓰는, 이미 조회된 후보(업체/제품) 사실관계."""

    recommendable_id: uuid.UUID
    category_concept_ids: frozenset[uuid.UUID]
    wholesale_price_amount: int | None
    min_order_quantity: int | None


@dataclass(frozen=True)
class BuyerProfileFacts:
    """08단계 바이어 프로파일에서 뽑아낸, 이미 해석된 거래 요구."""

    required_category_concept_ids: frozenset[uuid.UUID]
    target_price_max: int | None
    max_order_quantity: int | None


@dataclass(frozen=True)
class ExhibitorCandidateFacts:
    """양면 적합도의 업체->바이어 방향 계산에 쓰는, 이미 조회된 업체 사실관계."""

    recommendable_id: uuid.UUID
    monthly_capacity: int | None


@dataclass(frozen=True)
class ExhibitorProfileFacts:
    """업체가 이 바이어를 어느 정도 원하는지 판단하는 데 필요한, 바이어 쪽 요구량."""

    requested_monthly_units: int | None


def _price_match(
    price: int | None, price_min: int | None, price_max: int | None
) -> Decimal | None:
    """가격이 [price_min, price_max] 안에 있으면 1.0, 벗어난 정도에 따라 선형 감쇠한다.

    05단계 상세설계 5.6절 Feature Builder 출력 예시의 price_match(0.92 등 [0,1] 소수)와
    같은 형태를 따른다. 상·하한이 전혀 없으면(사용자가 가격을 입력하지 않음) None을
    반환한다 - 가격 조건 자체가 없으므로 "정보 없음"이 맞다.
    """

    if price is None or (price_min is None and price_max is None):
        return None
    if price_min is not None and price < price_min:
        gap = Decimal(price_min - price) / Decimal(max(price_min, 1))
        return max(Decimal(0), Decimal(1) - gap)
    if price_max is not None and price > price_max:
        gap = Decimal(price - price_max) / Decimal(max(price_max, 1))
        return max(Decimal(0), Decimal(1) - gap)
    return Decimal(1)


def _category_match(
    candidate_concepts: frozenset[uuid.UUID], required_concepts: frozenset[uuid.UUID]
) -> Decimal | None:
    """단순 교집합 기반 일치도. 상위·하위 개념 감쇠(match_strength)는 이후 온톨로지
    코드 해석 계층이 연결되면 여기에 추가한다 - 지금은 concept_id 자체만 비교한다."""

    if not required_concepts:
        return None
    return Decimal(1) if candidate_concepts & required_concepts else Decimal(0)


def build_consumer_components(
    candidate: ConsumerCandidateFacts, profile: ConsumerProfileFacts
) -> Mapping[str, Decimal | None]:
    """CONSUMER_SCORE_V1 구성요소(goal/category/sensory/price/alcohol/service/usage/
    behavior/trust) 중 계산 가능한 것만 채운다."""

    return {
        "goal": None,
        "category": _category_match(
            candidate.category_concept_ids, profile.required_category_concept_ids
        ),
        "sensory": None,
        "price": _price_match(
            candidate.event_price_amount, profile.price_min, profile.price_max
        ),
        "alcohol": None,
        "service": None,
        "usage": None,
        "behavior": None,
        "trust": None,
    }


def build_buyer_components(
    candidate: BuyerCandidateFacts, profile: BuyerProfileFacts
) -> Mapping[str, Decimal | None]:
    """BUYER_SCORE_V1 구성요소(business_goal/product/channel/price/moq/capacity/region/
    cooperation/meeting/trust) 중 계산 가능한 것만 채운다."""

    moq_score: Decimal | None
    if candidate.min_order_quantity is None or profile.max_order_quantity is None:
        moq_score = None
    elif candidate.min_order_quantity <= profile.max_order_quantity:
        moq_score = Decimal(1)
    else:
        moq_score = Decimal(0)

    return {
        "business_goal": None,
        "product": _category_match(
            candidate.category_concept_ids, profile.required_category_concept_ids
        ),
        "channel": None,
        "price": _price_match(
            candidate.wholesale_price_amount, None, profile.target_price_max
        ),
        "moq": moq_score,
        "capacity": None,
        "region": None,
        "cooperation": None,
        "meeting": None,
        "trust": None,
    }


def build_exhibitor_components(
    candidate: ExhibitorCandidateFacts, profile: ExhibitorProfileFacts
) -> Mapping[str, Decimal | None]:
    """EXHIBITOR_SCORE_V1 구성요소(buyer_type/channel/order_volume/region/trade_type/
    portfolio/decision_timing/verification/meeting_readiness) 중 계산 가능한 것만
    채운다 - 양면 적합도(calculate_reciprocal_score)의 업체->바이어 방향 입력이다."""

    order_volume_score: Decimal | None
    if candidate.monthly_capacity is None or profile.requested_monthly_units is None:
        order_volume_score = None
    elif candidate.monthly_capacity >= profile.requested_monthly_units:
        order_volume_score = Decimal(1)
    else:
        order_volume_score = Decimal(0)

    return {
        "buyer_type": None,
        "channel": None,
        "order_volume": order_volume_score,
        "region": None,
        "trade_type": None,
        "portfolio": None,
        "decision_timing": None,
        "verification": None,
        "meeting_readiness": None,
    }


def component_confidence(components: Mapping[str, Decimal | None]) -> Decimal:
    """채워진(None이 아닌) 구성요소 비율을 신뢰도 대리지표로 쓴다 (모듈 docstring
    "구현 범위와 남은 작업" 참고). 구성요소가 하나도 없으면(전부 None) 0을 반환한다 -
    아무 근거 없이 신뢰도를 지어내지 않는다."""

    if not components:
        return Decimal(0)
    filled = sum(1 for value in components.values() if value is not None)
    return Decimal(filled) / Decimal(len(components))
