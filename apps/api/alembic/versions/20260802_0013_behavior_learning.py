"""publish stage-17 behavior-learning policy and evidence ledger

Revision ID: 0013_behavior_learning
Revises: 0012_cold_start
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

revision: str = "0013_behavior_learning"
down_revision: str | None = "0012_cold_start"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMESPACE = uuid.UUID("6f6a8f6e-2f61-4e2a-9c8a-1a7c9e6d8b21")
_VERSION = "behavior-learning-policy-v1.0"
_PUBLISHED_AT = datetime(2026, 8, 2, tzinfo=UTC)
VISITOR_SIGNALS = {
    "VIEW.IMPRESSION": 0.00, "VIEW.CLICK": 0.08, "VIEW.DETAIL": 0.12,
    "VIEW.LONG_READ": 0.18, "VIEW.COMPARE": 0.28, "INTENT.FAVORITE": 0.45,
    "INTENT.ROUTE_ADD": 0.55, "FIELD.CHECK_IN": 0.65, "FIELD.TASTING": 0.00,
    "FIELD.PURCHASE": 0.95, "FEEDBACK.RELEVANT": 1.00, "VIEW.DISMISS": -0.08,
    "FIELD.SKIP": -0.12, "FEEDBACK.IRRELEVANT": -0.90,
}
BUYER_SIGNALS = {
    "VIEW.DETAIL": 0.10, "B2B.COMPARE": 0.20, "B2B.TRADE_TERM_VIEW": 0.25,
    "INTENT.FAVORITE": 0.35, "B2B.MEETING_VIEW": 0.45, "B2B.MEETING_REQUEST": 0.65,
    "B2B.MEETING_ACCEPT": 0.75, "B2B.MEETING_COMPLETE": 0.85,
    "B2B.SAMPLE_REQUEST": 0.88, "B2B.QUOTE_REQUEST": 0.92,
    "B2B.QUALIFIED_LEAD": 1.00, "B2B.FOLLOW_UP": 1.00,
    "B2B.MEETING_CANCEL": -0.25, "B2B.MEETING_REJECT": -0.40,
    "B2B.CONDITION_MISMATCH": -0.80, "B2B.SPAM_CONFIRMED": -1.00,
}
PROPAGATION = {
    "GENERAL_VISITOR": {"PRODUCT": 1.00, "EXHIBITOR": 0.15, "CATEGORY": 0.45, "TASTE": 0.35, "INGREDIENT": 0.20, "PRICE": 0.18, "USAGE": 0.30, "REGION": 0.10},
    "BUYER": {"EXHIBITOR": 1.00, "PRODUCT": 0.60, "CHANNEL": 0.35, "TRADE_TYPE": 0.40, "MOQ": 0.30, "REGION": 0.25, "COOPERATION": 0.35, "CAPACITY": 0.20},
}
LEARNING_POLICY_CONFIG = {
    "visitor_signals": VISITOR_SIGNALS,
    "buyer_signals": BUYER_SIGNALS,
    "propagation": PROPAGATION,
    "single_update_cap": {"GENERAL_VISITOR": 0.10, "BUYER": 0.05},
    "daily_automatic_cap": 0.20,
    "personal_weight_caps": {"single": 0.02, "session": 0.08, "long_term": 0.15},
    "tasting_without_feedback": "NEUTRAL_EXPERIENCE",
    "non_response": "EXPOSURE_POLICY_ONLY",
    "explicit_input_precedence": True,
    "position_propensity_floor": 0.20,
    "consent_required": True,
    "global_policy_online_update": False,
}


def _stable_id(kind: str, value: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{kind}:{value}")


def _hash(value: dict) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()).hexdigest()


def _seed_policy() -> None:
    op.drop_constraint("policy_type_allowed", "match_policy_version", schema="matching", type_="check")
    op.create_check_constraint(
        "policy_type_allowed", "match_policy_version",
        "policy_type IN ('HARD_FILTER', 'CONSUMER_SCORE', 'BUYER_SCORE', 'EXHIBITOR_SCORE', "
        "'RECIPROCAL_SCORE', 'CONTEXT_RERANK', 'SLATE_POLICY', 'COLD_START', 'BEHAVIOR_LEARNING')",
        schema="matching",
    )
    table = sa.table(
        "match_policy_version",
        sa.column("match_policy_version_id", postgresql.UUID(as_uuid=True)),
        sa.column("policy_type", sa.String()), sa.column("audience", sa.String()),
        sa.column("version", sa.String()), sa.column("formula_name", sa.String()),
        sa.column("config_json", postgresql.JSONB()), sa.column("config_hash", sa.String()),
        sa.column("status", sa.String()), sa.column("published_at", sa.DateTime(timezone=True)),
        schema="matching",
    )
    policy_id = _stable_id("policy", _VERSION)
    op.bulk_insert(table, [{
        "match_policy_version_id": policy_id, "policy_type": "BEHAVIOR_LEARNING",
        "audience": "ALL", "version": _VERSION,
        "formula_name": "cause-scoped-bounded-evidence-update",
        "config_json": op.inline_literal(json.dumps(LEARNING_POLICY_CONFIG, ensure_ascii=False, separators=(",", ":"), sort_keys=True), type_=sa.String()),
        "config_hash": _hash(LEARNING_POLICY_CONFIG), "status": "DRAFT", "published_at": None,
    }], multiinsert=False)
    op.execute(
        "UPDATE matching.match_policy_version SET status = 'PUBLISHED', "
        f"published_at = TIMESTAMPTZ '{_PUBLISHED_AT.isoformat()}' "
        f"WHERE match_policy_version_id = '{policy_id}'::uuid"
    )


def _create_tables() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS learning")
    op.create_table(
        "behavior_signal",
        sa.Column("behavior_signal_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("event_date", sa.Date(), nullable=False),
        sa.Column("event_log_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_policy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("signal_type", sa.String(10), nullable=False),
        sa.Column("signal_strength", sa.Numeric(7, 6), nullable=False),
        sa.Column("decayed_signal", sa.Numeric(7, 6), nullable=False),
        sa.Column("cause_code", sa.String(60), nullable=True),
        sa.Column("cause_scope", sa.String(40), nullable=False),
        sa.Column("confidence", sa.Numeric(7, 6), nullable=False),
        sa.Column("validation_status", sa.String(10), nullable=False),
        sa.Column("invalid_reason_codes", postgresql.JSONB(), nullable=False, server_default=sa.text("'[]'::jsonb")),
        sa.Column("input_fingerprint", sa.String(64), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["event_date", "event_log_id"], ["interaction.interaction_event.event_date", "interaction.interaction_event.interaction_event_id"], name="fk_behavior_signal_event"),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.user_profile.profile_id"]),
        sa.ForeignKeyConstraint(["match_policy_version_id"], ["matching.match_policy_version.match_policy_version_id"]),
        sa.UniqueConstraint("event_date", "event_log_id", name="uq_behavior_signal_event"),
        sa.CheckConstraint("signal_type IN ('POSITIVE', 'NEGATIVE', 'NEUTRAL')", name=op.f("ck_behavior_signal_signal_type_allowed")),
        sa.CheckConstraint("signal_strength >= -1 AND signal_strength <= 1", name=op.f("ck_behavior_signal_signal_strength_range")),
        sa.CheckConstraint("decayed_signal >= -1 AND decayed_signal <= 1", name=op.f("ck_behavior_signal_decayed_signal_range")),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name=op.f("ck_behavior_signal_confidence_range")),
        sa.CheckConstraint("validation_status IN ('VALID', 'INVALID')", name=op.f("ck_behavior_signal_validation_status_allowed")),
        schema="learning",
    )
    op.create_index("ix_behavior_signal_profile_time", "behavior_signal", ["profile_id", "processed_at"], schema="learning")
    op.create_table(
        "attribute_evidence",
        sa.Column("attribute_evidence_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("behavior_signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attribute_code", sa.String(100), nullable=False),
        sa.Column("target_level", sa.String(30), nullable=False),
        sa.Column("propagation_weight", sa.Numeric(7, 6), nullable=False),
        sa.Column("decayed_value", sa.Numeric(7, 6), nullable=False),
        sa.Column("positive", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["behavior_signal_id"], ["learning.behavior_signal.behavior_signal_id"]),
        sa.CheckConstraint("propagation_weight >= 0 AND propagation_weight <= 1", name=op.f("ck_attribute_evidence_propagation_weight_range")),
        sa.CheckConstraint("decayed_value >= -1 AND decayed_value <= 1", name=op.f("ck_attribute_evidence_decayed_value_range")),
        schema="learning",
    )
    op.create_index("ix_attribute_evidence_code_time", "attribute_evidence", ["attribute_code", "created_at"], schema="learning")
    op.create_table(
        "profile_adjustment",
        sa.Column("profile_adjustment_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attribute_code", sa.String(100), nullable=False),
        sa.Column("previous_value", postgresql.JSONB(), nullable=True),
        sa.Column("adjustment_value", sa.Numeric(7, 6), nullable=False),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_reference_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("confidence", sa.Numeric(7, 6), nullable=False),
        sa.Column("application_status", sa.String(30), nullable=False),
        sa.Column("applied", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("applied_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.user_profile.profile_id"]),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name=op.f("ck_profile_adjustment_confidence_range")),
        sa.CheckConstraint("application_status IN ('APPLIED', 'CONFIRMATION_REQUIRED', 'SKIPPED')", name=op.f("ck_profile_adjustment_application_status_allowed")),
        schema="learning",
    )
    op.create_index("ix_profile_adjustment_profile_time", "profile_adjustment", ["profile_id", "created_at"], schema="learning")
    op.create_table(
        "feedback_reason",
        sa.Column("feedback_reason_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("behavior_signal_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reason_code", sa.String(60), nullable=False),
        sa.Column("sentiment", sa.String(10), nullable=False),
        sa.Column("intensity", sa.Numeric(7, 6), nullable=False),
        sa.Column("source", sa.String(10), nullable=False),
        sa.Column("confidence", sa.Numeric(7, 6), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["behavior_signal_id"], ["learning.behavior_signal.behavior_signal_id"]),
        sa.CheckConstraint("sentiment IN ('POSITIVE', 'NEGATIVE', 'NEUTRAL')", name=op.f("ck_feedback_reason_sentiment_allowed")),
        sa.CheckConstraint("intensity >= 0 AND intensity <= 1", name=op.f("ck_feedback_reason_intensity_range")),
        sa.CheckConstraint("source IN ('USER', 'RULE', 'AI')", name=op.f("ck_feedback_reason_source_allowed")),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name=op.f("ck_feedback_reason_confidence_range")),
        schema="learning",
    )
    op.create_table(
        "model_reward",
        sa.Column("reward_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("recommendation_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("match_result_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reward_type", sa.String(40), nullable=False),
        sa.Column("raw_reward", sa.Numeric(7, 6), nullable=False),
        sa.Column("adjusted_reward", sa.Numeric(7, 6), nullable=False),
        sa.Column("position_adjustment", sa.Numeric(7, 6), nullable=False),
        sa.Column("valid", sa.Boolean(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["recommendation_session_id"], ["matching.recommendation_session.recommendation_session_id"]),
        sa.ForeignKeyConstraint(["match_result_id"], ["matching.match_result.match_result_id"]),
        sa.CheckConstraint("raw_reward >= -1 AND raw_reward <= 1", name=op.f("ck_model_reward_raw_reward_range")),
        sa.CheckConstraint("adjusted_reward >= -1 AND adjusted_reward <= 1", name=op.f("ck_model_reward_adjusted_reward_range")),
        sa.CheckConstraint("position_adjustment > 0", name=op.f("ck_model_reward_position_adjustment_positive")),
        schema="learning",
    )
    op.create_index("ix_model_reward_session_time", "model_reward", ["recommendation_session_id", "occurred_at"], schema="learning")
    op.create_table(
        "inference",
        sa.Column("inference_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attribute_code", sa.String(100), nullable=False),
        sa.Column("inferred_value", postgresql.JSONB(), nullable=False),
        sa.Column("condition_json", postgresql.JSONB(), nullable=True),
        sa.Column("confidence", sa.Numeric(7, 6), nullable=False),
        sa.Column("evidence_count", sa.Integer(), nullable=False),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("user_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("source_policy_version", sa.String(40), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["profile_id"], ["profile.user_profile.profile_id"]),
        sa.CheckConstraint("confidence >= 0 AND confidence <= 1", name=op.f("ck_inference_confidence_range")),
        sa.CheckConstraint("evidence_count >= 0", name=op.f("ck_inference_evidence_count_nonneg")),
        sa.CheckConstraint("status IN ('CANDIDATE', 'APPLIED', 'CONFIRMED', 'DELETED')", name=op.f("ck_inference_status_allowed")),
        schema="profile",
    )
    op.create_index("ix_profile_inference_profile_status", "inference", ["profile_id", "status"], schema="profile")


def _protect_evidence() -> None:
    op.execute(
        "CREATE OR REPLACE FUNCTION learning.reject_learning_evidence_mutation() RETURNS trigger "
        "LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'learning evidence is append-only'; END; $$"
    )
    for table in ("behavior_signal", "attribute_evidence", "profile_adjustment", "feedback_reason", "model_reward"):
        op.execute(
            f"CREATE TRIGGER trg_{table}_append_only BEFORE UPDATE OR DELETE ON learning.{table} "
            "FOR EACH ROW EXECUTE FUNCTION learning.reject_learning_evidence_mutation()"
        )


def upgrade() -> None:
    _seed_policy()
    _create_tables()
    _protect_evidence()


def downgrade() -> None:
    for table in ("model_reward", "feedback_reason", "profile_adjustment", "attribute_evidence", "behavior_signal"):
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_append_only ON learning.{table}")
    op.execute("DROP FUNCTION IF EXISTS learning.reject_learning_evidence_mutation()")
    op.drop_table("inference", schema="profile")
    for table in ("model_reward", "feedback_reason", "profile_adjustment", "attribute_evidence", "behavior_signal"):
        op.drop_table(table, schema="learning")
    op.execute("DROP SCHEMA IF EXISTS learning")
    op.execute("ALTER TABLE matching.match_policy_version DISABLE TRIGGER trg_match_policy_version_immutable")
    op.execute(f"DELETE FROM matching.match_policy_version WHERE match_policy_version_id = '{_stable_id('policy', _VERSION)}'::uuid")
    op.execute("ALTER TABLE matching.match_policy_version ENABLE TRIGGER trg_match_policy_version_immutable")
    op.drop_constraint("policy_type_allowed", "match_policy_version", schema="matching", type_="check")
    op.create_check_constraint(
        "policy_type_allowed", "match_policy_version",
        "policy_type IN ('HARD_FILTER', 'CONSUMER_SCORE', 'BUYER_SCORE', 'EXHIBITOR_SCORE', 'RECIPROCAL_SCORE', 'CONTEXT_RERANK', 'SLATE_POLICY', 'COLD_START')",
        schema="matching",
    )
