"""Contract tests keeping immutable DB policy seeds aligned with the scorer."""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from pathlib import Path

from app.services.matching.context_policy import (
    CONTEXT_COMPONENT_WEIGHTS,
    CONTEXT_POLICY_CONFIG,
)

from meet_ai.scoring.engine import (
    BUYER_SCORE_V1,
    CONSUMER_SCORE_V1,
    EXHIBITOR_SCORE_V1,
)


def _load_policy_migration():
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260801_0007_policy_ai_registry.py"
    )
    spec = importlib.util.spec_from_file_location(
        "policy_ai_registry_migration", migration_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_context_migration():
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "20260801_0010_context_rerank.py"
    )
    spec = importlib.util.spec_from_file_location(
        "context_rerank_migration", migration_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_seeded_directional_policies_match_deterministic_engine() -> None:
    migration = _load_policy_migration()
    policies = (CONSUMER_SCORE_V1, BUYER_SCORE_V1, EXHIBITOR_SCORE_V1)

    for policy in policies:
        seeded_weights = {
            component: Decimal(weight)
            for component, weight in migration.BASELINE_POLICY_WEIGHTS[
                policy.version
            ].items()
        }
        seeded_metadata = migration.BASELINE_POLICY_METADATA[policy.version]

        assert seeded_weights == dict(policy.weights)
        assert seeded_metadata["audience"] == policy.audience
        assert seeded_metadata["grade_prefix"] == policy.grade_prefix
        assert sum(seeded_weights.values()) == Decimal("1.00")


def test_seeded_context_policy_matches_runtime_policy() -> None:
    migration = _load_context_migration()

    assert migration.CONTEXT_POLICY_CONFIG == CONTEXT_POLICY_CONFIG
    assert {
        component: float(weight)
        for component, weight in migration.CONTEXT_POLICY_WEIGHTS.items()
    } == CONTEXT_COMPONENT_WEIGHTS
    assert sum(CONTEXT_COMPONENT_WEIGHTS.values()) == 1.0
