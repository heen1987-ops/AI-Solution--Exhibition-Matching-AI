"""행동·매칭 도메인 SQLAlchemy 모델.

근거 문서:
    - docs/frontend-backend-ai-interface-spec.md 9절(추천 API) - API 계약 1차 근거.
      match_result_id, rank, reasons[].code/text/evidence_refs 같은 필드명은 이 문서의
      응답 예시를 그대로 따른다.
    - docs/db-erd-table-spec.md 2절(원안 대비 필수 보정), 13.3절(exhibition.recommendable),
      15절(추천 정책·결과), 17.1절(interaction.interaction_event) - DB 정의 1차 근거.
      이 파일이 구현하는 테이블 대부분은 이 문서가 유일한 상세 근거다.

이 파일에서 구현하는 테이블:
    1. exhibition.recommendable       - db-erd 13.3 (다형 참조 제거용 레지스트리)
    2. interaction.interaction_event  - db-erd 17.1 (조회·저장·제외·QR·방문·평가 등 행동 이벤트)
    3. matching.recommendation_session - db-erd 15.2 (지시사항의 "MatchRun")
    4. matching.match_result          - db-erd 15.3
    5. matching.match_reason          - db-erd 15.4 (지시사항의 "추천 이유" 보정: reason_code +
       evidence_refs로 저장)
    6. matching.recommendation_delivery - 지시사항이 명시한 "RecommendationDelivery". 주의:
       db-erd-table-spec.md에는 이 테이블이 없다(25절 MVP 테이블 목록에도 없음). 이 테이블은
       docs/2026-backju-ai-matching-service-design.md 5.1절 엔터티 표(매칭 도메인 =
       "MatchRun, MatchResult, RecommendationDelivery")와 docs/ai-matching-architecture.md
       2.4절·docs/technical-design.md의 delivered_via/delivered_at 개념을 근거로, db-erd의
       테이블 설계 관례(스키마 규칙, 버전·근거 보존, recommendable FK 패턴)를 따라 이번
       작업에서 새로 설계했다. 채널 코드값(WIDGET/PUSH/SMS/KAKAO_ALIMTALK/EMAIL/CHATBOT 등)은
       6단계 온톨로지 문서가 없어 CHECK로 고정하지 않는다 (지시사항 원칙).
       TODO(db-erd 재정합): db-erd-table-spec.md가 이 테이블을 공식화하면 필드명을 그 문서에
       맞춰 재조정한다.

정책·AI 참조:
    matching.match_policy_version·match_weight·filter_rule은 app/models/policy.py가,
    ai.model_version·ai.ai_run은 app/models/ai.py가 소유한다. matching.filter_evaluation과
    filter_result는 app/models/filtering.py가 소유한다. 이 파일의 실행·결과 FK는 모두 이
    게시된 모델과 같은 Alembic 체인에서 생성된다.

크로스 스키마 참조에 대한 메모:
    이 파일의 여러 컬럼은 core.tenant, exhibition.event, exhibition.booth,
    exhibition.event_product, exhibition.exhibitor_participation, exhibition.program,
    ontology.taxonomy_version, profile.user_profile, profile.profile_version,
    profile.visit_session, matching.match_policy_version, ai.model_version, ai.ai_run 등
    다른 스키마 테이블을 참조한다. 모든 참조 대상은 0001~0007 마이그레이션에서 먼저
    생성되며, 0008은 테넌트·행사 복합 FK를 사용해 사이트 연동 입력이 다른 행사 데이터와
    교차 연결되지 않도록 한다.

    exhibition.recommendable은 db-erd 4절 스키마표 기준으로 물리 스키마가 exhibition이다
    (매칭 도메인 파일에 함께 두는 이유는 InteractionEvent·MatchResult·RecommendationDelivery가
    이 테이블 없이는 정의될 수 없기 때문). exhibition 도메인 에이전트가 별도 파일에서 같은
    테이블을 다시 정의하면 통합 시 중복 정의 충돌이 생기므로 조정이 필요하다.

    taxonomy_version_id는 db-erd 11.1절 제목이 그대로 "ontology.taxonomy_version"이므로(11절
    본문: "정본 계약은 6단계 매칭 분류체계·온톨로지 문서와 db/migrations/0001_ontology.sql이다")
    ontology.taxonomy_version.taxonomy_version_id를 참조하도록 구현했다. 이미 존재하는
    alembic/versions/20260801_0001_0002_ontology.py와 db/migrations/0001_ontology.sql이 실제로
    ontology 스키마에 taxonomy_version 테이블을 만들고 있고, app/models/core.py의
    Event.current_taxonomy_version_id도 동일하게 ontology.taxonomy_version을 참조하므로 세
    근거가 모두 일치한다. exhibition.taxonomy_version이라는 테이블은 db-erd·기존 마이그레이션
    어디에도 없다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_EXHIBITION, SCHEMA_INTERACTION, SCHEMA_MATCHING, Base
from app.models.common import new_uuid7

# db-erd-table-spec.md 6.1절: "애플리케이션 또는 검증된 DB 함수에서 생성한 UUID v7을 사용한다."
# app/models/core.py, identity.py, profile.py, consent.py와 동일하게 공유 uuid7 유틸리티를 쓴다.
_new_uuid = new_uuid7


class Recommendable(Base):
    """exhibition.recommendable - db-erd 13.3, 2절 "다형 참조" 보정.

    부스·행사제품·업체참가·프로그램 중 정확히 하나를 가리키는 추천 대상 레지스트리다.
    object_type + object_id 쌍을 여러 테이블에 흩뿌리는 대신, matching·interaction·ai
    스키마의 모든 추천 대상 FK(match_result, interaction_event, favorite, feedback, route,
    object_embedding 등)가 이 테이블의 PK 하나만 참조하도록 한다 (db-erd 13.3절 마지막 문단).
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
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "booth_id"],
            [
                f"{SCHEMA_EXHIBITION}.booth.tenant_id",
                f"{SCHEMA_EXHIBITION}.booth.event_id",
                f"{SCHEMA_EXHIBITION}.booth.booth_id",
            ],
            name="fk_recommendable_booth_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "event_product_id"],
            [
                f"{SCHEMA_EXHIBITION}.event_product.tenant_id",
                f"{SCHEMA_EXHIBITION}.event_product.event_id",
                f"{SCHEMA_EXHIBITION}.event_product.event_product_id",
            ],
            name="fk_recommendable_event_product_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "participation_id"],
            [
                f"{SCHEMA_EXHIBITION}.exhibitor_participation.tenant_id",
                f"{SCHEMA_EXHIBITION}.exhibitor_participation.event_id",
                f"{SCHEMA_EXHIBITION}.exhibitor_participation.participation_id",
            ],
            name="fk_recommendable_participation_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "program_id"],
            [
                f"{SCHEMA_EXHIBITION}.program.tenant_id",
                f"{SCHEMA_EXHIBITION}.program.event_id",
                f"{SCHEMA_EXHIBITION}.program.program_id",
            ],
            name="fk_recommendable_program_boundary",
        ),
        CheckConstraint(
            "object_type IN ('BOOTH', 'EVENT_PRODUCT', 'EXHIBITOR', 'PROGRAM')",
            name="object_type_allowed",
        ),
        # db-erd 13.3: "CHECK num_nonnulls(booth_id, event_product_id, participation_id,
        # program_id) = 1".
        CheckConstraint(
            "num_nonnulls(booth_id, event_product_id, participation_id, program_id) = 1",
            name="exactly_one_target",
        ),
        CheckConstraint(
            "(object_type = 'BOOTH' AND booth_id IS NOT NULL) OR "
            "(object_type = 'EVENT_PRODUCT' AND event_product_id IS NOT NULL) OR "
            "(object_type = 'EXHIBITOR' AND participation_id IS NOT NULL) OR "
            "(object_type = 'PROGRAM' AND program_id IS NOT NULL)",
            name="object_type_target_consistency",
        ),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "recommendable_id",
            name="uq_recommendable_boundary_id",
        ),
        # db-erd 13.3: "각 FK에 부분 UNIQUE를 적용한다" - 대상 하나당 recommendable 행 하나.
        Index(
            "uq_recommendable_booth_id",
            "booth_id",
            unique=True,
            postgresql_where=text("booth_id IS NOT NULL"),
        ),
        Index(
            "uq_recommendable_event_product_id",
            "event_product_id",
            unique=True,
            postgresql_where=text("event_product_id IS NOT NULL"),
        ),
        Index(
            "uq_recommendable_participation_id",
            "participation_id",
            unique=True,
            postgresql_where=text("participation_id IS NOT NULL"),
        ),
        Index(
            "uq_recommendable_program_id",
            "program_id",
            unique=True,
            postgresql_where=text("program_id IS NOT NULL"),
        ),
        Index("ix_recommendable_tenant_event", "tenant_id", "event_id", "active"),
        {"schema": SCHEMA_EXHIBITION},
    )

    recommendable_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    object_type: Mapped[str] = mapped_column(String(20), nullable=False)

    booth_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    event_product_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    participation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    program_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )

    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MatchRun(Base):
    """matching.recommendation_session - db-erd 15.2. 지시사항의 "MatchRun".

    2절 "추천 버전" 보정: 랭킹(ranking_model_version_id)·설명(explanation_model_version_id)·
    정책(policy_version_id)·택소노미(taxonomy_version_id)·현장 스냅샷(context_snapshot) 버전을
    각각 별도 컬럼으로 고정해, 추천이 만들어진 시점의 전체 맥락을 재현할 수 있게 한다
    (frontend-backend-ai-interface-spec.md 9.2절 "recommendation_session은 다음을 보존한다"와
    동일한 목록).
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
        ForeignKeyConstraint(
            ["profile_id", "profile_version_id"],
            [
                "profile.profile_version.profile_id",
                "profile.profile_version.profile_version_id",
            ],
            name="fk_recommendation_session_profile_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "profile_id"],
            [
                "profile.user_profile.tenant_id",
                "profile.user_profile.event_id",
                "profile.user_profile.profile_id",
            ],
            name="fk_recommendation_session_profile_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "visit_session_id"],
            [
                "profile.visit_session.tenant_id",
                "profile.visit_session.event_id",
                "profile.visit_session.visit_session_id",
            ],
            name="fk_recommendation_session_visit_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "filter_evaluation_id"],
            [
                f"{SCHEMA_MATCHING}.filter_evaluation.tenant_id",
                f"{SCHEMA_MATCHING}.filter_evaluation.event_id",
                f"{SCHEMA_MATCHING}.filter_evaluation.filter_evaluation_id",
            ],
            name="fk_recommendation_session_filter_boundary",
        ),
        UniqueConstraint(
            "filter_evaluation_id",
            name="uq_recommendation_session_filter_evaluation",
        ),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "recommendation_session_id",
            name="uq_recommendation_session_boundary_id",
        ),
        CheckConstraint(
            "recommendation_type IN ('BOOTH', 'PRODUCT', 'EXHIBITOR', 'PROGRAM', 'MIXED')",
            name="recommendation_type_allowed",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'EXPIRED', 'INVALIDATED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "candidate_count IS NULL OR candidate_count >= 0",
            name="candidate_count_nonneg",
        ),
        CheckConstraint(
            "filtered_count IS NULL OR filtered_count >= 0",
            name="filtered_count_nonneg",
        ),
        CheckConstraint(
            "result_count IS NULL OR result_count >= 0", name="result_count_nonneg"
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="latency_ms_nonneg"
        ),
        CheckConstraint(
            "generated_at IS NULL OR expires_at IS NULL OR generated_at < expires_at",
            name="generated_before_expires",
        ),
        Index("ix_recommendation_session_profile", "profile_id", "generated_at"),
        Index("ix_recommendation_session_tenant_event", "tenant_id", "event_id"),
        Index("ix_recommendation_session_visit", "visit_session_id"),
        {"schema": SCHEMA_MATCHING},
    )

    recommendation_session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    # profile 도메인 소유 테이블(app/models/profile.py). 통합 전에는 지연 FK로만 존재한다.
    profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profile.user_profile.profile_id"),
        nullable=False,
    )
    profile_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    visit_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    filter_evaluation_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )

    recommendation_type: Mapped[str] = mapped_column(String(20), nullable=False)

    policy_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_policy_version.match_policy_version_id"),
        nullable=False,
    )
    ranking_model_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ai.model_version.model_version_id"),
        nullable=False,
    )
    # db-erd 15.2: "설명, 템플릿이면 NULL".
    explanation_model_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ai.model_version.model_version_id"),
        nullable=True,
    )
    # 모듈 docstring 참고: db-erd 11.1절 제목이 "ontology.taxonomy_version"이며, 기존
    # ontology 마이그레이션·app/models/core.py의 Event.current_taxonomy_version_id와도 일치한다.
    taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("ontology.taxonomy_version.taxonomy_version_id"),
        nullable=False,
    )

    context_snapshot: Mapped[dict[str, Any] | None] = mapped_column(
        JSONB, nullable=True
    )
    # db-erd 15.2: "당시 동의" - 특정 단일 동의 레코드가 아니라 요청 시점 동의 스냅샷을 가리키는
    # 불투명 포인터라 FK를 걸지 않는다 (문서에도 "UUID"로만 표기되고 FK 표기가 없음).
    consent_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )

    candidate_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    filtered_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    result_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # db-erd 15.2: "TEMPLATE, CATEGORY_BROWSE 등" - "등"이 있어 개방형이므로 CHECK를 걸지 않는다.
    fallback_strategy: Mapped[str | None] = mapped_column(String(30), nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")

    generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)


class MatchResult(Base):
    """matching.match_result - db-erd 15.3.

    hard_filter를 통과하지 못한 후보는 이 테이블에 넣지 않는다(제외 근거는 matching.filter_result,
    이번 작업 범위 밖). 과거 결과를 덮어쓰지 않는 append-only 성격의 테이블이라 updated_at을
    두지 않는다 (db-erd 6.2절 규칙).
    """

    __tablename__ = "match_result"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendation_session_id"],
            [
                f"{SCHEMA_MATCHING}.recommendation_session.tenant_id",
                f"{SCHEMA_MATCHING}.recommendation_session.event_id",
                f"{SCHEMA_MATCHING}.recommendation_session.recommendation_session_id",
            ],
            name="fk_match_result_session_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                f"{SCHEMA_EXHIBITION}.recommendable.tenant_id",
                f"{SCHEMA_EXHIBITION}.recommendable.event_id",
                f"{SCHEMA_EXHIBITION}.recommendable.recommendable_id",
            ],
            name="fk_match_result_recommendable_boundary",
        ),
        UniqueConstraint(
            "recommendation_session_id", "rank", name="uq_match_result_session_rank"
        ),
        UniqueConstraint(
            "recommendation_session_id",
            "recommendable_id",
            name="uq_match_result_session_recommendable",
        ),
        UniqueConstraint(
            "recommendation_session_id",
            "match_result_id",
            name="uq_match_result_session_result",
        ),
        CheckConstraint("rank > 0", name="rank_positive"),
        CheckConstraint(
            "normalized_score IS NULL OR (normalized_score >= 0 AND normalized_score <= 1)",
            name="normalized_score_range",
        ),
        CheckConstraint(
            "final_score IS NULL OR (final_score >= 0 AND final_score <= 1)",
            name="final_score_range",
        ),
        CheckConstraint(
            "preference_score IS NULL OR (preference_score >= 0 AND preference_score <= 1)",
            name="preference_score_range",
        ),
        CheckConstraint(
            "goal_score IS NULL OR (goal_score >= 0 AND goal_score <= 1)",
            name="goal_score_range",
        ),
        CheckConstraint(
            "trade_score IS NULL OR (trade_score >= 0 AND trade_score <= 1)",
            name="trade_score_range",
        ),
        CheckConstraint(
            "context_score IS NULL OR (context_score >= 0 AND context_score <= 1)",
            name="context_score_range",
        ),
        CheckConstraint(
            "behavior_score IS NULL OR (behavior_score >= 0 AND behavior_score <= 1)",
            name="behavior_score_range",
        ),
        CheckConstraint(
            "trust_score IS NULL OR (trust_score >= 0 AND trust_score <= 1)",
            name="trust_score_range",
        ),
        CheckConstraint(
            "directional_confidence IS NULL OR "
            "(directional_confidence >= 0 AND directional_confidence <= 1)",
            name="directional_confidence_range",
        ),
        CheckConstraint(
            "exhibitor_directional_confidence IS NULL OR "
            "(exhibitor_directional_confidence >= 0 AND "
            "exhibitor_directional_confidence <= 1)",
            name="exhibitor_confidence_range",
        ),
        CheckConstraint(
            "(reciprocal_policy_version_id IS NULL) = "
            "(reciprocal_details IS NULL) AND "
            "(reciprocal_policy_version_id IS NULL) = "
            "(reciprocal_score_fingerprint IS NULL)",
            name="reciprocal_provenance_consistency",
        ),
        CheckConstraint(
            "(context_policy_version_id IS NULL AND context_components IS NULL "
            "AND context_effective_weights IS NULL AND context_contributions IS NULL "
            "AND context_input_fingerprint IS NULL AND context_score_fingerprint IS NULL) "
            "OR (context_policy_version_id IS NOT NULL AND context_components IS NOT NULL "
            "AND context_effective_weights IS NOT NULL AND context_contributions IS NOT NULL "
            "AND context_input_fingerprint IS NOT NULL AND context_score_fingerprint IS NOT NULL)",
            name="context_provenance_consistency",
        ),
        # db-erd 21절 idx_match_session_rank는 위 uq_match_result_session_rank 유니크 제약이
        # 만드는 인덱스로 이미 충족된다 (동일 컬럼 조합).
        Index("ix_match_result_target_created", "recommendable_id", "created_at"),
        {"schema": SCHEMA_MATCHING},
    )

    match_result_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    recommendation_session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    recommendable_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    directional_policy_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_policy_version.match_policy_version_id"),
        nullable=False,
    )
    exhibitor_policy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_policy_version.match_policy_version_id"),
        nullable=True,
    )
    reciprocal_policy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_policy_version.match_policy_version_id"),
        nullable=True,
    )
    context_policy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_policy_version.match_policy_version_id"),
        nullable=True,
    )

    # db-erd: "raw_score, normalized_score | NUMERIC | 내부 점수" - raw_score는 정규화 전
    # 내부 스케일이라 범위를 고정하지 않는다.
    raw_score: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    normalized_score: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    final_score: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    rank: Mapped[int] = mapped_column(Integer, nullable=False)

    directional_components: Mapped[dict] = mapped_column(JSONB, nullable=False)
    directional_effective_weights: Mapped[dict] = mapped_column(JSONB, nullable=False)
    directional_contributions: Mapped[dict] = mapped_column(JSONB, nullable=False)
    directional_missing_components: Mapped[list] = mapped_column(JSONB, nullable=False)
    directional_confidence: Mapped[float | None] = mapped_column(
        Numeric(7, 6), nullable=True
    )
    directional_grade: Mapped[str | None] = mapped_column(String(20), nullable=True)
    directional_score_fingerprint: Mapped[str] = mapped_column(
        String(64), nullable=False
    )

    exhibitor_directional_components: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )
    exhibitor_directional_effective_weights: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )
    exhibitor_directional_contributions: Mapped[dict | None] = mapped_column(
        JSONB, nullable=True
    )
    exhibitor_directional_missing_components: Mapped[list | None] = mapped_column(
        JSONB, nullable=True
    )
    exhibitor_directional_confidence: Mapped[float | None] = mapped_column(
        Numeric(7, 6), nullable=True
    )
    exhibitor_directional_score_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    reciprocal_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    reciprocal_score_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )

    preference_score: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    goal_score: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    trade_score: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    context_score: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    context_components: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    context_effective_weights: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    context_contributions: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    context_input_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    context_score_fingerprint: Mapped[str | None] = mapped_column(
        String(64), nullable=True
    )
    context_details: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    behavior_score: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    # db-erd: "다양성" 보정값 - 가·감산 조정치라 0~1 범위를 강제하지 않는다.
    diversity_adjustment: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    trust_score: Mapped[float | None] = mapped_column(Numeric(), nullable=True)

    # db-erd: "VISIT_NOW 등" - 개방형이라 CHECK를 걸지 않는다.
    recommended_action: Mapped[str | None] = mapped_column(String(30), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class MatchReason(Base):
    """matching.match_reason - db-erd 15.4. 지시사항의 "추천 이유" 보정.

    추천 이유를 자유 텍스트 하나로만 저장하지 않고, reason_code(재사용 가능한 사유 코드)와
    evidence_refs(사유를 뒷받침하는 승인된 데이터 참조)를 함께 저장한다
    (frontend-backend-ai-interface-spec.md 9.1절 응답 예시의 reasons[].code/text/evidence_refs와
    동일 구조).
    """

    __tablename__ = "match_reason"
    __table_args__ = (
        CheckConstraint(
            "contribution_score IS NULL OR (contribution_score >= 0 AND contribution_score <= 1)",
            name="contribution_score_range",
        ),
        CheckConstraint(
            "generated_by IN ('TEMPLATE', 'LLM')",
            name="generated_by_allowed",
        ),
        CheckConstraint(
            "validation_status IN ('VALID', 'REJECTED')",
            name="validation_status_allowed",
        ),
        Index("ix_match_reason_result_order", "match_result_id", "display_order"),
        {"schema": SCHEMA_MATCHING},
    )

    match_reason_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    match_result_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_result.match_result_id"),
        nullable=False,
    )

    # db-erd: "TASTE_MATCH 등" - 개방형 코드 목록. 6단계 온톨로지가 오기 전까지 자유 문자열로
    # 유지하고, 실제 허용 코드 목록은 시드 데이터/애플리케이션 카탈로그로 관리한다.
    reason_code: Mapped[str] = mapped_column(String(50), nullable=False)
    reason_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # 승인된 데이터에 대한 참조 목록. 예: ["product:p_14:taste_attributes"] (interface-spec 9.1).
    # ai.extracted_attribute의 APPROVED 레코드 등 "승인 전 AI 속성은 근거로 쓰지 않는다"는
    # db-erd 26절 검수 기준을 애플리케이션 계층에서 강제해야 한다 (DB 제약만으로는 불가능).
    evidence_refs: Mapped[list[Any] | None] = mapped_column(JSONB, nullable=True)
    contribution_score: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    display_order: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    generated_by: Mapped[str] = mapped_column(String(20), nullable=False)
    # ai 도메인 소유 테이블. LLM이 생성한 사유일 때만 채워진다 (TEMPLATE이면 NULL 허용).
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("ai.ai_run.ai_run_id"), nullable=True
    )
    validation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="VALID"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SlateResult(Base):
    """Immutable stage-15 list-level result for one recommendation session."""

    __tablename__ = "slate_result"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendation_session_id"],
            [
                f"{SCHEMA_MATCHING}.recommendation_session.tenant_id",
                f"{SCHEMA_MATCHING}.recommendation_session.event_id",
                f"{SCHEMA_MATCHING}.recommendation_session.recommendation_session_id",
            ],
            name="fk_slate_result_session_boundary",
        ),
        UniqueConstraint("recommendation_session_id", name="uq_slate_result_session"),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "slate_result_id",
            name="uq_slate_result_boundary_id",
        ),
        CheckConstraint("slate_size >= 0", name="slate_size_nonneg"),
        CheckConstraint(
            "diversity_score IS NULL OR (diversity_score >= 0 AND diversity_score <= 1)",
            name="diversity_score_range",
        ),
        CheckConstraint(
            "coverage_score IS NULL OR (coverage_score >= 0 AND coverage_score <= 1)",
            name="coverage_score_range",
        ),
        CheckConstraint(
            "exposure_fairness_score IS NULL OR "
            "(exposure_fairness_score >= 0 AND exposure_fairness_score <= 1)",
            name="exposure_fairness_score_range",
        ),
        CheckConstraint(
            "relevance_loss IS NULL OR relevance_loss >= 0",
            name="relevance_loss_nonneg",
        ),
        Index("ix_slate_result_event_created", "tenant_id", "event_id", "created_at"),
        {"schema": SCHEMA_MATCHING},
    )

    slate_result_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    recommendation_session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    slate_policy_version_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_policy_version.match_policy_version_id"),
        nullable=False,
    )
    slate_size: Mapped[int] = mapped_column(Integer, nullable=False)
    diversity_score: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    coverage_score: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    exposure_fairness_score: Mapped[float | None] = mapped_column(
        Numeric(), nullable=True
    )
    relevance_loss: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    score_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    metrics_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class SlateItem(Base):
    """Immutable stage-15 item calculation linked to the canonical match result."""

    __tablename__ = "slate_item"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "slate_result_id"],
            [
                f"{SCHEMA_MATCHING}.slate_result.tenant_id",
                f"{SCHEMA_MATCHING}.slate_result.event_id",
                f"{SCHEMA_MATCHING}.slate_result.slate_result_id",
            ],
            name="fk_slate_item_result_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                f"{SCHEMA_EXHIBITION}.recommendable.tenant_id",
                f"{SCHEMA_EXHIBITION}.recommendable.event_id",
                f"{SCHEMA_EXHIBITION}.recommendable.recommendable_id",
            ],
            name="fk_slate_item_target_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            [
                f"{SCHEMA_EXHIBITION}.exhibitor.tenant_id",
                f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id",
            ],
            name="fk_slate_item_exhibitor_boundary",
        ),
        UniqueConstraint("slate_result_id", "final_rank", name="uq_slate_item_rank"),
        UniqueConstraint("match_result_id", name="uq_slate_item_match_result"),
        UniqueConstraint(
            "tenant_id", "event_id", "slate_item_id", name="uq_slate_item_boundary_id"
        ),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "slate_result_id",
            "slate_item_id",
            name="uq_slate_item_result_boundary_id",
        ),
        CheckConstraint("base_rank > 0 AND final_rank > 0", name="ranks_positive"),
        CheckConstraint(
            "base_score >= 0 AND base_score <= 1 AND slate_score >= 0 AND slate_score <= 1",
            name="scores_range",
        ),
        CheckConstraint(
            "diversity_adjustment >= -0.05 AND diversity_adjustment <= 0.05",
            name="diversity_adjustment_range",
        ),
        CheckConstraint(
            "fairness_adjustment >= -0.05 AND fairness_adjustment <= 0.05",
            name="fairness_adjustment_range",
        ),
        CheckConstraint(
            "exploration_adjustment >= 0 AND exploration_adjustment <= 0.04",
            name="exploration_adjustment_range",
        ),
        CheckConstraint(
            "repeat_penalty >= 0 AND repeat_penalty <= 0.10",
            name="repeat_penalty_range",
        ),
        CheckConstraint(
            "concentration_penalty >= 0 AND concentration_penalty <= 0.05",
            name="concentration_penalty_range",
        ),
        CheckConstraint(
            "slot_type IN ('CORE', 'CONDITIONAL', 'DIVERSITY', 'EXPLORATION', 'NEW')",
            name="slot_type_allowed",
        ),
        Index("ix_slate_item_result_rank", "slate_result_id", "final_rank"),
        {"schema": SCHEMA_MATCHING},
    )

    slate_item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    slate_result_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    match_result_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_result.match_result_id"),
        nullable=False,
    )
    recommendable_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    exhibitor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
    )
    object_type: Mapped[str] = mapped_column(String(20), nullable=False)
    base_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    final_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    base_score: Mapped[float] = mapped_column(Numeric(), nullable=False)
    slate_score: Mapped[float] = mapped_column(Numeric(), nullable=False)
    mmr_score: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    diversity_adjustment: Mapped[float] = mapped_column(Numeric(), nullable=False)
    fairness_adjustment: Mapped[float] = mapped_column(Numeric(), nullable=False)
    exploration_adjustment: Mapped[float] = mapped_column(Numeric(), nullable=False)
    repeat_penalty: Mapped[float] = mapped_column(Numeric(), nullable=False)
    concentration_penalty: Mapped[float] = mapped_column(Numeric(), nullable=False)
    slot_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reason_codes: Mapped[list] = mapped_column(JSONB, nullable=False)
    related_object_ids: Mapped[list] = mapped_column(JSONB, nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    score_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RecommendationDelivery(Base):
    """matching.recommendation_delivery - 지시사항의 "RecommendationDelivery".

    db-erd-table-spec.md에는 공식화되어 있지 않은 테이블이다 (모듈 docstring 참고). 하나의
    match_result가 여러 채널로 여러 번 노출/발송될 수 있다는 전제로 설계했다 - 예를 들어
    위젯에 렌더링된 뒤 별도로 카카오 알림톡으로도 재전달되는 경우 각각 별도 행이 된다. 이렇게
    하면 delivered_via를 배열 컬럼(technical-design.md 방식)으로 뭉치지 않고, db-erd 전반의
    "행동 이벤트는 append-only, 과거 결과를 덮어쓰지 않는다" 원칙과 일관되게 유지할 수 있다.

    channel은 6단계 온톨로지가 없어 CHECK로 고정하지 않는다. 참고 후보값
    (ai-matching-architecture.md 2.4절, technical-design.md delivered_via): WIDGET, PUSH,
    SMS, KAKAO_ALIMTALK, EMAIL, CHATBOT.

    delivery_status는 이 테이블 자체가 새로 설계한 것이라 이번 작업에서 직접 정의한 개방형이
    아닌 마감(closed) 상태값으로 CHECK를 건다 - 필요하면 이후 값 추가 시 CHECK와 이 주석을
    함께 갱신한다.
    """

    __tablename__ = "recommendation_delivery"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendation_session_id"],
            [
                f"{SCHEMA_MATCHING}.recommendation_session.tenant_id",
                f"{SCHEMA_MATCHING}.recommendation_session.event_id",
                f"{SCHEMA_MATCHING}.recommendation_session.recommendation_session_id",
            ],
            name="fk_recommendation_delivery_session_boundary",
        ),
        ForeignKeyConstraint(
            ["recommendation_session_id", "match_result_id"],
            [
                f"{SCHEMA_MATCHING}.match_result.recommendation_session_id",
                f"{SCHEMA_MATCHING}.match_result.match_result_id",
            ],
            name="fk_recommendation_delivery_result_session",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                f"{SCHEMA_EXHIBITION}.recommendable.tenant_id",
                f"{SCHEMA_EXHIBITION}.recommendable.event_id",
                f"{SCHEMA_EXHIBITION}.recommendable.recommendable_id",
            ],
            name="fk_recommendation_delivery_target_boundary",
        ),
        CheckConstraint(
            "delivery_status IN ('QUEUED', 'SENT', 'DELIVERED', 'FAILED', 'SKIPPED')",
            name="delivery_status_allowed",
        ),
        CheckConstraint(
            "rank_at_delivery IS NULL OR rank_at_delivery > 0",
            name="rank_at_delivery_positive",
        ),
        CheckConstraint(
            "delivered_at IS NULL OR delivered_at >= requested_at",
            name="delivered_after_requested",
        ),
        Index("ix_recommendation_delivery_session", "recommendation_session_id"),
        Index("ix_recommendation_delivery_result", "match_result_id"),
        Index(
            "ix_recommendation_delivery_target_time", "recommendable_id", "requested_at"
        ),
        {"schema": SCHEMA_MATCHING},
    )

    recommendation_delivery_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)

    recommendation_session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    match_result_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    # match_result에서 파생 가능하지만, favorite/feedback/check_in 등 db-erd의 다른
    # interaction 테이블과 동일하게 조회 편의를 위해 중복 저장한다 (db-erd 13.3절 마지막 문단:
    # "matching, favorite, feedback, route, embedding은 recommendable_id를 참조한다").
    recommendable_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )

    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    delivery_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DELIVERED"
    )
    # 발송/렌더링 시점의 순위. match_result.rank와 다를 수 있다 (재정렬·다양성 보정 이후
    # 클라이언트에 실제로 노출된 순번을 남기고 싶을 때 사용).
    rank_at_delivery: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # SMS/카카오 알림톡 등 외부 발송 공급자가 반환하는 추적용 메시지 ID.
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # 위젯은 렌더링 즉시, 외부 채널은 공급자 콜백 수신 시각으로 채운다. 실패 시 NULL 유지.
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class InteractionEvent(Base):
    """interaction.interaction_event - db-erd 17.1.

    대량 append-only 행동 이벤트 로그다 (조회/저장/제외/QR/방문/평가). event_date로 RANGE
    파티셔닝한다 - 이 클래스는 파티션 부모(루트) 테이블만 선언하고, 실제 파티션 생성(기본
    파티션 포함)은 함께 추가하는 alembic 마이그레이션에서 수행한다.

    event_type은 6단계 온톨로지/표준 이벤트 카탈로그가 아직 없어 CHECK로 고정하지 않는다.
    참고 후보값 (지시사항·db-erd 5절: "조회, 저장, 제외, QR, 방문, 평가"): VIEW_IMPRESSION,
    VIEW_DETAIL, FAVORITE_ADD, FAVORITE_REMOVE, EXCLUDE, QR_SCAN, CHECK_IN, MEETING_REQUEST,
    FEEDBACK_SUBMIT 등. 허용 목록은 애플리케이션 계층에서 관리한다.
    """

    __tablename__ = "interaction_event"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_interaction_event_event_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                f"{SCHEMA_EXHIBITION}.recommendable.tenant_id",
                f"{SCHEMA_EXHIBITION}.recommendable.event_id",
                f"{SCHEMA_EXHIBITION}.recommendable.recommendable_id",
            ],
            name="fk_interaction_event_target_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendation_session_id"],
            [
                f"{SCHEMA_MATCHING}.recommendation_session.tenant_id",
                f"{SCHEMA_MATCHING}.recommendation_session.event_id",
                f"{SCHEMA_MATCHING}.recommendation_session.recommendation_session_id",
            ],
            name="fk_interaction_event_session_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "visit_session_id"],
            [
                "profile.visit_session.tenant_id",
                "profile.visit_session.event_id",
                "profile.visit_session.visit_session_id",
            ],
            name="fk_interaction_event_visit_boundary",
        ),
        ForeignKeyConstraint(
            ["recommendation_session_id", "match_result_id"],
            [
                f"{SCHEMA_MATCHING}.match_result.recommendation_session_id",
                f"{SCHEMA_MATCHING}.match_result.match_result_id",
            ],
            name="fk_interaction_event_result_session",
        ),
        # db-erd 17.1: "CHECK num_nonnulls(user_id, guest_session_id) <= 1. 서버가 세션에서
        # 주체를 채운다." (둘 다 NULL인 이벤트도 허용 - 예: 순수 시스템/운영 이벤트)
        CheckConstraint(
            "num_nonnulls(user_id, guest_session_id) <= 1",
            name="subject_at_most_one",
        ),
        CheckConstraint(
            "rank_at_event IS NULL OR rank_at_event > 0", name="rank_at_event_positive"
        ),
        CheckConstraint(
            "match_result_id IS NULL OR recommendation_session_id IS NOT NULL",
            name="result_requires_session",
        ),
        Index("ix_interaction_event_date_type", "event_date", "event_type"),
        Index("ix_interaction_event_session", "recommendation_session_id"),
        Index("ix_interaction_event_target_time", "recommendable_id", "occurred_at"),
        Index(
            "ix_interaction_event_received_brin", "received_at", postgresql_using="brin"
        ),
        {
            "schema": SCHEMA_INTERACTION,
            # db-erd 17.1 파티셔닝 절: "MVP·행사 기간: 일 또는 월 RANGE(event_date)".
            "postgresql_partition_by": "RANGE (event_date)",
        },
    )

    # 파티션 키를 포함한 복합 PK (db-erd 2절 "이벤트 PK" 보정: "파티션 키를 포함한 복합 PK 사용").
    event_date: Mapped[date] = mapped_column(Date, primary_key=True, nullable=False)
    interaction_event_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=_new_uuid
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("profile.user_account.user_id"), nullable=True
    )
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profile.guest_session.guest_session_id"),
        nullable=True,
    )
    visit_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )

    event_type: Mapped[str] = mapped_column(String(60), nullable=False)

    recommendable_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    recommendation_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    match_result_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    rank_at_event: Mapped[int | None] = mapped_column(Integer, nullable=True)
    screen_code: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # db-erd: "허용 목록 속성" - 자유 JSONB이지만 애플리케이션 계층에서 허용 키만 기록해야 한다.
    context_json: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # 클라이언트 오프라인 재전송 중복 제거용. integration.idempotency_record와는 별개로,
    # 클라이언트가 동일 이벤트를 재전송했는지 애플리케이션 계층에서 대조하는 값이다.
    client_event_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    consent_snapshot_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )

    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class InteractionClientEventDedupe(Base):
    """Non-partitioned global claim for offline client-event idempotency."""

    __tablename__ = "client_event_dedupe"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_client_event_dedupe_event_boundary",
        ),
        ForeignKeyConstraint(
            ["event_date", "interaction_event_id"],
            [
                f"{SCHEMA_INTERACTION}.interaction_event.event_date",
                f"{SCHEMA_INTERACTION}.interaction_event.interaction_event_id",
            ],
            name="fk_client_event_dedupe_interaction_event",
        ),
        Index("ix_client_event_dedupe_event", "tenant_id", "event_id"),
        {"schema": SCHEMA_INTERACTION},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True)
    client_event_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True
    )
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    interaction_event_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    payload_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class RecommendationImpression(Base):
    """Normalized append-only projection of a card that was actually visible."""

    __tablename__ = "recommendation_impression"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_recommendation_impression_event_boundary",
        ),
        ForeignKeyConstraint(
            ["event_date", "interaction_event_id"],
            [
                f"{SCHEMA_INTERACTION}.interaction_event.event_date",
                f"{SCHEMA_INTERACTION}.interaction_event.interaction_event_id",
            ],
            name="fk_recommendation_impression_interaction_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "visit_session_id"],
            [
                "profile.visit_session.tenant_id",
                "profile.visit_session.event_id",
                "profile.visit_session.visit_session_id",
            ],
            name="fk_recommendation_impression_visit_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "slate_result_id"],
            [
                f"{SCHEMA_MATCHING}.slate_result.tenant_id",
                f"{SCHEMA_MATCHING}.slate_result.event_id",
                f"{SCHEMA_MATCHING}.slate_result.slate_result_id",
            ],
            name="fk_recommendation_impression_slate_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "slate_result_id", "slate_item_id"],
            [
                f"{SCHEMA_MATCHING}.slate_item.tenant_id",
                f"{SCHEMA_MATCHING}.slate_item.event_id",
                f"{SCHEMA_MATCHING}.slate_item.slate_result_id",
                f"{SCHEMA_MATCHING}.slate_item.slate_item_id",
            ],
            name="fk_recommendation_impression_item_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                f"{SCHEMA_EXHIBITION}.recommendable.tenant_id",
                f"{SCHEMA_EXHIBITION}.recommendable.event_id",
                f"{SCHEMA_EXHIBITION}.recommendable.recommendable_id",
            ],
            name="fk_recommendation_impression_target_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            [
                f"{SCHEMA_EXHIBITION}.exhibitor.tenant_id",
                f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id",
            ],
            name="fk_recommendation_impression_exhibitor_boundary",
        ),
        CheckConstraint(
            "num_nonnulls(user_id, guest_session_id) <= 1",
            name="subject_at_most_one",
        ),
        CheckConstraint("final_rank > 0", name="final_rank_positive"),
        CheckConstraint("visible_duration_ms >= 0", name="visible_duration_ms_nonneg"),
        CheckConstraint(
            "content_type IN ('PERSONALIZED_RECOMMENDATION', 'SPONSORED_CONTENT', "
            "'OPERATOR_NOTICE', 'EDITORIAL_CONTENT')",
            name="content_type_allowed",
        ),
        CheckConstraint(
            "slot_type IN ('CORE', 'CONDITIONAL', 'DIVERSITY', 'EXPLORATION', "
            "'NEW', 'SPONSORED', 'NOTICE', 'EDITORIAL')",
            name="slot_type_allowed",
        ),
        UniqueConstraint(
            "event_date",
            "interaction_event_id",
            name="uq_recommendation_impression_interaction_event",
        ),
        Index(
            "ix_recommendation_impression_subject_time",
            "visit_session_id",
            "occurred_at",
        ),
        Index(
            "ix_recommendation_impression_user_time",
            "tenant_id",
            "event_id",
            "user_id",
            "occurred_at",
        ),
        Index(
            "ix_recommendation_impression_guest_time",
            "tenant_id",
            "event_id",
            "guest_session_id",
            "occurred_at",
        ),
        Index(
            "ix_recommendation_impression_exhibitor_time",
            "tenant_id",
            "event_id",
            "exhibitor_id",
            "occurred_at",
        ),
        {"schema": SCHEMA_INTERACTION},
    )

    impression_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    interaction_event_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("profile.user_account.user_id"), nullable=True
    )
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profile.guest_session.guest_session_id"),
        nullable=True,
    )
    visit_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    slate_result_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    slate_item_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    recommendable_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    exhibitor_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=True,
    )
    object_type: Mapped[str] = mapped_column(String(20), nullable=False)
    final_rank: Mapped[int] = mapped_column(Integer, nullable=False)
    slot_type: Mapped[str] = mapped_column(String(20), nullable=False)
    content_type: Mapped[str] = mapped_column(String(40), nullable=False)
    visible_duration_ms: Mapped[int] = mapped_column(Integer, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
