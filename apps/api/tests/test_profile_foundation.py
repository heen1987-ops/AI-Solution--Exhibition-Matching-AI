from __future__ import annotations

import time
import uuid
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import CheckConstraint

from app.db.base import Base
from app.models import consent, core, identity, profile  # noqa: F401
from app.models.common import new_uuid7

ROOT = Path(__file__).resolve().parents[1]  # apps/api


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


def test_alembic_history_is_single_linear_chain_through_profile_domain() -> None:
    """profile 도메인 마이그레이션(0004_profile_domain)까지는 단일 선형 체인이어야 한다.

    다른 도메인 에이전트가 그 뒤에 자신의 리비전을 계속 이어붙이는 것은 정상 동작이므로
    (여러 에이전트가 동시에 각자 마이그레이션을 추가하는 구조 - 예: interaction 도메인의
    0005_interaction_domain), 이 테스트는 전체 히스토리의 head를 하드코딩하지 않고
    "base부터 0004_profile_domain까지"만 검증한다. 대신 0004_profile_domain이 현재 모든
    head의 조상인지 확인해 브랜치가 갈라지지 않았음을 보장한다.
    """

    config = Config(str(ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(ROOT / "alembic"))
    script = ScriptDirectory.from_config(config)

    revisions = list(script.walk_revisions(base="base", head="0004_profile_domain"))
    assert [revision.revision for revision in revisions] == [
        "0004_profile_domain",
        "0003_foundation",
        "0002_ontology",
        "0001_create_schemas",
    ]

    for head in script.get_heads():
        ancestors = {
            revision.revision
            for revision in script.walk_revisions(base="base", head=head)
        }
        assert "0004_profile_domain" in ancestors, head
