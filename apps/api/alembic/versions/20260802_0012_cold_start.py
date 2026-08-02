"""publish stage-16 cold-start policy and persistence contract

Revision ID: 0012_cold_start
Revises: 0011_slate_policy
Create Date: 2026-08-02
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

revision: str = "0012_cold_start"
down_revision: str | None = "0011_slate_policy"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMESPACE = uuid.UUID("6f6a8f6e-2f61-4e2a-9c8a-1a7c9e6d8b21")
_VERSION = "cold-start-policy-v1.0"
_PUBLISHED_AT = datetime(2026, 8, 2, tzinfo=UTC)
COLD_START_POLICY_CONFIG = {
    "states": ["COLD", "WARMING", "STABLE", "RESET"],
    "visitor_stable": {"profile_completeness": 0.60, "valid_behavior_count": 5, "average_confidence": 0.70},
    "buyer_stable": {"profile_completeness": 0.70, "verified": True, "valid_consultation_count": 2},
    "exploration_ratio": {"COLD": 0.25, "WARMING": 0.15, "STABLE": 0.075, "BUYER_MAX": 0.10},
    "new_exhibitor_quality_weights": {
        "profile_completeness": 0.25,
        "product_data_quality": 0.20,
        "trade_readiness": 0.20,
        "verification": 0.15,
        "consultation_readiness": 0.10,
        "runtime_availability": 0.10,
    },
    "new_exhibitor": {"minimum_completeness": 0.70, "minimum_relevance": 0.45, "max_top10": 1},
    "confidence_caps": {"minimum_three_answers": 0.60, "five_answers": 0.72, "three_behaviors": 0.78, "feedback": 0.85},
    "bayesian_prior": {"minimum_count": 1.0},
    "protected_attribute_inference": False,
    "popularity_role": "LAST_RESORT_SUPPLEMENT",
    "bandit_enabled": False,
}


def _stable_id(kind: str, value: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{kind}:{value}")


def _config_hash(value: dict) -> str:
    payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _extend_policy_type() -> None:
    op.drop_constraint("policy_type_allowed", "match_policy_version", schema="matching", type_="check")
    op.create_check_constraint(
        "policy_type_allowed",
        "match_policy_version",
        "policy_type IN ('HARD_FILTER', 'CONSUMER_SCORE', 'BUYER_SCORE', 'EXHIBITOR_SCORE', "
        "'RECIPROCAL_SCORE', 'CONTEXT_RERANK', 'SLATE_POLICY', 'COLD_START')",
        schema="matching",
    )


def _seed_policy() -> None:
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
    policy_id = _stable_id("policy", _VERSION)
    op.bulk_insert(table, [{
        "match_policy_version_id": policy_id,
        "policy_type": "COLD_START",
        "audience": "ALL",
        "version": _VERSION,
        "formula_name": "missing-aware-fixed-exploration",
        "config_json": op.inline_literal(json.dumps(COLD_START_POLICY_CONFIG, ensure_ascii=False, separators=(",", ":"), sort_keys=True), type_=sa.String()),
        "config_hash": _config_hash(COLD_START_POLICY_CONFIG),
        "status": "DRAFT",
        "published_at": None,
    }], multiinsert=False)
    op.execute(
        "UPDATE matching.match_policy_version SET status = 'PUBLISHED', "
        f"published_at = TIMESTAMPTZ '{_PUBLISHED_AT.isoformat()}' "
        f"WHERE match_policy_version_id = '{policy_id}'::uuid"
    )


def _create_tables() -> None:
    op.create_table(
        "cold_start_status",
        sa.Column("cold_start_status_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_type", sa.String(20), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("cold_start_type", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("previous_status", sa.String(20), nullable=True),
        sa.Column("stability_score", sa.Numeric(7, 6), nullable=False),
        sa.Column("signal_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("profile_completeness", sa.Numeric(5, 2), nullable=False),
        sa.Column("match_policy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("details_json", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("transitioned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["tenant_id", "event_id"], ["exhibition.event.tenant_id", "exhibition.event.event_id"], name="fk_cold_start_status_event_boundary"),
        sa.ForeignKeyConstraint(["match_policy_version_id"], ["matching.match_policy_version.match_policy_version_id"]),
        sa.CheckConstraint("object_type IN ('USER', 'BUYER', 'EXHIBITOR', 'PRODUCT', 'PROGRAM')", name=op.f("ck_cold_start_status_object_type_allowed")),
        sa.CheckConstraint("status IN ('COLD', 'WARMING', 'STABLE', 'RESET')", name=op.f("ck_cold_start_status_status_allowed")),
        sa.CheckConstraint("stability_score >= 0 AND stability_score <= 1", name=op.f("ck_cold_start_status_stability_score_range")),
        sa.CheckConstraint("profile_completeness >= 0 AND profile_completeness <= 100", name=op.f("ck_cold_start_status_profile_completeness_range")),
        schema="matching",
    )
    op.create_index("ix_cold_start_status_current", "cold_start_status", ["tenant_id", "event_id", "object_type", "object_id", "evaluated_at"], schema="matching")

    op.create_table(
        "question_definition",
        sa.Column("question_id", sa.String(60), primary_key=True),
        sa.Column("user_type", sa.String(30), nullable=False),
        sa.Column("attribute_code", sa.String(100), nullable=False),
        sa.Column("question_text", sa.String(500), nullable=False),
        sa.Column("option_json", postgresql.JSONB(), nullable=False),
        sa.Column("required", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("base_priority", sa.Integer(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("definition_version", sa.String(30), nullable=False),
        sa.CheckConstraint("user_type IN ('GENERAL_VISITOR', 'BUYER')", name=op.f("ck_question_definition_user_type_allowed")),
        sa.CheckConstraint("base_priority > 0", name=op.f("ck_question_definition_base_priority_positive")),
        schema="matching",
    )
    op.create_table(
        "question_response",
        sa.Column("response_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("question_id", sa.String(60), nullable=False),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("answer_json", postgresql.JSONB(), nullable=False),
        sa.Column("response_source", sa.String(30), nullable=False),
        sa.Column("information_gain", sa.Numeric(7, 6), nullable=True),
        sa.Column("responded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.user_profile.profile_id"]),
        sa.ForeignKeyConstraint(["question_id"], ["matching.question_definition.question_id"]),
        sa.CheckConstraint("response_source IN ('MINIMUM_PROFILE', 'NEXT_BEST_QUESTION', 'PAIRWISE')", name=op.f("ck_question_response_response_source_allowed")),
        sa.CheckConstraint("information_gain IS NULL OR (information_gain >= 0 AND information_gain <= 1)", name=op.f("ck_question_response_information_gain_range")),
        schema="matching",
    )
    op.create_index("ix_question_response_profile_time", "question_response", ["profile_id", "responded_at"], schema="matching")

    op.create_table(
        "cold_start_prior",
        sa.Column("prior_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("group_type", sa.String(40), nullable=False),
        sa.Column("group_key", sa.String(200), nullable=False),
        sa.Column("metric_code", sa.String(60), nullable=False),
        sa.Column("prior_mean", sa.Numeric(9, 8), nullable=False),
        sa.Column("prior_count", sa.Numeric(12, 3), nullable=False),
        sa.Column("model_version", sa.String(40), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("tenant_id", "event_id", "group_type", "group_key", "metric_code", "model_version", name="uq_cold_start_prior_versioned_group"),
        sa.CheckConstraint("prior_mean >= 0 AND prior_mean <= 1", name=op.f("ck_cold_start_prior_prior_mean_range")),
        sa.CheckConstraint("prior_count >= 1", name=op.f("ck_cold_start_prior_prior_count_positive")),
        sa.CheckConstraint("valid_until IS NULL OR valid_from <= valid_until", name=op.f("ck_cold_start_prior_valid_period_order")),
        schema="matching",
    )
    op.create_table(
        "exploration_result",
        sa.Column("exploration_result_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("object_type", sa.String(20), nullable=False),
        sa.Column("object_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendation_session_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("slot_type", sa.String(30), nullable=False),
        sa.Column("prior_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("prior_score", sa.Numeric(9, 8), nullable=False),
        sa.Column("observed_event", sa.String(60), nullable=True),
        sa.Column("reward_value", sa.Numeric(7, 6), nullable=False, server_default="0"),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_profile_id"], ["profile.user_profile.profile_id"]),
        sa.ForeignKeyConstraint(["recommendation_session_id"], ["matching.recommendation_session.recommendation_session_id"]),
        sa.ForeignKeyConstraint(["prior_id"], ["matching.cold_start_prior.prior_id"]),
        sa.CheckConstraint("slot_type IN ('NEW', 'PREFERENCE_LEARNING')", name=op.f("ck_exploration_result_slot_type_allowed")),
        sa.CheckConstraint("prior_score >= 0 AND prior_score <= 1", name=op.f("ck_exploration_result_prior_score_range")),
        sa.CheckConstraint("reward_value >= -1 AND reward_value <= 1", name=op.f("ck_exploration_result_reward_value_range")),
        schema="matching",
    )
    op.create_index("ix_exploration_result_object_time", "exploration_result", ["object_type", "object_id", "occurred_at"], schema="matching")


def upgrade() -> None:
    _extend_policy_type()
    _seed_policy()
    _create_tables()
    op.add_column("recommendation_session", sa.Column("cold_start_policy_version_id", postgresql.UUID(as_uuid=True), nullable=True), schema="matching")
    op.add_column("recommendation_session", sa.Column("cold_start_details", postgresql.JSONB(), nullable=True), schema="matching")
    op.create_foreign_key("fk_recommendation_session_cold_start_policy", "recommendation_session", "match_policy_version", ["cold_start_policy_version_id"], ["match_policy_version_id"], source_schema="matching", referent_schema="matching")
    op.add_column("match_result", sa.Column("cold_start_policy_version_id", postgresql.UUID(as_uuid=True), nullable=True), schema="matching")
    op.add_column("match_result", sa.Column("cold_start_details", postgresql.JSONB(), nullable=True), schema="matching")
    op.add_column("match_result", sa.Column("recommendation_confidence", sa.Numeric(7, 6), nullable=True), schema="matching")
    op.create_foreign_key("fk_match_result_cold_start_policy", "match_result", "match_policy_version", ["cold_start_policy_version_id"], ["match_policy_version_id"], source_schema="matching", referent_schema="matching")
    op.create_check_constraint("recommendation_confidence_range", "match_result", "recommendation_confidence IS NULL OR (recommendation_confidence >= 0 AND recommendation_confidence <= 1)", schema="matching")


def downgrade() -> None:
    op.drop_constraint("recommendation_confidence_range", "match_result", schema="matching", type_="check")
    op.drop_constraint("fk_match_result_cold_start_policy", "match_result", schema="matching", type_="foreignkey")
    for column in ("recommendation_confidence", "cold_start_details", "cold_start_policy_version_id"):
        op.drop_column("match_result", column, schema="matching")
    op.drop_constraint("fk_recommendation_session_cold_start_policy", "recommendation_session", schema="matching", type_="foreignkey")
    for column in ("cold_start_details", "cold_start_policy_version_id"):
        op.drop_column("recommendation_session", column, schema="matching")
    for table in ("exploration_result", "cold_start_prior", "question_response", "question_definition", "cold_start_status"):
        op.drop_table(table, schema="matching")
    op.execute("ALTER TABLE matching.match_policy_version DISABLE TRIGGER trg_match_policy_version_immutable")
    op.execute(f"DELETE FROM matching.match_policy_version WHERE match_policy_version_id = '{_stable_id('policy', _VERSION)}'::uuid")
    op.execute("ALTER TABLE matching.match_policy_version ENABLE TRIGGER trg_match_policy_version_immutable")
    op.drop_constraint("policy_type_allowed", "match_policy_version", schema="matching", type_="check")
    op.create_check_constraint("policy_type_allowed", "match_policy_version", "policy_type IN ('HARD_FILTER', 'CONSUMER_SCORE', 'BUYER_SCORE', 'EXHIBITOR_SCORE', 'RECIPROCAL_SCORE', 'CONTEXT_RERANK', 'SLATE_POLICY')", schema="matching")
