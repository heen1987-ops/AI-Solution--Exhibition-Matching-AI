"""interaction.check_in - QR check-in persistence model (BACKEND-016).

Scope note (BACKEND-016)
--------------------------------------------------------------------------------------------
Unlike CONTRACT-005/BACKEND-009's split (a CONTRACTS-track task publishes the model first, a
separate downstream task builds the router), BACKEND-016's ``.harness/backlog.yaml`` entry
owns only the router+schema paths and lists no prior model-publishing task. This file, its
Alembic migration, the schema, and the router are therefore built together in the same task -
a deliberate judgment call (nothing else owns the model and the feature is meaningless without
persistence), documented here and in the router/service module docstrings, not silently done.

Authoritative schema: docs/db-erd-table-spec.md §16.2 "interaction.check_in".
Authoritative wire contract: docs/frontend-backend-ai-interface-spec.md §13.1 "체크인".

Ownership is derived from visit_session, never duplicated here
--------------------------------------------------------------------------------------------
db-erd §16.2: "주체는 visit_session에서 파생하므로 user_id와 guest_session_id를 중복 저장하지
않는다" (the owner is derived from visit_session - do not duplicate user_id/guest_session_id
columns on this table). Unlike ``app/models/favorite.py::Favorite`` (which owns a direct
``CHECK num_nonnulls(user_id, guest_session_id) = 1``), this table has no owner columns at all -
``visit_session_id`` is the only subject link, and ``profile.visit_session`` itself already
carries the exactly-one-owner CHECK (``exactly_one_owner`` in ``app/models/profile.py``). A
caller resolves "whose check-in is this" by joining through ``visit_session``, never by reading
a column on this table directly.

visit_session / booth FK shape follows the established repo convention
--------------------------------------------------------------------------------------------
Every table that targets ``profile.visit_session`` from another schema
(``matching.recommendation_session``, ``matching.match_run``, ``matching.interaction_event`` -
all in ``app/models/matching.py``) uses a three-column composite
``ForeignKeyConstraint(["tenant_id", "event_id", "visit_session_id"], [...])`` into
``profile.visit_session``'s own ``(tenant_id, event_id, visit_session_id)`` unique boundary
(``uq_visit_session_boundary_id``), not a bare single-column FK - this keeps a check-in's
session inside the same tenant/event it was issued in. The same composite shape is used for
``booth_id`` against ``exhibition.booth``'s own ``uq_booth_boundary_id`` boundary. This file
follows both conventions exactly, mirroring ``app/models/favorite.py``'s
``fk_favorite_recommendable_boundary`` precedent.

``qr_id`` / ``qr_key_version`` are nullable
--------------------------------------------------------------------------------------------
db-erd §16.2 lists ``check_in_method | VARCHAR(20) | QR, MANUAL, STAFF``. Only the ``QR`` path
populates ``qr_id`` (FK to ``exhibition.booth_qr.booth_qr_id``) and ``qr_key_version`` (the
``BoothQr.key_version`` at verification time, so a later key rotation cannot retroactively
change what an already-recorded check-in was verified against) - a staff-recorded or
manually-coded check-in has no QR row to reference, so both columns are nullable. ``qr_id`` is a
plain single-column FK: ``exhibition.booth_qr.booth_qr_id`` is already a standalone PK (same
"single-column FK into another PK-only column" pattern ``favorite.py``'s ``match_result_id``
uses), and a QR's issuing booth is already re-derived and re-checked from ``booth_id`` at
check-in time regardless (see the router/service module docstring for why the *token* itself is
never trusted for booth/event identity - only the ``booth_qr`` row it hashes to is).

``match_result_id`` is optional
--------------------------------------------------------------------------------------------
Same rationale as ``favorite.py``: not every check-in originates from a specific recommendation
(a visitor can walk up to a booth QR without having seen a recommendation slate first).

5-minute duplicate window and Idempotency-Key are NOT modeled as columns/constraints here
--------------------------------------------------------------------------------------------
db-erd §16.2: "5분 중복방지는 트랜잭션 내 visit_session_id + booth_id advisory lock 후 최근
체크인을 조회한다" - this is a runtime query pattern (``pg_advisory_xact_lock`` + a bounded
``checked_in_at`` range query), not a schema constraint, because the window is time-relative
(there is no fixed-value UNIQUE index that can express "no more than one row per 5-minute
bucket" without pinning bucket boundaries the spec does not define). See
``app/services/checkin/service.py`` for the lock/query implementation, which mirrors the
``pg_advisory_xact_lock(hashtextextended(...))`` pattern already established in
``app/services/object_embeddings.py``.

"Idempotency-Key는 integration.idempotency_record에 별도 저장한다" - handled entirely by the
existing ``app/models/integration.py::IdempotencyRecord`` table (already used by
``app/api/v1/routers/webhooks.py`` for the same header). This module does not add a parallel
idempotency mechanism.

``client_event_id`` still gets a partial unique index here (in addition to the
``idempotency_record`` row) as a second, independent safety net against an offline-queued
duplicate landing under two different Idempotency-Key values (e.g. a client bug that
regenerates the key on retry but keeps the same ``client_event_id``) - belt-and-suspenders, not
a replacement for the idempotency_record path.
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
    Integer,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_EXHIBITION, SCHEMA_INTERACTION, SCHEMA_MATCHING, Base
from app.models.common import new_uuid7

#: db-erd-table-spec.md §16.2: "check_in_method | VARCHAR(20) | QR, MANUAL, STAFF".
CHECK_IN_METHODS: tuple[str, ...] = ("QR", "MANUAL", "STAFF")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class CheckIn(Base):
    """interaction.check_in - db-erd-table-spec.md §16.2.

    See the module docstring for the ownership-via-visit_session, FK-shape, and
    duplicate-window design rationale this table's constraints encode.
    """

    __tablename__ = "check_in"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_check_in_event_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "visit_session_id"],
            [
                "profile.visit_session.tenant_id",
                "profile.visit_session.event_id",
                "profile.visit_session.visit_session_id",
            ],
            name="fk_check_in_visit_session_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "booth_id"],
            [
                f"{SCHEMA_EXHIBITION}.booth.tenant_id",
                f"{SCHEMA_EXHIBITION}.booth.event_id",
                f"{SCHEMA_EXHIBITION}.booth.booth_id",
            ],
            name="fk_check_in_booth_boundary",
        ),
        CheckConstraint(
            f"check_in_method IN ({_in_list(CHECK_IN_METHODS)})",
            name="check_in_method_allowed",
        ),
        # 5-minute dedupe window lookup (db-erd §16.2): after the advisory lock, the service
        # queries the most recent check-in for this (tenant, event, visit_session, booth).
        Index(
            "ix_check_in_session_booth_time",
            "tenant_id",
            "event_id",
            "visit_session_id",
            "booth_id",
            "checked_in_at",
        ),
        # Belt-and-suspenders offline-dedupe safety net - see module docstring.
        Index(
            "uq_check_in_active_client_event",
            "tenant_id",
            "event_id",
            "client_event_id",
            unique=True,
            postgresql_where=text("client_event_id IS NOT NULL"),
        ),
        {"schema": SCHEMA_INTERACTION},
    )

    check_in_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    visit_session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), nullable=False
    )
    booth_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    match_result_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.match_result.match_result_id"),
        nullable=True,
    )
    check_in_method: Mapped[str] = mapped_column(
        String(20), nullable=False, default="QR"
    )
    activities: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    qr_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.booth_qr.booth_qr_id"),
        nullable=True,
    )
    qr_key_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    client_event_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    checked_in_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
