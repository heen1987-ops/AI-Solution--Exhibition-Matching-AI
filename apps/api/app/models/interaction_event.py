"""WAVE 2E BACKEND-EVENT-COLLECTION: client-reported UI event ingestion bookkeeping.

Important - prior art check (ASSUMPTION-003, this track's owned-paths note)
----------------------------------------------------------------------------
``interaction.interaction_event`` (the append-only, ``event_date``-partitioned behavior-event
log) and ``interaction.client_event_dedupe`` (the global per-tenant ``client_event_id``
idempotency claim table) **already exist** - both are defined in ``app/models/matching.py``
(``InteractionEvent``, ``InteractionClientEventDedupe``) and already published via the
``0008_matching_runtime`` Alembic revision (partition-parent table + default partition +
an append-only-enforcing trigger). ``app/services/behavior_learning.py`` and
``app/models/learning.py`` already consume rows written to that table.

This track therefore does **not** redefine those tables (that would collide with an already
zero-downtime-migrated shared table, per the "extend rather than collide" instruction). Instead:

  - ``app/services/interaction_event/ingestion.py`` writes new rows into the *existing*
    ``InteractionEvent`` + ``InteractionClientEventDedupe`` tables (imported from
    ``app.models.matching``), giving this track's client-beacon endpoint the same global
    dedup guarantee ``app/api/v1/routers/recommendations.py``'s ``/interactions/batch``
    already relies on - a ``client_event_id`` claimed by either endpoint is honoured by both.
  - This file adds only the one genuinely new table this track needs: an observability ledger
    for *rejected* client submissions (schema errors, disallowed kiosk identity fields, stale
    timestamps, oversized/rate-limited requests). No such table existed anywhere in the
    codebase before this track (grepped for "event_ingestion" repo-wide - no hits).

Privacy note (AGENTS.md "Never write personal data into logs, fixtures, or snapshots")
----------------------------------------------------------------------------------------
``detail`` must only ever contain an application-constructed, safe summary (e.g. which field
names failed validation) - never the raw exception text or the raw client payload, both of
which could echo back unmasked free-text search queries or other client-supplied values. See
``app/services/interaction_event/ingestion.py:_safe_validation_summary``. This mirrors the same
convention ``app/models/integration.py``'s ``SyncRowError.error_message`` documents.

No FK to ``exhibition.event``
------------------------------
Unlike ``InteractionEvent``, this table intentionally has **no** foreign-key boundary to
``exhibition.event`` (or any other table): a rejected submission may carry a ``tenant_id``/
``event_id`` that does not resolve to a real event at all (malformed client, replay attack,
fuzzing) - that is precisely the class of input this ledger exists to observe. Enforcing a
referential FK here would make exactly the failure modes we want to durably record raise a
second, unrelated FK violation instead of being written.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_INTERACTION, Base
from app.models.common import new_uuid7

#: Where the rejected submission claimed to originate from. Mirrors
#: ``app/schemas/interaction_event.py::EventSource`` (kept as a literal copy rather than an
#: import so this model module has no dependency on the schema layer).
EVENT_INGESTION_SOURCES: tuple[str, ...] = ("WEB", "KIOSK", "UNKNOWN")

#: Closed set of reasons this track's ingestion service records here. Kept in one place so a
#: new rejection path added later cannot silently write an unreviewed free-text reason.
EVENT_INGESTION_FAILURE_REASONS: tuple[str, ...] = (
    "SCHEMA_ERROR",
    "UNKNOWN_EVENT_TYPE",
    "KIOSK_IDENTITY_FIELD_FORBIDDEN",
    "TIMESTAMP_OUT_OF_RANGE",
    "IDEMPOTENCY_CONFLICT",
    "PERSIST_FAILED",
)


class EventIngestionFailure(Base):
    """interaction.event_ingestion_failure - WAVE2E observability ledger (new table).

    One row per *rejected* client event (not per duplicate - a duplicate replay is expected,
    successful, idempotent behaviour, not a failure, so it is not logged here). Operators use
    this to notice a misbehaving client build (e.g. a kiosk build that started sending
    ``user_id_hash``) without needing to grep application logs that may rotate away.
    """

    __tablename__ = "event_ingestion_failure"
    __table_args__ = (
        CheckConstraint(
            "source IN ('WEB', 'KIOSK', 'UNKNOWN')", name="source_allowed"
        ),
        CheckConstraint(
            "reason_code IN ("
            "'SCHEMA_ERROR', 'UNKNOWN_EVENT_TYPE', 'KIOSK_IDENTITY_FIELD_FORBIDDEN', "
            "'TIMESTAMP_OUT_OF_RANGE', 'IDEMPOTENCY_CONFLICT', 'PERSIST_FAILED'"
            ")",
            name="reason_code_allowed",
        ),
        Index(
            "ix_event_ingestion_failure_tenant_time", "tenant_id", "received_at"
        ),
        Index(
            "ix_event_ingestion_failure_reason_time", "reason_code", "received_at"
        ),
        {"schema": SCHEMA_INTERACTION},
    )

    event_ingestion_failure_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    #: Deliberately *not* a foreign key - see module docstring "No FK to exhibition.event".
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    event_id: Mapped[uuid.UUID | None] = mapped_column(PGUUID(as_uuid=True), nullable=True)
    source: Mapped[str] = mapped_column(String(10), nullable=False, default="UNKNOWN")
    #: Best-effort echo of the client's claimed idempotency key, for support/debugging
    #: correlation with client-side logs. Not a FK (the row was, by definition, rejected before
    #: any interaction_event/dedupe row was created for it).
    client_event_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True), nullable=True
    )
    event_type: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reason_code: Mapped[str] = mapped_column(String(40), nullable=False)
    #: Safe, application-constructed summary only - see module docstring privacy note.
    detail: Mapped[str | None] = mapped_column(String(300), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    #: The client's claimed ``occurred_at`` for TIMESTAMP_OUT_OF_RANGE diagnostics. Not used
    #: for anything but display - the authoritative clock is ``received_at``.
    claimed_occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    #: Free-form, allow-listed-key-only context echoed back for debugging (never raw free
    #: text - callers must pass already-sanitized/masked data, same discipline as
    #: InteractionEvent.context_json).
    context_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
