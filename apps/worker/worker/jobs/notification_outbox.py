"""notification_outbox job - drains `integration.outbox_event` rows.

Per the merge plan's STEP 30, this is the only worker job with zero blockers: main's
`integration.outbox_event` / `integration.notification_delivery` /
`integration.notification_attempt` tables and their SKIP LOCKED claim/mark primitives
already exist and are fully tested (`apps/api/app/services/notification_delivery.py`,
covered by `apps/api/tests/test_notification_delivery.py`). This module is the
orchestration loop around those primitives: claim a batch, load each delivery's
identity/event, dispatch, and mark the outbox row terminal or retryable.

Why this job imports `app.*` directly, unlike every other job in this package
------------------------------------------------------------------------------
The other ported jobs (`analytics_aggregation`, `data_quality`, `document_parsing`,
`indexing`, `cache_invalidation`) are pure-function cores behind a persistence Protocol
(`MetricSink`, `SegmentStore`, `IndexingBackend`, `CacheBackend`) because the worktree they
came from deliberately had zero dependency on `apps/api`. This job has no such boundary to
preserve: the entire job IS "read/write apps/api's own outbox/notification tables through
apps/api's own service functions" - there is nothing pure to extract, and
`app/services/notification_delivery.py` already owns 100% of the SQL. Re-declaring a
Protocol here would just add an unimplemented layer between this job and the one
implementation it will ever have.

Attempt cap / "give up" state
------------------------------
`app/models/integration.py::OUTBOX_STATUSES` is a DB `CHECK` constraint fixed at
`(PENDING, PROCESSING, PUBLISHED, FAILED)`. Widening it to add a `GIVEN_UP` value is an
Alembic migration, and the entire Alembic chain is Foundation-phase-owned (see the merge
plan's hard rules) - so a row that has exhausted `MAX_OUTBOX_ATTEMPTS` stays `status=FAILED`
(a legitimate terminal state already in the CHECK) but has its `next_attempt_at` pushed
`GIVEN_UP_HORIZON` into the future so `claim_notification_outbox`'s own claim query
(`status IN (PENDING, FAILED) AND next_attempt_at <= now`) never reclaims it again. An
operator can still find given-up rows with `status='FAILED' AND attempt_count >=
MAX_OUTBOX_ATTEMPTS`. This is a worker-level convention layered on top of main's schema,
not a schema change.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from app.core.config import Settings
from app.models.core import Event
from app.models.identity import UserIdentity
from app.models.integration import NotificationDelivery
from app.services.notification_delivery import (
    NotificationProvider,
    NotificationReleaseGate,
    claim_notification_outbox,
    dispatch_notification,
    mark_outbox_failed,
    mark_outbox_published,
)
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("worker.jobs.notification_outbox")

#: Outbox rows enqueued by enqueue_recommendation_ready carry exactly
#: {"notification_delivery_id": "<uuid>"} (see that function's OUTBOX_SCHEMA_VERSION) -
#: never raw contact info. claim_notification_outbox already filters on this event_type;
#: the check below is a defensive second gate, never a silent dispatch of an unknown kind.
NOTIFICATION_DELIVERY_REQUESTED = "NOTIFICATION_DELIVERY_REQUESTED"

#: After this many claim attempts (OutboxEvent.attempt_count, incremented once per claim by
#: claim_notification_outbox itself), a still-failing row is given up on rather than retried
#: forever. See module docstring "Attempt cap / give up state".
MAX_OUTBOX_ATTEMPTS = 8

#: Exponential backoff for retry scheduling: attempt 1 -> 30s, 2 -> 60s, 3 -> 120s, ...,
#: capped at one hour so a flaky provider is retried at a bounded cadence.
RETRY_BACKOFF_BASE_SECONDS = 30
RETRY_BACKOFF_CAP_SECONDS = 3_600

#: How far into the future a permanently given-up row's next_attempt_at is pushed - see
#: module docstring. Ten years is "never" for an MVP-scale operational deployment without
#: needing a sentinel NULL that claim_notification_outbox would treat as "due now".
GIVEN_UP_HORIZON = timedelta(days=3_650)

#: Default claim batch size / lease, matching claim_notification_outbox's own defaults.
DEFAULT_LIMIT = 100
DEFAULT_LEASE_SECONDS = 60


def retry_delay_seconds(attempt_count: int) -> int:
    """Pure backoff formula, independently testable without a DB."""

    delay = RETRY_BACKOFF_BASE_SECONDS * (2 ** max(0, attempt_count - 1))
    return min(delay, RETRY_BACKOFF_CAP_SECONDS)


def is_given_up(attempt_count: int) -> bool:
    """Pure attempt-cap predicate, independently testable without a DB."""

    return attempt_count >= MAX_OUTBOX_ATTEMPTS


@dataclass(frozen=True, slots=True)
class OutboxDrainResult:
    claimed: int
    published: int
    failed: int
    given_up: int
    skipped_missing_row: int


def _retry_or_give_up(row, *, attempt_count: int, current_time: datetime) -> bool:
    """Mark ``row`` FAILED, either scheduled for retry or parked as given-up.

    Returns True if the row was given up on (for the caller's result tally).
    """

    if is_given_up(attempt_count):
        mark_outbox_failed(row, retry_at=current_time + GIVEN_UP_HORIZON)
        return True
    mark_outbox_failed(
        row, retry_at=current_time + timedelta(seconds=retry_delay_seconds(attempt_count))
    )
    return False


async def drain_notification_outbox(
    db: AsyncSession,
    *,
    providers: dict[str, NotificationProvider] | None = None,
    release_gate: NotificationReleaseGate | None = None,
    settings: Settings | None = None,
    limit: int = DEFAULT_LIMIT,
    lease_seconds: int = DEFAULT_LEASE_SECONDS,
    now: datetime | None = None,
) -> OutboxDrainResult:
    """One drain pass: claim due rows, dispatch each, mark terminal/retry.

    Safe to run from multiple worker replicas concurrently - inherits that guarantee
    entirely from ``claim_notification_outbox``'s own SKIP LOCKED claim. ``providers``
    defaults to an empty map (no channel configured -> every attempt records
    PROVIDER_NOT_CONFIGURED and the delivery ends FAILED, never silently "sent"); the real
    Alimtalk/SMS/email adapters are injected by the caller once approved, per
    app/services/notification_delivery.py's own module docstring. ``release_gate`` defaults
    to the fully-closed gate (fail-closed by construction, matching
    NotificationReleaseGate's own documented defaults).

    The caller owns the transaction boundary (commit/rollback) - this function only flushes,
    exactly like every other function in app/services/notification_delivery.py.
    """

    providers = providers or {}
    release_gate = release_gate or NotificationReleaseGate()
    current_time = now or datetime.now(UTC)

    rows = await claim_notification_outbox(
        db, limit=limit, lease_seconds=lease_seconds, now=current_time
    )

    published = 0
    failed = 0
    given_up = 0
    skipped_missing_row = 0

    for row in rows:
        if row.event_type != NOTIFICATION_DELIVERY_REQUESTED:
            if _retry_or_give_up(row, attempt_count=row.attempt_count, current_time=current_time):
                given_up += 1
            else:
                failed += 1
            continue

        delivery_id = row.payload.get("notification_delivery_id") if row.payload else None
        delivery = (
            await db.scalar(
                select(NotificationDelivery).where(
                    NotificationDelivery.notification_delivery_id == delivery_id
                )
            )
            if delivery_id
            else None
        )
        if delivery is None:
            logger.warning(
                "notification_outbox: no NotificationDelivery for outbox_event_id=%s",
                row.outbox_event_id,
            )
            skipped_missing_row += 1
            if _retry_or_give_up(row, attempt_count=row.attempt_count, current_time=current_time):
                given_up += 1
            else:
                failed += 1
            continue

        identity = await db.scalar(
            select(UserIdentity).where(UserIdentity.user_id == delivery.user_id)
        )
        event = await db.scalar(select(Event).where(Event.event_id == delivery.event_id))
        if identity is None or event is None:
            logger.warning(
                "notification_outbox: missing identity/event for delivery_id=%s",
                delivery.notification_delivery_id,
            )
            if _retry_or_give_up(row, attempt_count=row.attempt_count, current_time=current_time):
                given_up += 1
            else:
                failed += 1
            continue

        outcome = await dispatch_notification(
            db,
            delivery,
            identity=identity,
            event=event,
            providers=providers,
            release_gate=release_gate,
            settings=settings,
            now=current_time,
        )

        if outcome.sent:
            mark_outbox_published(row, now=current_time)
            published += 1
            continue

        if _retry_or_give_up(row, attempt_count=row.attempt_count, current_time=current_time):
            given_up += 1
        else:
            failed += 1

    await db.flush()
    return OutboxDrainResult(
        claimed=len(rows),
        published=published,
        failed=failed,
        given_up=given_up,
        skipped_missing_row=skipped_missing_row,
    )
