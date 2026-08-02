"""publish stage-15 slate policy, result lineage, and visible impressions

Revision ID: 0011_slate_policy
Revises: 0010_context_rerank
Create Date: 2026-08-01
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011_slate_policy"
down_revision: str | None = "0010_context_rerank"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMESPACE = uuid.UUID("6f6a8f6e-2f61-4e2a-9c8a-1a7c9e6d8b21")
_VERSION = "slate-policy-v1.0"
_PUBLISHED_AT = datetime(2026, 8, 1, tzinfo=UTC)
SLATE_POLICY_CONFIG = {
    "relevance_floors": {"core": 0.70, "conditional": 0.55, "exploration": 0.45},
    "mmr_lambda": {"general": 0.80, "buyer": 0.85, "exploration": 0.65, "new": 0.70},
    "exhibitor_caps": {
        "general_top5": 1,
        "general_top10": 2,
        "general_top20": 3,
        "buyer": 1,
    },
    "category_caps": {"top5": 3, "top10": 5},
    "region_cap_top10": 4,
    "max_exploration_top10": 1,
    "repeat_penalty": {"two": 0.03, "three": 0.07, "five_exclude": True},
    "repeat_scope": {
        "booth": "VISIT_SESSION",
        "product": "P1D",
        "program": "EVENT_LIFETIME",
        "exhibitor": "EVENT_LIFETIME",
    },
    "user_preferences": {
        "balanced": "DEFAULT",
        "accuracy_first": "MMR_LAMBDA_PLUS_0.10",
        "diverse": "MMR_LAMBDA_MINUS_0.15",
        "nearby_first": {"relevance": 0.80, "proximity": 0.20},
        "new_discovery": "NEW_MMR_LAMBDA",
    },
    "adjustment_limits": {
        "diversity": [-0.05, 0.05],
        "fairness": [-0.05, 0.05],
        "exploration": [0.0, 0.04],
        "repeat": [0.0, 0.10],
        "concentration": [0.0, 0.05],
    },
    "relevance_loss_limits": {"top5": 0.03, "top10": 0.05},
    "sponsored_content_separated": True,
    "company_size_scoring": False,
    "missing_value_strategy": "DO_NOT_INFER",
}


def _stable_id(kind: str, value: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{kind}:{value}")


def _json_literal(value: dict) -> sa.sql.elements.BindParameter:
    return op.inline_literal(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        type_=sa.String(),
    )


def _config_hash(value: dict) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _extend_policy_type() -> None:
    op.drop_constraint(
        "policy_type_allowed", "match_policy_version", schema="matching", type_="check"
    )
    op.create_check_constraint(
        "policy_type_allowed",
        "match_policy_version",
        "policy_type IN ('HARD_FILTER', 'CONSUMER_SCORE', 'BUYER_SCORE', "
        "'EXHIBITOR_SCORE', 'RECIPROCAL_SCORE', 'CONTEXT_RERANK', 'SLATE_POLICY')",
        schema="matching",
    )


def _create_slate_tables() -> None:
    op.create_table(
        "slate_result",
        sa.Column("slate_result_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "recommendation_session_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column(
            "slate_policy_version_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("slate_size", sa.Integer(), nullable=False),
        sa.Column("diversity_score", sa.Numeric(), nullable=True),
        sa.Column("coverage_score", sa.Numeric(), nullable=True),
        sa.Column("exposure_fairness_score", sa.Numeric(), nullable=True),
        sa.Column("relevance_loss", sa.Numeric(), nullable=True),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("score_fingerprint", sa.String(64), nullable=False),
        sa.Column("metrics_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendation_session_id"],
            [
                "matching.recommendation_session.tenant_id",
                "matching.recommendation_session.event_id",
                "matching.recommendation_session.recommendation_session_id",
            ],
            name="fk_slate_result_session_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["slate_policy_version_id"],
            ["matching.match_policy_version.match_policy_version_id"],
            name="fk_slate_result_slate_policy_version_id_match_policy_version",
        ),
        sa.UniqueConstraint(
            "recommendation_session_id", name="uq_slate_result_session"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "slate_result_id",
            name="uq_slate_result_boundary_id",
        ),
        sa.CheckConstraint(
            "slate_size >= 0", name=op.f("ck_slate_result_slate_size_nonneg")
        ),
        sa.CheckConstraint(
            "diversity_score IS NULL OR (diversity_score >= 0 AND diversity_score <= 1)",
            name=op.f("ck_slate_result_diversity_score_range"),
        ),
        sa.CheckConstraint(
            "coverage_score IS NULL OR (coverage_score >= 0 AND coverage_score <= 1)",
            name=op.f("ck_slate_result_coverage_score_range"),
        ),
        sa.CheckConstraint(
            "exposure_fairness_score IS NULL OR "
            "(exposure_fairness_score >= 0 AND exposure_fairness_score <= 1)",
            name=op.f("ck_slate_result_exposure_fairness_score_range"),
        ),
        sa.CheckConstraint(
            "relevance_loss IS NULL OR relevance_loss >= 0",
            name=op.f("ck_slate_result_relevance_loss_nonneg"),
        ),
        schema="matching",
    )
    op.create_index(
        "ix_slate_result_event_created",
        "slate_result",
        ["tenant_id", "event_id", "created_at"],
        schema="matching",
    )

    op.create_table(
        "slate_item",
        sa.Column("slate_item_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slate_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendable_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exhibitor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("object_type", sa.String(20), nullable=False),
        sa.Column("base_rank", sa.Integer(), nullable=False),
        sa.Column("final_rank", sa.Integer(), nullable=False),
        sa.Column("base_score", sa.Numeric(), nullable=False),
        sa.Column("slate_score", sa.Numeric(), nullable=False),
        sa.Column("mmr_score", sa.Numeric(), nullable=True),
        sa.Column("diversity_adjustment", sa.Numeric(), nullable=False),
        sa.Column("fairness_adjustment", sa.Numeric(), nullable=False),
        sa.Column("exploration_adjustment", sa.Numeric(), nullable=False),
        sa.Column("repeat_penalty", sa.Numeric(), nullable=False),
        sa.Column("concentration_penalty", sa.Numeric(), nullable=False),
        sa.Column("slot_type", sa.String(20), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False),
        sa.Column("related_object_ids", postgresql.JSONB(), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("score_fingerprint", sa.String(64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "slate_result_id"],
            [
                "matching.slate_result.tenant_id",
                "matching.slate_result.event_id",
                "matching.slate_result.slate_result_id",
            ],
            name="fk_slate_item_result_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["match_result_id"],
            ["matching.match_result.match_result_id"],
            name="fk_slate_item_match_result_id_match_result",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                "exhibition.recommendable.tenant_id",
                "exhibition.recommendable.event_id",
                "exhibition.recommendable.recommendable_id",
            ],
            name="fk_slate_item_target_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            ["exhibition.exhibitor.tenant_id", "exhibition.exhibitor.exhibitor_id"],
            name="fk_slate_item_exhibitor_boundary",
        ),
        sa.UniqueConstraint("slate_result_id", "final_rank", name="uq_slate_item_rank"),
        sa.UniqueConstraint("match_result_id", name="uq_slate_item_match_result"),
        sa.UniqueConstraint(
            "tenant_id", "event_id", "slate_item_id", name="uq_slate_item_boundary_id"
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "event_id",
            "slate_result_id",
            "slate_item_id",
            name="uq_slate_item_result_boundary_id",
        ),
        sa.CheckConstraint(
            "base_rank > 0 AND final_rank > 0",
            name=op.f("ck_slate_item_ranks_positive"),
        ),
        sa.CheckConstraint(
            "base_score >= 0 AND base_score <= 1 AND slate_score >= 0 AND slate_score <= 1",
            name=op.f("ck_slate_item_scores_range"),
        ),
        sa.CheckConstraint(
            "diversity_adjustment >= -0.05 AND diversity_adjustment <= 0.05",
            name=op.f("ck_slate_item_diversity_adjustment_range"),
        ),
        sa.CheckConstraint(
            "fairness_adjustment >= -0.05 AND fairness_adjustment <= 0.05",
            name=op.f("ck_slate_item_fairness_adjustment_range"),
        ),
        sa.CheckConstraint(
            "exploration_adjustment >= 0 AND exploration_adjustment <= 0.04",
            name=op.f("ck_slate_item_exploration_adjustment_range"),
        ),
        sa.CheckConstraint(
            "repeat_penalty >= 0 AND repeat_penalty <= 0.10",
            name=op.f("ck_slate_item_repeat_penalty_range"),
        ),
        sa.CheckConstraint(
            "concentration_penalty >= 0 AND concentration_penalty <= 0.05",
            name=op.f("ck_slate_item_concentration_penalty_range"),
        ),
        sa.CheckConstraint(
            "slot_type IN ('CORE', 'CONDITIONAL', 'DIVERSITY', 'EXPLORATION', 'NEW')",
            name=op.f("ck_slate_item_slot_type_allowed"),
        ),
        schema="matching",
    )
    op.create_index(
        "ix_slate_item_result_rank",
        "slate_item",
        ["slate_result_id", "final_rank"],
        schema="matching",
    )


def _create_impression_table() -> None:
    op.create_table(
        "recommendation_impression",
        sa.Column("impression_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column(
            "interaction_event_id", postgresql.UUID(as_uuid=True), nullable=False
        ),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("guest_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("visit_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("slate_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("slate_item_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendable_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exhibitor_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("object_type", sa.String(20), nullable=False),
        sa.Column("final_rank", sa.Integer(), nullable=False),
        sa.Column("slot_type", sa.String(20), nullable=False),
        sa.Column("content_type", sa.String(40), nullable=False),
        sa.Column("visible_duration_ms", sa.Integer(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_recommendation_impression_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["event_date", "interaction_event_id"],
            [
                "interaction.interaction_event.event_date",
                "interaction.interaction_event.interaction_event_id",
            ],
            name="fk_recommendation_impression_interaction_event",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "visit_session_id"],
            [
                "profile.visit_session.tenant_id",
                "profile.visit_session.event_id",
                "profile.visit_session.visit_session_id",
            ],
            name="fk_recommendation_impression_visit_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "slate_result_id"],
            [
                "matching.slate_result.tenant_id",
                "matching.slate_result.event_id",
                "matching.slate_result.slate_result_id",
            ],
            name="fk_recommendation_impression_slate_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "slate_result_id", "slate_item_id"],
            [
                "matching.slate_item.tenant_id",
                "matching.slate_item.event_id",
                "matching.slate_item.slate_result_id",
                "matching.slate_item.slate_item_id",
            ],
            name="fk_recommendation_impression_item_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                "exhibition.recommendable.tenant_id",
                "exhibition.recommendable.event_id",
                "exhibition.recommendable.recommendable_id",
            ],
            name="fk_recommendation_impression_target_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            ["exhibition.exhibitor.tenant_id", "exhibition.exhibitor.exhibitor_id"],
            name="fk_recommendation_impression_exhibitor_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["profile.user_account.user_id"],
            name="fk_recommendation_impression_user_id_user_account",
        ),
        sa.ForeignKeyConstraint(
            ["guest_session_id"],
            ["profile.guest_session.guest_session_id"],
            name="fk_recommendation_impression_guest_session_id_guest_session",
        ),
        sa.CheckConstraint(
            "num_nonnulls(user_id, guest_session_id) <= 1",
            name=op.f("ck_recommendation_impression_subject_at_most_one"),
        ),
        sa.CheckConstraint(
            "final_rank > 0",
            name=op.f("ck_recommendation_impression_final_rank_positive"),
        ),
        sa.CheckConstraint(
            "visible_duration_ms >= 0",
            name=op.f("ck_recommendation_impression_visible_duration_ms_nonneg"),
        ),
        sa.CheckConstraint(
            "content_type IN ('PERSONALIZED_RECOMMENDATION', 'SPONSORED_CONTENT', 'OPERATOR_NOTICE', 'EDITORIAL_CONTENT')",
            name=op.f("ck_recommendation_impression_content_type_allowed"),
        ),
        sa.CheckConstraint(
            "slot_type IN ('CORE', 'CONDITIONAL', 'DIVERSITY', 'EXPLORATION', 'NEW', 'SPONSORED', 'NOTICE', 'EDITORIAL')",
            name=op.f("ck_recommendation_impression_slot_type_allowed"),
        ),
        sa.UniqueConstraint(
            "event_date",
            "interaction_event_id",
            name="uq_recommendation_impression_interaction_event",
        ),
        schema="interaction",
    )
    op.create_index(
        "ix_recommendation_impression_subject_time",
        "recommendation_impression",
        ["visit_session_id", "occurred_at"],
        schema="interaction",
    )
    op.create_index(
        "ix_recommendation_impression_user_time",
        "recommendation_impression",
        ["tenant_id", "event_id", "user_id", "occurred_at"],
        schema="interaction",
    )
    op.create_index(
        "ix_recommendation_impression_guest_time",
        "recommendation_impression",
        ["tenant_id", "event_id", "guest_session_id", "occurred_at"],
        schema="interaction",
    )
    op.create_index(
        "ix_recommendation_impression_exhibitor_time",
        "recommendation_impression",
        ["tenant_id", "event_id", "exhibitor_id", "occurred_at"],
        schema="interaction",
    )


def _seed_policy() -> None:
    policy_id = _stable_id("policy", _VERSION)
    table = sa.table(
        "match_policy_version",
        sa.column("match_policy_version_id", postgresql.UUID(as_uuid=True)),
        sa.column("policy_type", sa.String()),
        sa.column("audience", sa.String()),
        sa.column("version", sa.String()),
        sa.column("formula_name", sa.String()),
        sa.column("config_json", postgresql.JSONB()),
        sa.column("config_hash", sa.String()),
        sa.column("status", sa.String()),
        sa.column("published_at", sa.DateTime(timezone=True)),
        schema="matching",
    )
    op.bulk_insert(
        table,
        [
            {
                "match_policy_version_id": policy_id,
                "policy_type": "SLATE_POLICY",
                "audience": "ALL",
                "version": _VERSION,
                "formula_name": "mmr-constrained-opportunity-slate",
                "config_json": _json_literal(SLATE_POLICY_CONFIG),
                "config_hash": _config_hash(SLATE_POLICY_CONFIG),
                "status": "DRAFT",
                "published_at": None,
            }
        ],
        multiinsert=False,
    )
    op.execute(
        "UPDATE matching.match_policy_version SET status = 'PUBLISHED', "
        f"published_at = TIMESTAMPTZ '{_PUBLISHED_AT.isoformat()}' "
        f"WHERE match_policy_version_id = '{policy_id}'::uuid"
    )


def upgrade() -> None:
    _extend_policy_type()
    _create_slate_tables()
    _create_impression_table()
    _seed_policy()
    for table_name in ("slate_result", "slate_item"):
        op.execute(
            f"CREATE TRIGGER trg_{table_name}_append_only "
            f"BEFORE UPDATE OR DELETE ON matching.{table_name} "
            "FOR EACH ROW EXECUTE FUNCTION matching.reject_matching_result_mutation()"
        )
    op.execute(
        "CREATE TRIGGER trg_recommendation_impression_append_only "
        "BEFORE UPDATE OR DELETE ON interaction.recommendation_impression "
        "FOR EACH ROW EXECUTE FUNCTION interaction.reject_interaction_event_mutation()"
    )


def downgrade() -> None:
    op.execute(
        "DROP TRIGGER IF EXISTS trg_recommendation_impression_append_only ON interaction.recommendation_impression"
    )
    op.drop_table("recommendation_impression", schema="interaction")
    for table_name in ("slate_item", "slate_result"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_append_only ON matching.{table_name}"
        )
        op.drop_table(table_name, schema="matching")

    policy_id = _stable_id("policy", _VERSION)
    op.execute(
        "ALTER TABLE matching.match_policy_version DISABLE TRIGGER trg_match_policy_version_immutable"
    )
    op.execute(
        f"DELETE FROM matching.match_policy_version WHERE match_policy_version_id = '{policy_id}'::uuid"
    )
    op.execute(
        "ALTER TABLE matching.match_policy_version ENABLE TRIGGER trg_match_policy_version_immutable"
    )
    op.drop_constraint(
        "policy_type_allowed", "match_policy_version", schema="matching", type_="check"
    )
    op.create_check_constraint(
        "policy_type_allowed",
        "match_policy_version",
        "policy_type IN ('HARD_FILTER', 'CONSUMER_SCORE', 'BUYER_SCORE', "
        "'EXHIBITOR_SCORE', 'RECIPROCAL_SCORE', 'CONTEXT_RERANK')",
        schema="matching",
    )
