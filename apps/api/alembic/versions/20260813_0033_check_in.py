"""publish interaction.check_in (BACKEND-016)

QR check-in persistence table declared by ``app/models/checkin.py::CheckIn``.
Authoritative schema: docs/db-erd-table-spec.md §16.2 "interaction.check_in".

Scope note: BACKEND-016's ``.harness/backlog.yaml`` entry owns only router+schema files, unlike
CONTRACT-005/BACKEND-009's split (a separate CONTRACTS-track task publishes the model first).
No such prior task exists for check-in, so this task also publishes the model + this migration
together with the router/schema/service - see ``app/models/checkin.py``'s module docstring for
the full rationale.

Ownership is derived from visit_session - no user_id/guest_session_id columns on this table (db-
erd §16.2: "주체는 visit_session에서 파생하므로 user_id와 guest_session_id를 중복 저장하지
않는다"). ``visit_session_id``/``booth_id`` use the same three-column composite FK shape into
their respective tables' own ``(tenant_id, event_id, <id>)`` unique boundaries that every other
table targeting those tables already uses (0032_favorite's ``fk_favorite_recommendable_boundary``
precedent). ``qr_id``/``qr_key_version``/``match_result_id`` are nullable (not every check-in is
QR-sourced or recommendation-attributed).

The 5-minute dedupe window and Idempotency-Key handling are runtime query patterns
(``pg_advisory_xact_lock`` + a bounded range query, and ``integration.idempotency_record`` reuse
respectively - see ``app/services/checkin/service.py``), not schema objects; this migration adds
only the lookup index the dedupe query needs and a belt-and-suspenders partial-unique index on
``client_event_id`` (see the model's docstring for why that second safety net exists).

Revision ID: 0033_check_in
Revises: 0032_favorite
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.db.base import SCHEMA_EXHIBITION, SCHEMA_INTERACTION, SCHEMA_MATCHING

# revision identifiers, used by Alembic.
revision: str = "0033_check_in"
down_revision: str | None = "0032_favorite"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Literal copy of app/models/checkin.py::CHECK_IN_METHODS - a migration is a historical record
# of the schema at the moment it was applied, so it must not import a value a later model edit
# could change underneath it (same convention as 0032_favorite's _SOURCES).
_METHODS = ("QR", "MANUAL", "STAFF")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "check_in",
        sa.Column("check_in_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("booth_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "match_result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_MATCHING}.match_result.match_result_id",
                name="fk_check_in_match_result_id_match_result",
            ),
            nullable=True,
        ),
        sa.Column("check_in_method", sa.String(20), nullable=False, server_default="QR"),
        sa.Column("activities", postgresql.JSONB, nullable=False),
        sa.Column(
            "qr_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_EXHIBITION}.booth_qr.booth_qr_id",
                name="fk_check_in_qr_id_booth_qr",
            ),
            nullable=True,
        ),
        sa.Column("qr_key_version", sa.Integer(), nullable=True),
        sa.Column("client_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "checked_in_at",
            sa.DateTime(timezone=True),
            nullable=False,
        ),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [f"{SCHEMA_EXHIBITION}.event.tenant_id", f"{SCHEMA_EXHIBITION}.event.event_id"],
            name="fk_check_in_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "visit_session_id"],
            [
                "profile.visit_session.tenant_id",
                "profile.visit_session.event_id",
                "profile.visit_session.visit_session_id",
            ],
            name="fk_check_in_visit_session_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "booth_id"],
            [
                f"{SCHEMA_EXHIBITION}.booth.tenant_id",
                f"{SCHEMA_EXHIBITION}.booth.event_id",
                f"{SCHEMA_EXHIBITION}.booth.booth_id",
            ],
            name="fk_check_in_booth_boundary",
        ),
        # NOTE: name= wrapped in op.f() - see 0032_favorite's identical note on why an unwrapped
        # plain string gets double-run through NAMING_CONVENTION's ck template.
        sa.CheckConstraint(
            f"check_in_method IN ({_in_list(_METHODS)})",
            name=op.f("ck_check_in_check_in_method_allowed"),
        ),
        schema=SCHEMA_INTERACTION,
    )
    op.create_index(
        "ix_check_in_session_booth_time",
        "check_in",
        ["tenant_id", "event_id", "visit_session_id", "booth_id", "checked_in_at"],
        schema=SCHEMA_INTERACTION,
    )
    op.create_index(
        "uq_check_in_active_client_event",
        "check_in",
        ["tenant_id", "event_id", "client_event_id"],
        unique=True,
        schema=SCHEMA_INTERACTION,
        postgresql_where=sa.text("client_event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_check_in_active_client_event", table_name="check_in", schema=SCHEMA_INTERACTION
    )
    op.drop_index(
        "ix_check_in_session_booth_time", table_name="check_in", schema=SCHEMA_INTERACTION
    )
    op.drop_table("check_in", schema=SCHEMA_INTERACTION)
