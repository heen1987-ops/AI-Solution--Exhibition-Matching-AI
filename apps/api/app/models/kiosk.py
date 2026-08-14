"""Anonymous, short-lived kiosk session and QR handoff ledger.

PROJECT_SCOPE.md and the redesign master spec (docs/vibe-coding-master-spec-v1.md, §17-26)
require the kiosk module to stay anonymous and short-lived: no signup, no phone/email
collection, no long-lived profile. This module intentionally defines *only* the columns
needed to (a) enforce a 60-120s inactivity TTL and (b) keep the minimal audit trail admin
stats (§ kiosk KPIs: session count, no-input auto-reset rate, QR handoff rate, ...) need
after the live Redis-backed session cache (app/services/kiosk.py) has already expired the
key. There is deliberately no name/phone/email/password/long-lived-preference column here -
that omission is the whole point of this file, not an oversight.

Redis (app/services/kiosk.py:RedisKioskStore) remains the source of truth for the *live*
session (fast TTL enforcement, in-flight search query/results) per db-erd-table-spec.md
3절 ("세션, 속도 제한, 추천 캐시, 부스상태 캐시" -> Redis). The tables below are the durable,
low-cardinality counterpart: one row per session/handoff, written alongside the Redis writes,
so a session's lifecycle survives the Redis TTL for audit/statistics purposes even though the
*enforcement* of "quiet -> reset" stays the frontend/worker's timer + this backend's expiry
check (docs/vibe-coding-master-spec-v1.md §24: "실제 타이머는 프론트/워커 책임, 백엔드는
만료시각 계산과 만료체크만").

The integration pass registers these models in ``app.models`` and publishes the
corresponding Alembic revision, so they are part of the canonical metadata.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_KIOSK, Base
from app.models.common import new_uuid7

#: Kiosk session lifecycle. ACTIVE -> HANDED_OFF (QR issued, screen resets for the next
#: visitor) | TIMED_OUT (backend-computed expiry reached) | CLOSED (explicit end-of-use).
KIOSK_SESSION_STATUSES: tuple[str, ...] = (
    "ACTIVE",
    "HANDED_OFF",
    "TIMED_OUT",
    "CLOSED",
)


class KioskSession(Base):
    """One row per anonymous kiosk session (docs/vibe-coding-master-spec-v1.md §38-39).

    No identity, phone, email, or profile columns exist here by design - the kiosk module
    must never collect them (PROJECT_SCOPE.md exclusions; §25 "키오스크에서 금지할 기능").
    """

    __tablename__ = "kiosk_session"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_kiosk_session_event_boundary",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'HANDED_OFF', 'TIMED_OUT', 'CLOSED')",
            name="status_allowed",
        ),
        Index(
            "ix_kiosk_session_kiosk_status_expiry",
            "kiosk_id",
            "status",
            "expires_at",
        ),
        {"schema": SCHEMA_KIOSK},
    )

    session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    #: Kiosk device/config code (docs §26 "kiosk_id"), not a person - matches
    #: KioskSessionCreateRequest.kiosk_id's pattern-validated free-form device code.
    kiosk_id: Mapped[str] = mapped_column(String(80), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Bumped on every kiosk interaction (session create, search). The 60-120s TTL window is
    #: always recomputed from this value - see `compute_session_expiry`.
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    #: Absolute wall-clock deadline; `is_session_expired` is the only expiry *check* the
    #: backend performs. Nothing here runs a background sweep - see module docstring.
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class KioskQrHandoff(Base):
    """Signed QR handoff record (docs/vibe-coding-master-spec-v1.md §23, §38-39).

    `selected_result_ids` stores only opaque search-result identifiers (see
    app/schemas/search.py:SearchResult.result_id, e.g. "exhibitor:<uuid>:booth:<uuid>") -
    never contact details. `token_hash` lets the API confirm a presented token was actually
    issued by this service without needing to keep the full token around.
    """

    __tablename__ = "kiosk_qr_handoff"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_kiosk_qr_handoff_event_boundary",
        ),
        {"schema": SCHEMA_KIOSK},
    )

    handoff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    kiosk_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_KIOSK}.kiosk_session.session_id"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    selected_result_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    #: Set the first (and only) time a guest claims the handoff on the guest web. This
    #: task does not implement the claim endpoint (that is USER_WEB's QR-guest-view work);
    #: the column exists now so that work does not need its own migration.
    claimed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


def compute_session_expiry(reference_time: datetime, timeout_seconds: int) -> datetime:
    """Derive the absolute expiry instant from a last-activity time + TTL.

    Pure function - this is the entirety of the backend's "만료시각 계산" responsibility
    (docs/vibe-coding-master-spec-v1.md §24). No timer, no background job.
    """

    return reference_time + timedelta(seconds=timeout_seconds)


def is_session_expired(expires_at: datetime, *, now: datetime | None = None) -> bool:
    """The backend's entire "만료체크" responsibility: has `expires_at` passed?"""

    current = now if now is not None else datetime.now(UTC)
    return expires_at <= current
