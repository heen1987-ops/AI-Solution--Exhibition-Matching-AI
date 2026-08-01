"""create exhibition, product, booth, and supply-profile domains

Revision ID: 0005_exhibition
Revises: 0004_profile_domain
Create Date: 2026-08-01
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from pathlib import Path

from alembic import op

revision: str = "0005_exhibition"
down_revision: str | None = "0004_profile_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_DDL_SHA256 = "18aaaa3d8f6a72e7ab548b3ddec0b7be0d56b1c219c6e856144ffaed16609a96"


def _ddl_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "db"
        / "migrations"
        / "0002_exhibition.sql"
    )


def _split_sql(script: str) -> list[str]:
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
            "exhibition DDL changed after migration publication; regenerate it and "
            "publish a new migration instead of mutating migration 0005"
        )
    for statement in _split_sql(ddl.decode("utf-8")):
        op.execute(statement)


def downgrade() -> None:
    for function_name in (
        "validate_user_role_scope",
        "validate_supply_attribute_target",
        "validate_product_profile_category_code",
        "validate_supply_capability_owner",
        "validate_trade_condition_scope",
        "validate_event_product_owner",
    ):
        op.execute(f"DROP FUNCTION IF EXISTS exhibition.{function_name}() CASCADE")

    op.drop_constraint(
        "fk_user_role_exhibitor_boundary",
        "user_role",
        schema="profile",
        type_="foreignkey",
    )

    for table in (
        "trade_condition_term",
        "trade_condition",
        "staff_topic",
        "booth_status_history",
        "booth_qr",
        "supply_capability",
        "product_profile",
        "product_image",
        "product_attribute",
        "participation_category",
        "exhibitor_staff",
        "event_product",
        "booth",
        "program",
        "product",
        "exhibitor_profile",
        "exhibitor_participation",
        "exhibitor_business_type",
        "buyer_preference",
        "profile_attribute",
        "exhibitor",
    ):
        op.drop_table(table, schema="exhibition")
