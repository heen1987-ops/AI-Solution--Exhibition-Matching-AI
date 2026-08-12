"""publish interaction.feedback (BACKEND-017)

Visit feedback persistence table declared by ``app/models/feedback.py::Feedback``.
Authoritative schema: docs/db-erd-table-spec.md §16.3 "interaction.feedback".

Scope note: BACKEND-017's ``.harness/backlog.yaml`` entry owns only router+schema files,
mirroring BACKEND-016's own precedent (0033_check_in) - no prior CONTRACTS-track task published
a feedback model, so this task also publishes the model + this migration together with the
router/schema/service - see ``app/models/feedback.py``'s module docstring for the full
rationale.

Ownership is derived from visit_session - no user_id/guest_session_id columns on this table (db-
erd §16.3, same "주체는 visit_session에서 파생" convention 0033_check_in already established).
``visit_session_id``/``recommendable_id`` use the same three-column composite FK shape into
their respective tables' own ``(tenant_id, event_id, <id>)`` unique boundaries that
0032_favorite's ``fk_favorite_recommendable_boundary`` and 0033_check_in's
``fk_check_in_visit_session_boundary`` already establish. ``match_result_id`` is nullable (not
every feedback event traces back to a specific recommendation).

``rating`` gets a DB-level CHECK (closed 3-value set per the wire contract's processing table).
``positive_reasons``/``negative_reasons`` are unconstrained JSONB at the DB layer (validated at
the Pydantic schema layer instead - see the model's docstring for why, mirroring
``check_in.activities``'s own precedent of no DB-level JSONB-array-element CHECK in this
codebase). ``comment_enc`` is a ``BYTEA`` column holding AES-GCM ciphertext only, never
plaintext (``app/core/auth.py::encrypt_secret``, purpose="feedback-comment").

No update/delete surface exists (db-erd §16.3: "원본 피드백은 수정하지 않는다") - no
``updated_at``/``deleted_at`` columns, matching ``Feedback``'s append-only design.

This migration adds two lookup indexes for future "feedback history"/"feedback per target"
queries and a belt-and-suspenders partial-unique index on ``client_event_id`` (see the model's
docstring for why that second safety net exists alongside the primary
``integration.idempotency_record``-based Idempotency-Key mechanism).

Revision ID: 0034_feedback
Revises: 0033_check_in
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.db.base import SCHEMA_EXHIBITION, SCHEMA_INTERACTION, SCHEMA_MATCHING

# revision identifiers, used by Alembic.
revision: str = "0034_feedback"
down_revision: str | None = "0033_check_in"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Literal copy of app/models/feedback.py::FEEDBACK_RATINGS - a migration is a historical record
# of the schema at the moment it was applied, so it must not import a value a later model edit
# could change underneath it (same convention as 0032_favorite's _SOURCES / 0033_check_in's
# _METHODS).
_RATINGS = ("VERY_RELEVANT", "RELEVANT", "NOT_RELEVANT")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("feedback_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("recommendable_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "match_result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_MATCHING}.match_result.match_result_id",
                name="fk_feedback_match_result_id_match_result",
            ),
            nullable=True,
        ),
        sa.Column("rating", sa.String(20), nullable=False),
        sa.Column(
            "positive_reasons",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column(
            "negative_reasons",
            postgresql.JSONB,
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("comment_enc", sa.LargeBinary(), nullable=True),
        sa.Column("client_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [f"{SCHEMA_EXHIBITION}.event.tenant_id", f"{SCHEMA_EXHIBITION}.event.event_id"],
            name="fk_feedback_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "visit_session_id"],
            [
                "profile.visit_session.tenant_id",
                "profile.visit_session.event_id",
                "profile.visit_session.visit_session_id",
            ],
            name="fk_feedback_visit_session_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                f"{SCHEMA_EXHIBITION}.recommendable.tenant_id",
                f"{SCHEMA_EXHIBITION}.recommendable.event_id",
                f"{SCHEMA_EXHIBITION}.recommendable.recommendable_id",
            ],
            name="fk_feedback_recommendable_boundary",
        ),
        # NOTE: name= wrapped in op.f() - see 0032_favorite's identical note on why an unwrapped
        # plain string gets double-run through NAMING_CONVENTION's ck template.
        sa.CheckConstraint(
            f"rating IN ({_in_list(_RATINGS)})",
            name=op.f("ck_feedback_feedback_rating_allowed"),
        ),
        schema=SCHEMA_INTERACTION,
    )
    op.create_index(
        "ix_feedback_visit_session_created",
        "feedback",
        ["tenant_id", "event_id", "visit_session_id", "created_at"],
        schema=SCHEMA_INTERACTION,
    )
    op.create_index(
        "ix_feedback_recommendable_created",
        "feedback",
        ["tenant_id", "event_id", "recommendable_id", "created_at"],
        schema=SCHEMA_INTERACTION,
    )
    op.create_index(
        "uq_feedback_active_client_event",
        "feedback",
        ["tenant_id", "event_id", "client_event_id"],
        unique=True,
        schema=SCHEMA_INTERACTION,
        postgresql_where=sa.text("client_event_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_feedback_active_client_event", table_name="feedback", schema=SCHEMA_INTERACTION
    )
    op.drop_index(
        "ix_feedback_recommendable_created", table_name="feedback", schema=SCHEMA_INTERACTION
    )
    op.drop_index(
        "ix_feedback_visit_session_created", table_name="feedback", schema=SCHEMA_INTERACTION
    )
    op.drop_table("feedback", schema=SCHEMA_INTERACTION)
