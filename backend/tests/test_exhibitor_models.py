from __future__ import annotations

import hashlib
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.db.base import Base
from app.models import exhibitor  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
DDL_PATH = ROOT / "db" / "migrations" / "0002_exhibition.sql"
EXPECTED_DDL_DIGEST = "18aaaa3d8f6a72e7ab548b3ddec0b7be0d56b1c219c6e856144ffaed16609a96"


def _foreign_key_targets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in table.foreign_key_constraints
    }


def test_metadata_contains_published_supply_and_filter_tables() -> None:
    expected = {
        "exhibition.exhibitor_profile",
        "exhibition.product_profile",
        "exhibition.supply_capability",
        "exhibition.buyer_preference",
        "exhibition.profile_attribute",
        "matching.filter_evaluation",
        "matching.filter_result",
        "matching.match_policy_version",
        "matching.recommendation_session",
        "matching.match_result",
        "ai.model_version",
        "ai.ai_run",
    }

    assert expected <= set(Base.metadata.tables)
    assert len(Base.metadata.sorted_tables) == 61


def test_event_product_and_booth_are_bound_to_participation_event() -> None:
    expected = (
        "exhibition.exhibitor_participation.tenant_id",
        "exhibition.exhibitor_participation.event_id",
        "exhibition.exhibitor_participation.participation_id",
    )

    assert expected in _foreign_key_targets("exhibition.event_product")
    assert expected in _foreign_key_targets("exhibition.booth")


def test_matching_records_preserve_tenant_and_event_boundaries() -> None:
    assert (
        "profile.user_profile.tenant_id",
        "profile.user_profile.event_id",
        "profile.user_profile.profile_id",
    ) in _foreign_key_targets("matching.filter_evaluation")
    assert (
        "matching.filter_evaluation.tenant_id",
        "matching.filter_evaluation.event_id",
        "matching.filter_evaluation.filter_evaluation_id",
    ) in _foreign_key_targets("matching.recommendation_session")
    assert (
        "matching.recommendation_session.tenant_id",
        "matching.recommendation_session.event_id",
        "matching.recommendation_session.recommendation_session_id",
    ) in _foreign_key_targets("matching.match_result")
    assert (
        "exhibition.recommendable.tenant_id",
        "exhibition.recommendable.event_id",
        "exhibition.recommendable.recommendable_id",
    ) in _foreign_key_targets("matching.match_result")
    assert (
        "exhibition.recommendable.tenant_id",
        "exhibition.recommendable.event_id",
        "exhibition.recommendable.recommendable_id",
    ) in _foreign_key_targets("interaction.interaction_event")


def test_supply_attribute_code_is_bound_to_canonical_concept() -> None:
    assert (
        "ontology.concept_revision.taxonomy_version_id",
        "ontology.concept_revision.concept_id",
    ) in _foreign_key_targets("exhibition.profile_attribute")
    assert (
        "ontology.concept.concept_id",
        "ontology.concept.concept_code",
    ) in _foreign_key_targets("exhibition.profile_attribute")


def test_unpublished_ai_run_table_is_not_a_dangling_foreign_key() -> None:
    targets = _foreign_key_targets("exhibition.product_attribute")

    assert ("ai.ai_run.ai_run_id",) not in targets


def test_exhibition_sql_contract_is_immutable_and_has_hard_boundary_triggers() -> None:
    ddl = DDL_PATH.read_bytes()
    text = ddl.decode("utf-8")

    assert hashlib.sha256(ddl).hexdigest() == EXPECTED_DDL_DIGEST
    assert text.count("CREATE TABLE exhibition.") == 21
    assert "CREATE TRIGGER trg_event_product_owner_boundary" in text
    assert "CREATE TRIGGER trg_trade_condition_scope" in text
    assert "CREATE TRIGGER trg_supply_capability_owner" in text
    assert "CREATE TRIGGER trg_supply_attribute_target" in text
    assert "CREATE TRIGGER trg_user_role_scope" in text
    assert "exhibition.taxonomy_" not in text


def test_alembic_chain_has_one_published_head() -> None:
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["0008_matching_runtime"]
