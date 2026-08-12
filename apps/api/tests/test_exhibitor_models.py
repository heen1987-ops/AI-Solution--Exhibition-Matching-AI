from __future__ import annotations

import hashlib
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.db.base import Base
from app.models import exhibitor  # noqa: F401

APP_ROOT = Path(__file__).resolve().parents[1]  # apps/api
REPO_ROOT = (
    Path(__file__).resolve().parents[3]
)  # repo root: <root>/apps/api/tests/this_file.py
DDL_PATH = REPO_ROOT / "db" / "migrations" / "0002_exhibition.sql"
OBJECT_EMBEDDING_MIGRATION = (
    APP_ROOT / "alembic" / "versions" / "20260802_0017_object_embedding.py"
)
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
        "matching.slate_result",
        "matching.slate_item",
        "matching.cold_start_status",
        "matching.question_definition",
        "interaction.client_event_dedupe",
        "interaction.recommendation_impression",
        "learning.behavior_signal",
        "learning.attribute_evidence",
        "profile.inference",
        "conversation.conversation_session",
        "conversation.message",
        "conversation.entity_extraction",
        "ai.model_version",
        "ai.ai_run",
        "ai.object_embedding",
        "kiosk.kiosk_session",
        "kiosk.kiosk_qr_handoff",
        "integration.notification_delivery",
        "integration.notification_attempt",
        "integration.outbox_event",
    }

    assert expected <= set(Base.metadata.tables)
    # 103 (pre-merge main) + 26 (WAVE 2C/2D/2E domains) + 6 (notification.*) = 135,
    # + 1 (CONTRACT-005 interaction.favorite, 0032_favorite) = 136.
    assert len(Base.metadata.sorted_tables) == 136
    assert "context_details" in Base.metadata.tables["matching.match_result"].c
    assert (
        "context_policy_version_id" in Base.metadata.tables["matching.match_result"].c
    )
    assert (
        "context_score_fingerprint" in Base.metadata.tables["matching.match_result"].c
    )
    reason_columns = Base.metadata.tables["matching.match_reason"].c
    assert "explanation_policy_version" in reason_columns
    assert not reason_columns["explanation_policy_version"].nullable
    assert "input_fingerprint" in reason_columns
    assert not reason_columns["input_fingerprint"].nullable
    conversation_message = Base.metadata.tables["conversation.message"].c
    assert "masked_text" in conversation_message
    assert "message_text" not in conversation_message
    assert "raw_text" not in conversation_message


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
    assert (
        "matching.slate_item.tenant_id",
        "matching.slate_item.event_id",
        "matching.slate_item.slate_result_id",
        "matching.slate_item.slate_item_id",
    ) in _foreign_key_targets("interaction.recommendation_impression")
    assert (
        "exhibition.recommendable.tenant_id",
        "exhibition.recommendable.event_id",
        "exhibition.recommendable.recommendable_id",
    ) in _foreign_key_targets("ai.object_embedding")


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
    config = Config(str(APP_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(APP_ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["0032_favorite"]


def test_object_embedding_migration_fail_closes_stale_catalog_summaries() -> None:
    migration = OBJECT_EMBEDDING_MIGRATION.read_text(encoding="utf-8")

    assert "DECLARE target_type text;\n        DECLARE" not in migration
    assert "deactivate_participation_catalog_embeddings" in migration
    assert "lock_catalog_embedding_sources" in migration
    assert "hashtextextended('catalog-embedding-source'" in migration
    assert "trg_embedding_source_lock_event_product" in migration
    assert "trg_embedding_source_lock_product" in migration
    assert "trg_embedding_source_lock_participation" in migration
    assert "trg_embedding_source_lock_exhibitor" in migration
    assert "trg_embedding_source_lock_recommendable" in migration
    assert (
        migration.count(
            "FOR EACH STATEMENT EXECUTE FUNCTION ai.lock_catalog_embedding_sources()"
        )
        == 5
    )
    assert "trg_embedding_invalidate_event_product_summary" in migration
    assert "trg_embedding_invalidate_product_summary" in migration
    assert "trg_embedding_invalidate_participation_summary" in migration
    assert "trg_embedding_invalidate_exhibitor_summary" in migration
    assert "trg_embedding_invalidate_recommendable" in migration
    assert "embedding.recommendable_id = OLD.recommendable_id" in migration
    assert "embedding.recommendable_id = NEW.recommendable_id" in migration
