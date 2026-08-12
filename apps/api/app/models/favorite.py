"""interaction.favorite - persistent saved-items ("watchlist") model (CONTRACT-005).

Scope note (CONTRACT-005, CONTRACTS track)
--------------------------------------------
This file publishes ONLY the model (plus its Alembic migration, in the same commit). It does
not define, and must not be imported by, any router/schema/service - the CRUD API
(``GET/POST/DELETE /me/favorites``) is BACKEND-009's separate, downstream task per
``.harness/backlog.yaml``. See
``.harness/handoffs/contracts/change-request-005-favorites.md`` for the full design record and
the BACKEND-009 handoff notes.

Not the same table as InteractionEvent's FAVORITE_ADD/FAVORITE_REMOVE
------------------------------------------------------------------------
``app/models/matching.py::InteractionEvent`` already lists ``FAVORITE_ADD``/``FAVORITE_REMOVE``
among its candidate ``event_type`` values (see that module's docstring, ~line 990) - that is an
append-only *behavioral analytics event log* (one row per click), already migrated (0008_
matching_runtime). This table is a different, already-distinct-in-db-erd concept: the persistent
"my saved items" list a user or guest could later list/query (docs/db-erd-table-spec.md §16.1).
An application may write both an ``InteractionEvent`` row and a row here when a user favorites
something (one records "it happened", the other records "it is still true") - that wiring is
BACKEND-009's job, not this file's. Do not merge or alias the two tables.

Authoritative schema: docs/db-erd-table-spec.md §16.1 "interaction.favorite".

Ownership boundary (db-erd §16.1)
------------------------------------
Exactly one of an authenticated user (``user_id``) or an anonymous guest (``guest_session_id``)
owns a favorite row: ``CHECK num_nonnulls(user_id, guest_session_id) = 1`` - never both, never
neither. This is stricter than ``InteractionEvent.subject_at_most_one`` (``<= 1``, which also
allows a subject-less system event) because a favorite is meaningless without an owner.

Duplicate-prevention / soft-delete policy
--------------------------------------------
db-erd §16.1: "인증·익명 각각 활성 partial unique를 적용한다" (apply an active partial unique
separately for the authenticated and anonymous cases). A given owner (user OR guest) may hold at
most one *active* (``deleted_at IS NULL``) favorite per ``recommendable_id`` within a tenant/
event - enforced by two partial unique indexes, one scoped to ``user_id IS NOT NULL`` and one to
``guest_session_id IS NOT NULL``, mirroring the exactly-one-of-four partial-unique family
``exhibition.recommendable`` already uses for its own target columns (``uq_recommendable_booth_id``
and siblings in ``app/models/matching.py``). Because both indexes are scoped to
``deleted_at IS NULL``, a prior soft-deleted row never blocks a fresh active favorite for the
same owner/recommendable pair - a visitor may unfavorite and later re-favorite the same item
without a unique violation, and the old deleted row and the new active row simply coexist.

Recommendable FK shape follows the established repo convention
------------------------------------------------------------------
Every existing table that targets ``exhibition.recommendable`` (``MatchResult``,
``InteractionEvent``, ``RecommendationImpression`` - all in ``app/models/matching.py``) uses a
three-column composite ``ForeignKeyConstraint(["tenant_id", "event_id", "recommendable_id"],
[...])`` into ``exhibition.recommendable``'s own ``(tenant_id, event_id, recommendable_id)``
unique boundary (``uq_recommendable_boundary_id``), not a bare single-column FK on
``recommendable_id`` alone - this keeps a favorite's target inside the same tenant/event it was
created in. This file follows that exact convention.

``match_result_id`` is optional
----------------------------------
Not every favorite originates from a specific recommendation - a visitor may favorite something
found through free-text/category search (``source = 'SEARCH'``) with no ``match_result_id`` at
all. ``match_result_id`` is therefore nullable. Per db-erd §16.1's column list it is a plain
single-column FK to ``matching.match_result.match_result_id`` - that column is already a
standalone primary key, so a composite tenant/event boundary FK is unnecessary (the same pattern
``app/models/matching.py::MatchResult.directional_policy_version_id`` uses for its own
single-column FK into another PK-only column).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_EXHIBITION, SCHEMA_INTERACTION, SCHEMA_MATCHING, Base
from app.models.common import new_uuid7

#: db-erd-table-spec.md §16.1: "source | VARCHAR(20) | SEARCH, RECOMMENDATION".
FAVORITE_SOURCES: tuple[str, ...] = ("SEARCH", "RECOMMENDATION")


class Favorite(Base):
    """interaction.favorite - db-erd-table-spec.md §16.1.

    See the module docstring for the full ownership/duplicate/soft-delete policy this table's
    constraints enforce.
    """

    __tablename__ = "favorite"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_favorite_event_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "recommendable_id"],
            [
                f"{SCHEMA_EXHIBITION}.recommendable.tenant_id",
                f"{SCHEMA_EXHIBITION}.recommendable.event_id",
                f"{SCHEMA_EXHIBITION}.recommendable.recommendable_id",
            ],
            name="fk_favorite_recommendable_boundary",
        ),
        # db-erd §16.1: "CHECK num_nonnulls(user_id, guest_session_id) = 1" - exactly one owner,
        # never both, never neither (contrast InteractionEvent.subject_at_most_one, which is
        # "<= 1" and allows a subject-less system event).
        CheckConstraint(
            "num_nonnulls(user_id, guest_session_id) = 1",
            name="subject_exactly_one",
        ),
        CheckConstraint(
            "source IN ('SEARCH', 'RECOMMENDATION')",
            name="source_allowed",
        ),
        # db-erd §16.1: "인증·익명 각각 활성 partial unique를 적용한다" - one active favorite per
        # owner+recommendable, scoped separately per owner type so guest and user activity never
        # collide with each other, and a prior soft-delete never blocks a fresh re-favorite.
        Index(
            "uq_favorite_active_user_recommendable",
            "tenant_id",
            "event_id",
            "user_id",
            "recommendable_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND user_id IS NOT NULL"),
        ),
        Index(
            "uq_favorite_active_guest_recommendable",
            "tenant_id",
            "event_id",
            "guest_session_id",
            "recommendable_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND guest_session_id IS NOT NULL"),
        ),
        # Lookup indexes for the eventual BACKEND-009 "list my favorites" query - mirrors the
        # ix_recommendation_impression_user_time / _guest_time pair in app/models/matching.py.
        Index("ix_favorite_user_created", "tenant_id", "event_id", "user_id", "created_at"),
        Index(
            "ix_favorite_guest_created",
            "tenant_id",
            "event_id",
            "guest_session_id",
            "created_at",
        ),
        {"schema": SCHEMA_INTERACTION},
    )

    favorite_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("profile.user_account.user_id"), nullable=True
    )
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profile.guest_session.guest_session_id"),
        nullable=True,
    )
    recommendable_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    match_result_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_result.match_result_id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
