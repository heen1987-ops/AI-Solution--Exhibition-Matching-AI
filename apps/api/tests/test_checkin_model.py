"""Tests for BACKEND-016: interaction.check_in model + migration.

No live Postgres is reachable in this environment. Following the project's established
convention (test_favorite_model.py, tests/test_indexing.py): DDL-level guarantees (CHECK
constraints, FK boundaries, indexes) are proven by compiling the SQLAlchemy table definition to
PostgreSQL DDL text, not against a live database.
"""

from __future__ import annotations

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateIndex, CreateTable

import app.models  # noqa: F401  # registers every domain module on Base.metadata
from app.db.base import Base
from app.models.checkin import CHECK_IN_METHODS, CheckIn


def _table_ddl() -> str:
    return str(CreateTable(CheckIn.__table__).compile(dialect=postgresql.dialect()))


def _index_ddl(index_name: str) -> str:
    (index,) = [idx for idx in CheckIn.__table__.indexes if idx.name == index_name]
    return str(CreateIndex(index).compile(dialect=postgresql.dialect()))


def test_check_in_registers_on_base_metadata() -> None:
    assert "interaction.check_in" in Base.metadata.tables
    assert Base.metadata.tables["interaction.check_in"] is CheckIn.__table__


def test_check_in_method_constants_match_db_erd() -> None:
    assert CHECK_IN_METHODS == ("QR", "MANUAL", "STAFF")


def test_check_in_table_is_in_interaction_schema() -> None:
    assert CheckIn.__table__.schema == "interaction"
    assert CheckIn.__table__.name == "check_in"


def test_check_in_method_check_is_present_and_named_per_convention() -> None:
    ddl = _table_ddl()
    assert (
        "CONSTRAINT ck_check_in_check_in_method_allowed "
        "CHECK (check_in_method IN ('QR', 'MANUAL', 'STAFF'))" in ddl
    )


def test_check_in_has_no_owner_columns() -> None:
    """db-erd §16.2: ownership is derived from visit_session, never duplicated here - unlike
    app/models/favorite.py::Favorite, which does own user_id/guest_session_id directly."""

    columns = CheckIn.__table__.columns
    assert "user_id" not in columns
    assert "guest_session_id" not in columns


def test_check_in_visit_session_fk_is_the_established_composite_boundary_shape() -> None:
    ddl = _table_ddl()
    assert (
        "CONSTRAINT fk_check_in_visit_session_boundary FOREIGN KEY"
        "(tenant_id, event_id, visit_session_id) REFERENCES profile.visit_session "
        "(tenant_id, event_id, visit_session_id)" in ddl
    )


def test_check_in_booth_fk_is_the_established_composite_boundary_shape() -> None:
    ddl = _table_ddl()
    assert (
        "CONSTRAINT fk_check_in_booth_boundary FOREIGN KEY(tenant_id, event_id, booth_id) "
        "REFERENCES exhibition.booth (tenant_id, event_id, booth_id)" in ddl
    )
    assert (
        "CONSTRAINT fk_check_in_event_boundary FOREIGN KEY(tenant_id, event_id) "
        "REFERENCES exhibition.event (tenant_id, event_id)" in ddl
    )


def test_check_in_qr_and_match_result_fks_are_nullable_plain_column_fks() -> None:
    ddl = _table_ddl()
    assert (
        "CONSTRAINT fk_check_in_qr_id_booth_qr FOREIGN KEY(qr_id) "
        "REFERENCES exhibition.booth_qr (booth_qr_id)" in ddl
    )
    assert (
        "CONSTRAINT fk_check_in_match_result_id_match_result FOREIGN KEY(match_result_id) "
        "REFERENCES matching.match_result (match_result_id)" in ddl
    )
    columns = CheckIn.__table__.columns
    assert columns["qr_id"].nullable is True
    assert columns["qr_key_version"].nullable is True
    assert columns["match_result_id"].nullable is True


def test_check_in_required_columns_are_not_nullable() -> None:
    columns = CheckIn.__table__.columns
    for name in (
        "check_in_id",
        "tenant_id",
        "event_id",
        "visit_session_id",
        "booth_id",
        "check_in_method",
        "activities",
        "checked_in_at",
        "received_at",
        "created_at",
    ):
        assert columns[name].nullable is False, name


def test_check_in_dedupe_lookup_index_covers_the_full_window_key() -> None:
    ddl = _index_ddl("ix_check_in_session_booth_time")
    assert "(tenant_id, event_id, visit_session_id, booth_id, checked_in_at)" in ddl


def test_check_in_client_event_partial_unique_index_is_correctly_scoped() -> None:
    ddl = _index_ddl("uq_check_in_active_client_event")
    assert "UNIQUE" in ddl
    assert "(tenant_id, event_id, client_event_id)" in ddl
    assert "WHERE client_event_id IS NOT NULL" in ddl


def test_check_in_is_not_confused_with_favorite() -> None:
    from app.models.favorite import Favorite

    assert CheckIn.__table__.name != Favorite.__table__.name
    assert "check_in_id" in CheckIn.__table__.columns
    assert "check_in_id" not in Favorite.__table__.columns
