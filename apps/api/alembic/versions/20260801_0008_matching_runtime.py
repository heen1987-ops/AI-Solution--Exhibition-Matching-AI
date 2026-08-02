"""create matching runtime, result, delivery, and interaction tables

This revision publishes the previously pending matching-domain draft after the
exhibition, policy, and AI registries are available on the single migration chain.

The historical draft notes below describe the former dependency gap and are retained
only as provenance. They are superseded by revisions 0005 through 0007; every listed
target exists before this revision runs, and ``down_revision`` is no longer a root.

이 마이그레이션을 작성하는 시점(2026-08-01)에 이미 존재하는 선행 마이그레이션 덕분에 다음
의존 테이블은 실제로 존재한다:

    - core.tenant, exhibition.event                    - 0003_foundation
    - profile.user_account, profile.guest_session       - 0003_foundation
    - ontology.taxonomy_version                         - 0002_ontology
    - profile.user_profile, profile.profile_version,
      profile.visit_session                             - 20260801144653_profile_domain

반면 다음은 이 시점까지 어떤 마이그레이션도 만들지 않는다 (여러 도메인 에이전트가 동시에
작업 중이라 발생하는 타이밍 문제):

    - exhibition.booth, exhibition.event_product, exhibition.exhibitor_participation,
      exhibition.program을 만드는 마이그레이션
    - ai 도메인 테이블을 만드는 마이그레이션 (ai.model_version, ai.ai_run)
    - matching.match_policy_version / match_weight / filter_rule을 만드는 마이그레이션
      (db-erd-table-spec.md 15.1절 - 이번 작업 범위 밖. app/models/matching.py 모듈
      docstring 참고)

또한 20260801144653_profile_domain 마이그레이션 자체가 아직 0003_foundation 위로
체이닝되어 있지 않다(down_revision=None인 별도 root). 즉 이 마이그레이션이 실제로 필요로
하는 선행 테이블은 서로 다른 두 개의 독립된 리비전 갈래(0003_foundation 갈래와
profile_domain 갈래)와 위에 나열한 아직 존재하지 않는 마이그레이션들에 걸쳐 있어, 단일
down_revision으로는 정확히 표현할 수 없다. 따라서 지시된 대로 down_revision을 None으로
두고 이 주석을 남긴다.

통합 담당자를 위한 처리 순서 제안:
    1. profile_domain의 down_revision을 0003_foundation으로 재배치(또는 병합 리비전 추가).
    2. exhibition.booth/event_product/exhibitor_participation/program 마이그레이션 작성.
    3. ai.model_version/ai.ai_run 마이그레이션 작성.
    4. matching.match_policy_version 계열 마이그레이션 작성.
    5. 위 1~4가 모두 한 줄기로 이어진 뒤, 그 마지막 리비전을 이 마이그레이션의 down_revision으로
       설정.

이 마이그레이션이 생성하는 테이블 중 다음 컬럼은 ForeignKey이며, 그 대상이 실제로 존재해야
upgrade()가 성공한다 (이미 존재하는 대상과 아직 없는 대상을 구분해 표기):
    - core.tenant(tenant_id)                              [존재: 0003_foundation]
    - exhibition.event(event_id)                          [존재: 0003_foundation]
    - exhibition.booth(booth_id)                          [없음] recommendable.booth_id
    - exhibition.event_product(event_product_id)          [없음] recommendable.event_product_id
    - exhibition.exhibitor_participation(participation_id) [없음] recommendable.participation_id
    - exhibition.program(program_id)                      [없음] recommendable.program_id
    - ontology.taxonomy_version(taxonomy_version_id)      [존재: 0002_ontology]
      recommendation_session.taxonomy_version_id (app/models/matching.py 모듈 docstring 참고:
      db-erd-table-spec.md 11.1절 제목이 "ontology.taxonomy_version"이며 exhibition 스키마가
      아니다)
    - profile.user_profile(profile_id)                    [존재: profile_domain]
    - profile.profile_version(profile_version_id)         [존재: profile_domain]
    - profile.visit_session(visit_session_id)             [존재: profile_domain]
      recommendation_session.visit_session_id, interaction_event.visit_session_id
    - profile.user_account(user_id)                       [존재: 0003_foundation]
      interaction_event.user_id
    - profile.guest_session(guest_session_id)             [존재: 0003_foundation]
      interaction_event.guest_session_id
    - matching.match_policy_version(match_policy_version_id) [없음] recommendation_session.policy_version_id
    - ai.model_version(model_version_id)                  [없음] recommendation_session.ranking_model_version_id,
      recommendation_session.explanation_model_version_id
    - ai.ai_run(ai_run_id)                                 [없음] match_reason.ai_run_id

근거 문서: docs/db-erd-table-spec.md 2절(원안 대비 필수 보정), 13.3절(exhibition.recommendable),
15절(추천 정책·결과), 17.1절(interaction.interaction_event).
API 계약 근거: docs/frontend-backend-ai-interface-spec.md 9절(추천 API), 16절(행동 이벤트 API).
대응하는 SQLAlchemy 모델: backend/app/models/matching.py.

Revision ID: 0008_matching_runtime
Revises: 0007_policy_ai_registry
Create Date: 2026-08-01

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import SCHEMA_EXHIBITION, SCHEMA_INTERACTION, SCHEMA_MATCHING
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0008_matching_runtime"
down_revision: str | None = "0007_policy_ai_registry"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_user_profile_boundary_id",
        "user_profile",
        ["tenant_id", "event_id", "profile_id"],
        schema="profile",
    )
    op.create_unique_constraint(
        "uq_booth_boundary_id",
        "booth",
        ["tenant_id", "event_id", "booth_id"],
        schema="exhibition",
    )
    op.create_unique_constraint(
        "uq_program_boundary_id",
        "program",
        ["tenant_id", "event_id", "program_id"],
        schema="exhibition",
    )
    op.create_unique_constraint(
        "uq_visit_session_boundary_id",
        "visit_session",
        ["tenant_id", "event_id", "visit_session_id"],
        schema="profile",
    )
    op.create_unique_constraint(
        "uq_filter_evaluation_boundary_id",
        "filter_evaluation",
        ["tenant_id", "event_id", "filter_evaluation_id"],
        schema="matching",
    )
    op.create_foreign_key(
        "fk_filter_evaluation_profile_boundary",
        "filter_evaluation",
        "user_profile",
        ["tenant_id", "event_id", "profile_id"],
        ["tenant_id", "event_id", "profile_id"],
        source_schema="matching",
        referent_schema="profile",
    )

    # 1) exhibition.recommendable - db-erd 13.3, 2절 "다형 참조" 보정.
    op.create_table(
        "recommendable",
        sa.Column("recommendable_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("object_type", sa.String(20), nullable=False),
        sa.Column(
            "booth_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "event_product_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "participation_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "program_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "object_type IN ('BOOTH', 'EVENT_PRODUCT', 'EXHIBITOR', 'PROGRAM')",
            name="object_type_allowed",
        ),
        sa.CheckConstraint(
            "num_nonnulls(booth_id, event_product_id, participation_id, program_id) = 1",
            name="exactly_one_target",
        ),
        sa.CheckConstraint(
            "(object_type = 'BOOTH' AND booth_id IS NOT NULL) OR "
            "(object_type = 'EVENT_PRODUCT' AND event_product_id IS NOT NULL) OR "
            "(object_type = 'EXHIBITOR' AND participation_id IS NOT NULL) OR "
            "(object_type = 'PROGRAM' AND program_id IS NOT NULL)",
            name="object_type_target_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_recommendable_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "booth_id"],
            [
                "exhibition.booth.tenant_id",
                "exhibition.booth.event_id",
                "exhibition.booth.booth_id",
            ],
            name="fk_recommendable_booth_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "event_product_id"],
            [
                "exhibition.event_product.tenant_id",
                "exhibition.event_product.event_id",
                "exhibition.event_product.event_product_id",
            ],
            name="fk_recommendable_event_product_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "participation_id"],
            [
                "exhibition.exhibitor_participation.tenant_id",
                "exhibition.exhibitor_participation.event_id",
                "exhibition.exhibitor_participation.participation_id",
            ],
            name="fk_recommendable_participation_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "program_id"],
            [
                "exhibition.program.tenant_id",
                "exhibition.program.event_id",
                "exhibition.program.program_id",
            ],
            name="fk_recommendable_program_boundary",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "recommendable_id",
            name="uq_recommendable_boundary_id",
        ),
        schema=SCHEMA_EXHIBITION,
    )
    op.create_index(
        "uq_recommendable_booth_id",
        "recommendable",
        ["booth_id"],
        unique=True,
        schema=SCHEMA_EXHIBITION,
        postgresql_where=sa.text("booth_id IS NOT NULL"),
    )
    op.create_index(
        "uq_recommendable_event_product_id",
        "recommendable",
        ["event_product_id"],
        unique=True,
        schema=SCHEMA_EXHIBITION,
        postgresql_where=sa.text("event_product_id IS NOT NULL"),
    )
    op.create_index(
        "uq_recommendable_participation_id",
        "recommendable",
        ["participation_id"],
        unique=True,
        schema=SCHEMA_EXHIBITION,
        postgresql_where=sa.text("participation_id IS NOT NULL"),
    )
    op.create_index(
        "uq_recommendable_program_id",
        "recommendable",
        ["program_id"],
        unique=True,
        schema=SCHEMA_EXHIBITION,
        postgresql_where=sa.text("program_id IS NOT NULL"),
    )
    op.create_index(
        "ix_recommendable_tenant_event",
        "recommendable",
        ["tenant_id", "event_id", "active"],
        schema=SCHEMA_EXHIBITION,
    )

    # 2) matching.recommendation_session - db-erd 15.2 (지시사항의 "MatchRun"). 2절 "추천 버전" 보정.
    op.create_table(
        "recommendation_session",
        sa.Column(
            "recommendation_session_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("profile.user_profile.profile_id"),
            nullable=False,
        ),
        sa.Column(
            "profile_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "visit_session_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "filter_evaluation_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("recommendation_type", sa.String(20), nullable=False),
        sa.Column(
            "policy_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_MATCHING}.match_policy_version.match_policy_version_id"
            ),
            nullable=False,
        ),
        sa.Column(
            "ranking_model_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai.model_version.model_version_id"),
            nullable=False,
        ),
        sa.Column(
            "explanation_model_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai.model_version.model_version_id"),
            nullable=True,
        ),
        sa.Column(
            "taxonomy_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ontology.taxonomy_version.taxonomy_version_id"),
            nullable=False,
        ),
        sa.Column("context_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column("consent_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=True),
        sa.Column("filtered_count", sa.Integer(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=True),
        sa.Column("fallback_strategy", sa.String(30), nullable=True),
        sa.Column(
            "status", sa.String(20), nullable=False, server_default=sa.text("'ACTIVE'")
        ),
        sa.Column("generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "recommendation_type IN ('BOOTH', 'PRODUCT', 'EXHIBITOR', 'PROGRAM', 'MIXED')",
            name="recommendation_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'EXPIRED', 'INVALIDATED')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "candidate_count IS NULL OR candidate_count >= 0",
            name="candidate_count_nonneg",
        ),
        sa.CheckConstraint(
            "filtered_count IS NULL OR filtered_count >= 0",
            name="filtered_count_nonneg",
        ),
        sa.CheckConstraint(
            "result_count IS NULL OR result_count >= 0",
            name="result_count_nonneg",
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="latency_ms_nonneg",
        ),
        sa.CheckConstraint(
            "generated_at IS NULL OR expires_at IS NULL OR generated_at < expires_at",
            name="generated_before_expires",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_recommendation_session_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id", "profile_version_id"],
            [
                "profile.profile_version.profile_id",
                "profile.profile_version.profile_version_id",
            ],
            name="fk_recommendation_session_profile_version",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "profile_id"],
            [
                "profile.user_profile.tenant_id",
                "profile.user_profile.event_id",
                "profile.user_profile.profile_id",
            ],
            name="fk_recommendation_session_profile_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "visit_session_id"],
            [
                "profile.visit_session.tenant_id",
                "profile.visit_session.event_id",
                "profile.visit_session.visit_session_id",
            ],
            name="fk_recommendation_session_visit_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "filter_evaluation_id"],
            [
                "matching.filter_evaluation.tenant_id",
                "matching.filter_evaluation.event_id",
                "matching.filter_evaluation.filter_evaluation_id",
            ],
            name="fk_recommendation_session_filter_boundary",
        ),
        sa.UniqueConstraint(
            "filter_evaluation_id",
            name="uq_recommendation_session_filter_evaluation",
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "recommendation_session_id",
            name="uq_recommendation_session_boundary_id",
        ),
        schema=SCHEMA_MATCHING,
    )
    op.create_index(
        "ix_recommendation_session_profile",
        "recommendation_session",
        ["profile_id", "generated_at"],
        schema=SCHEMA_MATCHING,
    )
    op.create_index(
        "ix_recommendation_session_tenant_event",
        "recommendation_session",
        ["tenant_id", "event_id"],
        schema=SCHEMA_MATCHING,
    )
    op.create_index(
        "ix_recommendation_session_visit",
        "recommendation_session",
        ["visit_session_id"],
        schema=SCHEMA_MATCHING,
    )

    # 3) matching.match_result - db-erd 15.3.
    op.create_table(
        "match_result",
        sa.Column("match_result_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "recommendation_session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "recommendable_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "directional_policy_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_MATCHING}.match_policy_version.match_policy_version_id"
            ),
            nullable=False,
        ),
        sa.Column(
            "exhibitor_policy_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_MATCHING}.match_policy_version.match_policy_version_id"
            ),
            nullable=True,
        ),
        sa.Column(
            "reciprocal_policy_version_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_MATCHING}.match_policy_version.match_policy_version_id"
            ),
            nullable=True,
        ),
        sa.Column("raw_score", sa.Numeric(), nullable=True),
        sa.Column("normalized_score", sa.Numeric(), nullable=True),
        sa.Column("final_score", sa.Numeric(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("directional_components", postgresql.JSONB(), nullable=False),
        sa.Column("directional_effective_weights", postgresql.JSONB(), nullable=False),
        sa.Column("directional_contributions", postgresql.JSONB(), nullable=False),
        sa.Column("directional_missing_components", postgresql.JSONB(), nullable=False),
        sa.Column("directional_confidence", sa.Numeric(7, 6), nullable=True),
        sa.Column("directional_grade", sa.String(20), nullable=True),
        sa.Column("directional_score_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "exhibitor_directional_components", postgresql.JSONB(), nullable=True
        ),
        sa.Column(
            "exhibitor_directional_effective_weights",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "exhibitor_directional_contributions",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column(
            "exhibitor_directional_missing_components",
            postgresql.JSONB(),
            nullable=True,
        ),
        sa.Column("exhibitor_directional_confidence", sa.Numeric(7, 6), nullable=True),
        sa.Column(
            "exhibitor_directional_score_fingerprint",
            sa.String(64),
            nullable=True,
        ),
        sa.Column("reciprocal_details", postgresql.JSONB(), nullable=True),
        sa.Column("reciprocal_score_fingerprint", sa.String(64), nullable=True),
        sa.Column("preference_score", sa.Numeric(), nullable=True),
        sa.Column("goal_score", sa.Numeric(), nullable=True),
        sa.Column("trade_score", sa.Numeric(), nullable=True),
        sa.Column("context_score", sa.Numeric(), nullable=True),
        sa.Column("behavior_score", sa.Numeric(), nullable=True),
        sa.Column("diversity_adjustment", sa.Numeric(), nullable=True),
        sa.Column("trust_score", sa.Numeric(), nullable=True),
        sa.Column("recommended_action", sa.String(30), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "recommendation_session_id", "rank", name="uq_match_result_session_rank"
        ),
        sa.UniqueConstraint(
            "recommendation_session_id",
            "recommendable_id",
            name="uq_match_result_session_recommendable",
        ),
        sa.UniqueConstraint(
            "recommendation_session_id",
            "match_result_id",
            name="uq_match_result_session_result",
        ),
        sa.CheckConstraint("rank > 0", name="rank_positive"),
        sa.CheckConstraint(
            "normalized_score IS NULL OR (normalized_score >= 0 AND normalized_score <= 1)",
            name="normalized_score_range",
        ),
        sa.CheckConstraint(
            "final_score IS NULL OR (final_score >= 0 AND final_score <= 1)",
            name="final_score_range",
        ),
        sa.CheckConstraint(
            "preference_score IS NULL OR (preference_score >= 0 AND preference_score <= 1)",
            name="preference_score_range",
        ),
        sa.CheckConstraint(
            "goal_score IS NULL OR (goal_score >= 0 AND goal_score <= 1)",
            name="goal_score_range",
        ),
        sa.CheckConstraint(
            "trade_score IS NULL OR (trade_score >= 0 AND trade_score <= 1)",
            name="trade_score_range",
        ),
        sa.CheckConstraint(
            "context_score IS NULL OR (context_score >= 0 AND context_score <= 1)",
            name="context_score_range",
        ),
        sa.CheckConstraint(
            "behavior_score IS NULL OR (behavior_score >= 0 AND behavior_score <= 1)",
            name="behavior_score_range",
        ),
        sa.CheckConstraint(
            "trust_score IS NULL OR (trust_score >= 0 AND trust_score <= 1)",
            name="trust_score_range",
        ),
        sa.CheckConstraint(
            "directional_confidence IS NULL OR "
            "(directional_confidence >= 0 AND directional_confidence <= 1)",
            name="directional_confidence_range",
        ),
        sa.CheckConstraint(
            "exhibitor_directional_confidence IS NULL OR "
            "(exhibitor_directional_confidence >= 0 AND "
            "exhibitor_directional_confidence <= 1)",
            name="exhibitor_confidence_range",
        ),
        sa.CheckConstraint(
            "(reciprocal_policy_version_id IS NULL) = "
            "(reciprocal_details IS NULL) AND "
            "(reciprocal_policy_version_id IS NULL) = "
            "(reciprocal_score_fingerprint IS NULL)",
            name="reciprocal_provenance_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendation_session_id"],
            [
                "matching.recommendation_session.tenant_id",
                "matching.recommendation_session.event_id",
                "matching.recommendation_session.recommendation_session_id",
            ],
            name="fk_match_result_session_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                "exhibition.recommendable.tenant_id",
                "exhibition.recommendable.event_id",
                "exhibition.recommendable.recommendable_id",
            ],
            name="fk_match_result_recommendable_boundary",
        ),
        schema=SCHEMA_MATCHING,
    )
    op.create_index(
        "ix_match_result_target_created",
        "match_result",
        ["recommendable_id", "created_at"],
        schema=SCHEMA_MATCHING,
    )

    # 4) matching.match_reason - db-erd 15.4, 지시사항의 "추천 이유" 보정
    #    (reason_code + evidence_refs로 저장).
    op.create_table(
        "match_reason",
        sa.Column("match_reason_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "match_result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(f"{SCHEMA_MATCHING}.match_result.match_result_id"),
            nullable=False,
        ),
        sa.Column("reason_code", sa.String(50), nullable=False),
        sa.Column("reason_text", sa.String(500), nullable=True),
        sa.Column("evidence_refs", postgresql.JSONB(), nullable=True),
        sa.Column("contribution_score", sa.Numeric(), nullable=True),
        sa.Column("display_order", sa.SmallInteger(), nullable=True),
        sa.Column("generated_by", sa.String(20), nullable=False),
        sa.Column(
            "ai_run_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("ai.ai_run.ai_run_id"),
            nullable=True,
        ),
        sa.Column(
            "validation_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'VALID'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "contribution_score IS NULL OR (contribution_score >= 0 AND contribution_score <= 1)",
            name="contribution_score_range",
        ),
        sa.CheckConstraint(
            "generated_by IN ('TEMPLATE', 'LLM')",
            name="generated_by_allowed",
        ),
        sa.CheckConstraint(
            "validation_status IN ('VALID', 'REJECTED')",
            name="validation_status_allowed",
        ),
        schema=SCHEMA_MATCHING,
    )
    op.create_index(
        "ix_match_reason_result_order",
        "match_reason",
        ["match_result_id", "display_order"],
        schema=SCHEMA_MATCHING,
    )

    # 5) matching.recommendation_delivery - db-erd-table-spec.md에는 없는 테이블.
    #    app/models/matching.py의 RecommendationDelivery 클래스 docstring 참고
    #    (지시사항이 명시한 대상이지만 db-erd 문서에는 공식화되어 있지 않아 이번 작업에서
    #    db-erd의 설계 관례를 따라 새로 설계함).
    op.create_table(
        "recommendation_delivery",
        sa.Column(
            "recommendation_delivery_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "recommendation_session_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "match_result_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "recommendable_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("channel", sa.String(20), nullable=False),
        sa.Column(
            "delivery_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'DELIVERED'"),
        ),
        sa.Column("rank_at_delivery", sa.Integer(), nullable=True),
        sa.Column("provider_message_id", sa.String(200), nullable=True),
        sa.Column("failure_reason", sa.String(200), nullable=True),
        sa.Column(
            "requested_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "delivery_status IN ('QUEUED', 'SENT', 'DELIVERED', 'FAILED', 'SKIPPED')",
            name="delivery_status_allowed",
        ),
        sa.CheckConstraint(
            "rank_at_delivery IS NULL OR rank_at_delivery > 0",
            name="rank_at_delivery_positive",
        ),
        sa.CheckConstraint(
            "delivered_at IS NULL OR delivered_at >= requested_at",
            name="delivered_after_requested",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendation_session_id"],
            [
                "matching.recommendation_session.tenant_id",
                "matching.recommendation_session.event_id",
                "matching.recommendation_session.recommendation_session_id",
            ],
            name="fk_recommendation_delivery_session_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_session_id", "match_result_id"],
            [
                "matching.match_result.recommendation_session_id",
                "matching.match_result.match_result_id",
            ],
            name="fk_recommendation_delivery_result_session",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                "exhibition.recommendable.tenant_id",
                "exhibition.recommendable.event_id",
                "exhibition.recommendable.recommendable_id",
            ],
            name="fk_recommendation_delivery_target_boundary",
        ),
        schema=SCHEMA_MATCHING,
    )
    op.create_index(
        "ix_recommendation_delivery_session",
        "recommendation_delivery",
        ["recommendation_session_id"],
        schema=SCHEMA_MATCHING,
    )
    op.create_index(
        "ix_recommendation_delivery_result",
        "recommendation_delivery",
        ["match_result_id"],
        schema=SCHEMA_MATCHING,
    )
    op.create_index(
        "ix_recommendation_delivery_target_time",
        "recommendation_delivery",
        ["recommendable_id", "requested_at"],
        schema=SCHEMA_MATCHING,
    )

    # 6) interaction.interaction_event - db-erd 17.1. 대량 append-only 행동 이벤트.
    #    파티션 키(event_date)를 포함한 복합 PK (db-erd 2절 "이벤트 PK" 보정).
    op.create_table(
        "interaction_event",
        sa.Column("event_date", sa.Date(), primary_key=True, nullable=False),
        sa.Column(
            "interaction_event_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "event_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("profile.user_account.user_id"),
            nullable=True,
        ),
        sa.Column(
            "guest_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("profile.guest_session.guest_session_id"),
            nullable=True,
        ),
        sa.Column(
            "visit_session_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("event_type", sa.String(60), nullable=False),
        sa.Column(
            "recommendable_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "recommendation_session_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "match_result_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column("rank_at_event", sa.Integer(), nullable=True),
        sa.Column("screen_code", sa.String(30), nullable=True),
        sa.Column("context_json", postgresql.JSONB(), nullable=True),
        sa.Column("client_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("consent_snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(user_id, guest_session_id) <= 1",
            name="subject_at_most_one",
        ),
        sa.CheckConstraint(
            "rank_at_event IS NULL OR rank_at_event > 0",
            name="rank_at_event_positive",
        ),
        sa.CheckConstraint(
            "match_result_id IS NULL OR recommendation_session_id IS NOT NULL",
            name="result_requires_session",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_interaction_event_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                "exhibition.recommendable.tenant_id",
                "exhibition.recommendable.event_id",
                "exhibition.recommendable.recommendable_id",
            ],
            name="fk_interaction_event_target_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendation_session_id"],
            [
                "matching.recommendation_session.tenant_id",
                "matching.recommendation_session.event_id",
                "matching.recommendation_session.recommendation_session_id",
            ],
            name="fk_interaction_event_session_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "visit_session_id"],
            [
                "profile.visit_session.tenant_id",
                "profile.visit_session.event_id",
                "profile.visit_session.visit_session_id",
            ],
            name="fk_interaction_event_visit_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_session_id", "match_result_id"],
            [
                "matching.match_result.recommendation_session_id",
                "matching.match_result.match_result_id",
            ],
            name="fk_interaction_event_result_session",
        ),
        schema=SCHEMA_INTERACTION,
        postgresql_partition_by="RANGE (event_date)",
    )
    op.create_index(
        "ix_interaction_event_date_type",
        "interaction_event",
        ["event_date", "event_type"],
        schema=SCHEMA_INTERACTION,
    )
    op.create_index(
        "ix_interaction_event_session",
        "interaction_event",
        ["recommendation_session_id"],
        schema=SCHEMA_INTERACTION,
    )
    op.create_index(
        "ix_interaction_event_target_time",
        "interaction_event",
        ["recommendable_id", "occurred_at"],
        schema=SCHEMA_INTERACTION,
    )
    op.create_index(
        "ix_interaction_event_received_brin",
        "interaction_event",
        ["received_at"],
        schema=SCHEMA_INTERACTION,
        postgresql_using="brin",
    )
    # db-erd 17.1 파티셔닝 절: "기본 파티션으로 잘못된 날짜 격리". 실제 event_date 범위별
    # 파티션(일 또는 월 RANGE)은 운영 스크립트/스케줄러가 사전 생성하고, 이 기본 파티션은
    # 그 범위를 벗어난 값이 들어와도 insert 자체가 실패하지 않도록 하는 안전망이다.
    op.execute(
        f"CREATE TABLE {SCHEMA_INTERACTION}.interaction_event_default "
        f"PARTITION OF {SCHEMA_INTERACTION}.interaction_event DEFAULT"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION matching.protect_recommendation_session()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'recommendation sessions cannot be deleted';
            END IF;
            IF OLD.status = 'ACTIVE'
               AND NEW.status IN ('EXPIRED', 'INVALIDATED')
               AND (to_jsonb(NEW) - 'status') = (to_jsonb(OLD) - 'status') THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'recommendation provenance is immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_recommendation_session_provenance
        BEFORE UPDATE OR DELETE ON matching.recommendation_session
        FOR EACH ROW EXECUTE FUNCTION matching.protect_recommendation_session()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION matching.reject_matching_result_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'matching result artifacts are append-only';
        END;
        $$
        """
    )
    for table_name in ("match_result", "match_reason"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_append_only
            BEFORE UPDATE OR DELETE ON matching.{table_name}
            FOR EACH ROW EXECUTE FUNCTION matching.reject_matching_result_mutation()
            """
        )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION interaction.reject_interaction_event_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'interaction events are append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_interaction_event_append_only
        BEFORE UPDATE OR DELETE ON interaction.interaction_event
        FOR EACH ROW EXECUTE FUNCTION interaction.reject_interaction_event_mutation()
        """
    )


def downgrade() -> None:
    # 생성 역순으로 제거한다. 파티션 자식 테이블은 부모보다 먼저 명시적으로 드롭한다.
    op.execute(
        "DROP TRIGGER IF EXISTS trg_interaction_event_append_only "
        "ON interaction.interaction_event"
    )
    op.execute(
        "DROP FUNCTION IF EXISTS interaction.reject_interaction_event_mutation()"
    )
    for table_name in ("match_reason", "match_result"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only "
            f"ON matching.{table_name}"
        )
    op.execute("DROP FUNCTION IF EXISTS matching.reject_matching_result_mutation()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_recommendation_session_provenance "
        "ON matching.recommendation_session"
    )
    op.execute("DROP FUNCTION IF EXISTS matching.protect_recommendation_session()")
    op.execute(f"DROP TABLE IF EXISTS {SCHEMA_INTERACTION}.interaction_event_default")
    op.drop_table("interaction_event", schema=SCHEMA_INTERACTION)
    op.drop_table("recommendation_delivery", schema=SCHEMA_MATCHING)
    op.drop_table("match_reason", schema=SCHEMA_MATCHING)
    op.drop_table("match_result", schema=SCHEMA_MATCHING)
    op.drop_table("recommendation_session", schema=SCHEMA_MATCHING)
    op.drop_table("recommendable", schema=SCHEMA_EXHIBITION)
    op.drop_constraint(
        "fk_filter_evaluation_profile_boundary",
        "filter_evaluation",
        schema="matching",
        type_="foreignkey",
    )
    op.drop_constraint(
        "uq_filter_evaluation_boundary_id",
        "filter_evaluation",
        schema="matching",
        type_="unique",
    )
    op.drop_constraint(
        "uq_visit_session_boundary_id",
        "visit_session",
        schema="profile",
        type_="unique",
    )
    op.drop_constraint(
        "uq_program_boundary_id",
        "program",
        schema="exhibition",
        type_="unique",
    )
    op.drop_constraint(
        "uq_booth_boundary_id",
        "booth",
        schema="exhibition",
        type_="unique",
    )
    op.drop_constraint(
        "uq_user_profile_boundary_id",
        "user_profile",
        schema="profile",
        type_="unique",
    )
