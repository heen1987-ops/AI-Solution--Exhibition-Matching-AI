from __future__ import annotations

import time
import uuid
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from app.db.base import Base
from app.models import consent, core, identity, profile  # noqa: F401
from app.models.common import new_uuid7
from sqlalchemy import CheckConstraint

ROOT = Path(__file__).resolve().parents[2]


def _foreign_key_targets(table_name: str) -> set[tuple[str, ...]]:
    table = Base.metadata.tables[table_name]
    return {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in table.foreign_key_constraints
    }


def test_uuid7_has_expected_version_variant_and_current_timestamp() -> None:
    before_ms = time.time_ns() // 1_000_000
    generated = new_uuid7()
    after_ms = time.time_ns() // 1_000_000

    assert generated.version == 7
    assert generated.variant == uuid.RFC_4122
    assert before_ms <= generated.int >> 80 <= after_ms


def test_profile_foundation_uses_only_canonical_ontology() -> None:
    tables = set(Base.metadata.tables)

    assert "exhibition.taxonomy_version" not in tables
    assert "exhibition.taxonomy_term" not in tables
    assert ("ontology.taxonomy_version.taxonomy_version_id",) in _foreign_key_targets(
        "exhibition.event"
    )
    assert (
        "ontology.concept_revision.taxonomy_version_id",
        "ontology.concept_revision.concept_id",
    ) in _foreign_key_targets("profile.profile_attribute")
    assert (
        "ontology.concept.concept_id",
        "ontology.concept.concept_code",
    ) in _foreign_key_targets("profile.profile_attribute")


def test_event_scoped_models_enforce_tenant_event_boundary() -> None:
    expected = (
        "exhibition.event.tenant_id",
        "exhibition.event.event_id",
    )

    for table_name in (
        "exhibition.event_day",
        "exhibition.event_zone",
        "profile.user_role",
        "profile.guest_session",
        "profile.consent_policy",
        "profile.user_consent",
        "profile.user_profile",
        "profile.visit_session",
        "audit.audit_log",
    ):
        assert expected in _foreign_key_targets(table_name), table_name


def test_requirement_level_distinguishes_unknown_from_excluded() -> None:
    table = Base.metadata.tables["profile.profile_attribute"]
    requirement_constraint = next(
        constraint
        for constraint in table.constraints
        if isinstance(constraint, CheckConstraint)
        and constraint.name == "ck_profile_attribute_requirement_level_allowed"
    )
    expression = str(requirement_constraint.sqltext)

    assert "ACCEPTABLE" in expression
    assert "EXCLUDED" in expression
    assert "UNKNOWN" not in expression
    assert "NEUTRAL" not in expression


def test_alembic_history_is_single_linear_chain() -> None:
    config = Config(str(ROOT / "backend" / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "backend" / "alembic"))
    script = ScriptDirectory.from_config(config)

    assert script.get_heads() == ["0004_profile_domain"]
    revisions = list(script.walk_revisions(base="base", head="heads"))
    assert [revision.revision for revision in revisions] == [
        "0004_profile_domain",
        "0003_foundation",
        "0002_ontology",
        "0001_create_schemas",
    ]
