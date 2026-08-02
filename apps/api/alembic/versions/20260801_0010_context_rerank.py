"""publish stage-14 context re-ranking policy and provenance

Revision ID: 0010_context_rerank
Revises: 0009_recommendation_api
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

revision: str = "0010_context_rerank"
down_revision: str | None = "0009_recommendation_api"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NAMESPACE = uuid.UUID("6f6a8f6e-2f61-4e2a-9c8a-1a7c9e6d8b21")
_VERSION = "context-rerank-v1.0"
_PUBLISHED_AT = datetime(2026, 8, 1, tzinfo=UTC)
CONTEXT_POLICY_WEIGHTS: dict[str, str] = {
    "proximity": "0.20",
    "time_feasibility": "0.20",
    "wait_congestion": "0.15",
    "operational_availability": "0.15",
    "meeting_availability": "0.10",
    "schedule_feasibility": "0.10",
    "inventory_urgency": "0.05",
    "recent_behavior": "0.05",
}
CONTEXT_POLICY_CONFIG = {
    "base_score_weight": 0.85,
    "context_score_weight": 0.15,
    "component_weights": {
        key: float(value) for key, value in CONTEXT_POLICY_WEIGHTS.items()
    },
    "missing_value_strategy": "REWEIGHT_PRESENT_ONLY",
    "distance_unit_to_meters": 5.0,
    "walk_speed_meters_per_minute": 60.0,
    "default_visit_minutes": 10,
    "score_range": [0.0, 1.0],
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


def upgrade() -> None:
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

    op.add_column(
        "match_result",
        sa.Column(
            "context_policy_version_id", postgresql.UUID(as_uuid=True), nullable=True
        ),
        schema="matching",
    )
    op.add_column(
        "match_result",
        sa.Column("context_components", postgresql.JSONB(), nullable=True),
        schema="matching",
    )
    op.add_column(
        "match_result",
        sa.Column("context_effective_weights", postgresql.JSONB(), nullable=True),
        schema="matching",
    )
    op.add_column(
        "match_result",
        sa.Column("context_contributions", postgresql.JSONB(), nullable=True),
        schema="matching",
    )
    op.add_column(
        "match_result",
        sa.Column("context_input_fingerprint", sa.String(64), nullable=True),
        schema="matching",
    )
    op.add_column(
        "match_result",
        sa.Column("context_score_fingerprint", sa.String(64), nullable=True),
        schema="matching",
    )
    op.create_foreign_key(
        "fk_match_result_context_policy",
        "match_result",
        "match_policy_version",
        ["context_policy_version_id"],
        ["match_policy_version_id"],
        source_schema="matching",
        referent_schema="matching",
    )
    op.create_check_constraint(
        "context_provenance_consistency",
        "match_result",
        "(context_policy_version_id IS NULL AND context_components IS NULL "
        "AND context_effective_weights IS NULL AND context_contributions IS NULL "
        "AND context_input_fingerprint IS NULL AND context_score_fingerprint IS NULL) "
        "OR (context_policy_version_id IS NOT NULL AND context_components IS NOT NULL "
        "AND context_effective_weights IS NOT NULL AND context_contributions IS NOT NULL "
        "AND context_input_fingerprint IS NOT NULL AND context_score_fingerprint IS NOT NULL)",
        schema="matching",
    )

    policy_id = _stable_id("policy", _VERSION)
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
    op.bulk_insert(
        policy_table,
        [
            {
                "match_policy_version_id": policy_id,
                "policy_type": "CONTEXT_RERANK",
                "audience": "ALL",
                "version": _VERSION,
                "formula_name": "missing-aware-context-blend",
                "config_json": _json_literal(CONTEXT_POLICY_CONFIG),
                "config_hash": _config_hash(CONTEXT_POLICY_CONFIG),
                "status": "DRAFT",
                "published_at": None,
            }
        ],
        multiinsert=False,
    )
    weight_table = sa.table(
        "match_weight",
        sa.column("match_weight_id", postgresql.UUID(as_uuid=True)),
        sa.column("match_policy_version_id", postgresql.UUID(as_uuid=True)),
        sa.column("component", sa.String()),
        sa.column("weight", sa.Numeric()),
        sa.column("min_value", sa.Numeric()),
        sa.column("max_value", sa.Numeric()),
        sa.column("config_json", postgresql.JSONB()),
        schema="matching",
    )
    op.bulk_insert(
        weight_table,
        [
            {
                "match_weight_id": _stable_id("weight", f"{_VERSION}:{component}"),
                "match_policy_version_id": policy_id,
                "component": component,
                "weight": Decimal(value),
                "min_value": Decimal(0),
                "max_value": Decimal(1),
                "config_json": _json_literal({}),
            }
            for component, value in CONTEXT_POLICY_WEIGHTS.items()
        ],
        multiinsert=False,
    )
    op.execute(
        "UPDATE matching.match_policy_version SET status = 'PUBLISHED', "
        f"published_at = TIMESTAMPTZ '{_PUBLISHED_AT.isoformat()}' "
        f"WHERE match_policy_version_id = '{policy_id}'::uuid"
    )


def downgrade() -> None:
    policy_id = _stable_id("policy", _VERSION)
    op.drop_constraint(
        "context_provenance_consistency",
        "match_result",
        schema="matching",
        type_="check",
    )
    op.drop_constraint(
        "fk_match_result_context_policy",
        "match_result",
        schema="matching",
        type_="foreignkey",
    )
    for column in (
        "context_score_fingerprint",
        "context_input_fingerprint",
        "context_contributions",
        "context_effective_weights",
        "context_components",
        "context_policy_version_id",
    ):
        op.drop_column("match_result", column, schema="matching")

    op.execute(
        "ALTER TABLE matching.match_weight DISABLE TRIGGER "
        "trg_match_weight_published_immutable"
    )
    op.execute(
        "ALTER TABLE matching.match_policy_version DISABLE TRIGGER "
        "trg_match_policy_version_immutable"
    )
    op.execute(
        "DELETE FROM matching.match_weight "
        f"WHERE match_policy_version_id = '{policy_id}'::uuid"
    )
    op.execute(
        "DELETE FROM matching.match_policy_version "
        f"WHERE match_policy_version_id = '{policy_id}'::uuid"
    )
    op.execute(
        "ALTER TABLE matching.match_policy_version ENABLE TRIGGER "
        "trg_match_policy_version_immutable"
    )
    op.execute(
        "ALTER TABLE matching.match_weight ENABLE TRIGGER "
        "trg_match_weight_published_immutable"
    )

    op.drop_constraint(
        "policy_type_allowed", "match_policy_version", schema="matching", type_="check"
    )
    op.create_check_constraint(
        "policy_type_allowed",
        "match_policy_version",
        "policy_type IN ('HARD_FILTER', 'CONSUMER_SCORE', 'BUYER_SCORE', "
        "'EXHIBITOR_SCORE', 'RECIPROCAL_SCORE')",
        schema="matching",
    )
