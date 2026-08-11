"""Notification domain SQLAlchemy models.

WAVE 2E BACKEND-NOTIFICATION. Six tables in the new ``notification`` schema (added to
``app/db/base.py`` additively, following the SCHEMA_DOCUMENT/SCHEMA_KIOSK precedent - see that
module's comment for the rationale):

    1. notification.notification_preferences        - per (user, notification_type) email opt-in
    2. notification.notification_templates           - title/body templates per (type, channel)
    3. notification.notification_rules               - which business event maps to which
                                                         notification_type, and its frequency cap
    4. notification.notifications                     - the notification itself (what GET
                                                         /me/notifications reads)
    5. notification.notification_deliveries           - one row per channel attempted for a
                                                         notification (IN_APP always, EMAIL
                                                         conditionally)
    6. notification.notification_delivery_attempts    - append-only retry/attempt log per
                                                         delivery row

No db-erd-table-spec.md section exists for this domain (grepped - no hits), so every column
here is this track's own reasonable design, not a transcription of an existing spec.

Why this schema exists at all
------------------------------
This track's job (per the harness task) is: "notification creation triggered by business events
(meeting accepted/time-proposed, content-review-requested/result, recommendation-ready,
event-day reminders, operator notices) with the dedup key from CONTRACTS-OPERATIONS
(notification_type + recipient_id + object_id + relevant_version) strictly enforced." No
``.harness/contracts/`` document named CONTRACTS-OPERATIONS exists in this repository (checked -
only .harness/contracts/openapi.json, event catalog, ontology, error codes exist, none of which
define a notification dedup key). Per this repo's Blocker Score rule (assumption, not a stop):
the impact is real but the direction is unambiguous - the task text itself spells out the exact
four-column dedup key - so this file takes that literal tuple
(tenant_id, notification_type, recipient_user_id, object_id, relevant_version; tenant_id added
for multi-tenant safety, does not change the semantics) as the canonical dedup key and enforces
it with a real UNIQUE constraint (not just application-layer checking) on
notification.notifications. See ``uq_notifications_dedup_key`` below.

Cross-schema references (read-only) to other tracks' owned tables
--------------------------------------------------------------------
This module references ``core.tenant``, ``exhibition.event`` and ``profile.user_account`` by
string FK path only (``app/db/base.py`` convention) - it does not import those model modules
(same multi-agent-safety practice as ``app/models/meeting.py``: "다른 스키마의 테이블은
app/db/base.py가 안내하는 대로 '스키마명.테이블명.컬럼명' 문자열 ForeignKey 경로만 사용하고
다른 모델 모듈을 import하지 않는다").

identity.user_identity (email_enc/email_hmac) is deliberately never referenced here, even
read-only: app/db/base.py's module docstring states "identity와 audit 스키마는 일반 서비스
역할의 직접 조회를 금지한다". This is why the EMAIL channel adapter
(app/services/notification/email_adapter.py) takes only a ``recipient_user_id`` and does not
resolve/decrypt a real address itself - address resolution behind that boundary is a TODO for
whichever track owns identity-schema access.

recipient_user_id is intentionally NOT nullable / never a guest_session_id
------------------------------------------------------------------------------
PROJECT_SCOPE.md explicitly excludes "kiosk long-term personalization" and "kiosk personal-data
entry" - kiosk sessions are anonymous and have no durable identity to notify later. Every
notification in this domain is addressed to a registered ``profile.user_account`` row.

Why relevant_version is a free string, not an integer/FK
------------------------------------------------------------
Different business events version their source object differently: a meeting has a numeric
``row_version``, a content review has an approval decision, a daily recommendation batch has a
calendar date, an operator notice may have no natural version at all. A single free-form string
column (populated by the triggering caller - see app/services/notification/triggers.py) lets the
same dedup mechanism serve all of them without a polymorphic FK. This mirrors the
"free string, documented candidate values, no CHECK" pattern already used for
``audit.audit_log.resource_type``/``integration.external_reference.internal_id`` (polymorphic,
no single referent) rather than the "closed CHECK enum" pattern used for actual application
state machines (``meeting.status`` etc).

notification_type IS a closed CHECK enum (unlike relevant_version)
------------------------------------------------------------------------
Unlike db-erd's "purpose"/"reason_code" free-string fields (which explicitly say "예시" / "등"
in their source prose), this track owns notification_type outright with no prior art to defer
to, and the frequency-cap/consent logic in app/services/notification/service.py needs to reason
about specific known types (e.g. "is this RECOMMENDATION_READY, which gets the once-per-day
cap"). So it is CHECK-constrained against NOTIFICATION_TYPES, the single source of truth also
imported by the schemas/service/router layers.
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
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    SCHEMA_CORE,
    SCHEMA_EXHIBITION,
    SCHEMA_NOTIFICATION,
    SCHEMA_PROFILE,
    Base,
)
from app.models.common import new_uuid7

_new_uuid = new_uuid7


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


#: Candidate business events named in this track's task: "meeting accepted/time-proposed,
#: content-review-requested/result, recommendation-ready, event-day reminders, operator
#: notices". CHECK-constrained (see module docstring "notification_type IS a closed CHECK
#: enum") - the service/trigger layer is the only place new values get added.
NOTIFICATION_TYPES: tuple[str, ...] = (
    "MEETING_ACCEPTED",
    "MEETING_TIME_PROPOSED",
    "CONTENT_REVIEW_REQUESTED",
    "CONTENT_REVIEW_RESULT",
    "RECOMMENDATION_READY",
    "EVENT_DAY_REMINDER",
    "OPERATOR_NOTICE",
)

#: "IN_APP always created; EMAIL only attempted if ..." (task spec). Room for future channels
#: (PUSH/SMS) without a migration to the CHECK values list itself - just extend this tuple.
NOTIFICATION_CHANNELS: tuple[str, ...] = ("IN_APP", "EMAIL")

NOTIFICATION_DELIVERY_STATUSES: tuple[str, ...] = ("PENDING", "SENT", "FAILED", "SKIPPED")

NOTIFICATION_DELIVERY_ATTEMPT_STATUSES: tuple[str, ...] = ("SUCCESS", "FAILED")


class NotificationPreference(Base):
    """notification.notification_preferences - per (tenant, user, notification_type) email
    opt-in.

    IN_APP has no toggle here - the task spec says "IN_APP always created", so there is nothing
    to gate. Default (no row present) is email_enabled=False: this is a privacy-preserving
    default (opt-in, not opt-out) consistent with the rest of this repo's consent-first stance
    (AGENTS.md invariant 6, PROJECT_SCOPE privacy stance) - a missing preference row must never
    silently be treated as "yes, email me".
    """

    __tablename__ = "notification_preferences"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "user_id",
            "notification_type",
            name="uq_notification_preferences_user_type",
        ),
        CheckConstraint(
            f"notification_type IN ({_in_list(NOTIFICATION_TYPES)})",
            name="notification_type_allowed",
        ),
        {"schema": SCHEMA_NOTIFICATION},
    )

    notification_preference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
    )
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    email_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class NotificationTemplate(Base):
    """notification.notification_templates - title/body templates per (type, channel).

    tenant_id nullable = platform-default template (applies to every tenant that has no
    tenant-specific override). Templates are simple ``str.format``-style placeholder text
    (rendering happens in the service layer, not here) - no templating engine dependency is
    added for MVP.
    """

    __tablename__ = "notification_templates"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "notification_type",
            "channel",
            name="uq_notification_templates_scope",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            f"notification_type IN ({_in_list(NOTIFICATION_TYPES)})",
            name="notification_type_allowed",
        ),
        CheckConstraint(
            f"channel IN ({_in_list(NOTIFICATION_CHANNELS)})", name="channel_allowed"
        ),
        {"schema": SCHEMA_NOTIFICATION},
    )

    notification_template_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"), nullable=True
    )
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    title_template: Mapped[str] = mapped_column(Text, nullable=False)
    body_template: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class NotificationRule(Base):
    """notification.notification_rules - maps a business event to a notification_type, and
    carries that type's frequency cap / operational-exemption flag.

    "Frequency limits: one general-recommendation notification per recipient per day max
    (operational notices are exempt)" (task spec) - ``frequency_cap_per_recipient_per_day`` and
    ``is_operational`` are how that rule is expressed and persisted (rather than hardcoded in
    Python), so operators can retune the cap without a code change. tenant_id nullable =
    platform-default rule, same override pattern as NotificationTemplate.
    """

    __tablename__ = "notification_rules"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "notification_type",
            "business_event_code",
            name="uq_notification_rules_scope",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            f"notification_type IN ({_in_list(NOTIFICATION_TYPES)})",
            name="notification_type_allowed",
        ),
        CheckConstraint(
            "frequency_cap_per_recipient_per_day IS NULL "
            "OR frequency_cap_per_recipient_per_day > 0",
            name="frequency_cap_positive",
        ),
        {"schema": SCHEMA_NOTIFICATION},
    )

    notification_rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"), nullable=True
    )
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Free string on purpose (module docstring pattern for polymorphic/non-enum event names) -
    # e.g. "MEETING_STATUS_CHANGED", "CONTENT_REVIEW_COMPLETED", "RECOMMENDATION_GENERATED",
    # "EVENT_DAY_REMINDER_DUE", "OPERATOR_NOTICE_PUBLISHED". A given notification_type may be
    # triggered by more than one business_event_code (e.g. MEETING_ACCEPTED could plausibly be
    # raised by both "MEETING_STATUS_CHANGED" and a bulk "MEETING_AUTO_CONFIRMED" event), so this
    # is a many-rows-per-type table, not a 1:1 lookup.
    business_event_code: Mapped[str] = mapped_column(String(100), nullable=False)
    # NULL = unlimited. Only RECOMMENDATION_READY has a cap by default (seeded in the migration);
    # every other type is unlimited unless an operator adds a rule row for it.
    frequency_cap_per_recipient_per_day: Mapped[int | None] = mapped_column(
        SmallInteger, nullable=True
    )
    # "operational notices are exempt" - OPERATOR_NOTICE rows should set this True so the
    # frequency cap check is skipped entirely regardless of frequency_cap_per_recipient_per_day.
    is_operational: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


class Notification(Base):
    """notification.notifications - the notification itself.

    ``uq_notifications_dedup_key`` is the literal enforcement of this track's required dedup key
    (module docstring: "notification_type + recipient_id + object_id + relevant_version",
    tenant_id added for multi-tenant safety). ``postgresql_nulls_not_distinct=True`` matters here
    - several notification_types legitimately have NULL object_id/relevant_version (e.g. a plain
    OPERATOR_NOTICE with no target object), and without nulls-not-distinct, Postgres would treat
    every NULL as unique and the dedup constraint would silently stop working for exactly the
    rows most likely to be re-fired (broadcast notices). app/services/notification/service.py is
    the only writer and always resolves-before-insert against this same key, but the DB
    constraint is the real guarantee (matches this repo's general pattern of application checks
    backed by a real constraint, e.g. meeting.py's EXCLUDE constraints).
    """

    __tablename__ = "notifications"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [f"{SCHEMA_EXHIBITION}.event.tenant_id", f"{SCHEMA_EXHIBITION}.event.event_id"],
            name="fk_notifications_tenant_event",
        ),
        CheckConstraint(
            f"notification_type IN ({_in_list(NOTIFICATION_TYPES)})",
            name="notification_type_allowed",
        ),
        UniqueConstraint(
            "tenant_id",
            "notification_type",
            "recipient_user_id",
            "object_id",
            "relevant_version",
            name="uq_notifications_dedup_key",
            postgresql_nulls_not_distinct=True,
        ),
        Index(
            "ix_notifications_recipient_created",
            "tenant_id",
            "recipient_user_id",
            "created_at",
        ),
        # Powers GET /me/notifications/unread-count without a full table scan (read_at IS NULL
        # is the "unread" predicate everywhere in this domain - see service.py).
        Index(
            "ix_notifications_recipient_unread",
            "tenant_id",
            "recipient_user_id",
            "read_at",
        ),
        {"schema": SCHEMA_NOTIFICATION},
    )

    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"), nullable=False
    )
    # Nullable - OPERATOR_NOTICE may be tenant-wide rather than tied to one event (mirrors
    # profile.consent_policy's "event_id NULL = tenant-wide" pattern; the composite FK above
    # only enforces when both columns are non-null, MATCH SIMPLE - see app/models/meeting.py's
    # module docstring for why that is safe here).
    event_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    recipient_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
    )
    notification_type: Mapped[str] = mapped_column(String(50), nullable=False)
    # Polymorphic target reference, same pattern as audit.audit_log.resource_type/resource_id -
    # no FK (the referent table varies by object_type and by notification_type).
    object_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    object_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # Part of the dedup key - see module docstring "Why relevant_version is a free string".
    relevant_version: Mapped[str | None] = mapped_column(String(50), nullable=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # Extra client-rendering payload (e.g. a deep-link path, a counterparty name already
    # resolved at creation time so the client doesn't need a second round-trip). Never holds
    # anything the object_type/object_id owner would not already let this recipient see.
    data_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # Which business_event_code produced this row (audit/debug trail back to notification_rules
    # - not itself part of the dedup key, since the same notification_type can legitimately be
    # raised by more than one business_event_code, per NotificationRule's own docstring).
    source_business_event_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # Snapshotted from the resolved NotificationRule at creation time (see service.py
    # resolve_notification_rule) so read paths never need to re-join notification_rules just to
    # know whether a row was exempt from the frequency cap.
    is_operational: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    deliveries: Mapped[list[NotificationChannelDelivery]] = relationship(
        back_populates="notification", cascade="all, delete-orphan"
    )


class NotificationChannelDelivery(Base):
    """notification.notification_deliveries - one row per channel attempted for a notification.

    Always exactly one IN_APP row (created in the same transaction as the Notification row - "IN
    APP always created"), and at most one EMAIL row (only when preference+consent gate passes -
    see service.py). "If EMAIL delivery fails, IN_APP must remain intact" is enforced by never
    writing to/deleting the IN_APP delivery row (or the parent Notification row) as part of the
    EMAIL attempt - see service.py's ``_attempt_email_delivery``, which is wrapped so that any
    exception there can never propagate back and roll back the already-committed IN_APP write.
    """

    __tablename__ = "notification_deliveries"
    __table_args__ = (
        UniqueConstraint(
            "notification_id", "channel", name="uq_notification_deliveries_notification_channel"
        ),
        CheckConstraint(
            f"channel IN ({_in_list(NOTIFICATION_CHANNELS)})", name="channel_allowed"
        ),
        CheckConstraint(
            f"status IN ({_in_list(NOTIFICATION_DELIVERY_STATUSES)})", name="status_allowed"
        ),
        {"schema": SCHEMA_NOTIFICATION},
    )

    notification_delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    notification_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NOTIFICATION}.notifications.notification_id"),
        nullable=False,
    )
    channel: Mapped[str] = mapped_column(String(10), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    # e.g. "PREFERENCE_DISABLED", "CONSENT_MISSING" - why an EMAIL row was never actually sent.
    skipped_reason: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # Safe, application-generated message only - never a raw provider exception (same rule as
    # integration.sync_row_error.error_message).
    failure_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    notification: Mapped[Notification] = relationship(back_populates="deliveries")
    attempts: Mapped[list[NotificationChannelDeliveryAttempt]] = relationship(
        back_populates="delivery", cascade="all, delete-orphan"
    )


class NotificationChannelDeliveryAttempt(Base):
    """notification.notification_delivery_attempts - append-only retry/attempt log.

    One row per send attempt (first synchronous attempt from service.py, plus any later retry
    from apps/worker/app/jobs/notification_delivery.py's sweep). Append-only, like
    interaction.meeting_status_history - never updated/deleted, so "retry/failure logging for
    delivery attempts" (task spec) has a real audit trail rather than only the delivery row's
    current status.
    """

    __tablename__ = "notification_delivery_attempts"
    __table_args__ = (
        UniqueConstraint(
            "notification_delivery_id",
            "attempt_number",
            name="uq_notification_delivery_attempts_number",
        ),
        CheckConstraint("attempt_number > 0", name="attempt_number_positive"),
        CheckConstraint(
            f"status IN ({_in_list(NOTIFICATION_DELIVERY_ATTEMPT_STATUSES)})",
            name="status_allowed",
        ),
        Index(
            "ix_notification_delivery_attempts_delivery",
            "notification_delivery_id",
            "attempt_number",
        ),
        {"schema": SCHEMA_NOTIFICATION},
    )

    notification_delivery_attempt_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    notification_delivery_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_NOTIFICATION}.notification_deliveries.notification_delivery_id"),
        nullable=False,
    )
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    delivery: Mapped[NotificationChannelDelivery] = relationship(back_populates="attempts")


__all__ = [
    "NOTIFICATION_CHANNELS",
    "NOTIFICATION_DELIVERY_ATTEMPT_STATUSES",
    "NOTIFICATION_DELIVERY_STATUSES",
    "NOTIFICATION_TYPES",
    "Notification",
    "NotificationChannelDelivery",
    "NotificationChannelDeliveryAttempt",
    "NotificationPreference",
    "NotificationRule",
    "NotificationTemplate",
]
