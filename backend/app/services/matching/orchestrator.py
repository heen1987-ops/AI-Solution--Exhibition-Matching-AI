"""RecommendationOrchestrator - docs/05-ai-matching-engine-architecture.md 4절·12.2절.

12단계를 문서 4절이 그린 순서 그대로 호출하는 것 외의 책임을 갖지 않는다. 각 단계의 실제
판단 로직은 같은 패키지의 해당 모듈이 갖고, 이 클래스는 그것들을 오케스트레이션한다
(12.2절 "MVP 내부 모듈": ``RecommendationOrchestrator.generate(command)``).

내부 모듈 경계는 12.2절이 정의한 것처럼 "동일 배포 단위의 typed interface"로만 존재하고,
외부에는 공개하지 않는다 - 공개 API는
``app/api/v1/routers/recommendations.py``의 ``POST /api/v1/recommendations`` 하나뿐이다.
"""

from __future__ import annotations

import time
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.matching import (
    base_scoring,
    candidate_generator,
    context_reranker,
    context_resolver,
    diversity_policy,
    errors,
    explanation_generator,
    feature_builder,
    hard_filter,
    profile_resolver,
    reciprocal_matching,
    request_validator,
    result_store,
)
from app.services.matching.types import (
    PipelineTrace,
    RecommendationOutcome,
    SubjectContext,
)


def _elapsed_ms(start: float) -> int:
    return int((time.perf_counter() - start) * 1000)


class RecommendationOrchestrator:
    async def generate(
        self,
        db: AsyncSession,
        *,
        subject: SubjectContext,
        recommendation_type: str,
        context_input: dict[str, Any] | None,
        limit: int | None,
    ) -> RecommendationOutcome:
        pipeline_start = time.perf_counter()
        timings: dict[str, int] = {}

        # ① Request Validator
        step_start = time.perf_counter()
        validated = await request_validator.validate_request(
            db,
            subject=subject,
            recommendation_type=recommendation_type,
            context_input=context_input,
            limit=limit,
        )
        timings["request_validator"] = _elapsed_ms(step_start)

        # ② Profile Resolver
        step_start = time.perf_counter()
        profile = await profile_resolver.resolve_profile(db, subject=subject)
        timings["profile_resolver"] = _elapsed_ms(step_start)

        # ③ Context Resolver
        step_start = time.perf_counter()
        context = await context_resolver.resolve_context(
            db, subject=subject, validated=validated, profile=profile
        )
        timings["context_resolver"] = _elapsed_ms(step_start)

        # ④ Candidate Generator
        step_start = time.perf_counter()
        candidates, channel_counts = await candidate_generator.generate_candidates(
            db, validated=validated, profile=profile, context=context
        )
        timings["candidate_generator"] = _elapsed_ms(step_start)

        # ⑤ Hard Filter Engine
        step_start = time.perf_counter()
        excluded_recommendable_ids = await context_resolver.resolve_explicit_exclusions(
            db, subject=subject
        )
        filter_evaluation = await hard_filter.apply_hard_filters(
            db,
            candidates=candidates,
            subject=subject,
            profile=profile,
            context=context,
            excluded_recommendable_ids=excluded_recommendable_ids,
        )
        eligible = filter_evaluation.eligible_candidates
        timings["hard_filter"] = _elapsed_ms(step_start)

        if not eligible:
            # 05번 문서 10.5절은 필터를 무작정 해제하지 않고 사용자 동의 하에 선택조건을
            # 완화해 재추천하는 절차를 요구한다. 그 협상 흐름(완화안 제시 -> 사용자 동의 ->
            # 재추천)은 별도 UX/세션 상태가 필요해 이 MVP 스켈레톤 범위 밖이다.
            # TODO(10.5절 조건 완화 협상 플로우 구현): 지금은 422 NO_CANDIDATE만 반환한다.
            raise errors.no_candidate()

        # ⑥ Feature Builder
        step_start = time.perf_counter()
        await feature_builder.build_features(
            db, eligible, profile=profile, context=context
        )
        timings["feature_builder"] = _elapsed_ms(step_start)

        # ⑦ Base Scoring Engine
        step_start = time.perf_counter()
        await base_scoring.score_candidates(
            db,
            eligible,
            profile=profile,
            eligibility_evaluation_id=str(filter_evaluation.filter_evaluation_id),
        )
        timings["base_scoring"] = _elapsed_ms(step_start)

        # ⑧ Reciprocal Matching Engine (일반 관람객은 no-op)
        step_start = time.perf_counter()
        reciprocal_matching.apply_reciprocal_matching(eligible, profile=profile)
        timings["reciprocal_matching"] = _elapsed_ms(step_start)

        # ⑨ Context Re-ranker
        step_start = time.perf_counter()
        await context_reranker.rerank_by_context(
            db, eligible, profile=profile, context=context
        )
        timings["context_reranker"] = _elapsed_ms(step_start)

        # ⑩ Diversity & Policy Controller
        step_start = time.perf_counter()
        slate = await diversity_policy.apply_diversity_policy(
            db,
            eligible,
            limit=validated.limit,
            profile=profile,
            subject=validated.subject,
            user_preference=validated.context_input.get("slate_preference", "BALANCED"),
        )
        final_candidates = slate.items
        timings["diversity_policy"] = _elapsed_ms(step_start)

        # ⑪ Explanation Generator
        step_start = time.perf_counter()
        explanation_generator.generate_explanations(final_candidates, profile=profile)
        timings["explanation_generator"] = _elapsed_ms(step_start)

        trace = PipelineTrace(
            candidate_count=len(candidates),
            filtered_count=len(candidates) - len(eligible),
            result_count=len(final_candidates),
            source_channel_counts=channel_counts,
            fallback_strategy="CATEGORY_BROWSE" if validated.exploration_mode else None,
            filter_outcomes=filter_evaluation.outcomes,
            latency_ms=timings,
            slate_policy_version=slate.policy_version,
            slate_input_fingerprint=slate.input_fingerprint,
            slate_score_fingerprint=slate.score_fingerprint,
            slate_metrics=slate.metrics,
        )
        trace.latency_ms["total"] = _elapsed_ms(pipeline_start)

        # ⑫ Result Store & Event Logger
        step_start = time.perf_counter()
        outcome = await result_store.store_recommendation(
            db,
            validated=validated,
            profile=profile,
            context=context,
            candidates=final_candidates,
            trace=trace,
        )
        trace.latency_ms["result_store"] = _elapsed_ms(step_start)
        return outcome


recommendation_orchestrator = RecommendationOrchestrator()
