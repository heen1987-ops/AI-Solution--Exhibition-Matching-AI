"""rename mismatched CheckConstraint names to their NAMING_CONVENTION-derived form (QUALITY-003)

Why this revision exists
-------------------------
``app/db/base.py::NAMING_CONVENTION`` derives check-constraint names as
``ck_%(table_name)s_%(constraint_name)s``. Alembic's ``op.create_table`` picks up this exact
convention from ``target_metadata`` (``alembic/operations/schemaobj.py`` reads
``naming_convention`` off whatever metadata ``env.py`` configures) even though the ``Table`` it
builds is throwaway - so a hand-written ``sa.CheckConstraint(..., name="...")`` that is NOT
wrapped in ``op.f()`` still gets run back through the convention, using the literal ``name=``
string as the ``%(constraint_name)s`` token.

That is harmless when the given name is the short, unprefixed form (e.g. ``name="status_allowed"``
-> ``ck_<table>_status_allowed``, which is exactly what the equivalent ORM-level constraint
resolves to as well). It is NOT harmless when the given name was already hand-prefixed with the
full ``ck_<table>_...`` convention output, expecting it to be taken literally: the convention
wraps it a second time, producing a double-prefixed, often-truncated-and-hashed name. That is
what happened in two of this codebase's migrations:

  * ``0030_event_ingestion_failure`` - both ``CheckConstraint`` calls pass an already-prefixed
    ``name="ck_event_ingestion_failure_..."``. Compiled today (``alembic upgrade head --sql``),
    these come out as ``ck_event_ingestion_failure_ck_event_ingestion_failure_s_7615`` and
    ``..._r_f22d`` (>63-byte identifiers, Postgres-truncated with a hash suffix) instead of the
    ORM-metadata-derived ``ck_event_ingestion_failure_source_allowed`` /
    ``..._reason_code_allowed``.
  * ``0031_integration_source_sync`` - the same pattern, ten times over, across
    ``source_system``/``external_reference``/``sync_job``/``sync_row_error``. Both files'
    docstrings say the spelled-out names were meant to already equal what NAMING_CONVENTION
    would derive (a defensive, if mistaken, belief that ``op.create_table`` uses a bare
    ``MetaData`` with no naming convention at all) - so the double-prefix here was unintentional.

A systematic grep-and-diff sweep (comparing every ``CheckConstraint`` compiled by
``alembic upgrade head --sql`` against every ``CheckConstraint`` on the equivalent
``Base.metadata`` table, matched by condition text) confirms these twelve are the *only* actual
mismatches among the eleven migration files that skip ``op.f()``. The other nine files also pass
unwrapped ``name=`` strings, but every one of them already uses the short, unprefixed form, so
the convention only applies once and the compiled name already equals the ORM-derived name - no
functional bug, nothing to rename.

Why a new migration instead of editing the eleven files in place
------------------------------------------------------------------
Published migrations are this codebase's immutable historical record (see the sha256 DDL-hash
guards in 0002_ontology / 0004_0005_exhibition, and this session's own append-only harness-log
convention). Editing a ``CheckConstraint(..., name=...)`` string inside an already-merged
migration would mean a database that already ran the old version of that file ends up with
different constraint names than a fresh database that runs the edited version - real (if
currently untested, since no live Postgres is reachable in this sandbox) name drift. Instead this
revision *additively* renames the twelve already-wrong constraints in place, on top of whatever
state 0030/0031 already produced, using Postgres's ``ALTER TABLE ... RENAME CONSTRAINT`` (no
dedicated Alembic op for this - ``op.execute`` with the raw DDL is the standard approach).

``tests/test_alembic_constraint_naming.py`` (added alongside this revision) compiles the full
chain and asserts every table's compiled CHECK-constraint name set now equals
``Base.metadata``'s, so a fresh mismatch introduced by some future migration fails loudly instead
of silently recurring.

Revision ID: 0035_check_constraint_naming_fix
Revises: 0034_feedback
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0035_check_constraint_naming_fix"
down_revision: str | None = "0034_feedback"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (schema, table, wrong_name_as_compiled_by_0030/0031, correct_name = ORM NAMING_CONVENTION
# output for the equivalent Base.metadata CheckConstraint). Computed by diffing
# `alembic upgrade head --sql`'s compiled CHECK-constraint names (matched to their table by
# condition text) against `Base.metadata`'s CheckConstraint.name for the same table/condition -
# not hand-derived, per this task's own instruction not to hand-guess NAMING_CONVENTION's
# string-formatting/truncation rules.
_RENAMES: tuple[tuple[str, str, str, str], ...] = (
    (
        "interaction",
        "event_ingestion_failure",
        "ck_event_ingestion_failure_ck_event_ingestion_failure_s_7615",
        "ck_event_ingestion_failure_source_allowed",
    ),
    (
        "interaction",
        "event_ingestion_failure",
        "ck_event_ingestion_failure_ck_event_ingestion_failure_r_f22d",
        "ck_event_ingestion_failure_reason_code_allowed",
    ),
    (
        "integration",
        "source_system",
        "ck_source_system_ck_source_system_sync_type_allowed",
        "ck_source_system_sync_type_allowed",
    ),
    (
        "integration",
        "external_reference",
        "ck_external_reference_ck_external_reference_object_type_allowed",
        "ck_external_reference_object_type_allowed",
    ),
    (
        "integration",
        "external_reference",
        "ck_external_reference_ck_external_reference_sync_status_allowed",
        "ck_external_reference_sync_status_allowed",
    ),
    (
        "integration",
        "sync_job",
        "ck_sync_job_ck_sync_job_job_type_allowed",
        "ck_sync_job_job_type_allowed",
    ),
    (
        "integration",
        "sync_job",
        "ck_sync_job_ck_sync_job_status_allowed",
        "ck_sync_job_status_allowed",
    ),
    (
        "integration",
        "sync_job",
        "ck_sync_job_ck_sync_job_total_rows_nonneg",
        "ck_sync_job_total_rows_nonneg",
    ),
    (
        "integration",
        "sync_job",
        "ck_sync_job_ck_sync_job_success_rows_nonneg",
        "ck_sync_job_success_rows_nonneg",
    ),
    (
        "integration",
        "sync_job",
        "ck_sync_job_ck_sync_job_failed_rows_nonneg",
        "ck_sync_job_failed_rows_nonneg",
    ),
    (
        "integration",
        "sync_row_error",
        "ck_sync_row_error_ck_sync_row_error_row_number_nonneg",
        "ck_sync_row_error_row_number_nonneg",
    ),
    (
        "integration",
        "sync_row_error",
        "ck_sync_row_error_ck_sync_row_error_retry_status_allowed",
        "ck_sync_row_error_retry_status_allowed",
    ),
)


def upgrade() -> None:
    for schema, table, wrong_name, correct_name in _RENAMES:
        op.execute(
            f'ALTER TABLE "{schema}"."{table}" '
            f'RENAME CONSTRAINT "{wrong_name}" TO "{correct_name}"'
        )


def downgrade() -> None:
    for schema, table, wrong_name, correct_name in reversed(_RENAMES):
        op.execute(
            f'ALTER TABLE "{schema}"."{table}" '
            f'RENAME CONSTRAINT "{correct_name}" TO "{wrong_name}"'
        )
