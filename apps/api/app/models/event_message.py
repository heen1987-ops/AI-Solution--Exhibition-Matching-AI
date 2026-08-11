"""Event-message (operator-authored campaign) domain SQLAlchemy models.

WAVE 2E ADMIN-NOTIFICATION. Two tables in the new ``event_message`` schema (added additively to
``app/db/base.py``, following the SCHEMA_KIOSK/SCHEMA_DOCUMENT/SCHEMA_NOTIFICATION precedent -
see ``app/db/base.py``'s ``SCHEMA_EVENT_MESSAGE`` comment for why this is a separate schema
from ``notification`` rather than new columns on that track's tables):

    1. event_message.event_message            - the authored message and its workflow state
    2. event_message.event_message_recipient   - fan-out ledger written when a message is
                                                  published (who was resolved as a target)

Why this is a separate domain from ``app/models/notification.py`` (BACKEND-NOTIFICATION)
------------------------------------------------------------------------------------------
That track's ``notification.notifications`` table is auto-generated, one row per recipient,
directly from real business events (meeting accepted, content review result, ...) - see that
module's own docstring. This track's job (per the harness task) is the opposite kind of thing:
an **operator authors** a message (title/body/channels/target audience/scheduled time) through
a DRAFT -> PREVIEWED -> APPROVED -> SCHEDULED/PUBLISHED -> COMPLETED workflow *before* any
recipient is known, and meeting-status notifications are explicitly excluded from this track's
scope. Modeling both as rows in the same table would conflate "system fact, one row already
addressed to one user" with "operator draft, not yet resolved to anyone" - different lifecycles,
different write paths, different actors. Hence a new schema and new tables rather than reusing
``notification.notifications``/``notification.notification_templates``.

Downstream delivery integration is an explicit TODO, not implemented here
---------------------------------------------------------------------------
Publishing an event message in this module only resolves the target audience and writes
``EventMessageRecipient`` rows (this track's own audit ledger of "who did we resolve as a
target at publish time"). It does **not** insert into ``notification.notifications`` or trigger
an actual send - that table/pipeline is owned by a different track (BACKEND-NOTIFICATION,
``app/services/notification/service.py``) and no integration contract between the two tracks
exists yet in this batch (the task spec itself anticipates this: "Call BACKEND-NOTIFICATION's
event-message endpoints if they exist ... a small addition ... is needed at integration"). See
``app/services/event_message/service.py`` module docstring for the exact TODO.

Small-audience suppression (repo-wide invariant, not specific to this track)
--------------------------------------------------------------------------------
This repo's harness rule is: "any aggregate with fewer than 5 underlying users must be
suppressed or shown as 'fewer than 5' rather than an exact number." ``preview_target_count``
below stores the true resolved count (the operator authoring *this exact message* is not a
third party being shown an aggregate - the system of record needs the real number for audit and
for the publish-time re-check), but every API-facing read path
(``app/schemas/event_message.py::EventMessagePreview``) suppresses the exact figure below 5 and
returns a "fewer than 5" display string plus a ``small_audience_warning`` flag instead. Never
add a new read path that echoes ``preview_target_count`` verbatim without going through that
schema's suppression logic.

Coarse-only targeting (repo-wide invariant, not specific to this track)
------------------------------------------------------------------------
``target_segment`` is a closed CHECK enum of six coarse, legitimate segments (see
``EVENT_MESSAGE_TARGET_SEGMENTS``). There is deliberately no column here for a sensitive
attribute (e.g. a profile_attribute value) or a fine-grained behavioral filter (e.g. "viewed
booth X 3+ times") - the task spec explicitly requires the admin UI and this schema to
"reject/disallow any UI affordance for sensitive-attribute-based or fine-grained-behavior-based
targeting". Enforced twice: the CHECK constraint here (defense in depth against any direct
writer bypassing the API), and ``app/services/event_message/targeting.py``'s
``validate_target_segment`` (the actual runtime guard the service/router call before ever
building a targeting query).

Multi-agent-safety note (mirrors app/models/exhibitor_preference.py's own docstring)
----------------------------------------------------------------------------------------
This module does not import other tracks' model modules (``app/models/profile.py``,
``app/models/identity.py``, ``app/models/core.py``, ``app/models/consent.py``) even though the
service layer built on top of it reads them read-only - cross-schema references here use the
"schema명.table명.column명" string ForeignKey path convention documented in ``app/db/base.py``,
same as ``app/models/meeting.py``/``app/models/notification.py``.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    SCHEMA_CORE,
    SCHEMA_EVENT_MESSAGE,
    SCHEMA_EXHIBITION,
    SCHEMA_PROFILE,
    Base,
)
from app.models.common import new_uuid7

_new_uuid = new_uuid7


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


#: Operator-authored operational message types (task spec, wave 2E ADMIN-NOTIFICATION).
#: Meeting-status types (MEETING_ACCEPTED etc, app/models/notification.py) are deliberately
#: absent - those are auto-generated by BACKEND-NOTIFICATION from real business events, never
#: operator-authored, and out of scope for this track.
EVENT_MESSAGE_TYPES: tuple[str, ...] = (
    "EVENT_OPERATION_NOTICE",
    "EVENT_START_REMINDER",
    "PROFILE_CONFIRMATION_REMINDER",
    "RECOMMENDATION_READY_NOTICE",
    "POST_EVENT_RESOURCE_NOTICE",
)

#: DRAFT -> PREVIEWED -> APPROVED -> SCHEDULED/PUBLISHED -> COMPLETED (task spec), plus
#: CANCELLED (an operator must be able to withdraw a SCHEDULED/APPROVED message before it
#: fires - not in the task spec's literal list but a safe, reversible addition documented here
#: rather than left unhandled; see app/services/event_message/workflow.py).
EVENT_MESSAGE_STATUSES: tuple[str, ...] = (
    "DRAFT",
    "PREVIEWED",
    "APPROVED",
    "SCHEDULED",
    "PUBLISHED",
    "COMPLETED",
    "CANCELLED",
)

#: Same two-channel set as app/models/notification.py's NOTIFICATION_CHANNELS - re-declared
#: rather than imported (repo convention, see that module's own docstring / this module's
#: module docstring "why a separate domain" section for why the two tracks do not share a
#: module).
EVENT_MESSAGE_CHANNELS: tuple[str, ...] = ("IN_APP", "EMAIL")

#: The only six targeting segments this track allows (task spec: "targeting restricted to
#: coarse, legitimate segments only"). SPECIFIC_ROLE additionally requires target_role_code.
EVENT_MESSAGE_TARGET_SEGMENTS: tuple[str, ...] = (
    "ALL_REGISTERED_USERS",
    "PROFILE_UNCONFIRMED",
    "RECOMMENDATION_READY",
    "BUYERS",
    "EXHIBITOR_STAFF",
    "SPECIFIC_ROLE",
)

#: Mirrors profile.role.role_code's fixed 5-value CHECK (app/models/identity.py) - re-declared
#: for the same reason as EVENT_MESSAGE_CHANNELS above (no cross-track model import).
EVENT_MESSAGE_TARGET_ROLE_CODES: tuple[str, ...] = (
    "VISITOR",
    "BUYER",
    "EXHIBITOR",
    "OPERATOR",
    "ADMIN",
)


class EventMessage(Base):
    """event_message.event_message - operator-authored campaign + its workflow state.

    ``preview_target_count``/``preview_consent_excluded_count``/``preview_duplicate_warning``/
    ``previewed_at`` are a snapshot captured the moment the message last transitioned into
    PREVIEWED (``app/services/event_message/service.py::preview_event_message``). Any edit to
    targeting or content while in PREVIEWED/APPROVED resets status back to DRAFT and clears the
    snapshot (module docstring of the workflow module) - so a stale snapshot can never be
    APPROVED/published against a description of the message that no longer matches it. Publish
    time re-resolves the audience fresh regardless (defense in depth, not just trusting the
    snapshot).
    """

    __tablename__ = "event_message"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [f"{SCHEMA_EXHIBITION}.event.tenant_id", f"{SCHEMA_EXHIBITION}.event.event_id"],
            name="fk_event_message_tenant_event",
        ),
        CheckConstraint(
            f"message_type IN ({_in_list(EVENT_MESSAGE_TYPES)})",
            name="message_type_allowed",
        ),
        CheckConstraint(
            f"status IN ({_in_list(EVENT_MESSAGE_STATUSES)})",
            name="status_allowed",
        ),
        CheckConstraint(
            f"target_segment IN ({_in_list(EVENT_MESSAGE_TARGET_SEGMENTS)})",
            name="target_segment_allowed",
        ),
        CheckConstraint(
            f"target_role_code IS NULL OR target_role_code IN "
            f"({_in_list(EVENT_MESSAGE_TARGET_ROLE_CODES)})",
            name="target_role_code_allowed",
        ),
        # SPECIFIC_ROLE must carry a role; every other segment must not (module docstring
        # "coarse-only targeting" - target_role_code is the only per-segment parameter this
        # domain allows at all, so this CHECK is the entire "no fine-grained parameter" fence).
        CheckConstraint(
            "(target_segment = 'SPECIFIC_ROLE') = (target_role_code IS NOT NULL)",
            name="target_role_code_matches_segment",
        ),
        # Internal route only: starts with a single "/" (not "//", which is a protocol-relative
        # URL that a browser resolves to an external origin exactly like "https://host" does)
        # and contains no "://" anywhere. Mirrors
        # app/services/event_message/content.py::validate_destination_screen exactly - defense
        # in depth against any writer that bypasses the service layer.
        CheckConstraint(
            "destination_screen LIKE '/%' AND destination_screen NOT LIKE '//%' "
            "AND destination_screen NOT LIKE '%://%'",
            name="destination_screen_is_internal_route",
        ),
        CheckConstraint("row_version > 0", name="row_version_positive"),
        Index("ix_event_message_tenant_event_status", "tenant_id", "event_id", "status"),
        {"schema": SCHEMA_EVENT_MESSAGE},
    )

    event_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    message_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")

    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # Author-entered markdown / small safe-HTML-subset content. Always passed through
    # app/services/event_message/content.py's sanitizer/validator before being written here -
    # this column never holds unvalidated input (defense in depth: even if a future writer
    # bypasses the service, nothing renders this without re-sanitizing on read too).
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # list[str] subset of EVENT_MESSAGE_CHANNELS, validated at the schema/service layer (not a
    # DB CHECK - Postgres cannot easily constrain "every element of a JSONB array is one of N
    # values" without a trigger, and this repo's convention for JSON payload columns elsewhere
    # - e.g. notification.notifications.data_json - is app-layer validation, not a DB CHECK).
    channels_json: Mapped[list] = mapped_column(JSONB, nullable=False)

    target_segment: Mapped[str] = mapped_column(String(30), nullable=False)
    target_role_code: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Deep-link destination inside the app. CHECK above enforces "starts with / and contains no
    # ://" so this column can never hold an absolute external URL (task spec: "no arbitrary
    # external URLs beyond an allowlist (internal routes are always fine)" - a destination
    # screen is never anything but an internal route in this domain, so the allowlist for it is
    # simply "must look like one").
    destination_screen: Mapped[str] = mapped_column(String(200), nullable=False)

    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Preview snapshot - see class docstring.
    preview_target_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preview_consent_excluded_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preview_duplicate_warning: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    previewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Actor stubs - same TODO as every other router in this repo (no session/JWT middleware
    # yet, see e.g. app/api/v1/routers/exhibitor_preference.py's module docstring). Not FK'd to
    # a role check here (that is the router/service's job) - just who acted, when.
    created_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"), nullable=True
    )
    approved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"), nullable=True
    )

    # Optimistic concurrency (mirrors profile.user_profile.row_version / meeting.py's pattern) -
    # two operators editing the same draft, or an approve racing an edit, must not silently
    # clobber each other.
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    recipients: Mapped[list[EventMessageRecipient]] = relationship(
        back_populates="event_message", cascade="all, delete-orphan"
    )


class EventMessageRecipient(Base):
    """event_message.event_message_recipient - fan-out ledger written at publish time.

    See module docstring "downstream delivery integration is an explicit TODO" - this table is
    this track's own record of who was resolved as a target when the message was published. It
    is not itself a delivery/send record (no channel/status columns) - actually dispatching to
    ``notification.notifications`` or an email provider is out of this track's owned paths.
    """

    __tablename__ = "event_message_recipient"
    __table_args__ = (
        UniqueConstraint(
            "event_message_id",
            "recipient_user_id",
            name="uq_event_message_recipient_message_user",
        ),
        Index("ix_event_message_recipient_message", "event_message_id"),
        {"schema": SCHEMA_EVENT_MESSAGE},
    )

    event_message_recipient_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    event_message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EVENT_MESSAGE}.event_message.event_message_id"),
        nullable=False,
    )
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
    )
    # True when this recipient was resolved into the target audience but excluded from the
    # EMAIL channel specifically for lack of a valid NOTIFICATION_EMAIL consent (mirrors
    # app/services/notification/service.py's own consent gate/purpose string - see
    # app/services/event_message/targeting.py). Never means "excluded from IN_APP" - IN_APP has
    # no consent gate anywhere in this repo (module docstring of notification.py).
    email_consent_excluded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    event_message: Mapped[EventMessage] = relationship(back_populates="recipients")


__all__ = [
    "EVENT_MESSAGE_CHANNELS",
    "EVENT_MESSAGE_STATUSES",
    "EVENT_MESSAGE_TARGET_ROLE_CODES",
    "EVENT_MESSAGE_TARGET_SEGMENTS",
    "EVENT_MESSAGE_TYPES",
    "EventMessage",
    "EventMessageRecipient",
]
