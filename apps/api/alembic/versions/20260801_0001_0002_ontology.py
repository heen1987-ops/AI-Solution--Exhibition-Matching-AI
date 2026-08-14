"""create the versioned matching ontology

Revision ID: 0002_ontology
Revises: 0001_create_schemas
Create Date: 2026-08-01

The DDL is kept in the repository-level database contract so it can also be
reviewed and applied outside Alembic.  A digest guard makes the historical
migration fail closed if that immutable file is edited in place; changes must
be introduced as a new migration.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0002_ontology"
down_revision: str | None = "0001_create_schemas"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DDL_SHA256 = "6ac7938ad5ca0c449cf4b082bccd45978323f15f00bd1598ee9b291c1088d1dd"


def _ddl_path() -> Path:
    # parents[4] = repo root: <root>/apps/api/alembic/versions/this_file.py
    return (
        Path(__file__).resolve().parents[4] / "db" / "migrations" / "0001_ontology.sql"
    )


def _split_sql(script: str) -> list[str]:
    """Split PostgreSQL statements while preserving quoted and dollar blocks."""

    statements: list[str] = []
    buffer: list[str] = []
    quote: str | None = None
    dollar_tag: str | None = None
    index = 0

    while index < len(script):
        if dollar_tag is not None:
            if script.startswith(dollar_tag, index):
                buffer.append(dollar_tag)
                index += len(dollar_tag)
                dollar_tag = None
            else:
                buffer.append(script[index])
                index += 1
            continue

        char = script[index]
        if quote is not None:
            buffer.append(char)
            index += 1
            if char == quote:
                if index < len(script) and script[index] == quote:
                    buffer.append(script[index])
                    index += 1
                else:
                    quote = None
            continue

        if char in {"'", '"'}:
            quote = char
            buffer.append(char)
            index += 1
            continue

        if char == "$":
            match = re.match(r"\$[A-Za-z_][A-Za-z0-9_]*\$|\$\$", script[index:])
            if match:
                dollar_tag = match.group(0)
                buffer.append(dollar_tag)
                index += len(dollar_tag)
                continue

        if char == ";":
            statement = "".join(buffer).strip()
            if statement and statement.upper() not in {"BEGIN", "COMMIT"}:
                statements.append(statement)
            buffer.clear()
            index += 1
            continue

        buffer.append(char)
        index += 1

    trailing = "".join(buffer).strip()
    if trailing:
        statements.append(trailing)
    return statements


def upgrade() -> None:
    ddl = _ddl_path().read_bytes()
    actual_digest = hashlib.sha256(ddl).hexdigest()
    if actual_digest != _DDL_SHA256:
        raise RuntimeError(
            "ontology DDL changed after migration publication; "
            "restore db/migrations/0001_ontology.sql and add a new migration"
        )
    for statement in _split_sql(ddl.decode("utf-8")):
        op.execute(statement)


def downgrade() -> None:
    op.execute(
        "DROP FUNCTION IF EXISTS ontology.reject_published_child_mutation() CASCADE"
    )
    for table in (
        "unknown_term_queue",
        "external_mapping",
        "concept_relation",
        "concept_synonym",
        "concept_label",
        "concept_revision",
        "concept",
        "taxonomy_version",
    ):
        op.execute(f'DROP TABLE IF EXISTS ontology."{table}" CASCADE')
