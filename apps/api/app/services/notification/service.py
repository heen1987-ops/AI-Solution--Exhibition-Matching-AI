"""Notification creation/dedup/frequency-cap/delivery pipeline (in-app INBOX half).

See ``app/services/notification/__init__.py`` for how this package relates to the outbound
provider fan-out in ``app/services/notification_delivery.py``, and for the mapping between the
two ``notification_type`` vocabularies.

Layering (mirrors app/services/document/*'s "pure core + storage boundary" split so everything
here is testable without a live Postgres, per the repo's test convention):

- ``BusinessEvent`` / ``NotificationService`` - storage-agnostic pipeline logic. This is where
  the track's binding rules live:
    1. Dedup: (tenant_id, notification_type, recipient_user_id, object_id, relevant_version)
       is checked before insert AND enforced by the repository (in-memory repo raises
       ``DuplicateNotificationError``, Postgres raises on ``uq_notifications_dedup_key`` and
       the SQLAlchemy repository translates that IntegrityError into the same error type) -
       firing the "same" business event twice never creates two notifications.
    2. Frequency cap: RECOMMENDATION_READY is capped at 1 per recipient per UTC day by
       default; rows whose resolved rule ``is_operational`` (OPERATOR_NOTICE) are exempt.
    3. IN_APP always created, in the same repository write as the notification row.
    4. EMAIL only attempted when the recipient's per-type preference is enabled AND a valid
       processing basis exists (an accepted, currently-effective ``NOTIFICATION_EMAIL``
       consent - see ``email_processing_basis_stmt``). Missing either produces a SKIPPED
       delivery row (reason PREFERENCE_DISABLED / CONSENT_MISSING), never an attempt.
    5. EMAIL failure can never remove/roll back the IN_APP record: the IN_APP write is
       committed in its own transaction before the email phase begins, and the whole email
       phase is additionally wrapped so no exception (adapter bug included) propagates past
       ``_attempt_email_delivery``; it only ever appends EMAIL delivery/attempt rows.

- ``NotificationRepository`` (Protocol) - the storage boundary.
  ``InMemoryNotificationRepository`` is the reference implementation used by this domain's own
  tests; ``SqlAlchemyNotificationRepository`` is the production implementation, built on the
  module-level ``*_stmt`` builder functions so tests can compile them and assert the WHERE
  clauses (same pattern as app/services/exhibitor_preference/service.py).

Every read path is scoped by (tenant_id, recipient_user_id), never recipient_user_id alone:
both ``ix_notifications_recipient_created`` and ``ix_notifications_recipient_unread`` lead
with tenant_id, so a tenant-less predicate cannot use either index, and a tenant-scoped
predicate is also the stricter isolation boundary.

"Status-change notifications only fire on an actual state change, never on re-reads" is
enforced structurally: nothing in this module (or the router) creates notifications from a
read path - creation happens only through ``handle_business_event``, whose callers are state
transitions (see triggers.py), and re-firing the same transition is absorbed by dedup rule 1.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Literal, Protocol

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import get_sessionmaker
from app.models.consent import ConsentPolicy, UserConsent
from app.models.notification import (
    NOTIFICATION_TYPES,
    Notification,
    NotificationChannelDelivery,
    NotificationChannelDeliveryAttempt,
    NotificationPreference,
    NotificationRule,
)
from app.services.notification.email_adapter import EmailAdapter, default_email_adapter

#: consent_policy.purpose value gating the EMAIL channel (free-string column by design - see
#: app/models/consent.py docstring; this value follows CONTRACTS-OPERATIONS §3.4's proposed
#: ``NOTIFICATION_EMAIL`` convention).
NOTIFICATION_EMAIL_CONSENT_PURPOSE = "NOTIFICATION_EMAIL"

#: Task spec: "one general-recommendation notification per recipient per day max". Persisted
#: NotificationRule rows (seeded in the migration) override these in production; the in-code
#: defaults keep the invariant enforced even before/without seed data.
DEFAULT_FREQUENCY_CAPS: dict[str, int] = {"RECOMMENDATION_READY": 1}

#: Task spec: "operational notices are exempt" from frequency caps.
DEFAULT_OPERATIONAL_TYPES: frozenset[str] = frozenset({"OPERATOR_NOTICE"})

#: Retry budget for the EMAIL channel (first synchronous attempt here + retries from the
#: worker's notification-delivery sweep).
MAX_EMAIL_ATTEMPTS = 3


class NotificationServiceError(Exception):
    """Base class for this module's typed errors."""


class DuplicateNotificationError(NotificationServiceError):
    """Raised by a repository when an insert violates the dedup key - the storage-level
    equivalent of Postgres raising on ``uq_notifications_dedup_key``."""


class UnknownNotificationTypeError(NotificationServiceError):
    pass


# ---------------------------------------------------------------------------
# Storage-agnostic record shapes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class BusinessEvent:
    """One business-side occurrence that may produce a notification.

    ``relevant_version`` semantics vary per type (see the model module docstring): a meeting's
    ``row_version``, a document's ``version_no``, a recommendation batch's calendar date, an
    operator notice's published version. It is part of the dedup key, so callers must only
    change it when the underlying state actually changed.
    """

    business_event_code: str
    notification_type: str
    tenant_id: uuid.UUID
    recipient_user_id: uuid.UUID
    title: str
    body: str
    event_id: uuid.UUID | None = None
    object_type: str | None = None
    object_id: uuid.UUID | None = None
    relevant_version: str | None = None
    data: dict | None = None


@dataclass
class NotificationRecord:
    notification_id: uuid.UUID
    tenant_id: uuid.UUID
    recipient_user_id: uuid.UUID
    notification_type: str
    title: str
    body: str
    created_at: datetime
    event_id: uuid.UUID | None = None
    object_type: str | None = None
    object_id: uuid.UUID | None = None
    relevant_version: str | None = None
    data_json: dict | None = None
    source_business_event_code: str | None = None
    is_operational: bool = False
    read_at: datetime | None = None

    @property
    def is_read(self) -> bool:
        return self.read_at is not None


@dataclass
class DeliveryRecord:
    notification_delivery_id: uuid.UUID
    notification_id: uuid.UUID
    channel: str
    status: str
    created_at: datetime
    skipped_reason: str | None = None
    failure_reason: str | None = None
    sent_at: datetime | None = None


@dataclass(frozen=True)
class AttemptRecord:
    notification_delivery_id: uuid.UUID
    attempt_number: int
    status: str
    attempted_at: datetime
    error_message: str | None = None


@dataclass(frozen=True)
class RuleResolution:
    notification_type: str
    frequency_cap_per_recipient_per_day: int | None
    is_operational: bool


@dataclass(frozen=True)
class NotificationOutcome:
    result: Literal["CREATED", "DUPLICATE", "SUPPRESSED_FREQUENCY_CAP"]
    notification: NotificationRecord | None
    #: "SENT" | "FAILED" | "SKIPPED_PREFERENCE_DISABLED" | "SKIPPED_CONSENT_MISSING" | None
    #: (None = no email phase ran because no notification was created).
    email_result: str | None = None


# ---------------------------------------------------------------------------
# Repository boundary
# ---------------------------------------------------------------------------


class NotificationRepository(Protocol):
    """Persistence boundary for the notification pipeline (async to match AsyncSession)."""

    # -- write side (creation pipeline) --
    async def find_by_dedup_key(
        self,
        *,
        tenant_id: uuid.UUID,
        notification_type: str,
        recipient_user_id: uuid.UUID,
        object_id: uuid.UUID | None,
        relevant_version: str | None,
    ) -> NotificationRecord | None: ...

    async def count_for_day(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        notification_type: str,
        day: date,
    ) -> int: ...

    async def get_rule(self, notification_type: str) -> RuleResolution | None: ...

    async def insert_notification_with_in_app(
        self, record: NotificationRecord, in_app: DeliveryRecord
    ) -> None: ...

    async def insert_delivery(self, delivery: DeliveryRecord) -> None: ...

    async def update_delivery(
        self,
        delivery_id: uuid.UUID,
        *,
        status: str,
        failure_reason: str | None = None,
        sent_at: datetime | None = None,
    ) -> None: ...

    async def insert_attempt(self, attempt: AttemptRecord) -> None: ...

    async def email_preference_enabled(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, notification_type: str
    ) -> bool: ...

    async def has_email_processing_basis(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime
    ) -> bool: ...

    # -- read side (/me/notifications*) --
    async def list_for_recipient(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        unread_only: bool,
        limit: int,
        before: datetime | None,
    ) -> list[NotificationRecord]: ...

    async def unread_count(
        self, *, tenant_id: uuid.UUID, recipient_user_id: uuid.UUID
    ) -> int: ...

    async def get_own(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        notification_id: uuid.UUID,
    ) -> NotificationRecord | None: ...

    async def mark_read(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        notification_id: uuid.UUID,
        now: datetime,
    ) -> datetime | None: ...

    async def mark_all_read(
        self, *, tenant_id: uuid.UUID, recipient_user_id: uuid.UUID, now: datetime
    ) -> int: ...

    async def get_email_preferences(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> dict[str, bool]: ...

    async def upsert_email_preference(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_type: str,
        email_enabled: bool,
    ) -> None: ...


# ---------------------------------------------------------------------------
# Statement builders (compiled/asserted by tests; used by the SQLAlchemy repository)
# ---------------------------------------------------------------------------


def dedup_lookup_stmt(
    *,
    tenant_id: uuid.UUID,
    notification_type: str,
    recipient_user_id: uuid.UUID,
    object_id: uuid.UUID | None,
    relevant_version: str | None,
) -> Select:
    """NULL-safe dedup lookup - mirrors ``uq_notifications_dedup_key``'s
    ``postgresql_nulls_not_distinct=True`` semantics (a NULL object_id matches a NULL
    object_id, unlike plain ``=``)."""

    object_clause = (
        Notification.object_id.is_(None)
        if object_id is None
        else Notification.object_id == object_id
    )
    version_clause = (
        Notification.relevant_version.is_(None)
        if relevant_version is None
        else Notification.relevant_version == relevant_version
    )
    return select(Notification).where(
        and_(
            Notification.tenant_id == tenant_id,
            Notification.notification_type == notification_type,
            Notification.recipient_user_id == recipient_user_id,
            object_clause,
            version_clause,
        )
    )


def frequency_count_stmt(
    *,
    tenant_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
    notification_type: str,
    day_start: datetime,
    day_end: datetime,
) -> Select:
    return select(func.count(Notification.notification_id)).where(
        and_(
            Notification.tenant_id == tenant_id,
            Notification.recipient_user_id == recipient_user_id,
            Notification.notification_type == notification_type,
            Notification.created_at >= day_start,
            Notification.created_at < day_end,
        )
    )


def email_processing_basis_stmt(
    *, tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime
) -> Select:
    """Latest NOTIFICATION_EMAIL consent decision for this user against a currently-effective
    policy. The caller checks ``accepted`` on the single returned row - taking the *latest*
    row (consent history is append-only, per app/models/consent.py) means a later withdrawal
    (accepted=False) correctly wins over an earlier grant."""

    return (
        select(UserConsent.accepted)
        .join(ConsentPolicy, UserConsent.consent_policy_id == ConsentPolicy.consent_policy_id)
        .where(
            and_(
                UserConsent.tenant_id == tenant_id,
                UserConsent.user_id == user_id,
                ConsentPolicy.purpose == NOTIFICATION_EMAIL_CONSENT_PURPOSE,
                ConsentPolicy.effective_from <= now,
                or_(
                    ConsentPolicy.effective_until.is_(None),
                    ConsentPolicy.effective_until >= now,
                ),
            )
        )
        .order_by(UserConsent.occurred_at.desc())
        .limit(1)
    )


def own_notifications_stmt(
    *,
    tenant_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
    unread_only: bool,
    before: datetime | None,
    limit: int,
) -> Select:
    """Every read path filters on (tenant_id, recipient_user_id) - own-notification access is
    a WHERE clause, never a post-filter, so a cross-user id can never load another user's row.
    tenant_id leads ``ix_notifications_recipient_created``/``ix_notifications_recipient_unread``
    and so must be part of the predicate for either index to be usable."""

    stmt = select(Notification).where(
        and_(
            Notification.tenant_id == tenant_id,
            Notification.recipient_user_id == recipient_user_id,
        )
    )
    if unread_only:
        stmt = stmt.where(Notification.read_at.is_(None))
    if before is not None:
        stmt = stmt.where(Notification.created_at < before)
    return stmt.order_by(Notification.created_at.desc()).limit(limit)


def unread_count_stmt(*, tenant_id: uuid.UUID, recipient_user_id: uuid.UUID) -> Select:
    return select(func.count(Notification.notification_id)).where(
        and_(
            Notification.tenant_id == tenant_id,
            Notification.recipient_user_id == recipient_user_id,
            Notification.read_at.is_(None),
        )
    )


def own_notification_stmt(
    *,
    tenant_id: uuid.UUID,
    recipient_user_id: uuid.UUID,
    notification_id: uuid.UUID,
) -> Select:
    return select(Notification).where(
        and_(
            Notification.notification_id == notification_id,
            Notification.tenant_id == tenant_id,
            Notification.recipient_user_id == recipient_user_id,
        )
    )


def rule_lookup_stmt(*, notification_type: str) -> Select:
    return (
        select(NotificationRule)
        .where(
            and_(
                NotificationRule.notification_type == notification_type,
                NotificationRule.active.is_(True),
            )
        )
        # Tenant-specific overrides would sort before the platform default (tenant_id NULL);
        # MVP resolves platform defaults only, so any active row for the type suffices.
        .order_by(NotificationRule.tenant_id.desc().nulls_last())
        .limit(1)
    )


# ---------------------------------------------------------------------------
# In-memory repository (reference implementation; enforces the same constraints)
# ---------------------------------------------------------------------------


@dataclass
class InMemoryNotificationRepository:
    """Test/reference implementation. Enforces the dedup unique constraint on insert (raises
    ``DuplicateNotificationError``) exactly like Postgres's ``uq_notifications_dedup_key``
    with nulls-not-distinct, so service-level tests exercise the same failure surface."""

    notifications: list[NotificationRecord] = field(default_factory=list)
    deliveries: list[DeliveryRecord] = field(default_factory=list)
    attempts: list[AttemptRecord] = field(default_factory=list)
    rules: dict[str, RuleResolution] = field(default_factory=dict)
    #: (tenant_id, user_id, notification_type) -> email_enabled
    preferences: dict[tuple[uuid.UUID, uuid.UUID, str], bool] = field(default_factory=dict)
    #: (tenant_id, user_id) -> has an accepted, effective NOTIFICATION_EMAIL consent
    email_consent_basis: set[tuple[uuid.UUID, uuid.UUID]] = field(default_factory=set)

    def _dedup_key(
        self, record: NotificationRecord
    ) -> tuple[uuid.UUID, str, uuid.UUID, uuid.UUID | None, str | None]:
        return (
            record.tenant_id,
            record.notification_type,
            record.recipient_user_id,
            record.object_id,
            record.relevant_version,
        )

    async def find_by_dedup_key(
        self,
        *,
        tenant_id: uuid.UUID,
        notification_type: str,
        recipient_user_id: uuid.UUID,
        object_id: uuid.UUID | None,
        relevant_version: str | None,
    ) -> NotificationRecord | None:
        key = (tenant_id, notification_type, recipient_user_id, object_id, relevant_version)
        for record in self.notifications:
            if self._dedup_key(record) == key:
                return record
        return None

    async def count_for_day(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        notification_type: str,
        day: date,
    ) -> int:
        return sum(
            1
            for record in self.notifications
            if record.tenant_id == tenant_id
            and record.recipient_user_id == recipient_user_id
            and record.notification_type == notification_type
            and record.created_at.astimezone(UTC).date() == day
        )

    async def get_rule(self, notification_type: str) -> RuleResolution | None:
        return self.rules.get(notification_type)

    async def insert_notification_with_in_app(
        self, record: NotificationRecord, in_app: DeliveryRecord
    ) -> None:
        if await self.find_by_dedup_key(
            tenant_id=record.tenant_id,
            notification_type=record.notification_type,
            recipient_user_id=record.recipient_user_id,
            object_id=record.object_id,
            relevant_version=record.relevant_version,
        ):
            raise DuplicateNotificationError(str(self._dedup_key(record)))
        self.notifications.append(record)
        self.deliveries.append(in_app)

    async def insert_delivery(self, delivery: DeliveryRecord) -> None:
        self.deliveries.append(delivery)

    async def update_delivery(
        self,
        delivery_id: uuid.UUID,
        *,
        status: str,
        failure_reason: str | None = None,
        sent_at: datetime | None = None,
    ) -> None:
        for delivery in self.deliveries:
            if delivery.notification_delivery_id == delivery_id:
                delivery.status = status
                delivery.failure_reason = failure_reason
                delivery.sent_at = sent_at
                return

    async def insert_attempt(self, attempt: AttemptRecord) -> None:
        self.attempts.append(attempt)

    async def email_preference_enabled(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, notification_type: str
    ) -> bool:
        # Missing row => False (opt-in default; see NotificationPreference docstring).
        return self.preferences.get((tenant_id, user_id, notification_type), False)

    async def has_email_processing_basis(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime
    ) -> bool:
        del now
        return (tenant_id, user_id) in self.email_consent_basis

    async def list_for_recipient(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        unread_only: bool,
        limit: int,
        before: datetime | None,
    ) -> list[NotificationRecord]:
        rows = [
            record
            for record in self.notifications
            if record.tenant_id == tenant_id
            and record.recipient_user_id == recipient_user_id
            and (not unread_only or record.read_at is None)
            and (before is None or record.created_at < before)
        ]
        rows.sort(key=lambda record: record.created_at, reverse=True)
        return rows[:limit]

    async def unread_count(
        self, *, tenant_id: uuid.UUID, recipient_user_id: uuid.UUID
    ) -> int:
        return sum(
            1
            for record in self.notifications
            if record.tenant_id == tenant_id
            and record.recipient_user_id == recipient_user_id
            and record.read_at is None
        )

    async def get_own(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        notification_id: uuid.UUID,
    ) -> NotificationRecord | None:
        for record in self.notifications:
            if (
                record.notification_id == notification_id
                and record.tenant_id == tenant_id
                and record.recipient_user_id == recipient_user_id
            ):
                return record
        return None

    async def mark_read(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        notification_id: uuid.UUID,
        now: datetime,
    ) -> datetime | None:
        record = await self.get_own(
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            notification_id=notification_id,
        )
        if record is None:
            return None
        if record.read_at is None:
            record.read_at = now
        return record.read_at

    async def mark_all_read(
        self, *, tenant_id: uuid.UUID, recipient_user_id: uuid.UUID, now: datetime
    ) -> int:
        marked = 0
        for record in self.notifications:
            if (
                record.tenant_id == tenant_id
                and record.recipient_user_id == recipient_user_id
                and record.read_at is None
            ):
                record.read_at = now
                marked += 1
        return marked

    async def get_email_preferences(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> dict[str, bool]:
        return {
            notification_type: self.preferences.get(
                (tenant_id, user_id, notification_type), False
            )
            for notification_type in NOTIFICATION_TYPES
        }

    async def upsert_email_preference(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_type: str,
        email_enabled: bool,
    ) -> None:
        self.preferences[(tenant_id, user_id, notification_type)] = email_enabled


# ---------------------------------------------------------------------------
# SQLAlchemy repository (production; thin - every query is a builder above)
# ---------------------------------------------------------------------------


def _record_from_model(row: Notification) -> NotificationRecord:
    return NotificationRecord(
        notification_id=row.notification_id,
        tenant_id=row.tenant_id,
        recipient_user_id=row.recipient_user_id,
        notification_type=row.notification_type,
        title=row.title,
        body=row.body,
        created_at=row.created_at,
        event_id=row.event_id,
        object_type=row.object_type,
        object_id=row.object_id,
        relevant_version=row.relevant_version,
        data_json=row.data_json,
        source_business_event_code=row.source_business_event_code,
        is_operational=row.is_operational,
        read_at=row.read_at,
    )


class SqlAlchemyNotificationRepository:
    """AsyncSession-backed implementation of ``NotificationRepository``.

    Transaction ownership (why this takes a sessionmaker, not a session)
    --------------------------------------------------------------------
    This repository opens and commits a SHORT-LIVED session of its OWN per operation instead
    of calling ``commit()`` on a caller-supplied ``AsyncSession``. Committing a request-scoped
    session from inside a service is not a private act: it also commits whatever partial work
    the caller had pending, which for a caller like ``approve_extraction`` (which fires a
    notification trigger mid-transaction) would publish half a state transition the moment the
    notification pipeline runs.

    Owning the boundary here is also what keeps the email-isolation guarantee real rather than
    incidental: ``insert_notification_with_in_app`` commits the notification + IN_APP delivery
    in a completed transaction of its own, so by the time ``_attempt_email_delivery`` runs, no
    email failure - and no caller-side rollback - can take the in-app record back. Four tests
    exist to protect exactly that property.

    Passing an ``AsyncSession`` here is a hard error rather than a silent behaviour change; see
    ``__init__``.
    """

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ) -> None:
        if isinstance(session_factory, AsyncSession):
            raise TypeError(
                "SqlAlchemyNotificationRepository owns its own transaction boundary and takes "
                "an async_sessionmaker, not an AsyncSession. Pass "
                "app.db.session.get_sessionmaker(), or omit the argument to use it."
            )
        self._session_factory = session_factory

    @asynccontextmanager
    async def _session_scope(self) -> AsyncIterator[AsyncSession]:
        """One short-lived, self-owned session per operation.

        Resolved lazily so constructing the repository never builds an engine - importing or
        instantiating this class must not require a reachable database (same rule as
        app/db/session.py's module docstring).
        """

        if self._session_factory is None:
            self._session_factory = get_sessionmaker()
        async with self._session_factory() as session:
            try:
                yield session
            except Exception:
                await session.rollback()
                raise

    async def find_by_dedup_key(self, **kwargs) -> NotificationRecord | None:
        async with self._session_scope() as session:
            result = await session.execute(dedup_lookup_stmt(**kwargs))
            row = result.scalars().first()
            return _record_from_model(row) if row else None

    async def count_for_day(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        notification_type: str,
        day: date,
    ) -> int:
        day_start = datetime(day.year, day.month, day.day, tzinfo=UTC)
        async with self._session_scope() as session:
            result = await session.execute(
                frequency_count_stmt(
                    tenant_id=tenant_id,
                    recipient_user_id=recipient_user_id,
                    notification_type=notification_type,
                    day_start=day_start,
                    day_end=day_start + timedelta(days=1),
                )
            )
            return int(result.scalar_one())

    async def get_rule(self, notification_type: str) -> RuleResolution | None:
        async with self._session_scope() as session:
            result = await session.execute(
                rule_lookup_stmt(notification_type=notification_type)
            )
            row = result.scalars().first()
            if row is None:
                return None
            return RuleResolution(
                notification_type=row.notification_type,
                frequency_cap_per_recipient_per_day=row.frequency_cap_per_recipient_per_day,
                is_operational=row.is_operational,
            )

    async def insert_notification_with_in_app(
        self, record: NotificationRecord, in_app: DeliveryRecord
    ) -> None:
        """Commits its own transaction - the durable boundary the email phase sits behind.

        A concurrent insert racing past ``find_by_dedup_key`` surfaces here as an
        ``IntegrityError`` on ``uq_notifications_dedup_key``; it is translated into the same
        ``DuplicateNotificationError`` the in-memory reference implementation raises so both
        implementations honour one Protocol contract and the service's DUPLICATE branch works
        against either.
        """

        async with self._session_scope() as session:
            session.add(
                Notification(
                    notification_id=record.notification_id,
                    tenant_id=record.tenant_id,
                    event_id=record.event_id,
                    recipient_user_id=record.recipient_user_id,
                    notification_type=record.notification_type,
                    object_type=record.object_type,
                    object_id=record.object_id,
                    relevant_version=record.relevant_version,
                    title=record.title,
                    body=record.body,
                    data_json=record.data_json,
                    source_business_event_code=record.source_business_event_code,
                    is_operational=record.is_operational,
                    created_at=record.created_at,
                )
            )
            session.add(
                NotificationChannelDelivery(
                    notification_delivery_id=in_app.notification_delivery_id,
                    notification_id=in_app.notification_id,
                    channel=in_app.channel,
                    status=in_app.status,
                    sent_at=in_app.sent_at,
                )
            )
            try:
                await session.commit()
            except IntegrityError as exc:
                await session.rollback()
                raise DuplicateNotificationError(str(record.notification_id)) from exc

    async def insert_delivery(self, delivery: DeliveryRecord) -> None:
        async with self._session_scope() as session:
            session.add(
                NotificationChannelDelivery(
                    notification_delivery_id=delivery.notification_delivery_id,
                    notification_id=delivery.notification_id,
                    channel=delivery.channel,
                    status=delivery.status,
                    skipped_reason=delivery.skipped_reason,
                    failure_reason=delivery.failure_reason,
                    sent_at=delivery.sent_at,
                )
            )
            await session.commit()

    async def update_delivery(
        self,
        delivery_id: uuid.UUID,
        *,
        status: str,
        failure_reason: str | None = None,
        sent_at: datetime | None = None,
    ) -> None:
        async with self._session_scope() as session:
            row = await session.get(NotificationChannelDelivery, delivery_id)
            if row is not None:
                row.status = status
                row.failure_reason = failure_reason
                row.sent_at = sent_at
                await session.commit()

    async def insert_attempt(self, attempt: AttemptRecord) -> None:
        async with self._session_scope() as session:
            session.add(
                NotificationChannelDeliveryAttempt(
                    notification_delivery_id=attempt.notification_delivery_id,
                    attempt_number=attempt.attempt_number,
                    status=attempt.status,
                    error_message=attempt.error_message,
                    attempted_at=attempt.attempted_at,
                )
            )
            await session.commit()

    async def email_preference_enabled(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, notification_type: str
    ) -> bool:
        async with self._session_scope() as session:
            result = await session.execute(
                select(NotificationPreference.email_enabled).where(
                    and_(
                        NotificationPreference.tenant_id == tenant_id,
                        NotificationPreference.user_id == user_id,
                        NotificationPreference.notification_type == notification_type,
                    )
                )
            )
            value = result.scalar_one_or_none()
            return bool(value) if value is not None else False

    async def has_email_processing_basis(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, now: datetime
    ) -> bool:
        async with self._session_scope() as session:
            result = await session.execute(
                email_processing_basis_stmt(tenant_id=tenant_id, user_id=user_id, now=now)
            )
            accepted = result.scalar_one_or_none()
            return bool(accepted)

    async def list_for_recipient(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        unread_only: bool,
        limit: int,
        before: datetime | None,
    ) -> list[NotificationRecord]:
        async with self._session_scope() as session:
            result = await session.execute(
                own_notifications_stmt(
                    tenant_id=tenant_id,
                    recipient_user_id=recipient_user_id,
                    unread_only=unread_only,
                    before=before,
                    limit=limit,
                )
            )
            return [_record_from_model(row) for row in result.scalars().all()]

    async def unread_count(
        self, *, tenant_id: uuid.UUID, recipient_user_id: uuid.UUID
    ) -> int:
        async with self._session_scope() as session:
            result = await session.execute(
                unread_count_stmt(
                    tenant_id=tenant_id, recipient_user_id=recipient_user_id
                )
            )
            return int(result.scalar_one())

    async def get_own(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        notification_id: uuid.UUID,
    ) -> NotificationRecord | None:
        async with self._session_scope() as session:
            result = await session.execute(
                own_notification_stmt(
                    tenant_id=tenant_id,
                    recipient_user_id=recipient_user_id,
                    notification_id=notification_id,
                )
            )
            row = result.scalars().first()
            return _record_from_model(row) if row else None

    async def mark_read(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        notification_id: uuid.UUID,
        now: datetime,
    ) -> datetime | None:
        async with self._session_scope() as session:
            result = await session.execute(
                own_notification_stmt(
                    tenant_id=tenant_id,
                    recipient_user_id=recipient_user_id,
                    notification_id=notification_id,
                )
            )
            row = result.scalars().first()
            if row is None:
                return None
            if row.read_at is None:
                row.read_at = now
                await session.commit()
            return row.read_at

    async def mark_all_read(
        self, *, tenant_id: uuid.UUID, recipient_user_id: uuid.UUID, now: datetime
    ) -> int:
        async with self._session_scope() as session:
            result = await session.execute(
                own_notifications_stmt(
                    tenant_id=tenant_id,
                    recipient_user_id=recipient_user_id,
                    unread_only=True,
                    before=None,
                    limit=10_000,
                )
            )
            rows = result.scalars().all()
            for row in rows:
                row.read_at = now
            if rows:
                await session.commit()
            return len(rows)

    async def get_email_preferences(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> dict[str, bool]:
        async with self._session_scope() as session:
            result = await session.execute(
                select(
                    NotificationPreference.notification_type,
                    NotificationPreference.email_enabled,
                ).where(
                    and_(
                        NotificationPreference.tenant_id == tenant_id,
                        NotificationPreference.user_id == user_id,
                    )
                )
            )
            stored = {row[0]: bool(row[1]) for row in result.all()}
        return {
            notification_type: stored.get(notification_type, False)
            for notification_type in NOTIFICATION_TYPES
        }

    async def upsert_email_preference(
        self,
        *,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        notification_type: str,
        email_enabled: bool,
    ) -> None:
        async with self._session_scope() as session:
            result = await session.execute(
                select(NotificationPreference).where(
                    and_(
                        NotificationPreference.tenant_id == tenant_id,
                        NotificationPreference.user_id == user_id,
                        NotificationPreference.notification_type == notification_type,
                    )
                )
            )
            row = result.scalars().first()
            if row is None:
                session.add(
                    NotificationPreference(
                        tenant_id=tenant_id,
                        user_id=user_id,
                        notification_type=notification_type,
                        email_enabled=email_enabled,
                    )
                )
            else:
                row.email_enabled = email_enabled
            await session.commit()


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


class NotificationService:
    def __init__(
        self,
        repository: NotificationRepository,
        email_adapter: EmailAdapter = default_email_adapter,
    ) -> None:
        self._repository = repository
        self._email_adapter = email_adapter

    async def handle_business_event(
        self, event: BusinessEvent, *, now: datetime | None = None
    ) -> NotificationOutcome:
        if event.notification_type not in NOTIFICATION_TYPES:
            raise UnknownNotificationTypeError(event.notification_type)
        now = now or datetime.now(UTC)

        # 1. Dedup - same business event twice never creates two notifications.
        existing = await self._repository.find_by_dedup_key(
            tenant_id=event.tenant_id,
            notification_type=event.notification_type,
            recipient_user_id=event.recipient_user_id,
            object_id=event.object_id,
            relevant_version=event.relevant_version,
        )
        if existing is not None:
            return NotificationOutcome(result="DUPLICATE", notification=existing)

        # 2. Frequency cap (operational rows exempt).
        rule = await self._resolve_rule(event.notification_type)
        if not rule.is_operational and rule.frequency_cap_per_recipient_per_day is not None:
            count = await self._repository.count_for_day(
                tenant_id=event.tenant_id,
                recipient_user_id=event.recipient_user_id,
                notification_type=event.notification_type,
                day=now.astimezone(UTC).date(),
            )
            if count >= rule.frequency_cap_per_recipient_per_day:
                return NotificationOutcome(
                    result="SUPPRESSED_FREQUENCY_CAP", notification=None
                )

        # 3. Create notification + IN_APP delivery atomically. A concurrent duplicate insert
        #    (race between the check in step 1 and this insert) surfaces as
        #    DuplicateNotificationError from the constraint - resolve it as DUPLICATE.
        record = NotificationRecord(
            notification_id=uuid.uuid4(),
            tenant_id=event.tenant_id,
            event_id=event.event_id,
            recipient_user_id=event.recipient_user_id,
            notification_type=event.notification_type,
            object_type=event.object_type,
            object_id=event.object_id,
            relevant_version=event.relevant_version,
            title=event.title,
            body=event.body,
            data_json=event.data,
            source_business_event_code=event.business_event_code,
            is_operational=rule.is_operational,
            created_at=now,
        )
        in_app = DeliveryRecord(
            notification_delivery_id=uuid.uuid4(),
            notification_id=record.notification_id,
            channel="IN_APP",
            # IN_APP is delivered by existing in the inbox - no async provider involved.
            status="SENT",
            sent_at=now,
            created_at=now,
        )
        try:
            await self._repository.insert_notification_with_in_app(record, in_app)
        except DuplicateNotificationError:
            existing = await self._repository.find_by_dedup_key(
                tenant_id=event.tenant_id,
                notification_type=event.notification_type,
                recipient_user_id=event.recipient_user_id,
                object_id=event.object_id,
                relevant_version=event.relevant_version,
            )
            return NotificationOutcome(result="DUPLICATE", notification=existing)

        # 4. EMAIL phase - fully isolated; can never undo step 3 (which is already committed
        #    in its own transaction; see SqlAlchemyNotificationRepository's docstring).
        email_result = await self._attempt_email_delivery(record, now=now)
        return NotificationOutcome(
            result="CREATED", notification=record, email_result=email_result
        )

    async def _resolve_rule(self, notification_type: str) -> RuleResolution:
        persisted = await self._repository.get_rule(notification_type)
        if persisted is not None:
            return persisted
        return RuleResolution(
            notification_type=notification_type,
            frequency_cap_per_recipient_per_day=DEFAULT_FREQUENCY_CAPS.get(
                notification_type
            ),
            is_operational=notification_type in DEFAULT_OPERATIONAL_TYPES,
        )

    async def _attempt_email_delivery(
        self, record: NotificationRecord, *, now: datetime
    ) -> str:
        """Preference/consent-gated EMAIL attempt. Never raises - any failure (including a
        misbehaving adapter that raises despite its contract) only ever produces a
        FAILED/SKIPPED EMAIL delivery row; the IN_APP record is already committed."""

        try:
            enabled = await self._repository.email_preference_enabled(
                tenant_id=record.tenant_id,
                user_id=record.recipient_user_id,
                notification_type=record.notification_type,
            )
            if not enabled:
                await self._repository.insert_delivery(
                    DeliveryRecord(
                        notification_delivery_id=uuid.uuid4(),
                        notification_id=record.notification_id,
                        channel="EMAIL",
                        status="SKIPPED",
                        skipped_reason="PREFERENCE_DISABLED",
                        created_at=now,
                    )
                )
                return "SKIPPED_PREFERENCE_DISABLED"

            basis = await self._repository.has_email_processing_basis(
                tenant_id=record.tenant_id, user_id=record.recipient_user_id, now=now
            )
            if not basis:
                await self._repository.insert_delivery(
                    DeliveryRecord(
                        notification_delivery_id=uuid.uuid4(),
                        notification_id=record.notification_id,
                        channel="EMAIL",
                        status="SKIPPED",
                        skipped_reason="CONSENT_MISSING",
                        created_at=now,
                    )
                )
                return "SKIPPED_CONSENT_MISSING"

            delivery = DeliveryRecord(
                notification_delivery_id=uuid.uuid4(),
                notification_id=record.notification_id,
                channel="EMAIL",
                status="PENDING",
                created_at=now,
            )
            await self._repository.insert_delivery(delivery)

            try:
                send_result = await self._email_adapter.send(
                    recipient_user_id=record.recipient_user_id,
                    subject=record.title,
                    body=record.body,
                )
                success = send_result.success
                error_message = send_result.error_message
            except Exception as exc:  # noqa: BLE001 - adapter contract says "never raise";
                # guard anyway: an adapter bug must not break the pipeline.
                success = False
                error_message = f"adapter raised {type(exc).__name__}"

            await self._repository.insert_attempt(
                AttemptRecord(
                    notification_delivery_id=delivery.notification_delivery_id,
                    attempt_number=1,
                    status="SUCCESS" if success else "FAILED",
                    error_message=None if success else error_message,
                    attempted_at=now,
                )
            )
            if success:
                await self._repository.update_delivery(
                    delivery.notification_delivery_id, status="SENT", sent_at=now
                )
                return "SENT"
            await self._repository.update_delivery(
                delivery.notification_delivery_id,
                status="FAILED",
                failure_reason=error_message or "send failed",
            )
            return "FAILED"
        except Exception:  # noqa: BLE001 - last-resort isolation (task spec: an email
            # provider outage must never remove the in-app record).
            return "FAILED"

    # -- read side ---------------------------------------------------------

    async def list_notifications(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        unread_only: bool = False,
        limit: int = 20,
        before: datetime | None = None,
    ) -> list[NotificationRecord]:
        return await self._repository.list_for_recipient(
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            unread_only=unread_only,
            limit=limit,
            before=before,
        )

    async def unread_count(
        self, *, tenant_id: uuid.UUID, recipient_user_id: uuid.UUID
    ) -> int:
        return await self._repository.unread_count(
            tenant_id=tenant_id, recipient_user_id=recipient_user_id
        )

    async def mark_read(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        notification_id: uuid.UUID,
        now: datetime | None = None,
    ) -> datetime | None:
        return await self._repository.mark_read(
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            notification_id=notification_id,
            now=now or datetime.now(UTC),
        )

    async def mark_all_read(
        self,
        *,
        tenant_id: uuid.UUID,
        recipient_user_id: uuid.UUID,
        now: datetime | None = None,
    ) -> int:
        return await self._repository.mark_all_read(
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            now=now or datetime.now(UTC),
        )

    async def get_email_preferences(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID
    ) -> dict[str, bool]:
        return await self._repository.get_email_preferences(
            tenant_id=tenant_id, user_id=user_id
        )

    async def update_email_preferences(
        self, *, tenant_id: uuid.UUID, user_id: uuid.UUID, updates: dict[str, bool]
    ) -> dict[str, bool]:
        for notification_type, email_enabled in updates.items():
            if notification_type not in NOTIFICATION_TYPES:
                raise UnknownNotificationTypeError(notification_type)
            await self._repository.upsert_email_preference(
                tenant_id=tenant_id,
                user_id=user_id,
                notification_type=notification_type,
                email_enabled=email_enabled,
            )
        return await self._repository.get_email_preferences(
            tenant_id=tenant_id, user_id=user_id
        )
