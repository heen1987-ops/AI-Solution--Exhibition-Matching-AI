"""ORM-vs-migration parity: every declared table must have a creating migration.

Why this test exists
--------------------
Both codebases merged in the WAVE 2C/2D/2E integration shipped ORM tables that no migration
ever created, and nobody noticed:

  * ``interaction.meeting`` and its six siblings - the whole meeting family - sat in
    ``alembic/pending/`` while ``app/models/meeting.py`` declared them (now 0020);
  * ``interaction.event_ingestion_failure`` was declared but created nowhere (now 0030);
  * ``integration.source_system`` / ``external_reference`` / ``sync_job`` /
    ``sync_row_error`` / ``idempotency_record`` were declared but created nowhere (now 0031).

Each of those compiles fine and passes ``alembic heads``; they only fail at runtime, on the
first statement that touches the table. The one test that would have caught it,
``tests/integration/test_postgres_recommendation_contract.py``, is skipped unless
``POSTGRES_TEST_DATABASE_URL`` is set, so it never runs in this environment.

This test needs no database: it compiles the whole chain offline (``alembic upgrade head
--sql``) and compares the set of ``CREATE TABLE`` names in the emitted SQL against
``Base.metadata``.

``ontology.*`` is excluded deliberately: those tables are created by the externally-managed
immutable SQL contract in ``db/migrations/0001_ontology.sql``, and ``alembic/env.py``'s
``include_object`` hook keeps them out of autogenerate for the same reason.
"""

from __future__ import annotations

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

import app.models  # noqa: F401  # registers every domain module on Base.metadata
from alembic import command
from app.db.base import Base

APP_ROOT = Path(__file__).resolve().parents[1]  # apps/api

#: Matches the CREATE TABLE forms alembic and the raw db/migrations/*.sql files emit,
#: including quoted identifiers, IF NOT EXISTS, and partition parents.
_CREATE_TABLE = re.compile(
    r"CREATE\s+(?:UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    r'(?:"?(?P<schema>[A-Za-z_]\w*)"?\.)?"?(?P<table>[A-Za-z_]\w*)"?',
    re.IGNORECASE,
)

_EXTERNALLY_MANAGED_SCHEMAS = ("ontology.",)


def _alembic_config() -> Config:
    config = Config(str(APP_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(APP_ROOT / "alembic"))
    return config


def _compiled_chain_sql() -> str:
    """Full offline SQL for base -> head. Never touches a database."""

    buffer = io.StringIO()
    with redirect_stdout(buffer):
        command.upgrade(_alembic_config(), "head", sql=True)
    return buffer.getvalue()


def _created_table_names(sql: str) -> set[str]:
    names: set[str] = set()
    for match in _CREATE_TABLE.finditer(sql):
        schema = match.group("schema") or "public"
        names.add(f"{schema}.{match.group('table')}")
    return names


def _declared_table_names() -> set[str]:
    return {
        name
        for name in Base.metadata.tables
        if not name.startswith(_EXTERNALLY_MANAGED_SCHEMAS)
    }


def test_alembic_has_exactly_one_head() -> None:
    script = ScriptDirectory.from_config(_alembic_config())

    heads = script.get_heads()
    assert len(heads) == 1, f"expected a single linear chain, got heads: {heads}"


def test_every_orm_table_has_a_creating_migration() -> None:
    created = _created_table_names(_compiled_chain_sql())
    declared = _declared_table_names()

    missing = sorted(declared - created)
    assert not missing, (
        "these tables are declared in app/models but no migration creates them - "
        "they will raise 'relation does not exist' on first use: " + ", ".join(missing)
    )


def test_the_parity_check_would_notice_a_missing_create_table() -> None:
    """Guards the guard: if the regex or the comparison silently stopped matching,
    the test above would pass vacuously."""

    sql = _compiled_chain_sql()
    created = _created_table_names(sql)
    assert "interaction.meeting" in created
    assert "integration.source_system" in created

    # Removing one CREATE TABLE from the compiled SQL must surface as a missing table.
    without_meeting = sql.replace("CREATE TABLE interaction.meeting ", "SELECT 1; -- ", 1)
    assert "interaction.meeting" in _declared_table_names() - _created_table_names(
        without_meeting
    )
