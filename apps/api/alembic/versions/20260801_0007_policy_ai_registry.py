"""create immutable policy and AI registries

Revision ID: 0007_policy_ai_registry
Revises: 0006_filter_evaluation
Create Date: 2026-08-01
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007_policy_ai_registry"
down_revision: str | None = "0006_filter_evaluation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMESPACE = uuid.UUID("6f6a8f6e-2f61-4e2a-9c8a-1a7c9e6d8b21")
_PUBLISHED_AT = datetime(2026, 8, 1, tzinfo=UTC)

# These values are imported by the migration contract test.  The migration and
# deterministic scorer must publish the same immutable baseline artifacts.
BASELINE_POLICY_WEIGHTS: dict[str, dict[str, str]] = {
    "consumer-score-v1.0": {
        "goal": "0.20",
        "category": "0.18",
        "sensory": "0.18",
        "price": "0.12",
        "alcohol": "0.08",
        "service": "0.09",
        "usage": "0.06",
        "behavior": "0.04",
        "trust": "0.05",
    },
    "buyer-score-v1.0": {
        "business_goal": "0.12",
        "product": "0.15",
        "channel": "0.12",
        "price": "0.10",
        "moq": "0.12",
        "capacity": "0.10",
        "region": "0.08",
        "cooperation": "0.08",
        "meeting": "0.05",
        "trust": "0.08",
    },
    "exhibitor-score-v1.0": {
        "buyer_type": "0.15",
        "channel": "0.16",
        "order_volume": "0.16",
        "region": "0.10",
        "trade_type": "0.12",
        "portfolio": "0.10",
        "decision_timing": "0.08",
        "verification": "0.08",
        "meeting_readiness": "0.05",
    },
}

BASELINE_POLICY_METADATA: dict[str, dict[str, str | None]] = {
    "consumer-score-v1.0": {
        "audience": "GENERAL_VISITOR",
        "grade_prefix": "R",
    },
    "buyer-score-v1.0": {
        "audience": "BUYER_TO_EXHIBITOR",
        "grade_prefix": "B",
    },
    "exhibitor-score-v1.0": {
        "audience": "EXHIBITOR_TO_BUYER",
        "grade_prefix": None,
    },
}


def _stable_id(kind: str, value: str) -> uuid.UUID:
    return uuid.uuid5(_NAMESPACE, f"{kind}:{value}")


def _config_hash(config: dict) -> str:
    payload = json.dumps(
        config, ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _json_literal(value: dict) -> sa.sql.elements.BindParameter:
    return op.inline_literal(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True),
        type_=sa.String(),
    )


def _create_policy_tables() -> None:
    op.create_table(
        "match_policy_version",
        sa.Column(
            "match_policy_version_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("policy_type", sa.String(30), nullable=False),
        sa.Column("audience", sa.String(30), nullable=False),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("formula_name", sa.String(80), nullable=False),
        sa.Column("config_json", postgresql.JSONB(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "policy_type IN ('HARD_FILTER', 'CONSUMER_SCORE', 'BUYER_SCORE', "
            "'EXHIBITOR_SCORE', 'RECIPROCAL_SCORE')",
            name="policy_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'RETIRED')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND published_at IS NULL) OR "
            "(status IN ('PUBLISHED', 'RETIRED') AND published_at IS NOT NULL)",
            name="publication_state",
        ),
        sa.CheckConstraint(
            "retired_at IS NULL OR published_at IS NOT NULL",
            name="retirement_requires_publication",
        ),
        sa.UniqueConstraint(
            "policy_type", "version", name="uq_match_policy_type_version"
        ),
        sa.UniqueConstraint("version", name="uq_match_policy_version"),
        sa.UniqueConstraint(
            "match_policy_version_id",
            "policy_type",
            name="uq_match_policy_id_type",
        ),
        schema="matching",
    )

    op.create_table(
        "match_weight",
        sa.Column("match_weight_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "match_policy_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("component", sa.String(60), nullable=False),
        sa.Column("weight", sa.Numeric(9, 8), nullable=False),
        sa.Column("min_value", sa.Numeric(12, 6), nullable=True),
        sa.Column("max_value", sa.Numeric(12, 6), nullable=True),
        sa.Column("config_json", postgresql.JSONB(), nullable=False),
        sa.CheckConstraint("weight >= 0 AND weight <= 1", name="weight_range"),
        sa.CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR min_value <= max_value",
            name="min_max_order",
        ),
        sa.ForeignKeyConstraint(
            ["match_policy_version_id"],
            ["matching.match_policy_version.match_policy_version_id"],
            name="fk_match_weight_policy",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "match_policy_version_id",
            "component",
            name="uq_match_weight_policy_component",
        ),
        schema="matching",
    )

    op.create_table(
        "filter_rule",
        sa.Column("filter_rule_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "match_policy_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column("rule_code", sa.String(60), nullable=False),
        sa.Column("evaluation_order", sa.SmallInteger(), nullable=False),
        sa.Column("rule_kind", sa.String(10), nullable=False),
        sa.Column("config_json", postgresql.JSONB(), nullable=False),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.CheckConstraint("rule_kind IN ('HARD', 'SOFT')", name="rule_kind_allowed"),
        sa.CheckConstraint("evaluation_order > 0", name="evaluation_order_positive"),
        sa.ForeignKeyConstraint(
            ["match_policy_version_id"],
            ["matching.match_policy_version.match_policy_version_id"],
            name="fk_filter_rule_policy",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint(
            "match_policy_version_id",
            "rule_code",
            name="uq_filter_rule_policy_code",
        ),
        sa.UniqueConstraint(
            "match_policy_version_id",
            "evaluation_order",
            name="uq_filter_rule_policy_order",
        ),
        schema="matching",
    )

    op.create_table(
        "event_policy_binding",
        sa.Column(
            "event_policy_binding_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("policy_type", sa.String(30), nullable=False),
        sa.Column(
            "match_policy_version_id",
            postgresql.UUID(as_uuid=True),
            nullable=False,
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "activated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deactivated_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "deactivated_at IS NULL OR deactivated_at >= activated_at",
            name="activation_time_order",
        ),
        sa.CheckConstraint(
            "(active AND deactivated_at IS NULL) OR "
            "(NOT active AND deactivated_at IS NOT NULL)",
            name="active_state_consistency",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_event_policy_binding_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["match_policy_version_id", "policy_type"],
            [
                "matching.match_policy_version.match_policy_version_id",
                "matching.match_policy_version.policy_type",
            ],
            name="fk_event_policy_binding_policy_type",
        ),
        schema="matching",
    )
    op.create_index(
        "uq_event_policy_binding_active",
        "event_policy_binding",
        ["tenant_id", "event_id", "policy_type"],
        unique=True,
        schema="matching",
        postgresql_where=sa.text("active"),
    )
    op.create_index(
        "ix_event_policy_binding_history",
        "event_policy_binding",
        ["tenant_id", "event_id", "policy_type", "activated_at"],
        schema="matching",
    )


def _create_ai_tables() -> None:
    op.create_table(
        "model_version",
        sa.Column("model_version_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("model_type", sa.String(30), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model_name", sa.String(120), nullable=False),
        sa.Column("provider_version", sa.String(120), nullable=True),
        sa.Column("version", sa.String(80), nullable=False),
        sa.Column("gateway_adapter", sa.String(50), nullable=True),
        sa.Column("config_json", postgresql.JSONB(), nullable=False),
        sa.Column("config_hash", sa.String(64), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deployed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retired_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "model_type IN ('RANKING', 'EXPLANATION', 'EXTRACTION', 'EMBEDDING')",
            name="model_type_allowed",
        ),
        sa.CheckConstraint(
            "status IN ('DRAFT', 'DEPLOYED', 'RETIRED')",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "(status = 'DRAFT' AND deployed_at IS NULL) OR "
            "(status IN ('DEPLOYED', 'RETIRED') AND deployed_at IS NOT NULL)",
            name="deployment_state",
        ),
        sa.CheckConstraint(
            "retired_at IS NULL OR deployed_at IS NOT NULL",
            name="retirement_requires_deployment",
        ),
        sa.UniqueConstraint(
            "model_type", "version", name="uq_model_version_type_version"
        ),
        schema="ai",
    )

    op.create_table(
        "ai_run",
        sa.Column("ai_run_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_type", sa.String(30), nullable=False),
        sa.Column("input_reference_type", sa.String(40), nullable=True),
        sa.Column("input_reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("input_hash", sa.LargeBinary(), nullable=False),
        sa.Column("schema_version", sa.String(30), nullable=False),
        sa.Column("prompt_version", sa.String(50), nullable=False),
        sa.Column("validated_output_json", postgresql.JSONB(), nullable=True),
        sa.Column("validation_status", sa.String(20), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("token_input", sa.Integer(), nullable=True),
        sa.Column("token_output", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(14, 6), nullable=True),
        sa.Column("error_code", sa.String(50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.CheckConstraint(
            "task_type IN ('ATTRIBUTE_EXTRACTION', 'EXPLANATION', 'EMBEDDING')",
            name="task_type_allowed",
        ),
        sa.CheckConstraint(
            "validation_status IN ('VALID', 'INVALID', 'REVIEW', 'FAILED')",
            name="validation_status_allowed",
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name="latency_nonnegative",
        ),
        sa.CheckConstraint(
            "token_input IS NULL OR token_input >= 0",
            name="token_input_nonnegative",
        ),
        sa.CheckConstraint(
            "token_output IS NULL OR token_output >= 0",
            name="token_output_nonnegative",
        ),
        sa.CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0",
            name="estimated_cost_nonnegative",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_ai_run_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["model_version_id"],
            ["ai.model_version.model_version_id"],
            name="fk_ai_run_model_version",
        ),
        schema="ai",
    )


def _seed_baselines() -> None:
    policy_table = sa.table(
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
    weight_table = sa.table(
        "match_weight",
        sa.column("match_weight_id", postgresql.UUID(as_uuid=True)),
        sa.column("match_policy_version_id", postgresql.UUID(as_uuid=True)),
        sa.column("component", sa.String()),
        sa.column("weight", sa.Numeric()),
        sa.column("config_json", postgresql.JSONB()),
        schema="matching",
    )
    rule_table = sa.table(
        "filter_rule",
        sa.column("filter_rule_id", postgresql.UUID(as_uuid=True)),
        sa.column("match_policy_version_id", postgresql.UUID(as_uuid=True)),
        sa.column("rule_code", sa.String()),
        sa.column("evaluation_order", sa.SmallInteger()),
        sa.column("rule_kind", sa.String()),
        sa.column("config_json", postgresql.JSONB()),
        sa.column("active", sa.Boolean()),
        schema="matching",
    )

    policy_specs = (
        (
            "HARD_FILTER",
            "ALL",
            "hard-filter-v1.0",
            "first-failure-eligibility-gate",
            {"first_failure_wins": True, "output": "FINAL_CANDIDATE_DECISION"},
            {},
        ),
        (
            "CONSUMER_SCORE",
            "GENERAL_VISITOR",
            "consumer-score-v1.0",
            "weighted-sum-renormalized-missing",
            {"scale": 100, "missing": "RENORMALIZE", "grade_prefix": "R"},
            BASELINE_POLICY_WEIGHTS["consumer-score-v1.0"],
        ),
        (
            "BUYER_SCORE",
            "BUYER_TO_EXHIBITOR",
            "buyer-score-v1.0",
            "weighted-sum-renormalized-missing",
            {"scale": 100, "missing": "RENORMALIZE", "grade_prefix": "B"},
            BASELINE_POLICY_WEIGHTS["buyer-score-v1.0"],
        ),
        (
            "EXHIBITOR_SCORE",
            "EXHIBITOR_TO_BUYER",
            "exhibitor-score-v1.0",
            "weighted-sum-renormalized-missing",
            {"scale": 100, "missing": "RENORMALIZE", "grade_prefix": None},
            BASELINE_POLICY_WEIGHTS["exhibitor-score-v1.0"],
        ),
        (
            "RECIPROCAL_SCORE",
            "RECIPROCAL",
            "reciprocal-score-v1.0",
            "harmonic-mean-with-gates",
            {
                "acceptance_floor": "0.80",
                "acceptance_span": "0.20",
                "confidence_floor": "0.90",
                "confidence_span": "0.10",
                "imbalance_lambda": "10",
                "minimum_gate_caps": [["40", "45"], ["55", "65"]],
                "rounding": "ROUND_HALF_UP_0.01",
            },
            {},
        ),
    )

    policy_rows = []
    weight_rows = []
    for policy_type, audience, version, formula, config, weights in policy_specs:
        policy_id = _stable_id("policy", version)
        complete_config = {**config, "weights": weights}
        policy_rows.append(
            {
                "match_policy_version_id": policy_id,
                "policy_type": policy_type,
                "audience": audience,
                "version": version,
                "formula_name": formula,
                "config_json": _json_literal(complete_config),
                "config_hash": _config_hash(complete_config),
                "status": "PUBLISHED",
                "published_at": _PUBLISHED_AT,
            }
        )
        weight_rows.extend(
            {
                "match_weight_id": _stable_id("weight", f"{version}:{component}"),
                "match_policy_version_id": policy_id,
                "component": component,
                "weight": Decimal(weight),
                "config_json": _json_literal({}),
            }
            for component, weight in weights.items()
        )

    op.bulk_insert(policy_table, policy_rows, multiinsert=False)
    if weight_rows:
        op.bulk_insert(weight_table, weight_rows, multiinsert=False)

    hard_filter_id = _stable_id("policy", "hard-filter-v1.0")
    rule_codes = (
        "ADMIN_NOT_APPROVED",
        "PARTICIPATION_CANCELLED",
        "BOOTH_CLOSED",
        "PRODUCT_SOLD_OUT",
        "PRODUCT_UNAVAILABLE",
        "PROGRAM_CANCELLED",
        "USER_EXCLUDED",
        "INSUFFICIENT_DATA",
        "PRICE_OVER_LIMIT",
        "TIME_INSUFFICIENT",
        "ALREADY_VISITED",
        "MOQ_MISMATCH",
        "CAPACITY_INSUFFICIENT",
        "REGION_MISMATCH",
        "CHANNEL_MISMATCH",
        "OEM_MISMATCH",
        "PRIVATE_LABEL_MISMATCH",
        "EXPORT_MISMATCH",
        "MEETING_UNAVAILABLE",
    )
    op.bulk_insert(
        rule_table,
        [
            {
                "filter_rule_id": _stable_id("rule", f"hard-filter-v1.0:{code}"),
                "match_policy_version_id": hard_filter_id,
                "rule_code": code,
                "evaluation_order": order,
                "rule_kind": "HARD",
                "config_json": _json_literal({}),
                "active": True,
            }
            for order, code in enumerate(rule_codes, start=1)
        ],
        multiinsert=False,
    )

    model_config = {
        "implementation": "meet_ai.scoring",
        "external_inference": False,
        "provider_adapter": None,
    }
    model_table = sa.table(
        "model_version",
        sa.column("model_version_id", postgresql.UUID(as_uuid=True)),
        sa.column("model_type", sa.String()),
        sa.column("provider", sa.String()),
        sa.column("model_name", sa.String()),
        sa.column("provider_version", sa.String()),
        sa.column("version", sa.String()),
        sa.column("gateway_adapter", sa.String()),
        sa.column("config_json", postgresql.JSONB()),
        sa.column("config_hash", sa.String()),
        sa.column("status", sa.String()),
        sa.column("deployed_at", sa.DateTime(timezone=True)),
        schema="ai",
    )
    op.bulk_insert(
        model_table,
        [
            {
                "model_version_id": _stable_id("model", "match-v1.0-baseline"),
                "model_type": "RANKING",
                "provider": "INTERNAL",
                "model_name": "deterministic-score-core",
                "provider_version": None,
                "version": "match-v1.0-baseline",
                "gateway_adapter": None,
                "config_json": _json_literal(model_config),
                "config_hash": _config_hash(model_config),
                "status": "DEPLOYED",
                "deployed_at": _PUBLISHED_AT,
            }
        ],
        multiinsert=False,
    )


def _create_immutability_triggers() -> None:
    op.execute(
        """
        CREATE OR REPLACE FUNCTION matching.protect_published_policy()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status <> 'DRAFT' THEN
                    RAISE EXCEPTION 'published policy versions are immutable';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.status = 'DRAFT' THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'PUBLISHED'
               AND NEW.status = 'RETIRED'
               AND (to_jsonb(NEW) - ARRAY['status', 'retired_at'])
                   = (to_jsonb(OLD) - ARRAY['status', 'retired_at']) THEN
                IF EXISTS (
                    SELECT 1 FROM matching.event_policy_binding
                    WHERE match_policy_version_id = OLD.match_policy_version_id
                      AND active
                ) THEN
                    RAISE EXCEPTION 'an active event binding still uses this policy';
                END IF;
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'published policy versions are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_match_policy_version_immutable
        BEFORE UPDATE OR DELETE ON matching.match_policy_version
        FOR EACH ROW EXECUTE FUNCTION matching.protect_published_policy()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION matching.protect_published_policy_child()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE policy_status text;
        DECLARE old_policy_status text;
        DECLARE target_policy_id uuid;
        BEGIN
            target_policy_id := CASE
                WHEN TG_OP = 'DELETE' THEN OLD.match_policy_version_id
                ELSE NEW.match_policy_version_id
            END;
            SELECT status INTO policy_status
            FROM matching.match_policy_version
            WHERE match_policy_version_id = target_policy_id;
            IF policy_status <> 'DRAFT' THEN
                RAISE EXCEPTION 'published policy children are immutable';
            END IF;
            IF TG_OP = 'UPDATE' THEN
                SELECT status INTO old_policy_status
                FROM matching.match_policy_version
                WHERE match_policy_version_id = OLD.match_policy_version_id;
                IF old_policy_status <> 'DRAFT' THEN
                    RAISE EXCEPTION 'published policy children are immutable';
                END IF;
            END IF;
            IF TG_OP = 'DELETE' THEN
                RETURN OLD;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    for table_name in ("match_weight", "filter_rule"):
        op.execute(
            f"""
            CREATE TRIGGER trg_{table_name}_published_immutable
            BEFORE INSERT OR UPDATE OR DELETE ON matching.{table_name}
            FOR EACH ROW EXECUTE FUNCTION matching.protect_published_policy_child()
            """
        )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION matching.validate_event_policy_binding()
        RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE policy_status text;
        BEGIN
            IF NEW.active THEN
                SELECT status INTO policy_status
                FROM matching.match_policy_version
                WHERE match_policy_version_id = NEW.match_policy_version_id;
                IF policy_status <> 'PUBLISHED' THEN
                    RAISE EXCEPTION 'only published policies can be activated';
                END IF;
            END IF;
            RETURN NEW;
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_event_policy_binding_validate
        BEFORE INSERT OR UPDATE ON matching.event_policy_binding
        FOR EACH ROW EXECUTE FUNCTION matching.validate_event_policy_binding()
        """
    )

    op.execute(
        """
        CREATE OR REPLACE FUNCTION ai.protect_deployed_model()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                IF OLD.status <> 'DRAFT' THEN
                    RAISE EXCEPTION 'deployed model versions are immutable';
                END IF;
                RETURN OLD;
            END IF;
            IF OLD.status = 'DRAFT' THEN
                RETURN NEW;
            END IF;
            IF OLD.status = 'DEPLOYED'
               AND NEW.status = 'RETIRED'
               AND (to_jsonb(NEW) - ARRAY['status', 'retired_at'])
                   = (to_jsonb(OLD) - ARRAY['status', 'retired_at']) THEN
                RETURN NEW;
            END IF;
            RAISE EXCEPTION 'deployed model versions are immutable';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_model_version_immutable
        BEFORE UPDATE OR DELETE ON ai.model_version
        FOR EACH ROW EXECUTE FUNCTION ai.protect_deployed_model()
        """
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION ai.reject_immutable_ai_mutation()
        RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'AI audit artifacts are append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER trg_ai_run_append_only
        BEFORE UPDATE OR DELETE ON ai.ai_run
        FOR EACH ROW EXECUTE FUNCTION ai.reject_immutable_ai_mutation()
        """
    )


def upgrade() -> None:
    _create_policy_tables()
    _create_ai_tables()
    _seed_baselines()
    _create_immutability_triggers()


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_ai_run_append_only ON ai.ai_run")
    op.execute("DROP FUNCTION IF EXISTS ai.reject_immutable_ai_mutation()")
    op.execute("DROP TRIGGER IF EXISTS trg_model_version_immutable ON ai.model_version")
    op.execute("DROP FUNCTION IF EXISTS ai.protect_deployed_model()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_event_policy_binding_validate "
        "ON matching.event_policy_binding"
    )
    op.execute("DROP FUNCTION IF EXISTS matching.validate_event_policy_binding()")
    for table_name in ("filter_rule", "match_weight"):
        op.execute(
            f"DROP TRIGGER IF EXISTS trg_{table_name}_published_immutable "
            f"ON matching.{table_name}"
        )
    op.execute("DROP FUNCTION IF EXISTS matching.protect_published_policy_child()")
    op.execute(
        "DROP TRIGGER IF EXISTS trg_match_policy_version_immutable "
        "ON matching.match_policy_version"
    )
    op.execute("DROP FUNCTION IF EXISTS matching.protect_published_policy()")

    op.drop_table("ai_run", schema="ai")
    op.drop_table("model_version", schema="ai")
    op.drop_index(
        "ix_event_policy_binding_history",
        table_name="event_policy_binding",
        schema="matching",
    )
    op.drop_index(
        "uq_event_policy_binding_active",
        table_name="event_policy_binding",
        schema="matching",
    )
    op.drop_table("event_policy_binding", schema="matching")
    op.drop_table("filter_rule", schema="matching")
    op.drop_table("match_weight", schema="matching")
    op.drop_table("match_policy_version", schema="matching")
