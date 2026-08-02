"""매칭엔진 12단계 파이프라인이 공유하는 데이터 구조.

필드명은 다음 문서를 근거로 한다.
    - docs/05-ai-matching-engine-architecture.md 5절 각 구성요소 입출력 예시, 6절 최종 점수
      개념 구조(Eligibility Gate + 기본 적합도 + 양면 적합도 + 행동 적합도 + 상황 보정 +
      데이터 신뢰도 + 다양성 보정 - 운영 위험 감점).
    - docs/07-user-profile-model.md 26.5·27절 (Profile Resolver 출력 형태).
    - docs/08-exhibitor-product-profile-model.md 29절 (공급 프로파일 입력 형태).
    - docs/frontend-backend-ai-interface-spec.md 9절 (공개 API 응답 형태).
    - backend/app/models/matching.py의 MatchResult 컬럼(raw_score, normalized_score,
      preference_score, goal_score, trade_score, context_score, behavior_score,
      diversity_adjustment, trust_score) - Base Scoring Engine 이후 각 단계가 채우는
      score_components 딕셔너리의 키를 이 컬럼명과 그대로 맞춘다 (Result Store가 그대로
      영속화할 수 있도록).

파이프라인 단계마다 새 dataclass를 만드는 대신, ``MatchCandidate`` 하나를 여러 단계가
점진적으로 채워나가는 방식을 택했다(문서 4절이 요구하는 단계 분리는 함수/클래스 경계로
지키고, 데이터 구조 자체는 단계마다 재정의하지 않는다). 각 단계가 정확히 어떤 필드를
채우는지는 해당 단계 모듈의 docstring에 명시한다.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

# docs/frontend-backend-ai-interface-spec.md 9.1절.
RECOMMENDATION_TYPES: tuple[str, ...] = (
    "BOOTH",
    "PRODUCT",
    "EXHIBITOR",
    "PROGRAM",
    "MIXED",
)
# docs/db-erd-table-spec.md profile.user_profile.user_type CHECK.
USER_TYPES: tuple[str, ...] = ("GENERAL_VISITOR", "BUYER")

#: matching.match_result.recommended_action - db-erd: "VISIT_NOW 등"(개방형).
#: docs/05-ai-matching-engine-architecture.md 7.2절 후보 값.
RECOMMENDED_ACTIONS: tuple[str, ...] = (
    "VISIT_NOW",
    "SAVE_FOR_LATER",
    "REQUEST_MEETING",
    "ADD_TO_ROUTE",
    "COMPARE_PRODUCTS",
    "JOIN_PROGRAM",
    "REFINE_PROFILE",
)

#: 05번 문서 9절 추천 세션 상태.
MATCH_LEVELS: tuple[str, ...] = ("VERY_HIGH", "HIGH", "MEDIUM", "LOW")


#: 05번 문서에 정확한 구간이 없어 합리적 기본값을 둔다. TODO(11/12단계 정책 확정 후 교체).
#: app/api/v1/routers/recommendations.py의 GET .../items도 저장된 normalized_score에서
#: match_level을 다시 계산할 때 이 함수를 그대로 재사용한다(중복 정의 방지).
def score_to_match_level(score: float) -> str:
    if score >= 0.85:
        return "VERY_HIGH"
    if score >= 0.7:
        return "HIGH"
    if score >= 0.5:
        return "MEDIUM"
    return "LOW"


SCORE_COMPONENT_KEYS: tuple[str, ...] = (
    "preference_score",
    "goal_score",
    "trade_score",
    "context_score",
    "behavior_score",
    "trust_score",
)


@dataclass(frozen=True)
class SubjectContext:
    """요청 주체 식별자. 인터페이스 명세 9.1절: "서버는 현재 인증·익명 세션에서 profile_id,
    visit_session_id, event_id를 파생한다. 클라이언트가 다른 프로파일 ID를 지정할 수 없다."

    TODO(인증 도메인 통합): 지금은 실제 인증·익명세션 미들웨어가 이 저장소에 아직 없어
    app/api/v1/routers/recommendations.py가 헤더 기반 임시 해석기로 이 값을 채운다
    (그 파일 docstring 참고). 인증 에이전트가 실제 세션 해석기를 구현하면 그 결과를
    그대로 SubjectContext로 옮기기만 하면 되도록 필드를 최소화했다.
    """

    tenant_id: uuid.UUID
    event_id: uuid.UUID
    profile_id: uuid.UUID
    visit_session_id: uuid.UUID | None
    user_id: uuid.UUID | None
    guest_session_id: uuid.UUID | None
    request_id: str
    idempotency_key: str | None
    server_time: datetime


@dataclass
class ValidatedRequest:
    """5.1 Request Validator 출력 (05번 문서 5.1절 "출력" + 파이프라인 후속 단계가 필요로 하는
    원본 요청 조각을 함께 들고 다닌다).
    """

    subject: SubjectContext
    request_valid: bool
    user_type: str
    recommendation_type: str
    limit: int
    context_input: dict[str, Any]
    missing_fields: list[str]
    policy_route: str
    exploration_mode: bool = False


@dataclass
class TaxonomyItem:
    """07번 문서 27절 requirements.categories/channels/regions 항목 하나."""

    code: str
    level: str  # REQUIRED | PREFERRED | ACCEPTABLE | EXCLUDED
    confidence: float


@dataclass
class GoalItem:
    """07번 문서 27절 goals 항목 하나."""

    code: str
    priority: int | None
    requirement_level: str
    confidence: float
    source: str


@dataclass
class ResolvedProfile:
    """5.2 Profile Resolver 출력. 07번 문서 27절 JSON 스펙을 그대로 따르되, 05번 문서 5.6절
    Feature Builder가 요구하는 취향(taste)·향(aroma) 축과, 6단계 온톨로지 concept_type 중
    분류되지 않은 나머지 축(extra)을 27절 스키마와 같은 모양(list[TaxonomyItem])으로 확장했다.
    """

    profile_id: uuid.UUID
    profile_version: int
    profile_version_id: uuid.UUID | None
    user_type: str
    completeness: float
    goals: list[GoalItem]
    categories: list[TaxonomyItem]
    channels: list[TaxonomyItem]
    regions: list[TaxonomyItem]
    taste: list[TaxonomyItem]
    aroma: list[TaxonomyItem]
    extra: dict[str, list[TaxonomyItem]]
    numeric_conditions: dict[str, Any]
    raw_context: dict[str, Any]

    def required_codes(self, *buckets: list[TaxonomyItem]) -> set[str]:
        codes: set[str] = set()
        for bucket in buckets:
            codes.update(item.code for item in bucket if item.level == "REQUIRED")
        return codes

    def all_codes(self, *buckets: list[TaxonomyItem]) -> set[str]:
        codes: set[str] = set()
        for bucket in buckets:
            codes.update(item.code for item in bucket)
        return codes


@dataclass
class ResolvedContext:
    """5.3 Context Resolver 출력 (05번 문서 5.3절 "출력")."""

    current_zone: str | None
    current_zone_id: uuid.UUID | None
    remaining_minutes: int | None
    visited_booth_ids: set[uuid.UUID]
    upcoming_meetings: list[dict[str, Any]]
    upcoming_meeting_booth_ids: set[uuid.UUID]
    operational_snapshot_version: int
    exclude_visited: bool
    include_meetings: bool
    avoid_congestion: bool
    server_time: datetime
    recently_viewed_recommendable_ids: set[uuid.UUID] = field(default_factory=set)


@dataclass
class MatchReasonDraft:
    """11 Explanation Generator가 생성하는 근거 한 건 (matching.match_reason 대응)."""

    code: str
    text: str
    evidence_refs: list[str]
    contribution_score: float | None
    generated_by: str  # TEMPLATE | LLM
    display_order: int = 0
    ai_run_id: uuid.UUID | None = None
    explanation_policy_version: str | None = None
    input_fingerprint: str | None = None


@dataclass
class MatchCandidate:
    """4~11단계가 점진적으로 채우는 후보 하나.

    필드 채움 순서(각 단계 docstring 참고):
        4  candidate_generator   -> object_type/object_id/recommendable_id/exhibitor_id/
                                     participation_id/public_object_id/source_channels/payload
        5  hard_filter           -> (탈락 후보는 별도 리스트로 분리, 통과 후보는 변경 없음)
        6  feature_builder       -> features
        7  base_scoring          -> score_components, raw_score, normalized_score
        8  reciprocal_matching   -> buyer_to_exhibitor/exhibitor_to_buyer/reciprocal_score/
                                     reciprocal_capped (+ score_components["trade_score"] 갱신)
        14 context_reranker      -> score_components["context_score"], context_adjustment,
                                     distance_meters/estimated_walk_minutes/estimated_wait_minutes,
                                     availability, status_observed_at, final_score
        16 cold_start_policy     -> cold-start state, confidence cap and eligible
                                     exploration annotations (relevance is unchanged)
        15 diversity_policy      -> slate_score, 노출 보정·감점, slot_type, rank,
                                     recommended_action (관련성 final_score는 유지)
        18 explanation_generator -> reasons
    """

    object_type: str
    object_id: uuid.UUID
    recommendable_id: uuid.UUID | None
    exhibitor_id: uuid.UUID | None
    participation_id: uuid.UUID | None
    public_object_id: str
    source_channels: set[str] = field(default_factory=set)
    payload: dict[str, Any] = field(default_factory=dict)

    features: dict[str, float | None] = field(default_factory=dict)
    score_components: dict[str, float | None] = field(default_factory=dict)
    raw_score: float = 0.0
    normalized_score: float = 0.0

    # Stage 10 -> 11 contract.  A candidate may not enter either directional
    # scorer without the immutable evaluation identifier that proved it passed
    # the hard filters.
    filter_evaluation_id: str | None = None

    # Stage 11/12 directional calculation provenance.  The legacy aggregate
    # ``score_components`` fields remain for the current API/DB projection, while
    # these fields preserve the exact published-policy calculation.
    directional_policy_version: str | None = None
    directional_components: dict[str, float | None] = field(default_factory=dict)
    directional_effective_weights: dict[str, float] = field(default_factory=dict)
    directional_contributions: dict[str, float] = field(default_factory=dict)
    directional_missing_components: tuple[str, ...] = ()
    directional_confidence: float | None = None
    directional_grade: str | None = None
    directional_score_fingerprint: str | None = None

    buyer_to_exhibitor: float | None = None
    exhibitor_to_buyer: float | None = None
    reciprocal_score: float | None = None
    reciprocal_capped: bool = False
    exhibitor_directional_policy_version: str | None = None
    exhibitor_directional_components: dict[str, float | None] = field(
        default_factory=dict
    )
    exhibitor_directional_effective_weights: dict[str, float] = field(
        default_factory=dict
    )
    exhibitor_directional_contributions: dict[str, float] = field(default_factory=dict)
    exhibitor_directional_missing_components: tuple[str, ...] = ()
    exhibitor_directional_confidence: float | None = None
    exhibitor_directional_score_fingerprint: str | None = None
    reciprocal_policy_version: str | None = None
    reciprocal_base_score: float | None = None
    minimum_direction_score: float | None = None
    minimum_direction_cap: float | None = None
    imbalance_value: float | None = None
    imbalance_penalty: float | None = None
    confidence_adjustment: float | None = None
    acceptance_capacity_score: float | None = None
    acceptance_adjustment: float | None = None
    reciprocal_grade: str | None = None
    reciprocal_status: str | None = None
    reciprocal_recommended_action: str | None = None
    reciprocal_score_fingerprint: str | None = None
    reciprocal_applied_cap_codes: tuple[str, ...] = ()

    context_adjustment: float = 0.0
    context_policy_version: str | None = None
    context_components: dict[str, float | None] = field(default_factory=dict)
    context_effective_weights: dict[str, float] = field(default_factory=dict)
    context_contributions: dict[str, float] = field(default_factory=dict)
    context_missing_components: tuple[str, ...] = ()
    context_input_fingerprint: str | None = None
    context_score_fingerprint: str | None = None
    context_blended_score: float | None = None
    distance_meters: float | None = None
    estimated_walk_minutes: int | None = None
    estimated_wait_minutes: int | None = None
    availability: dict[str, bool] = field(default_factory=dict)
    status_observed_at: datetime | None = None

    cold_start_policy_version: str | None = None
    cold_start_state: str | None = None
    cold_start_quality_score: float | None = None
    recommendation_confidence: float | None = None
    cold_start_reason_codes: tuple[str, ...] = ()
    cold_start_input_fingerprint: str | None = None

    diversity_adjustment: float = 0.0
    slate_policy_version: str | None = None
    slate_base_rank: int | None = None
    slate_score: float | None = None
    mmr_score: float | None = None
    fairness_adjustment: float = 0.0
    exploration_adjustment: float = 0.0
    repeat_penalty: float = 0.0
    concentration_penalty: float = 0.0
    slot_type: str = "CORE"
    slate_reason_codes: tuple[str, ...] = ()
    related_object_ids: tuple[str, ...] = ()
    slate_input_fingerprint: str | None = None
    slate_score_fingerprint: str | None = None
    final_score: float = 0.0
    rank: int = 0
    recommended_action: str = "SAVE_FOR_LATER"

    reasons: list[MatchReasonDraft] = field(default_factory=list)
    # 12 result_store가 matching.match_result를 실제로 insert한 뒤 채운다. FK 대상 테이블
    # (recommendable 미등록 등) 문제로 저장이 생략되면 None으로 남는다.
    match_result_id: uuid.UUID | None = None

    def match_level(self) -> str:
        return score_to_match_level(self.final_score)


@dataclass
class FilterOutcome:
    """5.5 Hard Filter Engine 처리 결과 (05번 문서 5.5절 "처리 결과" JSON 그대로)."""

    filter_evaluation_id: uuid.UUID
    object_id: uuid.UUID
    object_type: str
    recommendable_id: uuid.UUID | None
    passed: bool
    filter_code: str | None
    details: dict[str, Any] = field(default_factory=dict)
    evidence_refs: list[str] = field(default_factory=list)
    candidate_fingerprint: str = ""


@dataclass
class HardFilterEvaluation:
    """One reproducible stage-10 run and its admitted candidate set."""

    filter_evaluation_id: uuid.UUID
    policy_version: str
    input_fingerprint: str
    started_at: datetime
    completed_at: datetime
    eligible_candidates: list[MatchCandidate]
    outcomes: list[FilterOutcome]

    @property
    def rejected_count(self) -> int:
        return sum(not outcome.passed for outcome in self.outcomes)


@dataclass
class PipelineTrace:
    """12 Result Store & Event Logger가 저장할 실행 통계 (05번 문서 5.12절 "저장 항목")."""

    candidate_count: int = 0
    filtered_count: int = 0
    result_count: int = 0
    source_channel_counts: dict[str, int] = field(default_factory=dict)
    fallback_strategy: str | None = None
    latency_ms: dict[str, int] = field(default_factory=dict)
    filter_outcomes: list[FilterOutcome] = field(default_factory=list)
    slate_policy_version: str | None = None
    slate_input_fingerprint: str | None = None
    slate_score_fingerprint: str | None = None
    slate_metrics: dict[str, Any] = field(default_factory=dict)
    cold_start_policy_version: str | None = None
    cold_start_input_fingerprint: str | None = None
    cold_start_metrics: dict[str, Any] = field(default_factory=dict)


@dataclass
class RecommendationOutcome:
    """오케스트레이터 최종 반환값. docs/frontend-backend-ai-interface-spec.md 9.1절 응답
    형태를 채우는 데 필요한 모든 정보를 담는다.
    """

    recommendation_session_id: uuid.UUID
    generated_at: datetime
    expires_at: datetime
    profile_version: int
    ranking_version: str
    explanation_version: str
    policy_version: str
    items: list[MatchCandidate]
    trace: PipelineTrace
    stale: bool = False
