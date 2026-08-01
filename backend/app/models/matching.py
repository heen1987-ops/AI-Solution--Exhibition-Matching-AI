"""추천 정책·후보 레지스트리·매칭 결과 도메인 SQLAlchemy 모델 (matching/exhibition 스키마).

근거 문서와 우선순위
---------------------
- docs/db-erd-table-spec.md 13.3절(exhibition.recommendable), 15절(matching.match_policy_version
  /match_weight/filter_rule/recommendation_session/match_result/match_reason/filter_result) -
  이 파일의 1차 근거. AGENTS.md의 충돌 해소 순서(인터페이스 명세 > DB 정의서 > 해당 단계
  상세설계)에 따라 스키마 구조는 db-erd-table-spec.md를 따른다.
- docs/09-candidate-search-design.md, docs/10-hard-filter-exclusion-rules.md - 9·10단계
  상세설계. 후보검색 채널·병합·재현율 원칙과 Hard Filter/Soft Constraint 결과유형·재현성
  원칙의 1차 근거이지만, 두 문서가 제안한 matching.candidate_search/candidate_result/
  filter_policy/filter_evaluation 테이블은 db-erd 13.3절 "다형 FK를 제거하는 추천대상
  레지스트리(recommendable)" 설계와 충돌한다. 이 파일은 db-erd를 따르고, 두 설계 산출물
  중 스키마가 아닌 부분(채널 결합 전략, 필터 코드 체계, 재현성 원칙)만 서비스 계층
  (app/services/matching/)에서 그대로 구현한다. 자세한 보정 내역은
  docs/09-10-matching-implementation.md를 참고한다.

이 파일에서 구현하는 테이블
---------------------------
1. exhibition.recommendable   - db-erd 13.3. 부스·행사별제품·업체·프로그램에 대한 다형 FK를
   제거하는 레지스트리. exhibitor.py 모듈 docstring이 "app/models/matching.py가 이미
   정의했다"고 가정한 바로 그 테이블이며 실제로는 이 커밋에서 처음 만든다.
2. matching.match_policy_version - db-erd 15.1.
3. matching.match_weight         - db-erd 15.1 본문.
4. matching.filter_rule          - db-erd 15.1 본문 (10단계 상세설계의 필터 코드 체계는
   filter_rule.rule_code/config_json에 담는다).
5. matching.recommendation_session - db-erd 15.2.
6. matching.match_result         - db-erd 15.3.
7. matching.match_reason         - db-erd 15.4.
8. matching.filter_result        - db-erd 15.5. "통과한 모든 규칙을 모든 후보에 기록하면
   폭증하므로 최종 후보의 trace 또는 표본만 저장한다"는 지침에 따라, 서비스 계층은 기본적으로
   FAIL/POLICY_BLOCK/USER_EXCLUDED 등 후보를 제외시킨 규칙만 기록하고 PASS는 저장하지 않는다
   (app/services/matching/hard_filter_engine.py 참고).

의도적으로 이 파일에서 만들지 않은 것
--------------------------------------
- ai.ai_run : ai 도메인 모델이 아직 없다. match_reason.ai_run_id는 FK 없이 nullable UUID로만
  둔다 (다른 도메인이 구현되면 FK로 승격해야 한다).
- 다른 스키마 테이블(core.tenant, ontology.*, profile.*, exhibition.event/booth/event_product/
  exhibitor_participation/program)은 "스키마명.테이블명.컬럼명" 문자열 ForeignKey로만
  참조하고 다른 모델 모듈을 import하지 않는다 (exhibitor.py 상단 메모와 동일한 이유).

부분 FK 설계 메모
-------------------
recommendable.booth_id/event_product_id/participation_id/program_id는 각 대상 테이블의
PK(booth_id 등)만을 단일 컬럼 FK로 참조한다. exhibitor_participation/event_product처럼
(tenant_id, event_id, X_id) 복합 경계 FK를 쓰는 다른 도메인 테이블과 달리, 이 테이블들
자체에는 아직 그런 복합 UNIQUE 제약이 없어(Booth/Program에는 boundary-id UNIQUE가 없다)
복합 FK를 걸 수 없다. 각 X_id 컬럼의 PK가 이미 전역 유일(UUIDv7)하므로 단일 컬럼 FK로도
데이터 무결성은 보장되며, recommendable 자체의 tenant_id/event_id는 exhibition.event로
향하는 복합 FK로 테넌트 경계를 별도로 강제한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SCHEMA_EXHIBITION, SCHEMA_MATCHING, Base
from app.models.common import new_uuid7

_new_uuid = new_uuid7

# --------------------------------------------------------------------------
# 공용 상수. exhibitor.py의 _in_list 패턴을 그대로 따른다.
# --------------------------------------------------------------------------


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


#: db-erd 13.3절.
RECOMMENDABLE_OBJECT_TYPES: tuple[str, ...] = (
    "BOOTH",
    "EVENT_PRODUCT",
    "EXHIBITOR",
    "PROGRAM",
)

#: db-erd 15.1절 "한 행사·사용자유형에 ACTIVE 정책은 하나만 허용한다"의 상태값.
POLICY_STATUSES: tuple[str, ...] = ("DRAFT", "ACTIVE", "RETIRED")

#: 09/10단계 상세설계 공통: 일반 관람객·바이어 정책 분리.
POLICY_USER_TYPES: tuple[str, ...] = ("GENERAL_VISITOR", "BUYER")

#: db-erd 15.1 본문 "filter_rule은 ... HARD/SOFT ..."; 10단계 2.1절은 Warning도 별도
#: 결과유형(현재 상태 유지 + 경고 표시)으로 다루므로 규칙 유형에도 포함한다.
RULE_TYPES: tuple[str, ...] = ("HARD", "SOFT", "WARNING")

#: 10단계 상세설계 30절 필터 규칙 정의 구조의 unknown_policy.
UNKNOWN_POLICIES: tuple[str, ...] = (
    "EXCLUDE",
    "MANUAL_REVIEW",
    "TREAT_AS_PASS",
    "TREAT_AS_FAIL",
)

#: 10단계 상세설계 30절 failure_action.
FAILURE_ACTIONS: tuple[str, ...] = ("EXCLUDE", "SCORE_PENALTY", "MANUAL_REVIEW")

#: db-erd 15.2절.
RECOMMENDATION_TYPES: tuple[str, ...] = (
    "BOOTH",
    "PRODUCT",
    "EXHIBITOR",
    "PROGRAM",
    "MIXED",
)

#: db-erd 15.2절.
SESSION_STATUSES: tuple[str, ...] = ("ACTIVE", "EXPIRED", "INVALIDATED")

#: db-erd 15.2절 "TEMPLATE, CATEGORY_BROWSE 등" - 9단계 24절 검색 실패·장애 대응과 연결된다.
#: TODO(운영 정책 확정 후 재검토): 실제 폐쇄형 목록.
FALLBACK_STRATEGIES: tuple[str, ...] = (
    "NONE",
    "TEMPLATE",
    "CATEGORY_BROWSE",
    "POPULARITY_FALLBACK",
)

#: db-erd 15.3절 "VISIT_NOW 등"; 5단계 상세설계 7.2절 추천 행동 7종을 그대로 채택한다.
RECOMMENDED_ACTIONS: tuple[str, ...] = (
    "VISIT_NOW",
    "SAVE_FOR_LATER",
    "REQUEST_MEETING",
    "ADD_TO_ROUTE",
    "COMPARE_PRODUCTS",
    "JOIN_PROGRAM",
    "REFINE_PROFILE",
)

#: db-erd 15.4절.
REASON_GENERATED_BY: tuple[str, ...] = ("TEMPLATE", "LLM")
REASON_VALIDATION_STATUSES: tuple[str, ...] = ("VALID", "REJECTED")

#: 10단계 상세설계 4절 필터 결과 유형 8종. filter_result.result에 사용한다.
FILTER_RESULT_TYPES: tuple[str, ...] = (
    "PASS",
    "FAIL",
    "UNKNOWN",
    "CONDITIONAL_PASS",
    "MANUAL_REVIEW",
    "TEMPORARY_BLOCK",
    "POLICY_BLOCK",
    "USER_EXCLUDED",
)


# ============================================================================
# 1. 추천대상 레지스트리 (db-erd 13.3, exhibition 스키마)
# ============================================================================


class Recommendable(Base):
    """exhibition.recommendable - db-erd 13.3.

    다형 FK(object_type + object_id)를 걷어내고 부스·행사별제품·업체·프로그램 각각에
    단일 컬럼 FK를 두는 레지스트리다. matching/interaction/ai 도메인은 전부 이
    recommendable_id를 통해서만 추천 대상을 참조한다.
    """

    __tablename__ = "recommendable"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_recommendable_event_boundary",
        ),
        CheckConstraint(
            f"object_type IN ({_in_list(RECOMMENDABLE_OBJECT_TYPES)})",
            name="object_type_allowed",
        ),
        # db-erd 13.3 본문: "CHECK num_nonnulls(booth_id, event_product_id,
        # participation_id, program_id) = 1".
        CheckConstraint(
            "num_nonnulls(booth_id, event_product_id, participation_id, program_id)"
            " = 1",
            name="exactly_one_target",
        ),
        # db-erd 13.3 본문 "각 FK에 부분 UNIQUE를 적용한다" - object_type당 대상 하나에
        # recommendable이 하나만 대응하도록 보장한다.
        Index(
            "uq_recommendable_booth",
            "booth_id",
            unique=True,
            postgresql_where=text("booth_id IS NOT NULL"),
        ),
        Index(
            "uq_recommendable_event_product",
            "event_product_id",
            unique=True,
            postgresql_where=text("event_product_id IS NOT NULL"),
        ),
        Index(
            "uq_recommendable_participation",
            "participation_id",
            unique=True,
            postgresql_where=text("participation_id IS NOT NULL"),
        ),
        Index(
            "uq_recommendable_program",
            "program_id",
            unique=True,
            postgresql_where=text("program_id IS NOT NULL"),
        ),
        Index("idx_recommendable_event_type", "event_id", "object_type", "active"),
        {"schema": SCHEMA_EXHIBITION},
    )

    recommendable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_type: Mapped[str] = mapped_column(String(20), nullable=False)

    booth_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.booth.booth_id"),
        nullable=True,
    )
    event_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.event_product.event_product_id"),
        nullable=True,
    )
    participation_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor_participation.participation_id"),
        nullable=True,
    )
    program_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.program.program_id"),
        nullable=True,
    )

    active: Mapped[bool] = mapped_column(nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    match_results: Mapped[list[MatchResult]] = relationship(
        back_populates="recommendable"
    )
    filter_results: Mapped[list[FilterResult]] = relationship(
        back_populates="recommendable"
    )


# ============================================================================
# 2. 추천 정책 (db-erd 15.1)
# ============================================================================


class MatchPolicyVersion(Base):
    """matching.match_policy_version - db-erd 15.1.

    한 (tenant, event, user_type)에는 ACTIVE 정책이 최대 하나만 존재해야 한다. 정책
    활성화는 기존 ACTIVE를 RETIRED로 바꾸는 트랜잭션 뒤에 수행한다(서비스 계층 책임,
    db-erd 15.1 본문).
    """

    __tablename__ = "match_policy_version"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_match_policy_version_event_boundary",
        ),
        CheckConstraint(
            f"user_type IN ({_in_list(POLICY_USER_TYPES)})",
            name="user_type_allowed",
        ),
        CheckConstraint(
            f"status IN ({_in_list(POLICY_STATUSES)})",
            name="status_allowed",
        ),
        CheckConstraint(
            "effective_from IS NULL OR effective_until IS NULL "
            "OR effective_from < effective_until",
            name="effective_period_order",
        ),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "user_type",
            "version",
            name="uq_match_policy_version_identity",
        ),
        # "한 행사·사용자유형에 ACTIVE 정책은 하나만 허용한다".
        Index(
            "uq_match_policy_version_single_active",
            "tenant_id",
            "event_id",
            "user_type",
            unique=True,
            postgresql_where=text("status = 'ACTIVE'"),
        ),
        {"schema": SCHEMA_MATCHING},
    )

    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_type: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    effective_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    effective_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    weights: Mapped[list[MatchWeight]] = relationship(
        back_populates="policy", cascade="all, delete-orphan"
    )
    filter_rules: Mapped[list[FilterRule]] = relationship(
        back_populates="policy", cascade="all, delete-orphan"
    )


class MatchWeight(Base):
    """matching.match_weight - db-erd 15.1 본문.

    Soft Score 구성요소별 가중치(component, weight, min/max, config)를 정책 버전에
    귀속시킨다. component 코드는 meet_ai.scoring의 ScoringPolicy.weights 키(예:
    "taste", "goal", "price")와 1:1로 대응해야 한다 (feature_builder.py가 이 매핑을
    강제한다).
    """

    __tablename__ = "match_weight"
    __table_args__ = (
        UniqueConstraint(
            "policy_version_id", "score_component", name="uq_match_weight_component"
        ),
        CheckConstraint("weight_value > 0 AND weight_value <= 1", name="weight_range"),
        CheckConstraint(
            "min_score IS NULL OR max_score IS NULL OR min_score <= max_score",
            name="score_range_order",
        ),
        {"schema": SCHEMA_MATCHING},
    )

    match_weight_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_policy_version.policy_version_id"),
        nullable=False,
    )
    score_component: Mapped[str] = mapped_column(String(50), nullable=False)
    weight_value: Mapped[float] = mapped_column(Numeric(8, 5), nullable=False)
    min_score: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    max_score: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    config_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    policy: Mapped[MatchPolicyVersion] = relationship(back_populates="weights")


class FilterRule(Base):
    """matching.filter_rule - db-erd 15.1 본문 + 10단계 상세설계 30절.

    rule_code/rule_type/rule_order/config_json/active는 db-erd가 직접 요구하는 필드다.
    unknown_policy/failure_action은 10단계 30절의 "필터 규칙 정의 구조" JSON을 정규 컬럼으로
    승격한 것으로, hard_filter_engine.py가 UNKNOWN 결과와 실패 시 동작을 결정하는 데 쓴다.
    """

    __tablename__ = "filter_rule"
    __table_args__ = (
        UniqueConstraint(
            "policy_version_id", "rule_code", name="uq_filter_rule_policy_code"
        ),
        CheckConstraint(
            f"rule_type IN ({_in_list(RULE_TYPES)})", name="rule_type_allowed"
        ),
        CheckConstraint(
            f"unknown_policy IN ({_in_list(UNKNOWN_POLICIES)})",
            name="unknown_policy_allowed",
        ),
        CheckConstraint(
            f"failure_action IN ({_in_list(FAILURE_ACTIONS)})",
            name="failure_action_allowed",
        ),
        {"schema": SCHEMA_MATCHING},
    )

    filter_rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_policy_version.policy_version_id"),
        nullable=False,
    )
    rule_code: Mapped[str] = mapped_column(String(100), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_order: Mapped[int] = mapped_column(Integer, nullable=False)
    unknown_policy: Mapped[str] = mapped_column(
        String(30), nullable=False, default="MANUAL_REVIEW"
    )
    failure_action: Mapped[str] = mapped_column(
        String(30), nullable=False, default="EXCLUDE"
    )
    config_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    active: Mapped[bool] = mapped_column(nullable=False, default=True)

    policy: Mapped[MatchPolicyVersion] = relationship(back_populates="filter_rules")


# ============================================================================
# 3. 추천 세션과 결과 (db-erd 15.2 ~ 15.5)
# ============================================================================


class RecommendationSession(Base):
    """matching.recommendation_session - db-erd 15.2.

    추천 1회 실행 단위. context_snapshot에는 9단계 상세설계 4절의 검색 요청 객체와
    5단계 상세설계 5.3절 Context Resolver 출력을 함께 담아, 당시 위치·시간·운영상태
    버전을 재현 가능하게 한다.
    """

    __tablename__ = "recommendation_session"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_recommendation_session_event_boundary",
        ),
        CheckConstraint(
            f"recommendation_type IN ({_in_list(RECOMMENDATION_TYPES)})",
            name="recommendation_type_allowed",
        ),
        CheckConstraint(
            f"status IN ({_in_list(SESSION_STATUSES)})", name="status_allowed"
        ),
        CheckConstraint(
            f"fallback_strategy IS NULL OR fallback_strategy IN "
            f"({_in_list(FALLBACK_STRATEGIES)})",
            name="fallback_strategy_allowed",
        ),
        CheckConstraint(
            "candidate_count >= 0 AND filtered_count >= 0 AND result_count >= 0",
            name="counts_nonneg",
        ),
        Index("idx_recommendation_session_profile", "profile_id", "generated_at"),
        {"schema": SCHEMA_MATCHING},
    )

    recommendation_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.user_profile.profile_id"),
        nullable=False,
    )
    profile_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.profile_version.profile_version_id"),
        nullable=False,
    )
    visit_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.visit_session.visit_session_id"),
        nullable=True,
    )
    recommendation_type: Mapped[str] = mapped_column(String(20), nullable=False)
    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_policy_version.policy_version_id"),
        nullable=False,
    )
    # 랭킹·설명 모델 버전은 ai 도메인 모델(ai.ai_model_version)이 아직 없어 FK 없이 값만
    # 저장한다. 설명 모델은 템플릿만 쓴 세션에서 NULL일 수 있다 (db-erd 15.2 본문).
    ranking_model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    explanation_model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    taxonomy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("ontology.taxonomy_version.taxonomy_version_id"),
        nullable=True,
    )
    context_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    # db-erd 15.2 "당시 동의" - profile.user_consent는 개별 동의 행 여러 개이므로 이 세션이
    # 참조한 동의 스냅샷을 요약한 별도 식별자만 남긴다 (privacy 도메인이 아직 없어 FK 없음).
    consent_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filtered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallback_strategy: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)

    results: Mapped[list[MatchResult]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    filter_results: Mapped[list[FilterResult]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class MatchResult(Base):
    """matching.match_result - db-erd 15.3.

    Hard Filter를 통과한 최종 후보만 이 테이블에 들어간다. 제외된 후보의 근거는
    FilterResult에 저장한다(db-erd 15.3 본문).
    """

    __tablename__ = "match_result"
    __table_args__ = (
        UniqueConstraint(
            "recommendation_session_id", "rank", name="uq_match_result_session_rank"
        ),
        UniqueConstraint(
            "recommendation_session_id",
            "recommendable_id",
            name="uq_match_result_session_recommendable",
        ),
        CheckConstraint(
            f"recommended_action IS NULL OR recommended_action IN "
            f"({_in_list(RECOMMENDED_ACTIONS)})",
            name="recommended_action_allowed",
        ),
        CheckConstraint("rank >= 1", name="rank_positive"),
        Index("idx_match_session_rank", "recommendation_session_id", "rank"),
        # db-erd 21절: "(recommendable_id, created_at DESC)".
        Index("idx_match_target", "recommendable_id", text("created_at DESC")),
        {"schema": SCHEMA_MATCHING},
    )

    match_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    recommendation_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA_MATCHING}.recommendation_session.recommendation_session_id"
        ),
        nullable=False,
    )
    recommendable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.recommendable.recommendable_id"),
        nullable=False,
    )
    raw_score: Mapped[float] = mapped_column(Numeric(8, 5), nullable=False)
    normalized_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    preference_score: Mapped[float | None] = mapped_column(
        Numeric(8, 5), nullable=True
    )
    goal_score: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    trade_score: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    context_score: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    behavior_score: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    diversity_adjustment: Mapped[float | None] = mapped_column(
        Numeric(8, 5), nullable=True
    )
    trust_score: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    recommended_action: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped[RecommendationSession] = relationship(back_populates="results")
    recommendable: Mapped[Recommendable] = relationship(
        back_populates="match_results"
    )
    reasons: Mapped[list[MatchReason]] = relationship(
        back_populates="match_result", cascade="all, delete-orphan"
    )


class MatchReason(Base):
    """matching.match_reason - db-erd 15.4.

    18단계(추천 이유 생성)의 산출물을 저장한다. evidence_refs는 5단계 상세설계 5.11절
    "금지 근거"를 지키기 위해 문장이 참조한 승인된 구조화 데이터의 위치만 담고, 문장 자체가
    사실의 원천이 되지 않게 한다.
    """

    __tablename__ = "match_reason"
    __table_args__ = (
        CheckConstraint(
            f"generated_by IN ({_in_list(REASON_GENERATED_BY)})",
            name="generated_by_allowed",
        ),
        CheckConstraint(
            f"validation_status IN ({_in_list(REASON_VALIDATION_STATUSES)})",
            name="validation_status_allowed",
        ),
        Index("idx_match_reason_result_order", "match_result_id", "display_order"),
        {"schema": SCHEMA_MATCHING},
    )

    match_reason_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    match_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_result.match_result_id"),
        nullable=False,
    )
    reason_code: Mapped[str] = mapped_column(String(50), nullable=False)
    reason_text: Mapped[str] = mapped_column(String(500), nullable=False)
    evidence_refs: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    contribution_score: Mapped[float | None] = mapped_column(
        Numeric(8, 5), nullable=True
    )
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    generated_by: Mapped[str] = mapped_column(String(20), nullable=False)
    # ai.ai_run 모델이 아직 없어 FK 없이 값만 저장한다 (모듈 docstring 참고).
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    validation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="VALID"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    match_result: Mapped[MatchResult] = relationship(back_populates="reasons")


class FilterResult(Base):
    """matching.filter_result - db-erd 15.5.

    "실패한 후보의 rule code, recommendable_id, 정책버전, 최소 details_json을 저장한다.
    통과한 모든 규칙을 모든 후보에 기록하면 폭증하므로 최종 후보의 trace 또는 표본만
    저장한다"(db-erd 15.5 본문). result 컬럼은 10단계 상세설계 4절의 8종 결과유형을 그대로
    쓴다. user_value_json/candidate_value_json은 10단계 5절 필터 공통 데이터 구조의
    user_condition/candidate_value를 컬럼으로 승격한 것으로, 재현성 원칙(10단계 2.4절)을
    만족하기 위해 필요하다.
    """

    __tablename__ = "filter_result"
    __table_args__ = (
        CheckConstraint(
            f"result IN ({_in_list(FILTER_RESULT_TYPES)})", name="result_allowed"
        ),
        Index(
            "idx_filter_result_session_object",
            "recommendation_session_id",
            "recommendable_id",
        ),
        {"schema": SCHEMA_MATCHING},
    )

    filter_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    recommendation_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA_MATCHING}.recommendation_session.recommendation_session_id"
        ),
        nullable=False,
    )
    recommendable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.recommendable.recommendable_id"),
        nullable=False,
    )
    rule_code: Mapped[str] = mapped_column(String(100), nullable=False)
    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_policy_version.policy_version_id"),
        nullable=False,
    )
    result: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_value_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    candidate_value_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    details_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped[RecommendationSession] = relationship(
        back_populates="filter_results"
    )
    recommendable: Mapped[Recommendable] = relationship(
        back_populates="filter_results"
    )
