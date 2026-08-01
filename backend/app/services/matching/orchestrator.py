"""Recommendation Orchestrator: 9~13단계를 하나의 추천 실행으로 연결한다.

근거 문서: docs/05-ai-matching-engine-architecture.md 4절 매칭엔진 전체 구성,
docs/11-13-scoring-implementation.md "다음 구현 순서". 이 모듈이 그 순서의 1~3번
(후보검색 -> Hard Filter -> Feature Builder -> 점수 계산)을 실제로 이어 붙인 결과다.

구현 범위와 남은 작업
----------------------
- GENERAL_VISITOR/PRODUCT 경로만 끝까지 구현했다: 구조화 검색(하나뿐인 채널) -> 후보 풀
  구성 -> Hard Filter 평가 -> Feature Builder -> meet_ai.scoring.calculate_directional_score
  -> RecommendationSession/MatchResult/MatchReason/FilterResult 영속화까지 실제로 동작한다.
- BUYER/EXHIBITOR 경로, 양면 적합도(calculate_reciprocal_score) 연결, 14단계 상황 재정렬,
  18단계 추천 이유 생성(지금은 reason_text를 템플릿 문자열로만 채운다)은 아직 연결하지
  않았다 - candidate_generator/feature_builder가 그 입력을 아직 완전히 제공하지 않기
  때문이다(각 모듈 docstring의 "구현 범위" 참고).
- MatchResult.raw_score/normalized_score는 DirectionalScoreResult.uncapped_score(0~1 소수)와
  final_score(0~100)를 각각 그대로 담는다.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from meet_ai.scoring import (
    CONSUMER_SCORE_V1,
    DirectionalScoreResult,
    EligibilityDecision,
    calculate_directional_score,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exhibitor import EventProduct, Product
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
    structured_search_products,
)
from app.services.matching.context_resolver import resolve_context
from app.services.matching.feature_builder import (
    ConsumerCandidateFacts,
    ConsumerProfileFacts,
    build_consumer_components,
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
