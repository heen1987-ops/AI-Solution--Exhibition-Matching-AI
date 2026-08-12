"""publish interaction.favorite (CONTRACT-005)

Persistent saved-items ("watchlist") table declared by ``app/models/favorite.py::Favorite``.
Authoritative schema: docs/db-erd-table-spec.md §16.1 "interaction.favorite".

This is NOT the same table as ``interaction.interaction_event``'s ``FAVORITE_ADD``/
``FAVORITE_REMOVE`` event_type values (that append-only behavior log already exists, migrated in
0008_matching_runtime) - see ``app/models/favorite.py`` module docstring for the full
distinction. This revision creates only the new persistent list itself.

Ownership / duplicate / soft-delete policy (see the model's docstring for the full rationale):

  - ``CHECK num_nonnulls(user_id, guest_session_id) = 1`` - exactly one owner, never both,
    never neither.
  - ``source IN ('SEARCH', 'RECOMMENDATION')``.
  - Two partial UNIQUE indexes (one per owner type, both scoped to ``deleted_at IS NULL``) cap
    a given owner to one *active* favorite per ``recommendable_id`` within a tenant/event, while
    letting a soft-deleted row coexist with a later re-favorite of the same pair.

``recommendable_id`` uses the same three-column composite FK into ``exhibition.recommendable``
that ``matching.match_result``/``interaction.interaction_event``/
``interaction.recommendation_impression`` already use (0008_matching_runtime). ``match_result_id``
is a plain single-column FK (nullable) into ``matching.match_result.match_result_id`` - not every
favorite originates from a specific recommendation.

CONTRACTS-track scope note: this migration and its model publish ownership/schema only. The CRUD
API (``GET/POST/DELETE /me/favorites``) is BACKEND-009's separate downstream task.

Revision ID: 0032_favorite
Revises: 0031_integration_source_sync
Create Date: 2026-08-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from app.db.base import SCHEMA_EXHIBITION, SCHEMA_INTERACTION, SCHEMA_MATCHING

# revision identifiers, used by Alembic.
revision: str = "0032_favorite"
down_revision: str | None = "0031_integration_source_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Literal copy of app/models/favorite.py::FAVORITE_SOURCES. A migration is a historical record
# of the schema at the moment it was applied, so it must not import a value that a later edit to
# the model file could change underneath it (same convention as every other revision in this
# chain, e.g. 0030_event_ingestion_failure).
_SOURCES = ("SEARCH", "RECOMMENDATION")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "favorite",
        sa.Column("favorite_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "profile.user_account.user_id",
                name="fk_favorite_user_id_user_account",
            ),
            nullable=True,
        ),
        sa.Column(
            "guest_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "profile.guest_session.guest_session_id",
                name="fk_favorite_guest_session_id_guest_session",
            ),
            nullable=True,
        ),
        sa.Column("recommendable_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column(
            "match_result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_MATCHING}.match_result.match_result_id",
                name="fk_favorite_match_result_id_match_result",
            ),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [f"{SCHEMA_EXHIBITION}.event.tenant_id", f"{SCHEMA_EXHIBITION}.event.event_id"],
            name="fk_favorite_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                f"{SCHEMA_EXHIBITION}.recommendable.tenant_id",
                f"{SCHEMA_EXHIBITION}.recommendable.event_id",
                f"{SCHEMA_EXHIBITION}.recommendable.recommendable_id",
            ],
            name="fk_favorite_recommendable_boundary",
        ),
        # NOTE: name= is wrapped in op.f() deliberately - Alembic's op.create_table binds to
        # context.configure(target_metadata=Base.metadata) (see alembic/env.py), which carries
        # app/db/base.py's NAMING_CONVENTION. Its "ck"/"uq" templates contain %(constraint_name)s,
        # so an *unwrapped* plain string name gets run through the convention a second time and
        # doubled/truncated (e.g. plain "ck_favorite_subject_exactly_one" would compile to
        # "ck_favorite_ck_favorite_subject_exactly_one" - reproducible; see
        # 0030_event_ingestion_failure's compiled SQL, which has this exact latent bug). op.f()
        # marks the string as already-final so it is used verbatim, matching what
        # app/models/favorite.py::Favorite.__table__ actually computes (verified: ORM produces
        # exactly these two names from the short labels "subject_exactly_one"/"source_allowed").
        sa.CheckConstraint(
            "num_nonnulls(user_id, guest_session_id) = 1",
            name=op.f("ck_favorite_subject_exactly_one"),
        ),
        sa.CheckConstraint(
            f"source IN ({_in_list(_SOURCES)})",
            name=op.f("ck_favorite_source_allowed"),
        ),
        schema=SCHEMA_INTERACTION,
    )
    op.create_index(
        "uq_favorite_active_user_recommendable",
        "favorite",
        ["tenant_id", "event_id", "user_id", "recommendable_id"],
        unique=True,
        schema=SCHEMA_INTERACTION,
        postgresql_where=sa.text("deleted_at IS NULL AND user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_favorite_active_guest_recommendable",
        "favorite",
        ["tenant_id", "event_id", "guest_session_id", "recommendable_id"],
        unique=True,
        schema=SCHEMA_INTERACTION,
        postgresql_where=sa.text("deleted_at IS NULL AND guest_session_id IS NOT NULL"),
    )
    op.create_index(
        "ix_favorite_user_created",
        "favorite",
        ["tenant_id", "event_id", "user_id", "created_at"],
        schema=SCHEMA_INTERACTION,
    )
    op.create_index(
        "ix_favorite_guest_created",
        "favorite",
        ["tenant_id", "event_id", "guest_session_id", "created_at"],
        schema=SCHEMA_INTERACTION,
    )


def downgrade() -> None:
    op.drop_index("ix_favorite_guest_created", table_name="favorite", schema=SCHEMA_INTERACTION)
    op.drop_index("ix_favorite_user_created", table_name="favorite", schema=SCHEMA_INTERACTION)
    op.drop_index(
        "uq_favorite_active_guest_recommendable",
        table_name="favorite",
        schema=SCHEMA_INTERACTION,
    )
    op.drop_index(
        "uq_favorite_active_user_recommendable",
        table_name="favorite",
        schema=SCHEMA_INTERACTION,
    )
    op.drop_table("favorite", schema=SCHEMA_INTERACTION)
