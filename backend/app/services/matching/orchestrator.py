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
- 14단계 상황 재정렬, 18단계 추천 이유 생성(지금은 reason_text를 템플릿 문자열로만
  채운다)은 아직 연결하지 않았다.
- MatchResult.raw_score/normalized_score는 두 경로에서 의미가 다르다: GENERAL_VISITOR는
  DirectionalScoreResult.uncapped_score(0~1)/final_score(0~100), BUYER는
  ReciprocalScoreResult.uncapped_final_score/final_reciprocal_score(둘 다 0~100 스케일이라
  raw_score에도 100 스케일 그대로 넣는다 - 두 경로의 raw_score가 같은 척도가 아니라는 뜻이며,
  경로 간 raw_score를 직접 비교해서는 안 된다).

recommended_action 어휘 불일치
--------------------------------
meet_ai.scoring.calculate_reciprocal_score가 반환하는 recommended_action(DO_NOT_PUSH/
REQUEST_INFORMATION/CONFIRM_TRADE_CONDITION/REQUEST_MEETING)은 matching.match_result의
recommended_action CHECK 제약이 허용하는 5단계 7.2절 어휘(VISIT_NOW/SAVE_FOR_LATER/
REQUEST_MEETING/ADD_TO_ROUTE/COMPARE_PRODUCTS/JOIN_PROGRAM/REFINE_PROFILE)의 부분집합이
아니다. 두 값 체계를 하나로 합치는 스키마 변경 없이, 이 파일은 손실이 있는 매핑
(_map_reciprocal_action)을 쓴다: DO_NOT_PUSH는 아예 결과에서 제외하고, 나머지는 가장
가까운 기존 값으로 옮긴다. 정본 해법은 match_result CHECK 제약을 두 어휘의 합집합으로
넓히는 것이며, docs/09-10-matching-implementation.md의 "다음 구현 순서"에 남겨뒀다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
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
    TradeCondition,
)
from app.models.matching import (
    FilterResult,
    MatchReason,
    MatchResult,
    Recommendable,
    RecommendationSession,
)
from app.services.matching.candidate_generator import (
    build_candidate_pool,
    reciprocal_rank_fusion,
    structured_search_exhibitors,
    structured_search_products,
)
from app.services.matching.context_resolver import resolve_context
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
)
from app.services.matching.hard_filter_engine import (
    EligibilityResult,
    FilterContext,
    HardFilterRule,
    evaluate_candidates,
    to_filter_result_rows,
)
from app.services.matching.profile_resolver import resolve_profile
from app.services.matching.request_validator import validate_request

#: meet_ai.scoring.calculate_reciprocal_score의 recommended_action ->
#: matching.match_result.recommended_action(5단계 7.2절 어휘) 매핑. None은 "이 후보는 최종
#: 결과에서 제외한다"는 뜻이다 (모듈 docstring "recommended_action 어휘 불일치" 참고).
_RECIPROCAL_ACTION_MAP: dict[str, str | None] = {
    "DO_NOT_PUSH": None,
    "REQUEST_INFORMATION": "SAVE_FOR_LATER",
    "CONFIRM_TRADE_CONDITION": "REQUEST_MEETING",
    "REQUEST_MEETING": "REQUEST_MEETING",
}


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
    )

    scored: list[tuple[uuid.UUID, DirectionalScoreResult, EligibilityResult]] = []
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
        scored.append((recommendable_id, score_result, eligibility_result))

    scored.sort(key=lambda item: item[1].final_score, reverse=True)
    top = scored[: request.limit]

    for rank, (recommendable_id, score_result, _eligibility) in enumerate(top, start=1):
        # goal_score/trust_score만 CONSUMER_SCORE_V1 구성요소와 이름이 정확히 대응한다.
        # 나머지 match_result 점수 분해 컬럼(preference/trade/context/behavior_score)은
        # scoring 코어의 구성요소 이름과 1:1로 맞지 않아 지금은 채우지 않는다 - 억지로
        # category 등을 끼워 넣으면 나중에 진짜 preference_score를 정의할 때 혼동만 남는다.
        match_result = MatchResult(
            recommendation_session_id=recommendation_session.recommendation_session_id,
            recommendable_id=recommendable_id,
            raw_score=score_result.uncapped_score,
            normalized_score=score_result.final_score,
            rank=rank,
            goal_score=components_score(score_result, "goal"),
            trust_score=components_score(score_result, "trust"),
            recommended_action="VISIT_NOW",
        )
        session.add(match_result)
        await session.flush()
        session.add(
            MatchReason(
                match_result_id=match_result.match_result_id,
                reason_code="STRUCTURED_MATCH",
                reason_text=_template_reason_text(score_result),
                contribution_score=score_result.uncapped_score,
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


def components_score(result: DirectionalScoreResult, component: str) -> float | None:
    value = result.component_values.get(component)
    return float(value) if value is not None else None


def _template_reason_text(result: DirectionalScoreResult) -> str:
    """18단계(추천 이유 생성)가 아직 연결되지 않아 임시 템플릿만 채운다. contributions에서
    가장 기여도가 큰 구성요소 이름을 그대로 노출한다 - 05단계 5.11절 "금지 근거"(내부 점수
    노출 금지)를 지키려면 이 템플릿은 운영에 쓰기 전에 반드시 18단계 산출물로 교체해야
    한다."""

    if not result.contributions:
        return "조건에 부합하는 후보입니다."
    top_component = max(result.contributions.items(), key=lambda item: item[1])[0]
    return f"'{top_component}' 조건이 높은 비중으로 일치합니다."


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

    facts: dict[uuid.UUID, ConsumerCandidateFacts] = {}
    for recommendable_id, event_price_amount, category_concept_id in rows:
        concept_ids = set(concept_ids_by_recommendable.get(recommendable_id, ()))
        if category_concept_id is not None:
            concept_ids.add(category_concept_id)
        facts[recommendable_id] = ConsumerCandidateFacts(
            recommendable_id=recommendable_id,
            category_concept_ids=frozenset(concept_ids),
            event_price_amount=event_price_amount,
        )
    return facts


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
        session, list(eligible_by_id)
    )
    buyer_profile_facts = BuyerProfileFacts(
        required_category_concept_ids=request.required_category_concept_ids,
        target_price_max=request.target_price_max,
        max_order_quantity=request.max_order_quantity,
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

    # DO_NOT_PUSH는 최종 결과에서 제외한다 (모듈 docstring "recommended_action 어휘
    # 불일치" 참고).
    scored = [
        item
        for item in scored
        if _RECIPROCAL_ACTION_MAP.get(item[1].recommended_action) is not None
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
            recommended_action=_RECIPROCAL_ACTION_MAP[
                reciprocal_result.recommended_action
            ],
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
    """18단계가 아직 연결되지 않아 match_status를 그대로 노출하는 임시 템플릿이다.
    _template_reason_text와 같은 이유로 운영 전 교체가 필요하다."""

    labels = {
        "MUTUAL_MATCH": "양측 모두 높은 적합도를 보입니다.",
        "CONDITIONAL_MATCH": "조건부로 적합도가 있어 확인이 필요합니다.",
        "IMBALANCED_MATCH": "한쪽의 관심이 다른 쪽보다 두드러집니다.",
        "NOT_RECIPROCAL": "상호 적합도가 낮습니다.",
    }
    return labels.get(result.match_status, "상호 적합도를 확인해 주세요.")


async def _load_buyer_candidate_facts(
    session: AsyncSession, recommendable_ids: Sequence[uuid.UUID]
) -> tuple[
    dict[uuid.UUID, BuyerCandidateFacts], dict[uuid.UUID, ExhibitorCandidateFacts]
]:
    """업체 공통 거래조건(trade_condition, event_product_id IS NULL) 기준으로 바이어/업체
    양방향 사실관계를 함께 조회한다. 제품군(category_concept_ids)은 아직 채우지 않는다 -
    structured_search_exhibitors가 업체 단위로만 검색하고 제품 조인을 하지 않기 때문이다
    (candidate_generator.py의 같은 함수 docstring 참고)."""

    if not recommendable_ids:
        return {}, {}

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
            category_concept_ids=frozenset(),
            wholesale_price_amount=wholesale_price_max_amount,
            min_order_quantity=min_order_quantity,
        )
        exhibitor_facts[recommendable_id] = ExhibitorCandidateFacts(
            recommendable_id=recommendable_id, monthly_capacity=monthly_capacity
        )
    return buyer_facts, exhibitor_facts
