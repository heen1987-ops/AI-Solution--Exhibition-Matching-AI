"""Tests for CONTRACT-005: interaction.favorite model + migration.

No live Postgres is reachable in this environment. Following the project's established
convention (tests/test_indexing.py, tests/test_semantic_search.py): DDL-level guarantees (CHECK
constraints, partial unique indexes, FK boundaries) are proven by compiling the SQLAlchemy table
definition to PostgreSQL DDL text, not against a live database.

This is a CONTRACTS-track task: it proves the model/migration are correctly shaped. It
deliberately does not exercise any router/service, since the CRUD API is BACKEND-009's separate
downstream task.
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

import app.models  # noqa: F401  # registers every domain module on Base.metadata
from app.db.base import Base
from app.models.favorite import FAVORITE_SOURCES, Favorite


def _table_ddl() -> str:
    return str(CreateTable(Favorite.__table__).compile(dialect=postgresql.dialect()))


def _index_ddl(index_name: str) -> str:
    (index,) = [idx for idx in Favorite.__table__.indexes if idx.name == index_name]
    return str(CreateIndex(index).compile(dialect=postgresql.dialect()))


def test_favorite_registers_on_base_metadata() -> None:
    assert "interaction.favorite" in Base.metadata.tables
    assert Base.metadata.tables["interaction.favorite"] is Favorite.__table__


def test_favorite_source_constants_match_db_erd() -> None:
    assert FAVORITE_SOURCES == ("SEARCH", "RECOMMENDATION")


def test_favorite_table_is_in_interaction_schema() -> None:
    assert Favorite.__table__.schema == "interaction"
    assert Favorite.__table__.name == "favorite"


def test_favorite_num_nonnulls_check_is_present_and_named_per_convention() -> None:
    ddl = _table_ddl()
    # app/db/base.py NAMING_CONVENTION: "ck": "ck_%(table_name)s_%(constraint_name)s".
    assert (
        "CONSTRAINT ck_favorite_subject_exactly_one "
        "CHECK (num_nonnulls(user_id, guest_session_id) = 1)" in ddl
    )


def test_favorite_source_check_is_present_and_named_per_convention() -> None:
    ddl = _table_ddl()
    assert (
        "CONSTRAINT ck_favorite_source_allowed CHECK (source IN ('SEARCH', 'RECOMMENDATION'))"
        in ddl
    )


def test_favorite_recommendable_fk_is_the_established_composite_boundary_shape() -> None:
    """Every other table targeting exhibition.recommendable (MatchResult, InteractionEvent,
    RecommendationImpression in app/models/matching.py) uses a three-column composite FK into
    the (tenant_id, event_id, recommendable_id) boundary, not a bare recommendable_id FK."""

    ddl = _table_ddl()
    assert (
        "CONSTRAINT fk_favorite_recommendable_boundary FOREIGN KEY"
        "(tenant_id, event_id, recommendable_id) REFERENCES exhibition.recommendable "
        "(tenant_id, event_id, recommendable_id)" in ddl
    )
    assert (
        "CONSTRAINT fk_favorite_event_boundary FOREIGN KEY(tenant_id, event_id) "
        "REFERENCES exhibition.event (tenant_id, event_id)" in ddl
    )


def test_favorite_owner_fks_target_user_account_and_guest_session() -> None:
    ddl = _table_ddl()
    assert (
        "CONSTRAINT fk_favorite_user_id_user_account FOREIGN KEY(user_id) "
        "REFERENCES profile.user_account (user_id)" in ddl
    )
    assert (
        "CONSTRAINT fk_favorite_guest_session_id_guest_session FOREIGN KEY(guest_session_id) "
        "REFERENCES profile.guest_session (guest_session_id)" in ddl
    )


def test_favorite_match_result_fk_is_nullable_plain_column_fk() -> None:
    """match_result_id is optional (db-erd §16.1: not every favorite originates from a specific
    recommendation) and is a plain single-column FK since match_result_id is already a
    standalone PK."""

    ddl = _table_ddl()
    assert (
        "CONSTRAINT fk_favorite_match_result_id_match_result FOREIGN KEY(match_result_id) "
        "REFERENCES matching.match_result (match_result_id)" in ddl
    )
    match_result_column = Favorite.__table__.columns["match_result_id"]
    assert match_result_column.nullable is True


def test_favorite_owner_columns_are_nullable_for_the_exactly_one_check() -> None:
    assert Favorite.__table__.columns["user_id"].nullable is True
    assert Favorite.__table__.columns["guest_session_id"].nullable is True


def test_favorite_active_user_partial_unique_index_is_correctly_scoped() -> None:
    ddl = _index_ddl("uq_favorite_active_user_recommendable")
    assert "UNIQUE" in ddl
    assert "(tenant_id, event_id, user_id, recommendable_id)" in ddl
    assert "WHERE deleted_at IS NULL AND user_id IS NOT NULL" in ddl
    # Must not accidentally also gate on guest_session_id.
    assert "guest_session_id" not in ddl


def test_favorite_active_guest_partial_unique_index_is_correctly_scoped() -> None:
    ddl = _index_ddl("uq_favorite_active_guest_recommendable")
    assert "UNIQUE" in ddl
    assert "(tenant_id, event_id, guest_session_id, recommendable_id)" in ddl
    assert "WHERE deleted_at IS NULL AND guest_session_id IS NOT NULL" in ddl
    assert ddl.count("user_id") == 0


def test_favorite_has_exactly_two_active_partial_unique_indexes() -> None:
    unique_indexes = [idx for idx in Favorite.__table__.indexes if idx.unique]
    assert {idx.name for idx in unique_indexes} == {
        "uq_favorite_active_user_recommendable",
        "uq_favorite_active_guest_recommendable",
    }
    for idx in unique_indexes:
        assert idx.dialect_options["postgresql"]["where"] is not None


def test_favorite_soft_delete_partial_index_where_clause() -> None:
    """The partial indexes are scoped to deleted_at IS NULL, so a soft-deleted row (deleted_at
    set) and a fresh active row for the same owner+recommendable never collide - this is the
    mechanism, not a live-DB behavioural test, per this module's docstring."""

    for name in (
        "uq_favorite_active_user_recommendable",
        "uq_favorite_active_guest_recommendable",
    ):
        ddl = _index_ddl(name)
        assert "deleted_at IS NULL" in ddl


def test_favorite_deleted_at_and_created_at_columns_exist() -> None:
    columns = Favorite.__table__.columns
    assert columns["deleted_at"].nullable is True
    assert columns["created_at"].nullable is False


def test_favorite_is_not_confused_with_interaction_event_favorite_add_remove() -> None:
    """interaction.favorite (this table) and interaction_event's FAVORITE_ADD/FAVORITE_REMOVE
    event_type values are deliberately distinct concepts - guard against a future accidental
    merge/alias."""

    from app.models.matching import InteractionEvent

    assert Favorite.__table__.name != InteractionEvent.__table__.name
    assert "favorite_id" in Favorite.__table__.columns
    assert "favorite_id" not in InteractionEvent.__table__.columns
