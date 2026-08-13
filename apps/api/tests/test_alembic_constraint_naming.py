"""CHECK-constraint naming parity: compiled migration names must equal NAMING_CONVENTION
output (QUALITY-003).

Why this test exists
---------------------
``app/db/base.py::NAMING_CONVENTION`` derives CHECK-constraint names as
``ck_%(table_name)s_%(constraint_name)s``. SQLAlchemy applies this convention to *every*
``CheckConstraint`` that carries a plain ``name=`` string (CheckConstraint is the one
constraint type where ``%(constraint_name)s`` resolves to whatever ``name=`` was given,
rather than to something derived from the columns involved) - the only way to opt out is to
wrap the name in ``op.f(...)`` (migrations) or ``sa.schema.conv(...)`` (ORM models), which
marks the string as already-final.

Eleven early migrations (``0002_0003_foundation`` through ``0031_integration_source_sync``)
pass hand-written ``CheckConstraint(..., name="...")`` without ``op.f()``. Most of those names
are already the short, unprefixed form the convention would derive on its own, so applying the
convention once is a no-op and the compiled name matches ``Base.metadata``. Two of them
(``0030_event_ingestion_failure``, ``0031_integration_source_sync``) instead spelled out the
*already-prefixed* ``ck_<table>_...`` form, so the convention wraps it a second time, producing
a double-prefixed, truncated-and-hashed name that does not match the ORM-derived name at all.
``0035_check_constraint_naming_fix`` renames those twelve constraints (additively, via
``ALTER TABLE ... RENAME CONSTRAINT`` - the eleven source migrations are historical record and
are not edited in place) to the name the equivalent ``Base.metadata`` CheckConstraint actually
resolves to.

This test compiles the full chain offline (``alembic upgrade head --sql``, same technique as
``test_alembic_orm_parity.py``), applies any ``RENAME CONSTRAINT`` statements found in that
output, and asserts the resulting per-table CHECK-constraint name set equals what
``Base.metadata`` resolves to (via compiling ``CreateTable`` for each table with the
postgresql dialect, which runs every constraint through the same naming convention). A future
migration that reintroduces this bug on a new table - or a rename migration that gets a name
wrong - fails this test immediately, without a database.

Known exclusions (not this bug, deliberately out of scope for QUALITY-003)
----------------------------------------------------------------------------
* ``ontology.*`` - externally managed by ``db/migrations/0001_ontology.sql``, excluded from
  ``Base.metadata`` comparison for the same reason ``test_alembic_orm_parity.py`` excludes it.
* ``analytics.daily_metric`` / ``funnel_metric`` / ``search_no_result_summary`` /
  ``data_quality_snapshot`` - the *migration* (``0029_analytics_aggregation``) is correct, it
  already uses ``op.f()`` with the fully-resolved short name. The bug is the opposite direction
  and lives in ``app/models/analytics.py``: those ``CheckConstraint`` calls pass an
  already-prefixed bare ``name=`` string, so compiling DDL straight from ``Base.metadata``
  (as this test's ORM side does) double-prefixes it. That is a model-source bug, not a
  migration bug, outside QUALITY-003's owned paths (``alembic/versions/**``) - flagged
  separately, not fixed here.
* ``matching.match_result`` - ``app/models/matching.py`` declares a
  ``context_provenance_consistency`` CheckConstraint that no migration ever creates (a missing
  ``ADD CONSTRAINT``, not a naming mismatch - the constraints that *do* exist are named
  correctly on both sides). Also flagged separately; fixing it means adding DDL, which is a
  different class of change than this revision's renames.
"""

from __future__ import annotations

import io
import re
from contextlib import redirect_stdout
from pathlib import Path

from alembic.config import Config
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

import app.models  # noqa: F401  # registers every domain module on Base.metadata
from alembic import command
from app.db.base import Base

APP_ROOT = Path(__file__).resolve().parents[1]  # apps/api

_EXTERNALLY_MANAGED_SCHEMAS = ("ontology.",)

#: Pre-existing, out-of-scope mismatches - see module docstring. Keyed by full "schema.table"
#: name. Any OTHER table with a mismatch is a real regression and must fail the test.
_KNOWN_OUT_OF_SCOPE_MISMATCHES = frozenset(
    {
        "analytics.daily_metric",
        "analytics.funnel_metric",
        "analytics.search_no_result_summary",
        "analytics.data_quality_snapshot",
        "matching.match_result",
    }
)

_CHECK_CONSTRAINT_IN_CREATE = re.compile(
    r'CONSTRAINT\s+"?(ck_[A-Za-z0-9_]+)"?\s+CHECK'
)
_CREATE_TABLE_START = re.compile(
    r'CREATE\s+(?:UNLOGGED\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?'
    r'"?(?P<schema>[A-Za-z_]\w*)"?\."?(?P<table>[A-Za-z_]\w*)"?\s*\(',
    re.IGNORECASE,
)
_RENAME_CONSTRAINT = re.compile(
    r'ALTER\s+TABLE\s+"?(?P<schema>[A-Za-z_]\w*)"?\."?(?P<table>[A-Za-z_]\w*)"?\s+'
    r'RENAME\s+CONSTRAINT\s+"?(?P<old>[A-Za-z0-9_]+)"?\s+TO\s+"?(?P<new>[A-Za-z0-9_]+)"?',
    re.IGNORECASE,
)


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


def _compiled_check_constraint_names(sql: str) -> dict[str, set[str]]:
    """schema.table -> set of CHECK constraint names, as literally compiled by the migration
    chain's CREATE TABLE statements, THEN updated by any RENAME CONSTRAINT statements found
    later in the same chain (so the result reflects the final, post-migration-0035 state)."""

    by_table: dict[str, set[str]] = {}
    for statement in sql.split(";"):
        create_match = _CREATE_TABLE_START.search(statement)
        if create_match:
            full = f"{create_match.group('schema')}.{create_match.group('table')}"
            names = set(_CHECK_CONSTRAINT_IN_CREATE.findall(statement))
            if names:
                by_table.setdefault(full, set()).update(names)
            continue

        rename_match = _RENAME_CONSTRAINT.search(statement)
        if rename_match:
            full = f"{rename_match.group('schema')}.{rename_match.group('table')}"
            old, new = rename_match.group("old"), rename_match.group("new")
            table_names = by_table.setdefault(full, set())
            if old in table_names:
                table_names.discard(old)
            table_names.add(new)

    return by_table


def _orm_check_constraint_names() -> dict[str, set[str]]:
    """schema.table -> set of CHECK constraint names, as SQLAlchemy's naming convention
    resolves them straight from Base.metadata (compiling CreateTable, postgresql dialect -
    runs every constraint through the exact same convention alembic uses)."""

    by_table: dict[str, set[str]] = {}
    for full_name, table in Base.metadata.tables.items():
        if full_name.startswith(_EXTERNALLY_MANAGED_SCHEMAS):
            continue
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        names = set(_CHECK_CONSTRAINT_IN_CREATE.findall(ddl))
        if names:
            by_table[full_name] = names

    return by_table


def test_compiled_check_constraint_names_match_orm_naming_convention() -> None:
    compiled = _compiled_check_constraint_names(_compiled_chain_sql())
    orm = _orm_check_constraint_names()

    all_tables = sorted(
        table
        for table in set(compiled) | set(orm)
        if table not in _KNOWN_OUT_OF_SCOPE_MISMATCHES
        and not table.startswith(_EXTERNALLY_MANAGED_SCHEMAS)
    )
    mismatches = {
        table: (compiled.get(table, set()), orm.get(table, set()))
        for table in all_tables
        if compiled.get(table, set()) != orm.get(table, set())
    }

    assert not mismatches, (
        "compiled migration CHECK-constraint names diverge from the NAMING_CONVENTION-derived "
        "ORM names (a hand-written CheckConstraint(..., name=...) in a migration is not wrapped "
        "in op.f(), or a rename migration renamed to the wrong target):\n"
        + "\n".join(
            f"  {table}: compiled={sorted(c)} orm={sorted(o)}"
            for table, (c, o) in sorted(mismatches.items())
        )
    )


def test_the_naming_check_would_notice_a_fresh_mismatch() -> None:
    """Guards the guard: if the regexes or the comparison silently stopped matching, the test
    above would pass vacuously."""

    sql = _compiled_chain_sql()
    compiled = _compiled_check_constraint_names(sql)
    assert "ck_event_ingestion_failure_source_allowed" in compiled.get(
        "interaction.event_ingestion_failure", set()
    ), "expected 0035's rename to have already landed the corrected name"

    # Simulate a migration that reintroduces a bare, already-prefixed name (the same class of
    # bug this revision fixes) by dropping the rename: the old, wrong compiled name should then
    # surface as a mismatch against the ORM side.
    without_rename = sql.replace(
        'ALTER TABLE "interaction"."event_ingestion_failure" RENAME CONSTRAINT '
        '"ck_event_ingestion_failure_ck_event_ingestion_failure_s_7615" '
        'TO "ck_event_ingestion_failure_source_allowed";',
        "SELECT 1;",
        1,
    )
    assert without_rename != sql, "fixture RENAME statement text no longer found in compiled SQL"

    broken = _compiled_check_constraint_names(without_rename)
    orm = _orm_check_constraint_names()
    assert broken["interaction.event_ingestion_failure"] != orm["interaction.event_ingestion_failure"]
