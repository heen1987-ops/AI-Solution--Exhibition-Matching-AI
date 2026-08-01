"""create matching-domain tables and the recommendable registry

이 마이그레이션은 backend/app/models/matching.py를 대상으로 `alembic revision
--autogenerate`를 실행한 결과를 정리한 것이다 (0004_profile_domain의 수기 작성 관례 대신
autogenerate + 검토 방식을 택했다 - 8개 테이블·복합 FK·부분 UNIQUE 인덱스를 손으로 옮기며
제약 이름을 하나씩 맞추는 것보다 신뢰도가 높다).

근거 문서: docs/db-erd-table-spec.md 13.3절(exhibition.recommendable), 15절(matching.
match_policy_version/match_weight/filter_rule/recommendation_session/match_result/
match_reason/filter_result). 대응하는 SQLAlchemy 모델: backend/app/models/matching.py
(그 파일 docstring에 db-erd와 09·10단계 상세설계 사이의 스키마 불일치와 보정 근거가
정리되어 있다).

autogenerate가 감지했지만 이 마이그레이션에 포함하지 않은 변경 1건
------------------------------------------------------------------
`fk_supply_profile_attribute_concept_code` (exhibition.profile_attribute -> ontology.concept
복합 FK)도 함께 감지됐다. backend/app/models/exhibitor.py의 SupplyProfileAttribute 모델은
이 FK를 선언하지만 0005_exhibition 마이그레이션의 원본 SQL에는 빠져 있는 것으로 보인다 -
이 파일(matching 도메인)과 무관한 exhibition 도메인의 기존 갭이므로 여기서 조용히 고치지
않고 그대로 남겨둔다. exhibition 도메인 담당자가 0005_exhibition을 검토할 때 확인해야 한다.

Revision ID: 0006_matching
Revises: 0005_exhibition
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0006_matching"
down_revision: str | None = "0005_exhibition"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "match_policy_version",
        sa.Column("policy_version_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("user_type", sa.String(length=30), nullable=False),
        sa.Column("version", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("effective_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("effective_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'ACTIVE', 'RETIRED')",
            name=op.f("ck_match_policy_version_status_allowed"),
        ),
        sa.CheckConstraint(
            "user_type IN ('GENERAL_VISITOR', 'BUYER')",
            name=op.f("ck_match_policy_version_user_type_allowed"),
        ),
        sa.CheckConstraint(
            "effective_from IS NULL OR effective_until IS NULL "
            "OR effective_from < effective_until",
            name=op.f("ck_match_policy_version_effective_period_order"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_match_policy_version_event_boundary",
        ),
        sa.PrimaryKeyConstraint(
            "policy_version_id", name=op.f("pk_match_policy_version")
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "user_type",
            "version",
            name="uq_match_policy_version_identity",
        ),
        schema="matching",
    )
    op.create_index(
        "uq_match_policy_version_single_active",
        "match_policy_version",
        ["tenant_id", "event_id", "user_type"],
        unique=True,
        schema="matching",
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )

    op.create_table(
        "filter_rule",
        sa.Column("filter_rule_id", sa.UUID(), nullable=False),
        sa.Column("policy_version_id", sa.UUID(), nullable=False),
        sa.Column("rule_code", sa.String(length=100), nullable=False),
        sa.Column("rule_type", sa.String(length=20), nullable=False),
        sa.Column("rule_order", sa.Integer(), nullable=False),
        sa.Column("unknown_policy", sa.String(length=30), nullable=False),
        sa.Column("failure_action", sa.String(length=30), nullable=False),
        sa.Column(
            "config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.CheckConstraint(
            "failure_action IN ('EXCLUDE', 'SCORE_PENALTY', 'MANUAL_REVIEW')",
            name=op.f("ck_filter_rule_failure_action_allowed"),
        ),
        sa.CheckConstraint(
            "rule_type IN ('HARD', 'SOFT', 'WARNING')",
            name=op.f("ck_filter_rule_rule_type_allowed"),
        ),
        sa.CheckConstraint(
            "unknown_policy IN ('EXCLUDE', 'MANUAL_REVIEW', 'TREAT_AS_PASS', "
            "'TREAT_AS_FAIL')",
            name=op.f("ck_filter_rule_unknown_policy_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["matching.match_policy_version.policy_version_id"],
            name=op.f("fk_filter_rule_policy_version_id_match_policy_version"),
        ),
        sa.PrimaryKeyConstraint("filter_rule_id", name=op.f("pk_filter_rule")),
        sa.UniqueConstraint(
            "policy_version_id", "rule_code", name="uq_filter_rule_policy_code"
        ),
        schema="matching",
    )

    op.create_table(
        "match_weight",
        sa.Column("match_weight_id", sa.UUID(), nullable=False),
        sa.Column("policy_version_id", sa.UUID(), nullable=False),
        sa.Column("score_component", sa.String(length=50), nullable=False),
        sa.Column("weight_value", sa.Numeric(precision=8, scale=5), nullable=False),
        sa.Column("min_score", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column("max_score", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column(
            "config_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.CheckConstraint(
            "min_score IS NULL OR max_score IS NULL OR min_score <= max_score",
            name=op.f("ck_match_weight_score_range_order"),
        ),
        sa.CheckConstraint(
            "weight_value > 0 AND weight_value <= 1",
            name=op.f("ck_match_weight_weight_range"),
        ),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["matching.match_policy_version.policy_version_id"],
            name=op.f("fk_match_weight_policy_version_id_match_policy_version"),
        ),
        sa.PrimaryKeyConstraint("match_weight_id", name=op.f("pk_match_weight")),
        sa.UniqueConstraint(
            "policy_version_id", "score_component", name="uq_match_weight_component"
        ),
        schema="matching",
    )

    op.create_table(
        "recommendable",
        sa.Column("recommendable_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("object_type", sa.String(length=20), nullable=False),
        sa.Column("booth_id", sa.UUID(), nullable=True),
        sa.Column("event_product_id", sa.UUID(), nullable=True),
        sa.Column("participation_id", sa.UUID(), nullable=True),
        sa.Column("program_id", sa.UUID(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "object_type IN ('BOOTH', 'EVENT_PRODUCT', 'EXHIBITOR', 'PROGRAM')",
            name=op.f("ck_recommendable_object_type_allowed"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(booth_id, event_product_id, participation_id, program_id)"
            " = 1",
            name=op.f("ck_recommendable_exactly_one_target"),
        ),
        sa.ForeignKeyConstraint(
            ["booth_id"],
            ["exhibition.booth.booth_id"],
            name=op.f("fk_recommendable_booth_id_booth"),
        ),
        sa.ForeignKeyConstraint(
            ["event_product_id"],
            ["exhibition.event_product.event_product_id"],
            name=op.f("fk_recommendable_event_product_id_event_product"),
        ),
        sa.ForeignKeyConstraint(
            ["participation_id"],
            ["exhibition.exhibitor_participation.participation_id"],
            name=op.f(
                "fk_recommendable_participation_id_exhibitor_participation"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["program_id"],
            ["exhibition.program.program_id"],
            name=op.f("fk_recommendable_program_id_program"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_recommendable_event_boundary",
        ),
        sa.PrimaryKeyConstraint("recommendable_id", name=op.f("pk_recommendable")),
        schema="exhibition",
    )
    op.create_index(
        "idx_recommendable_event_type",
        "recommendable",
        ["event_id", "object_type", "active"],
        unique=False,
        schema="exhibition",
    )
    op.create_index(
        "uq_recommendable_booth",
        "recommendable",
        ["booth_id"],
        unique=True,
        schema="exhibition",
        postgresql_where=sa.text("booth_id IS NOT NULL"),
    )
    op.create_index(
        "uq_recommendable_event_product",
        "recommendable",
        ["event_product_id"],
        unique=True,
        schema="exhibition",
        postgresql_where=sa.text("event_product_id IS NOT NULL"),
    )
    op.create_index(
        "uq_recommendable_participation",
        "recommendable",
        ["participation_id"],
        unique=True,
        schema="exhibition",
        postgresql_where=sa.text("participation_id IS NOT NULL"),
    )
    op.create_index(
        "uq_recommendable_program",
        "recommendable",
        ["program_id"],
        unique=True,
        schema="exhibition",
        postgresql_where=sa.text("program_id IS NOT NULL"),
    )

    op.create_table(
        "recommendation_session",
        sa.Column("recommendation_session_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("profile_version_id", sa.UUID(), nullable=False),
        sa.Column("visit_session_id", sa.UUID(), nullable=True),
        sa.Column("recommendation_type", sa.String(length=20), nullable=False),
        sa.Column("policy_version_id", sa.UUID(), nullable=False),
        sa.Column("ranking_model_version_id", sa.UUID(), nullable=True),
        sa.Column("explanation_model_version_id", sa.UUID(), nullable=True),
        sa.Column("taxonomy_version_id", sa.UUID(), nullable=True),
        sa.Column(
            "context_snapshot", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("consent_snapshot_id", sa.UUID(), nullable=True),
        sa.Column("candidate_count", sa.Integer(), nullable=False),
        sa.Column("filtered_count", sa.Integer(), nullable=False),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("fallback_strategy", sa.String(length=30), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.CheckConstraint(
            "fallback_strategy IS NULL OR fallback_strategy IN "
            "('NONE', 'TEMPLATE', 'CATEGORY_BROWSE', 'POPULARITY_FALLBACK')",
            name=op.f("ck_recommendation_session_fallback_strategy_allowed"),
        ),
        sa.CheckConstraint(
            "recommendation_type IN "
            "('BOOTH', 'PRODUCT', 'EXHIBITOR', 'PROGRAM', 'MIXED')",
            name=op.f("ck_recommendation_session_recommendation_type_allowed"),
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'EXPIRED', 'INVALIDATED')",
            name=op.f("ck_recommendation_session_status_allowed"),
        ),
        sa.CheckConstraint(
            "candidate_count >= 0 AND filtered_count >= 0 AND result_count >= 0",
            name=op.f("ck_recommendation_session_counts_nonneg"),
        ),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["matching.match_policy_version.policy_version_id"],
            name=op.f(
                "fk_recommendation_session_policy_version_id_match_policy_version"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profile.user_profile.profile_id"],
            name=op.f("fk_recommendation_session_profile_id_user_profile"),
        ),
        sa.ForeignKeyConstraint(
            ["profile_version_id"],
            ["profile.profile_version.profile_version_id"],
            name=op.f(
                "fk_recommendation_session_profile_version_id_profile_version"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id"],
            ["ontology.taxonomy_version.taxonomy_version_id"],
            name=op.f(
                "fk_recommendation_session_taxonomy_version_id_taxonomy_version"
            ),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_recommendation_session_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["visit_session_id"],
            ["profile.visit_session.visit_session_id"],
            name=op.f(
                "fk_recommendation_session_visit_session_id_visit_session"
            ),
        ),
        sa.PrimaryKeyConstraint(
            "recommendation_session_id", name=op.f("pk_recommendation_session")
        ),
        schema="matching",
    )
    op.create_index(
        "idx_recommendation_session_profile",
        "recommendation_session",
        ["profile_id", "generated_at"],
        unique=False,
        schema="matching",
    )

    op.create_table(
        "filter_result",
        sa.Column("filter_result_id", sa.UUID(), nullable=False),
        sa.Column("recommendation_session_id", sa.UUID(), nullable=False),
        sa.Column("recommendable_id", sa.UUID(), nullable=False),
        sa.Column("rule_code", sa.String(length=100), nullable=False),
        sa.Column("policy_version_id", sa.UUID(), nullable=False),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("reason_code", sa.String(length=100), nullable=True),
        sa.Column(
            "user_value_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "candidate_value_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "details_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "result IN ('PASS', 'FAIL', 'UNKNOWN', 'CONDITIONAL_PASS', "
            "'MANUAL_REVIEW', 'TEMPORARY_BLOCK', 'POLICY_BLOCK', 'USER_EXCLUDED')",
            name=op.f("ck_filter_result_result_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["policy_version_id"],
            ["matching.match_policy_version.policy_version_id"],
            name=op.f("fk_filter_result_policy_version_id_match_policy_version"),
        ),
        sa.ForeignKeyConstraint(
            ["recommendable_id"],
            ["exhibition.recommendable.recommendable_id"],
            name=op.f("fk_filter_result_recommendable_id_recommendable"),
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_session_id"],
            ["matching.recommendation_session.recommendation_session_id"],
            name=op.f(
                "fk_filter_result_recommendation_session_id_recommendation_session"
            ),
        ),
        sa.PrimaryKeyConstraint("filter_result_id", name=op.f("pk_filter_result")),
        schema="matching",
    )
    op.create_index(
        "idx_filter_result_session_object",
        "filter_result",
        ["recommendation_session_id", "recommendable_id"],
        unique=False,
        schema="matching",
    )

    op.create_table(
        "match_result",
        sa.Column("match_result_id", sa.UUID(), nullable=False),
        sa.Column("recommendation_session_id", sa.UUID(), nullable=False),
        sa.Column("recommendable_id", sa.UUID(), nullable=False),
        sa.Column("raw_score", sa.Numeric(precision=8, scale=5), nullable=False),
        sa.Column("normalized_score", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("preference_score", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column("goal_score", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column("trade_score", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column("context_score", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column("behavior_score", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column(
            "diversity_adjustment", sa.Numeric(precision=8, scale=5), nullable=True
        ),
        sa.Column("trust_score", sa.Numeric(precision=8, scale=5), nullable=True),
        sa.Column("recommended_action", sa.String(length=30), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "recommended_action IS NULL OR recommended_action IN "
            "('VISIT_NOW', 'SAVE_FOR_LATER', 'REQUEST_MEETING', 'ADD_TO_ROUTE', "
            "'COMPARE_PRODUCTS', 'JOIN_PROGRAM', 'REFINE_PROFILE')",
            name=op.f("ck_match_result_recommended_action_allowed"),
        ),
        sa.CheckConstraint("rank >= 1", name=op.f("ck_match_result_rank_positive")),
        sa.ForeignKeyConstraint(
            ["recommendable_id"],
            ["exhibition.recommendable.recommendable_id"],
            name=op.f("fk_match_result_recommendable_id_recommendable"),
        ),
        sa.ForeignKeyConstraint(
            ["recommendation_session_id"],
            ["matching.recommendation_session.recommendation_session_id"],
            name=op.f(
                "fk_match_result_recommendation_session_id_recommendation_session"
            ),
        ),
        sa.PrimaryKeyConstraint("match_result_id", name=op.f("pk_match_result")),
        sa.UniqueConstraint(
            "recommendation_session_id", "rank", name="uq_match_result_session_rank"
        ),
        sa.UniqueConstraint(
            "recommendation_session_id",
            "recommendable_id",
            name="uq_match_result_session_recommendable",
        ),
        schema="matching",
    )
    op.create_index(
        "idx_match_session_rank",
        "match_result",
        ["recommendation_session_id", "rank"],
        unique=False,
        schema="matching",
    )
    op.create_index(
        "idx_match_target",
        "match_result",
        ["recommendable_id", sa.literal_column("created_at DESC")],
        unique=False,
        schema="matching",
    )

    op.create_table(
        "match_reason",
        sa.Column("match_reason_id", sa.UUID(), nullable=False),
        sa.Column("match_result_id", sa.UUID(), nullable=False),
        sa.Column("reason_code", sa.String(length=50), nullable=False),
        sa.Column("reason_text", sa.String(length=500), nullable=False),
        sa.Column(
            "evidence_refs", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "contribution_score", sa.Numeric(precision=8, scale=5), nullable=True
        ),
        sa.Column("display_order", sa.SmallInteger(), nullable=False),
        sa.Column("generated_by", sa.String(length=20), nullable=False),
        sa.Column("ai_run_id", sa.UUID(), nullable=True),
        sa.Column("validation_status", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "generated_by IN ('TEMPLATE', 'LLM')",
            name=op.f("ck_match_reason_generated_by_allowed"),
        ),
        sa.CheckConstraint(
            "validation_status IN ('VALID', 'REJECTED')",
            name=op.f("ck_match_reason_validation_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["match_result_id"],
            ["matching.match_result.match_result_id"],
            name=op.f("fk_match_reason_match_result_id_match_result"),
        ),
        sa.PrimaryKeyConstraint("match_reason_id", name=op.f("pk_match_reason")),
        schema="matching",
    )
    op.create_index(
        "idx_match_reason_result_order",
        "match_reason",
        ["match_result_id", "display_order"],
        unique=False,
        schema="matching",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_match_reason_result_order", table_name="match_reason", schema="matching"
    )
    op.drop_table("match_reason", schema="matching")
    op.drop_index("idx_match_target", table_name="match_result", schema="matching")
    op.drop_index(
        "idx_match_session_rank", table_name="match_result", schema="matching"
    )
    op.drop_table("match_result", schema="matching")
    op.drop_index(
        "idx_filter_result_session_object",
        table_name="filter_result",
        schema="matching",
    )
    op.drop_table("filter_result", schema="matching")
    op.drop_index(
        "idx_recommendation_session_profile",
        table_name="recommendation_session",
        schema="matching",
    )
    op.drop_table("recommendation_session", schema="matching")
    op.drop_index(
        "uq_recommendable_program",
        table_name="recommendable",
        schema="exhibition",
        postgresql_where=sa.text("program_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_recommendable_participation",
        table_name="recommendable",
        schema="exhibition",
        postgresql_where=sa.text("participation_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_recommendable_event_product",
        table_name="recommendable",
        schema="exhibition",
        postgresql_where=sa.text("event_product_id IS NOT NULL"),
    )
    op.drop_index(
        "uq_recommendable_booth",
        table_name="recommendable",
        schema="exhibition",
        postgresql_where=sa.text("booth_id IS NOT NULL"),
    )
    op.drop_index(
        "idx_recommendable_event_type", table_name="recommendable", schema="exhibition"
    )
    op.drop_table("recommendable", schema="exhibition")
    op.drop_table("match_weight", schema="matching")
    op.drop_table("filter_rule", schema="matching")
    op.drop_index(
        "uq_match_policy_version_single_active",
        table_name="match_policy_version",
        schema="matching",
        postgresql_where=sa.text("status = 'ACTIVE'"),
    )
    op.drop_table("match_policy_version", schema="matching")
