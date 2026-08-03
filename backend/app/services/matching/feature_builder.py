"""Feature Builder: 후보 특징을 meet_ai.scoring 구성요소 코드로 변환한다.

근거 문서: docs/11-13-scoring-implementation.md "다음 구현 순서" 3번 - "후보 특징을 본
계산 코어의 구성요소 코드로 변환하는 Feature Builder를 연결한다". 이 모듈이 그 연결부다.
출력 dict의 키는 meet_ai.scoring.CONSUMER_SCORE_V1/BUYER_SCORE_V1의 weights 키와 정확히
일치해야 하며(불일치 시 calculate_directional_score가 ScoreValidationError를 낸다), 값은
전부 [0, 1] 구간이거나 None(정보 없음)이다.

구현 범위와 남은 작업
----------------------
현재 채워지는 구성요소:
    - CONSUMER_SCORE_V1: category, price, goal/sensory/alcohol/usage(온톨로지 concept
      매칭, 아래 "concept 기반 구성요소" 참고), service(SERVICE.TASTING/SERVICE.PURCHASE
      요구를 exhibition.event_product.tasting_status/purchase_status와 비교)
    - BUYER_SCORE_V1: product, price, moq, business_goal/channel/region(concept 매칭),
      capacity(exhibition.supply_capability.available_capacity 숫자 비교),
      cooperation(TRADE.OEM/TRADE.PB/TRADE.EXPORT 요구를 exhibition.trade_condition의
      oem_status/private_label_status/export_status 상태값과 비교)
    - EXHIBITOR_SCORE_V1 (양면 적합도의 업체->바이어 방향): order_volume,
      buyer_type/channel/region(exhibition.buyer_preference와 바이어 자신의
      profile_attribute concept 매칭 - 아래 "concept 기반 구성요소" 참고),
      verification(exhibition.supply_capability.verification_status를 [0,1]로 변환 -
      매칭 대상이 아니라 후보 자체의 품질 신호라 profile 쪽 요구가 필요 없다)

`component_confidence()`는 calculate_reciprocal_score가 요구하는 buyer_confidence/
exhibitor_confidence(선택값이 아니라 필수 Number)를 만들기 위한 임시 대리지표다 - 실제
데이터 신뢰도 모델(08단계 16절)이 아직 연결되지 않아, 채워진 구성요소 비율로 대신한다.
근거 데이터가 늘어나면 이 함수를 실제 신뢰도 계산으로 교체해야 한다.

concept 기반 구성요소 (profile_resolver 연결)
------------------------------------------------
docs/06-matching-ontology.md 5.1/8~14절은 attribute_code 접두어(GOAL.*, TASTE.*,
AROMA.*, ALCOHOL_LEVEL.*, USE.*, BIZ_GOAL.*, CHANNEL.*, REGION.* 등)로 concept_type을
구분한다. `_COMPONENT_BY_CODE_PREFIX`가 그 접두어를 meet_ai.scoring 구성요소 이름에
매핑하고, `group_concept_ids_by_component()`가 (attribute_code, concept_id) 쌍들을
구성요소별 집합으로 묶는다. profile.profile_attribute.attribute_code는 이미 비정규화된
문자열이라 접두어를 바로 쓸 수 있지만(orchestrator._required_concept_ids_by_component),
후보 쪽(exhibition.product_attribute)은 concept_id만 있고 attribute_code가 없어
ontology.concept과 조인해 concept_code를 얻어야 한다(orchestrator._load_consumer_
candidate_facts 참고) - 이 모듈 자체는 이미 묶인 dict만 받아 순수하게 교집합만 비교한다.

여전히 None으로 남기는 구성요소와 이유:
    - trade_type(EXHIBITOR): cooperation(BUYER)과 원본 데이터(trade_condition의
      oem/pb/export status)는 같지만, exhibition.buyer_preference에 channel/region은
      있어도 "업체가 원하는 거래유형" 차원이 없어(그 테이블 CHECK가 buyer_type/channel/
      region 3개뿐) cooperation과 구분되는 반대 방향 신호가 없다 - 억지로 cooperation과
      같은 값을 넣으면 두 번 세는 것과 같아 None으로 둔다.
    - portfolio/decision_timing/meeting_readiness(EXHIBITOR): 각각 제품 포트폴리오
      다양성, profile.buyer_need.decision_timeline과의 비교, 상담 가능 시간대가
      필요한데 이 커밋 시점에는 그 데이터를 읽어올 조회 계층이 아직 없다.
    - meeting(BUYER), behavior(CONSUMER), trust(모두): 상담 주제 프로파일, 행동 이벤트
      집계, 데이터 신뢰도 모델이 각각 필요한데 이 커밋 시점에는 그 데이터를 읽어올 조회
      계층이 아직 없다.
meet_ai.scoring.calculate_directional_score는 None을 "정보 없음"으로 처리해 가중치
분모에서 제외하므로(11~13단계 구현 기록 "구현 범위" 2번), 이 모듈이 값을 지어내는 것보다
정직하게 None을 반환하는 편이 계산 계약에 맞다.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal

#: attribute_code의 "." 이전 접두어 -> meet_ai.scoring 구성요소 이름. docs/06-matching-
#: ontology.md 5.1/8~14절의 concept_type별 코드 접두어 규약을 그대로 따른다. sensory는
#: TASTE·AROMA 두 접두어를 묶는다(05단계 5.6절 "맛(sensory)"이 미각+후각을 합친 개념이라).
#: 매핑에 없는 접두어(예: PRICE_BAND, ACTION)는 이 모듈이 다루는 구성요소가 아니다.
_COMPONENT_BY_CODE_PREFIX: Mapping[str, str] = {
    "GOAL": "goal",
    "BIZ_GOAL": "business_goal",
    "TASTE": "sensory",
    "AROMA": "sensory",
    "ALCOHOL_LEVEL": "alcohol",
    "USE": "usage",
    "CHANNEL": "channel",
    "REGION": "region",
    "BUYER": "buyer_type",
}


def component_of_attribute_code(attribute_code: str) -> str | None:
    """예: "TASTE.DRY" -> "sensory". 이 모듈이 다루지 않는 접두어는 None을 반환한다."""

    prefix = attribute_code.split(".", 1)[0]
    return _COMPONENT_BY_CODE_PREFIX.get(prefix)


def group_concept_ids_by_component(
    codes_and_concepts: Iterable[tuple[str, uuid.UUID]],
) -> dict[str, frozenset[uuid.UUID]]:
    """(attribute_code, concept_id) 쌍들을 구성요소별 concept_id 집합으로 묶는다."""

    grouped: dict[str, set[uuid.UUID]] = {}
    for attribute_code, concept_id in codes_and_concepts:
        component = component_of_attribute_code(attribute_code)
        if component is None:
            continue
        grouped.setdefault(component, set()).add(concept_id)
    return {component: frozenset(ids) for component, ids in grouped.items()}


@dataclass(frozen=True)
class ConsumerCandidateFacts:
    """일반 관람객 점수 계산에 쓰는, 이미 조회된 후보 사실관계."""

    recommendable_id: uuid.UUID
    category_concept_ids: frozenset[uuid.UUID]
    event_price_amount: int | None
    #: exhibition.product_attribute를 concept_type별로 묶은 결과(group_concept_ids_
    #: by_component 출력). 데이터가 없으면 빈 dict - 모든 concept 기반 구성요소가 None이
    #: 된다.
    concept_ids_by_component: Mapping[str, frozenset[uuid.UUID]] = field(
        default_factory=dict
    )
    #: exhibition.event_product.tasting_status/purchase_status == 'AVAILABLE'.
    #: hard_filter_engine.rule_required_service와 같은 데이터를 소프트 점수용으로도 쓴다.
    tasting_available: bool | None = None
    purchase_available: bool | None = None


@dataclass(frozen=True)
class ConsumerProfileFacts:
    """9단계 검색 요청 객체·07단계 프로파일에서 뽑아낸, 이미 해석된 사용자 요구."""

    required_category_concept_ids: frozenset[uuid.UUID]
    price_min: int | None
    price_max: int | None
    #: profile.profile_attribute(active)의 attribute_code 중 "SERVICE."로 시작하는 것들
    #: (예: "SERVICE.TASTING") 전체 - concept_id가 아니라 문자열 자체로 비교한다(온톨로지
    #: 카탈로그의 고정 코드 "SERVICE.TASTING"/"SERVICE.PURCHASE"를 그대로 쓰는 게, concept_id
    #: 교집합보다 단순하고 이 두 값만 다루면 충분하기 때문이다 - _component_match 같은
    #: 범용 메커니즘을 새로 만들 필요가 없다).
    required_service_codes: frozenset[str] = field(default_factory=frozenset)
    #: profile.profile_attribute(active)를 concept_type별로 묶은 결과.
    required_concept_ids_by_component: Mapping[str, frozenset[uuid.UUID]] = field(
        default_factory=dict
    )


@dataclass(frozen=True)
class BuyerCandidateFacts:
    """바이어 점수 계산에 쓰는, 이미 조회된 후보(업체/제품) 사실관계."""

    recommendable_id: uuid.UUID
    category_concept_ids: frozenset[uuid.UUID]
    wholesale_price_amount: int | None
    min_order_quantity: int | None
    #: exhibition.trade_condition_term(term_type='CHANNEL'/'REGION')을 구성요소별로
    #: 묶은 결과 - term_type이 이미 소문자화하면 구성요소 이름과 같다("CHANNEL" ->
    #: "channel").
    concept_ids_by_component: Mapping[str, frozenset[uuid.UUID]] = field(
        default_factory=dict
    )
    #: exhibition.supply_capability.available_capacity(업체 공통, product_id IS NULL) -
    #: 10단계 15.2절 "전체 생산량이 아니라 신규계약에 쓸 수 있는 잔여 생산량"과 같은 값.
    #: trade_condition.monthly_capacity(전체 생산량, EXHIBITOR_SCORE_V1의 order_volume이
    #: 이미 쓴다)와는 다른 숫자다.
    available_capacity: int | None = None
    #: exhibition.trade_condition.oem_status/private_label_status/export_status
    #: (YES/NO/CONDITIONAL/NEGOTIABLE/UNKNOWN, 업체 공통). cooperation 구성요소가
    #: 바이어가 요구하는 거래유형(required_trade_codes)에 대응하는 상태만 골라 본다.
    oem_status: str | None = None
    private_label_status: str | None = None
    export_status: str | None = None


@dataclass(frozen=True)
class BuyerProfileFacts:
    """08단계 바이어 프로파일에서 뽑아낸, 이미 해석된 거래 요구."""

    required_category_concept_ids: frozenset[uuid.UUID]
    target_price_max: int | None
    max_order_quantity: int | None
    required_concept_ids_by_component: Mapping[str, frozenset[uuid.UUID]] = field(
        default_factory=dict
    )
    #: profile.buyer_need.monthly_units_min/max에서 뽑아낸, 바이어가 매달 구매하려는
    #: 물량 - available_capacity와 비교할 대상이다(ExhibitorProfileFacts.
    #: requested_monthly_units와 같은 값을 재사용해도 된다, orchestrator.py 참고).
    requested_monthly_units: int | None = None
    #: profile.profile_attribute(active)의 attribute_code 중 "TRADE."로 시작하는 것들
    #: (예: "TRADE.OEM") - service와 같은 이유로 concept_id가 아니라 문자열 자체로
    #: 비교한다(_TRADE_CODE_TO_STATUS_FIELD가 다루는 고정 코드 3개뿐이므로).
    required_trade_codes: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True)
class ExhibitorCandidateFacts:
    """양면 적합도의 업체->바이어 방향 계산에 쓰는, 이미 조회된 업체 사실관계."""

    recommendable_id: uuid.UUID
    monthly_capacity: int | None
    #: exhibition.buyer_preference(buyer_type_concept_id/channel_concept_id/
    #: region_concept_id)를 구성요소별로 묶은 결과 - "업체가 원하는 바이어 프로파일"
    #: (08단계 8.3절)이다.
    preference_concept_ids_by_component: Mapping[str, frozenset[uuid.UUID]] = field(
        default_factory=dict
    )
    #: exhibition.supply_capability.verification_status(SELF_DECLARED/DOCUMENT_SUBMITTED/
    #: OPERATOR_REVIEWED/VERIFIED/EXPIRED/REJECTED). 프로파일 쪽 "요구"가 없는 순수
    #: 후보 품질 신호라 매칭이 아니라 상태값 자체를 점수로 변환한다(_verification_score).
    verification_status: str | None = None


@dataclass(frozen=True)
class ExhibitorProfileFacts:
    """업체가 이 바이어를 어느 정도 원하는지 판단하는 데 필요한, 바이어 쪽 요구량."""

    requested_monthly_units: int | None
    #: 바이어 자신의 buyer_type/channel/region concept_id 집합 - BuyerProfileFacts.
    #: required_concept_ids_by_component와 같은 원본(profile.profile_attribute)에서
    #: 나온다(orchestrator.py에서 그대로 재사용한다).
    buyer_concept_ids_by_component: Mapping[str, frozenset[uuid.UUID]] = field(
        default_factory=dict
    )


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


def _component_match(
    component: str,
    candidate_concepts_by_component: Mapping[str, frozenset[uuid.UUID]],
    required_concepts_by_component: Mapping[str, frozenset[uuid.UUID]],
) -> Decimal | None:
    """_category_match와 같은 교집합 규칙(요구 없음=None, 후보에 없음=0, 교집합
    있음=1)을 구성요소별 concept_id 집합 dict에 재사용한다."""

    required = required_concepts_by_component.get(component, frozenset())
    if not required:
        return None
    candidate_concepts = candidate_concepts_by_component.get(component, frozenset())
    return Decimal(1) if candidate_concepts & required else Decimal(0)


#: 온톨로지 카탈로그의 고정 서비스 코드(BOOTH_SERVICE concept_type) -> 후보 사실관계
#: 필드 이름. 이 두 코드만 다루므로 attribute_code 문자열을 직접 비교한다(모듈 docstring
#: "concept 기반 구성요소" 참고 - concept_id 교집합 메커니즘을 새로 만들 필요가 없다).
_SERVICE_CODE_TO_AVAILABILITY_FIELD: Mapping[str, str] = {
    "SERVICE.TASTING": "tasting_available",
    "SERVICE.PURCHASE": "purchase_available",
}


def _service_match(
    candidate: ConsumerCandidateFacts, profile: ConsumerProfileFacts
) -> Decimal | None:
    """요구한 서비스(SERVICE.TASTING/SERVICE.PURCHASE) 중 하나라도 이용 불가면 0, 요구가
    없으면 None, 그 외(요구한 서비스가 전부 확인되고 이용 가능)면 1이다. hard_filter_
    engine.rule_required_service가 같은 데이터로 하드 배제를 하는 것과 달리, 여기서는
    소프트 점수 하나로만 반영한다."""

    if not profile.required_service_codes:
        return None
    for code in profile.required_service_codes:
        field_name = _SERVICE_CODE_TO_AVAILABILITY_FIELD.get(code)
        if field_name is None:
            continue
        if getattr(candidate, field_name) is False:
            return Decimal(0)
    return Decimal(1)


#: attribute_code(TRADE.*) -> exhibition.trade_condition 상태 필드 이름. 두 값 체계가
#: 다르므로(TRADE.* concept vs YES/NO/CONDITIONAL/NEGOTIABLE/UNKNOWN 상태) 여기서도
#: service처럼 concept_id가 아니라 문자열 자체로 비교한다.
_TRADE_CODE_TO_STATUS_FIELD: Mapping[str, str] = {
    "TRADE.OEM": "oem_status",
    "TRADE.PB": "private_label_status",
    "TRADE.EXPORT": "export_status",
}

#: exhibition.trade_condition의 YES/NO/CONDITIONAL/NEGOTIABLE/UNKNOWN 5단계(rule_
#: availability_status와 같은 값 체계, hard_filter_engine.py 참고) -> [0,1] 점수.
#: UNKNOWN은 매핑에 없다 - "정보 없음"으로 취급해 평균에서 제외한다.
_TRADE_STATUS_SCORE: Mapping[str, Decimal] = {
    "YES": Decimal(1),
    "CONDITIONAL": Decimal("0.5"),
    "NEGOTIABLE": Decimal("0.5"),
    "NO": Decimal(0),
}


def _cooperation_match(
    candidate: BuyerCandidateFacts, profile: BuyerProfileFacts
) -> Decimal | None:
    """바이어가 요구하는 거래유형(TRADE.OEM/TRADE.PB/TRADE.EXPORT)마다 업체의 실제
    상태값을 점수로 바꿔 평균한다. 요구가 없거나, 요구한 항목의 상태를 하나도 알 수
    없으면(전부 UNKNOWN이거나 매핑 밖 코드) None이다."""

    if not profile.required_trade_codes:
        return None
    scores: list[Decimal] = []
    for code in profile.required_trade_codes:
        field_name = _TRADE_CODE_TO_STATUS_FIELD.get(code)
        if field_name is None:
            continue
        status = getattr(candidate, field_name)
        score = _TRADE_STATUS_SCORE.get(status) if status is not None else None
        if score is not None:
            scores.append(score)
    if not scores:
        return None
    return sum(scores) / Decimal(len(scores))


def build_consumer_components(
    candidate: ConsumerCandidateFacts, profile: ConsumerProfileFacts
) -> Mapping[str, Decimal | None]:
    """CONSUMER_SCORE_V1 구성요소(goal/category/sensory/price/alcohol/service/usage/
    behavior/trust) 중 계산 가능한 것만 채운다."""

    def component(name: str) -> Decimal | None:
        return _component_match(
            name,
            candidate.concept_ids_by_component,
            profile.required_concept_ids_by_component,
        )

    return {
        "goal": component("goal"),
        "category": _category_match(
            candidate.category_concept_ids, profile.required_category_concept_ids
        ),
        "sensory": component("sensory"),
        "price": _price_match(
            candidate.event_price_amount, profile.price_min, profile.price_max
        ),
        "alcohol": component("alcohol"),
        "service": _service_match(candidate, profile),
        "usage": component("usage"),
        "behavior": None,
        "trust": None,
    }


def build_buyer_components(
    candidate: BuyerCandidateFacts, profile: BuyerProfileFacts
) -> Mapping[str, Decimal | None]:
    """BUYER_SCORE_V1 구성요소(business_goal/product/channel/price/moq/capacity/region/
    cooperation/meeting/trust) 중 계산 가능한 것만 채운다."""

    def component(name: str) -> Decimal | None:
        return _component_match(
            name,
            candidate.concept_ids_by_component,
            profile.required_concept_ids_by_component,
        )

    moq_score: Decimal | None
    if candidate.min_order_quantity is None or profile.max_order_quantity is None:
        moq_score = None
    elif candidate.min_order_quantity <= profile.max_order_quantity:
        moq_score = Decimal(1)
    else:
        moq_score = Decimal(0)

    capacity_score: Decimal | None
    if candidate.available_capacity is None or profile.requested_monthly_units is None:
        capacity_score = None
    elif candidate.available_capacity >= profile.requested_monthly_units:
        capacity_score = Decimal(1)
    else:
        capacity_score = Decimal(0)

    return {
        "business_goal": component("business_goal"),
        "product": _category_match(
            candidate.category_concept_ids, profile.required_category_concept_ids
        ),
        "channel": component("channel"),
        "price": _price_match(
            candidate.wholesale_price_amount, None, profile.target_price_max
        ),
        "moq": moq_score,
        "capacity": capacity_score,
        "region": component("region"),
        "cooperation": _cooperation_match(candidate, profile),
        "meeting": None,
        "trust": None,
    }


#: exhibition.supply_capability.verification_status(08단계 27.3절) -> [0,1] 점수. 검증
#: 단계가 깊을수록(자기신고 -> 서류제출 -> 운영자검토 -> 검증완료) 높은 점수를 준다.
#: EXPIRED/REJECTED는 한때 검증됐어도 지금은 신뢰할 수 없으므로 0이다.
_VERIFICATION_STATUS_SCORE: Mapping[str, Decimal] = {
    "VERIFIED": Decimal(1),
    "OPERATOR_REVIEWED": Decimal("0.75"),
    "DOCUMENT_SUBMITTED": Decimal("0.5"),
    "SELF_DECLARED": Decimal("0.25"),
    "EXPIRED": Decimal(0),
    "REJECTED": Decimal(0),
}


def _verification_score(verification_status: str | None) -> Decimal | None:
    """프로파일 쪽 "요구"가 없는 순수 후보 품질 신호라 매칭이 아니라 상태값 자체를
    점수로 바꾼다 - _category_match/_component_match와 달리 profile 인자를 받지 않는다."""

    if verification_status is None:
        return None
    return _VERIFICATION_STATUS_SCORE.get(verification_status)


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

    def preference_component(name: str) -> Decimal | None:
        # 여기서는 "요구"가 업체의 선호(candidate)고 "후보"가 바이어 자신의 속성
        # (profile)이다 - build_consumer/buyer_components와 candidate/required 역할이
        # 뒤바뀐다(이 방향은 "바이어가 업체의 희망 프로파일에 맞는지"를 묻기 때문).
        return _component_match(
            name,
            profile.buyer_concept_ids_by_component,
            candidate.preference_concept_ids_by_component,
        )

    return {
        "buyer_type": preference_component("buyer_type"),
        "channel": preference_component("channel"),
        "order_volume": order_volume_score,
        "region": preference_component("region"),
        "trade_type": None,
        "portfolio": None,
        "decision_timing": None,
        "verification": _verification_score(candidate.verification_status),
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
