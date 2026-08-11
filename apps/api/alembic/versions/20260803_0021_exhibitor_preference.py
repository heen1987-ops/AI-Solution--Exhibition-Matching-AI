"""publish exhibitor public trade availability + preferred cooperation types

Revision ID: 0021_exhibitor_preference
Revises: 0020_interaction_domain
Create Date: 2026-08-02

WAVE2C BACKEND-EXHIBITOR-PREFERENCE. See ``app/models/exhibitor_preference.py`` module
docstring for why only these two tables are new (the rest of the track's field list is
already covered by ``exhibition.trade_condition``/``exhibition.trade_condition_term``/
``exhibition.buyer_preference`` from earlier migrations and is composed read-only by
``app/services/exhibitor_preference/service.py``).
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0021_exhibitor_preference"
down_revision: str | None = "0020_interaction_domain"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TRADE_AVAILABILITY_STATUSES = "'YES', 'NO', 'CONDITIONAL', 'NEGOTIABLE', 'UNKNOWN'"
_PREFERENCE_APPROVAL_STATUSES = "'DRAFT', 'APPROVED', 'REJECTED'"


def upgrade() -> None:
    # exhibition 스키마는 0002_exhibition 마이그레이션에서 이미 생성되어 있다.
    op.create_table(
        "exhibitor_trade_availability",
        sa.Column(
            "exhibitor_trade_availability_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("exhibitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "new_trade_available",
            sa.String(20),
            nullable=False,
            server_default="UNKNOWN",
        ),
        sa.Column(
            "meeting_available",
            sa.String(20),
            nullable=False,
            server_default="UNKNOWN",
        ),
        sa.Column(
            "approval_status", sa.String(20), nullable=False, server_default="DRAFT"
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["exhibitor_id"],
            ["exhibition.exhibitor.exhibitor_id"],
            name="fk_exhibitor_trade_availability_exhibitor_id_exhibitor",
        ),
        sa.UniqueConstraint(
            "exhibitor_id", name="uq_exhibitor_trade_availability_exhibitor"
        ),
        sa.CheckConstraint(
            f"new_trade_available IN ({_TRADE_AVAILABILITY_STATUSES})",
            name=op.f("ck_exhibitor_trade_availability_new_trade_available_allowed"),
        ),
        sa.CheckConstraint(
            f"meeting_available IN ({_TRADE_AVAILABILITY_STATUSES})",
            name=op.f("ck_exhibitor_trade_availability_meeting_available_allowed"),
        ),
        sa.CheckConstraint(
            f"approval_status IN ({_PREFERENCE_APPROVAL_STATUSES})",
            name=op.f("ck_exhibitor_trade_availability_approval_status_allowed"),
        ),
        schema="exhibition",
    )

    op.create_table(
        "exhibitor_cooperation_type",
        sa.Column(
            "exhibitor_cooperation_type_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
        ),
        sa.Column("exhibitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("taxonomy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["exhibitor_id"],
            ["exhibition.exhibitor.exhibitor_id"],
            name="fk_exhibitor_cooperation_type_exhibitor_id_exhibitor",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_exhibitor_cooperation_type_ontology_revision",
        ),
        sa.UniqueConstraint(
            "exhibitor_id",
            "taxonomy_version_id",
            "concept_id",
            name="uq_exhibitor_cooperation_type_concept",
        ),
        schema="exhibition",
    )
    op.create_index(
        "ix_exhibitor_cooperation_type_lookup",
        "exhibitor_cooperation_type",
        ["exhibitor_id", "active"],
        schema="exhibition",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_exhibitor_cooperation_type_lookup",
        table_name="exhibitor_cooperation_type",
        schema="exhibition",
    )
    op.drop_table("exhibitor_cooperation_type", schema="exhibition")
    op.drop_table("exhibitor_trade_availability", schema="exhibition")
