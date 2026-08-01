"""Recommendation Orchestrator: 9~13단계를 하나의 추천 실행으로 연결한다.

근거 문서: docs/05-ai-matching-engine-architecture.md 4절 매칭엔진 전체 구성,
docs/11-13-scoring-implementation.md "다음 구현 순서". 이 모듈이 그 순서의 1~3번
(후보검색 -> Hard Filter -> Feature Builder -> 점수 계산)을 실제로 이어 붙인 결과다.

구현 범위와 남은 작업
----------------------
- GENERAL_VISITOR/PRODUCT 경로: 구조화 검색(하나뿐인 채널) -> 후보 풀 구성 -> Hard Filter
  평가 -> Feature Builder -> meet_ai.scoring.calculate_directional_score ->
  RecommendationSession/MatchResult/MatchReason/FilterResult 영속화까지 동작한다.
- BUYER/EXHIBITOR 경로: 같은 파이프라인에 calculate_reciprocal_score(양면 적합도)를
  더해 구현했다. recommended_action 어휘 불일치가 있다 - 아래 "recommended_action
  어휘 불일치" 절 참고.
- 14단계 상황 재정렬(`context_reranker.py`)과 18단계 추천 이유 생성(`reason_generator.py`)을
  GENERAL_VISITOR 경로에 연결했다. BUYER/EXHIBITOR 경로는 아직이다: 재정렬은 두 경로가
  같은 context_snapshot을 쓰므로 확장이 쉽지만, 이유 생성은 `ReciprocalScoreResult`에
  `contributions`가 없어(reason_generator.py 모듈 docstring 참고) 그대로 재사용할 수
  없다 - 기존 `_template_reciprocal_reason_text`를 유지한다.
- 상황 재정렬은 `context_resolver.py`가 실제로 제공하는 신호(remaining_minutes,
  next_schedule_at)만 쓴다 - 05단계 5.9절이 언급하는 부스 대기시간·품절 임박·프로그램
  시작시간은 혼잡도 스트림·재고 이벤트 파이프라인이 아직 없어 훅만 남겼다
  (context_reranker.py의 `ContextSignals` 참고).
- MatchResult.raw_score/normalized_score는 두 경로에서 의미가 다르다: GENERAL_VISITOR는
  DirectionalScoreResult.uncapped_score(0~1)/final_score(0~100), BUYER는
  ReciprocalScoreResult.uncapped_final_score/final_reciprocal_score(둘 다 0~100 스케일이라
  raw_score에도 100 스케일 그대로 넣는다 - 두 경로의 raw_score가 같은 척도가 아니라는 뜻이며,
  경로 간 raw_score를 직접 비교해서는 안 된다).

recommended_action 두 어휘 체계
--------------------------------
meet_ai.scoring.calculate_reciprocal_score가 반환하는 recommended_action(DO_NOT_PUSH/
REQUEST_INFORMATION/CONFIRM_TRADE_CONDITION/REQUEST_MEETING)은 GENERAL_VISITOR 경로가
쓰는 5단계 7.2절 어휘(VISIT_NOW 등)와 서로 다른 체계다. matching.match_result.
recommended_action CHECK 제약(app/models/matching.py의 RECOMMENDED_ACTIONS)은
0008_widen_recommended_action 마이그레이션 이후 두 어휘의 합집합을 허용하므로, 이 파일은
BUYER 경로의 recommended_action 값을 그대로 저장한다(더 이상 값 매핑이 필요 없다). 다만
DO_NOT_PUSH는 "이 후보를 밀지 말라"는 스코어링 코어의 판단이므로, 값 자체는 저장 가능해도
최종 추천 결과(top-N)에는 올리지 않는다 - 이는 어휘 제약이 아니라 추천 정책 결정이다
(_EXCLUDED_RECIPROCAL_ACTIONS 참고).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from meet_ai.scoring import (
    BUYER_SCORE_V1,
    CONSUMER_SCORE_V1,
    EXHIBITOR_SCORE_V1,
    DirectionalScoreResult,
    EligibilityDecision,
    ReciprocalScoreResult,
    calculate_directional_score,
    calculate_reciprocal_score,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exhibitor import (
    EventProduct,
    ExhibitorParticipation,
    Product,
    ProductAttribute,
    TradeCondition,
    TradeConditionTerm,
)
from app.models.matching import (
    FilterResult,
    MatchReason,
    MatchResult,
    Recommendable,
    RecommendationSession,
)
from app.models.ontology_refs import concept as ontology_concept
from app.services.matching.candidate_generator import (
    build_candidate_pool,
    reciprocal_rank_fusion,
    structured_search_exhibitors,
    structured_search_products,
)
from app.services.matching.context_reranker import ContextSignals
from app.services.matching.context_reranker import rerank as rerank_by_context
from app.services.matching.context_resolver import ContextResolution, resolve_context
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
    component_confidence,
    group_concept_ids_by_component,
)
from app.services.matching.hard_filter_engine import (
    EligibilityResult,
    FilterContext,
    HardFilterRule,
    evaluate_candidates,
    to_filter_result_rows,
)
from app.services.matching.profile_resolver import resolve_profile
from app.services.matching.reason_generator import generate_directional_reasons
from app.services.matching.request_validator import validate_request

#: 스코어링 코어가 "밀지 말라"고 판단한 후보는 값 자체는 저장 가능해도(모듈 docstring
#: "recommended_action 두 어휘 체계" 참고) 최종 추천 결과에는 올리지 않는다.
_EXCLUDED_RECIPROCAL_ACTIONS: frozenset[str] = frozenset({"DO_NOT_PUSH"})


@dataclass(frozen=True)
class GeneralVisitorRecommendationRequest:
    tenant_id: uuid.UUID
    event_id: uuid.UUID
    profile_id: uuid.UUID
    visit_session_id: uuid.UUID | None
    policy_version_id: uuid.UUID
    required_category_concept_ids: frozenset[uuid.UUID]
    price_min: int | None
    price_max: int | None
    limit: int = 10
    candidate_pool_target: int = 150
    candidate_pool_minimum: int = 20
    extra_hard_filter_rules: Sequence[HardFilterRule] = ()


async def generate_general_visitor_recommendations(
    session: AsyncSession, request: GeneralVisitorRecommendationRequest
) -> RecommendationSession:
    profile_resolution = await resolve_profile(session, request.profile_id)
    validate_request(
        profile=profile_resolution.profile,
        recommendation_type="PRODUCT",
        limit=request.limit,
    )
    context = await resolve_context(session, request.visit_session_id)

    channel_result = await structured_search_products(
        session,
        event_id=request.event_id,
        category_concept_ids=request.required_category_concept_ids or None,
        price_max=request.price_max,
        limit=max(request.candidate_pool_target, 1),
    )
    fused = reciprocal_rank_fusion([channel_result])
    pool = build_candidate_pool(
        fused,
        target_count=request.candidate_pool_target,
        minimum_count=request.candidate_pool_minimum,
    )

    recommendation_session = RecommendationSession(
        tenant_id=request.tenant_id,
        event_id=request.event_id,
        profile_id=profile_resolution.profile.profile_id,
        profile_version_id=profile_resolution.latest_version.profile_version_id,
        visit_session_id=request.visit_session_id,
        recommendation_type="PRODUCT",
        policy_version_id=request.policy_version_id,
        context_snapshot=context.to_snapshot(),
        candidate_count=len(fused),
        filtered_count=0,
        result_count=0,
        status="ACTIVE",
    )
    session.add(recommendation_session)
    await session.flush()

    recommendable_ids = [candidate.recommendable_id for candidate in pool.candidates]
    filter_context = FilterContext(candidate_values={}, user_requirements={})
    eligibility_results = evaluate_candidates(
        recommendable_ids,
        rules=request.extra_hard_filter_rules,
        context=filter_context,
        evaluation_id_of=lambda rid: (
            f"{recommendation_session.recommendation_session_id}:{rid}"
        ),
        mode="PRODUCTION",
    )
    eligible_by_id = {
        result.recommendable_id: result
        for result in eligibility_results
        if result.passed
    }

    facts_by_id = await _load_consumer_candidate_facts(
        session, list(eligible_by_id), fused
    )
    profile_facts = ConsumerProfileFacts(
        required_category_concept_ids=request.required_category_concept_ids,
        price_min=request.price_min,
        price_max=request.price_max,
        required_concept_ids_by_component=group_concept_ids_by_component(
            (attribute.attribute_code, attribute.concept_id)
            for attribute in profile_resolution.active_attributes
        ),
    )

    scored: dict[uuid.UUID, tuple[DirectionalScoreResult, EligibilityResult]] = {}
    for recommendable_id, candidate_facts in facts_by_id.items():
        eligibility_result = eligible_by_id[recommendable_id]
        components = build_consumer_components(candidate_facts, profile_facts)
        score_result = calculate_directional_score(
            CONSUMER_SCORE_V1,
            components,
            eligibility=EligibilityDecision(
                passed=True, evaluation_id=eligibility_result.evaluation_id
            ),
        )
        scored[recommendable_id] = (score_result, eligibility_result)

    # 14단계 상황 재정렬: 기본 적합도(final_score)는 그대로 두고 상황 신호로 최종 순위만
    # 다시 매긴다(context_reranker.py 모듈 docstring "기본 적합도와 분리해 저장한다").
    context_signals = _context_signals(context)
    reranked = rerank_by_context(
        [
            (recommendable_id, score_result.final_score)
            for recommendable_id, (score_result, _eligibility) in scored.items()
        ],
        signals_of=lambda _recommendable_id: context_signals,
    )
    top = reranked[: request.limit]

    for rank, reranked_candidate in enumerate(top, start=1):
        recommendable_id = reranked_candidate.recommendable_id
        score_result, _eligibility = scored[recommendable_id]
        # goal_score/trust_score만 CONSUMER_SCORE_V1 구성요소와 이름이 정확히 대응한다.
        # 나머지 match_result 점수 분해 컬럼(preference/trade/behavior_score)은 scoring
        # 코어의 구성요소 이름과 1:1로 맞지 않아 지금은 채우지 않는다 - 억지로 category
        # 등을 끼워 넣으면 나중에 진짜 preference_score를 정의할 때 혼동만 남는다.
        match_result = MatchResult(
            recommendation_session_id=recommendation_session.recommendation_session_id,
            recommendable_id=recommendable_id,
            raw_score=score_result.uncapped_score,
            normalized_score=score_result.final_score,
            rank=rank,
            goal_score=components_score(score_result, "goal"),
            trust_score=components_score(score_result, "trust"),
            context_score=reranked_candidate.context_score,
            recommended_action="VISIT_NOW",
        )
        session.add(match_result)
        await session.flush()
        for reason in generate_directional_reasons(score_result):
            session.add(
                MatchReason(
                    match_result_id=match_result.match_result_id,
                    reason_code=reason.reason_code,
                    reason_text=reason.reason_text,
                    contribution_score=reason.contribution_score,
                    display_order=reason.display_order,
                    generated_by="TEMPLATE",
                    validation_status="VALID",
                )
            )

    for row in to_filter_result_rows(
        eligibility_results,
        recommendation_session_id=recommendation_session.recommendation_session_id,
        policy_version_id=request.policy_version_id,
    ):
        session.add(FilterResult(**row))

    recommendation_session.filtered_count = len(recommendable_ids) - len(eligible_by_id)
    recommendation_session.result_count = len(top)

    return recommendation_session


def components_score(result: DirectionalScoreResult, component: str) -> float | None:
    value = result.component_values.get(component)
    return float(value) if value is not None else None


def _context_signals(context: ContextResolution) -> ContextSignals:
    """context_resolver.py의 ContextResolution -> context_reranker.py의 ContextSignals.

    지금은 방문세션 전체에 공통인 신호(남은 체류시간, 다음 확정 일정)만 있고 후보(부스)별
    신호가 없어, 모든 후보에 같은 ContextSignals를 재사용한다(orchestrator의
    rerank_by_context 호출부 참고) - 부스별 혼잡도·대기시간이 연결되면 recommendable_id로
    분기하는 signals_of로 바꿔야 한다.
    """

    if context.latest_context is None:
        return ContextSignals()
    return ContextSignals(
        remaining_minutes=context.latest_context.remaining_minutes,
        next_schedule_at=context.latest_context.next_schedule_at,
        now=context.latest_context.captured_at,
    )


async def _load_consumer_candidate_facts(
    session: AsyncSession,
    recommendable_ids: Sequence[uuid.UUID],
    fused_candidates: Sequence,
) -> dict[uuid.UUID, ConsumerCandidateFacts]:
    if not recommendable_ids:
        return {}

    concept_ids_by_recommendable = {
        candidate.recommendable_id: candidate.matched_concept_ids
        for candidate in fused_candidates
    }

    stmt = (
        select(
            Recommendable.recommendable_id,
            EventProduct.event_price_amount,
            Product.category_concept_id,
        )
        .join(
            EventProduct,
            EventProduct.event_product_id == Recommendable.event_product_id,
        )
        .join(Product, Product.product_id == EventProduct.product_id)
        .where(Recommendable.recommendable_id.in_(recommendable_ids))
    )
    rows = (await session.execute(stmt)).all()

    attribute_components_by_id = await _consumer_concept_ids_by_component(
        session, recommendable_ids
    )

    facts: dict[uuid.UUID, ConsumerCandidateFacts] = {}
    for recommendable_id, event_price_amount, category_concept_id in rows:
        concept_ids = set(concept_ids_by_recommendable.get(recommendable_id, ()))
        if category_concept_id is not None:
            concept_ids.add(category_concept_id)
        facts[recommendable_id] = ConsumerCandidateFacts(
            recommendable_id=recommendable_id,
            category_concept_ids=frozenset(concept_ids),
            event_price_amount=event_price_amount,
            concept_ids_by_component=attribute_components_by_id.get(
                recommendable_id, {}
            ),
        )
    return facts


async def _consumer_concept_ids_by_component(
    session: AsyncSession, recommendable_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, frozenset[uuid.UUID]]]:
    """recommendable_id -> feature_builder 구성요소별 concept_id 집합.

    exhibition.product_attribute는 concept_id만 갖고 attribute_code(비정규화 코드)가
    없어(app/models/exhibitor.py ProductAttribute 참고) ontology.concept과 조인해
    concept_code를 얻은 뒤 group_concept_ids_by_component로 묶는다. 검수를 통과한
    (review_status='APPROVED') 속성만 쓴다 - 그 모델 docstring의 "AI 추출 금지·제한사항"
    원칙에 따라 미검수 속성은 매칭 근거로 쓰지 않는다.
    """

    if not recommendable_ids:
        return {}

    stmt = (
        select(
            Recommendable.recommendable_id,
            ontology_concept.c.concept_code,
            ProductAttribute.concept_id,
        )
        .join(
            EventProduct,
            EventProduct.event_product_id == Recommendable.event_product_id,
        )
        .join(ProductAttribute, ProductAttribute.product_id == EventProduct.product_id)
        .join(
            ontology_concept,
            ontology_concept.c.concept_id == ProductAttribute.concept_id,
        )
        .where(
            Recommendable.recommendable_id.in_(recommendable_ids),
            ProductAttribute.review_status == "APPROVED",
        )
    )
    rows = (await session.execute(stmt)).all()

    codes_by_recommendable: dict[uuid.UUID, list[tuple[str, uuid.UUID]]] = {}
    for recommendable_id, concept_code, concept_id in rows:
        codes_by_recommendable.setdefault(recommendable_id, []).append(
            (concept_code, concept_id)
        )
    return {
        recommendable_id: group_concept_ids_by_component(codes)
        for recommendable_id, codes in codes_by_recommendable.items()
    }


# ============================================================================
# BUYER/EXHIBITOR 경로 - 양면 적합도(calculate_reciprocal_score) 연결
# ============================================================================


@dataclass(frozen=True)
class BuyerRecommendationRequest:
    tenant_id: uuid.UUID
    event_id: uuid.UUID
    profile_id: uuid.UUID
    visit_session_id: uuid.UUID | None
    policy_version_id: uuid.UUID
    required_category_concept_ids: frozenset[uuid.UUID]
    target_price_max: int | None
    max_order_quantity: int | None
    requested_monthly_units: int | None
    limit: int = 10
    candidate_pool_target: int = 150
    candidate_pool_minimum: int = 20
    extra_hard_filter_rules: Sequence[HardFilterRule] = ()


async def generate_buyer_recommendations(
    session: AsyncSession, request: BuyerRecommendationRequest
) -> RecommendationSession:
    profile_resolution = await resolve_profile(session, request.profile_id)
    validate_request(
        profile=profile_resolution.profile,
        recommendation_type="EXHIBITOR",
        limit=request.limit,
    )
    context = await resolve_context(session, request.visit_session_id)

    channel_result = await structured_search_exhibitors(
        session,
        event_id=request.event_id,
        moq_max=request.max_order_quantity,
        limit=max(request.candidate_pool_target, 1),
    )
    fused = reciprocal_rank_fusion([channel_result])
    pool = build_candidate_pool(
        fused,
        target_count=request.candidate_pool_target,
        minimum_count=request.candidate_pool_minimum,
    )

    recommendation_session = RecommendationSession(
        tenant_id=request.tenant_id,
        event_id=request.event_id,
        profile_id=profile_resolution.profile.profile_id,
        profile_version_id=profile_resolution.latest_version.profile_version_id,
        visit_session_id=request.visit_session_id,
        recommendation_type="EXHIBITOR",
        policy_version_id=request.policy_version_id,
        context_snapshot=context.to_snapshot(),
        candidate_count=len(fused),
        filtered_count=0,
        result_count=0,
        status="ACTIVE",
    )
    session.add(recommendation_session)
    await session.flush()

    recommendable_ids = [candidate.recommendable_id for candidate in pool.candidates]
    filter_context = FilterContext(candidate_values={}, user_requirements={})
    eligibility_results = evaluate_candidates(
        recommendable_ids,
        rules=request.extra_hard_filter_rules,
        context=filter_context,
        evaluation_id_of=lambda rid: (
            f"{recommendation_session.recommendation_session_id}:{rid}"
        ),
        mode="PRODUCTION",
    )
    eligible_by_id = {
        result.recommendable_id: result
        for result in eligibility_results
        if result.passed
    }

    buyer_facts_by_id, exhibitor_facts_by_id = await _load_buyer_candidate_facts(
        session, list(eligible_by_id), fused
    )
    buyer_profile_facts = BuyerProfileFacts(
        required_category_concept_ids=request.required_category_concept_ids,
        target_price_max=request.target_price_max,
        max_order_quantity=request.max_order_quantity,
        required_concept_ids_by_component=group_concept_ids_by_component(
            (attribute.attribute_code, attribute.concept_id)
            for attribute in profile_resolution.active_attributes
        ),
    )
    exhibitor_profile_facts = ExhibitorProfileFacts(
        requested_monthly_units=request.requested_monthly_units
    )

    scored: list[tuple[uuid.UUID, ReciprocalScoreResult, EligibilityResult]] = []
    for recommendable_id, eligibility_result in eligible_by_id.items():
        buyer_facts = buyer_facts_by_id.get(
            recommendable_id,
            BuyerCandidateFacts(
                recommendable_id=recommendable_id,
                category_concept_ids=frozenset(),
                wholesale_price_amount=None,
                min_order_quantity=None,
            ),
        )
        exhibitor_facts = exhibitor_facts_by_id.get(
            recommendable_id,
            ExhibitorCandidateFacts(
                recommendable_id=recommendable_id, monthly_capacity=None
            ),
        )

        buyer_to_exhibitor_components = build_buyer_components(
            buyer_facts, buyer_profile_facts
        )
        exhibitor_to_buyer_components = build_exhibitor_components(
            exhibitor_facts, exhibitor_profile_facts
        )

        eligibility = EligibilityDecision(
            passed=True, evaluation_id=eligibility_result.evaluation_id
        )
        buyer_to_exhibitor_result = calculate_directional_score(
            BUYER_SCORE_V1, buyer_to_exhibitor_components, eligibility=eligibility
        )
        exhibitor_to_buyer_result = calculate_directional_score(
            EXHIBITOR_SCORE_V1, exhibitor_to_buyer_components, eligibility=eligibility
        )

        # capacity 정보가 있고 요구량을 충족하면 수용여력 1.0, 정보가 없으면 중립값 0.5로
        # 둔다 - 09단계 15.2절 "잔여 생산능력" 개념의 임시 대리지표다. 실제 exhibitor_profile.
        # trade_readiness_score가 연결되면 이 값으로 교체해야 한다.
        acceptance_capacity_score = (
            exhibitor_to_buyer_components["order_volume"]
            if exhibitor_to_buyer_components.get("order_volume") is not None
            else Decimal("0.5")
        )

        reciprocal_result = calculate_reciprocal_score(
            buyer_to_exhibitor_score=buyer_to_exhibitor_result.final_score,
            exhibitor_to_buyer_score=exhibitor_to_buyer_result.final_score,
            buyer_confidence=component_confidence(buyer_to_exhibitor_components),
            exhibitor_confidence=component_confidence(exhibitor_to_buyer_components),
            acceptance_capacity_score=acceptance_capacity_score,
            eligibility=eligibility,
        )
        scored.append((recommendable_id, reciprocal_result, eligibility_result))

    # DO_NOT_PUSH는 최종 결과에서 제외한다 (모듈 docstring "recommended_action 두 어휘
    # 체계" 참고).
    scored = [
        item
        for item in scored
        if item[1].recommended_action not in _EXCLUDED_RECIPROCAL_ACTIONS
    ]
    scored.sort(key=lambda item: item[1].final_reciprocal_score, reverse=True)
    top = scored[: request.limit]

    for rank, (recommendable_id, reciprocal_result, _eligibility) in enumerate(
        top, start=1
    ):
        match_result = MatchResult(
            recommendation_session_id=recommendation_session.recommendation_session_id,
            recommendable_id=recommendable_id,
            raw_score=reciprocal_result.uncapped_final_score,
            normalized_score=reciprocal_result.final_reciprocal_score,
            rank=rank,
            trade_score=reciprocal_result.reciprocal_base_score,
            trust_score=reciprocal_result.confidence_score,
            recommended_action=reciprocal_result.recommended_action,
        )
        session.add(match_result)
        await session.flush()
        session.add(
            MatchReason(
                match_result_id=match_result.match_result_id,
                reason_code="RECIPROCAL_MATCH",
                reason_text=_template_reciprocal_reason_text(reciprocal_result),
                contribution_score=reciprocal_result.reciprocal_base_score,
                display_order=0,
                generated_by="TEMPLATE",
                validation_status="VALID",
            )
        )

    for row in to_filter_result_rows(
        eligibility_results,
        recommendation_session_id=recommendation_session.recommendation_session_id,
        policy_version_id=request.policy_version_id,
    ):
        session.add(FilterResult(**row))

    recommendation_session.filtered_count = len(recommendable_ids) - len(eligible_by_id)
    recommendation_session.result_count = len(top)

    return recommendation_session


def _template_reciprocal_reason_text(result: ReciprocalScoreResult) -> str:
    """ReciprocalScoreResult에는 contributions가 없어(reason_generator.py 모듈 docstring
    참고) generate_directional_reasons를 재사용할 수 없다. match_status(내부 점수가
    아닌 카테고리 값)만 문구로 바꾸므로 05단계 5.11절 "금지 근거"는 위반하지 않지만,
    구성요소별 다중 이유(최대 2~3개)는 아직 만들지 못한다 - GENERAL_VISITOR 경로와
    달리 이 경로는 여전히 이유 1개짜리 임시 템플릿이다."""

    labels = {
        "MUTUAL_MATCH": "양측 모두 높은 적합도를 보입니다.",
        "CONDITIONAL_MATCH": "조건부로 적합도가 있어 확인이 필요합니다.",
        "IMBALANCED_MATCH": "한쪽의 관심이 다른 쪽보다 두드러집니다.",
        "NOT_RECIPROCAL": "상호 적합도가 낮습니다.",
    }
    return labels.get(result.match_status, "상호 적합도를 확인해 주세요.")


async def _load_buyer_candidate_facts(
    session: AsyncSession,
    recommendable_ids: Sequence[uuid.UUID],
    fused_candidates: Sequence,
) -> tuple[
    dict[uuid.UUID, BuyerCandidateFacts], dict[uuid.UUID, ExhibitorCandidateFacts]
]:
    """업체 공통 거래조건(trade_condition, event_product_id IS NULL) 기준으로 바이어/업체
    양방향 사실관계를 함께 조회한다. category_concept_ids는 fused_candidates(RRF 병합
    결과)의 matched_concept_ids를 그대로 쓴다 - structured_search_exhibitors가 이미 업체별
    출품 제품의 category_concept_id 집합을 채워서 넘기기 때문이다(_load_consumer_candidate_
    facts와 같은 패턴, candidate_generator.py의 _exhibitor_category_concept_ids 참고)."""

    if not recommendable_ids:
        return {}, {}

    concept_ids_by_recommendable = {
        candidate.recommendable_id: candidate.matched_concept_ids
        for candidate in fused_candidates
    }

    stmt = (
        select(
            Recommendable.recommendable_id,
            TradeCondition.wholesale_price_max_amount,
            TradeCondition.min_order_quantity,
            TradeCondition.monthly_capacity,
        )
        .join(
            ExhibitorParticipation,
            ExhibitorParticipation.participation_id == Recommendable.participation_id,
        )
        .join(
            TradeCondition,
            TradeCondition.participation_id == ExhibitorParticipation.participation_id,
        )
        .where(
            Recommendable.recommendable_id.in_(recommendable_ids),
            TradeCondition.event_product_id.is_(None),
        )
    )
    rows = (await session.execute(stmt)).all()

    term_components_by_id = await _exhibitor_concept_ids_by_component(
        session, recommendable_ids
    )

    buyer_facts: dict[uuid.UUID, BuyerCandidateFacts] = {}
    exhibitor_facts: dict[uuid.UUID, ExhibitorCandidateFacts] = {}
    for (
        recommendable_id,
        wholesale_price_max_amount,
        min_order_quantity,
        monthly_capacity,
    ) in rows:
        buyer_facts[recommendable_id] = BuyerCandidateFacts(
            recommendable_id=recommendable_id,
            category_concept_ids=concept_ids_by_recommendable.get(
                recommendable_id, frozenset()
            ),
            wholesale_price_amount=wholesale_price_max_amount,
            min_order_quantity=min_order_quantity,
            concept_ids_by_component=term_components_by_id.get(recommendable_id, {}),
        )
        exhibitor_facts[recommendable_id] = ExhibitorCandidateFacts(
            recommendable_id=recommendable_id, monthly_capacity=monthly_capacity
        )
    return buyer_facts, exhibitor_facts


#: exhibition.trade_condition_term.term_type -> feature_builder 구성요소 이름. term_type
#: 자체가 이미 concept_type이라(TRADE_CONDITION_TERM_TYPES = REGION/CHANNEL/COUNTRY)
#: attribute_code 접두어 해석이 필요 없다 - 소문자로 바꾸면 바로 구성요소 이름과 같다.
#: COUNTRY는 BUYER_SCORE_V1에 대응 구성요소가 없어 제외한다.
_BUYER_TERM_TYPE_TO_COMPONENT: Mapping[str, str] = {
    "REGION": "region",
    "CHANNEL": "channel",
}


async def _exhibitor_concept_ids_by_component(
    session: AsyncSession, recommendable_ids: Sequence[uuid.UUID]
) -> dict[uuid.UUID, dict[str, frozenset[uuid.UUID]]]:
    """recommendable_id -> feature_builder 구성요소별 concept_id 집합(channel/region).

    업체 공통 거래조건(trade_condition, event_product_id IS NULL)에 걸린 term만 쓴다 -
    _load_buyer_candidate_facts의 메인 쿼리와 같은 범위(제품별 조건은 제외)다.
    """

    if not recommendable_ids:
        return {}

    stmt = (
        select(
            Recommendable.recommendable_id,
            TradeConditionTerm.term_type,
            TradeConditionTerm.concept_id,
        )
        .join(
            ExhibitorParticipation,
            ExhibitorParticipation.participation_id == Recommendable.participation_id,
        )
        .join(
            TradeCondition,
            TradeCondition.participation_id == ExhibitorParticipation.participation_id,
        )
        .join(
            TradeConditionTerm,
            TradeConditionTerm.trade_condition_id == TradeCondition.trade_condition_id,
        )
        .where(
            Recommendable.recommendable_id.in_(recommendable_ids),
            TradeCondition.event_product_id.is_(None),
        )
    )
    rows = (await session.execute(stmt)).all()

    grouped: dict[uuid.UUID, dict[str, set[uuid.UUID]]] = {}
    for recommendable_id, term_type, concept_id in rows:
        component = _BUYER_TERM_TYPE_TO_COMPONENT.get(term_type)
        if component is None:
            continue
        grouped.setdefault(recommendable_id, {}).setdefault(component, set()).add(
            concept_id
        )
    return {
        recommendable_id: {
            component: frozenset(ids) for component, ids in components.items()
        }
        for recommendable_id, components in grouped.items()
    }
