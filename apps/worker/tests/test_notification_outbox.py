from __future__ import annotations

import base64
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
from app.core.auth import encrypt_secret
from app.core.config import Settings
from app.models.core import Event
from app.models.identity import UserIdentity
from app.models.integration import NotificationDelivery, OutboxEvent
from app.services.notification_delivery import (
    NotificationReleaseGate,
    ProviderMessage,
    ProviderResult,
)

from worker.jobs.notification_outbox import (
    GIVEN_UP_HORIZON,
    MAX_OUTBOX_ATTEMPTS,
    NOTIFICATION_DELIVERY_REQUESTED,
    drain_notification_outbox,
    is_given_up,
    retry_delay_seconds,
)


def _settings() -> Settings:
    return Settings(
        SECRET_KEY="worker-outbox-test-secret-key",
        AUTH_TOKEN_PEPPER="worker-outbox-test-token-pepper",
        AUTH_ENCRYPTION_KEY_B64=base64.urlsafe_b64encode(b"w" * 32).decode(),
    )


def _event() -> Event:
    return Event(
        event_id=uuid4(),
        tenant_id=uuid4(),
        event_code="baekdudaegan-2026",
        event_name="2026 백주대간 우리술 전시회",
        start_date=date(2026, 9, 1),
        end_date=date(2026, 9, 3),
        event_status="OPEN",
    )


def _identity(settings: Settings, user_id) -> UserIdentity:
    return UserIdentity(
        identity_id=uuid4(),
        user_id=user_id,
        name_enc=encrypt_secret("김희섭", purpose="identity-name", settings=settings),
        phone_enc=encrypt_secret("01012345678", purpose="identity-phone", settings=settings),
        email_enc=encrypt_secret(
            "visitor@example.com", purpose="identity-email", settings=settings
        ),
    )


def _delivery(settings: Settings, event: Event, user_id) -> NotificationDelivery:
    return NotificationDelivery(
        notification_delivery_id=uuid4(),
        tenant_id=event.tenant_id,
        event_id=event.event_id,
        user_id=user_id,
        recommendation_session_id=uuid4(),
        personal_access_link_id=uuid4(),
        notification_type="RECOMMENDATION_READY",
        message_class="INFORMATIONAL",
        template_code="RECOMMENDATION_READY_V1",
        template_parameters={"recommendation_count": 5},
        access_url_enc=encrypt_secret(
            "https://match.example/e/baekdudaegan-2026/my?token=opaque",
            purpose="notification-access-url",
            settings=settings,
        ),
        dedupe_key="recommendation-ready:test",
        status="PROCESSING",
    )


def _outbox_row(*, delivery_id, attempt_count: int = 1, now: datetime | None = None) -> OutboxEvent:
    now = now or datetime(2026, 8, 3, tzinfo=UTC)
    return OutboxEvent(
        outbox_event_id=uuid4(),
        tenant_id=uuid4(),
        event_id=uuid4(),
        aggregate_type="NOTIFICATION_DELIVERY",
        aggregate_id=delivery_id,
        event_type=NOTIFICATION_DELIVERY_REQUESTED,
        schema_version="notification-delivery-requested-v1.0",
        payload={"notification_delivery_id": str(delivery_id)},
        dedupe_key=f"outbox:{delivery_id}",
        status="PROCESSING",
        attempt_count=attempt_count,
        locked_until=now + timedelta(seconds=60),
        created_at=now - timedelta(minutes=1),
    )


class _Provider:
    def __init__(self, channel: str, *, accepted: bool) -> None:
        self.channel = channel
        self.provider_code = f"TEST_{channel}"
        self.accepted = accepted
        self.messages: list[ProviderMessage] = []

    async def send(self, message: ProviderMessage) -> ProviderResult:
        self.messages.append(message)
        return ProviderResult(
            self.accepted, provider_message_id=("msg-1" if self.accepted else None)
        )


def _live_gate() -> NotificationReleaseGate:
    return NotificationReleaseGate(
        catalog_ready=True, operator_release_approved=True, external_sending_enabled=True
    )


class _FakeDb:
    """Queue-based fake AsyncSession: `claim_result` seeds the claim_notification_outbox
    scalars().all() call; `scalar_queue` feeds successive db.scalar() calls in call order
    (delivery lookup, identity lookup, event lookup, then dispatch_notification's own
    sequence-offset lookup) - mirroring the _RecordingDb pattern in
    apps/api/tests/test_notification_delivery.py, extended to support the several distinct
    scalar() results one drain pass needs."""

    def __init__(self, *, claim_result: list[object] | None = None, scalar_queue: list[object] | None = None) -> None:
        self._claim_result = list(claim_result or [])
        self._scalar_queue = list(scalar_queue or [])
        self.rows: list[object] = []
        self.flushes = 0
        self.commits = 0

    async def scalar(self, statement):
        if self._scalar_queue:
            return self._scalar_queue.pop(0)
        return None

    async def scalars(self, statement):
        rows = self._claim_result

        class _Rows:
            def all(self_inner) -> list[object]:
                return rows

        return _Rows()

    def add(self, row: object) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------


def test_retry_delay_backs_off_exponentially_and_caps() -> None:
    assert retry_delay_seconds(1) == 30
    assert retry_delay_seconds(2) == 60
    assert retry_delay_seconds(3) == 120
    assert retry_delay_seconds(20) == 3_600  # capped


def test_is_given_up_threshold() -> None:
    assert is_given_up(MAX_OUTBOX_ATTEMPTS - 1) is False
    assert is_given_up(MAX_OUTBOX_ATTEMPTS) is True
    assert is_given_up(MAX_OUTBOX_ATTEMPTS + 5) is True


# ---------------------------------------------------------------------------
# drain_notification_outbox
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_drain_publishes_on_successful_dispatch() -> None:
    settings = _settings()
    event = _event()
    user_id = uuid4()
    delivery = _delivery(settings, event, user_id)
    identity = _identity(settings, user_id)
    row = _outbox_row(delivery_id=delivery.notification_delivery_id, attempt_count=1)

    db = _FakeDb(
        claim_result=[row],
        scalar_queue=[delivery, identity, event, None],  # None = no prior attempt sequence
    )
    provider = _Provider("KAKAO_ALIMTALK", accepted=True)

    result = await drain_notification_outbox(
        db,  # type: ignore[arg-type]
        providers={"KAKAO_ALIMTALK": provider},
        release_gate=_live_gate(),
        settings=settings,
        now=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert result.claimed == 1
    assert result.published == 1
    assert result.failed == 0
    assert result.given_up == 0
    assert row.status == "PUBLISHED"
    assert row.next_attempt_at is None
    assert len(provider.messages) == 1


@pytest.mark.asyncio
async def test_drain_retries_with_backoff_on_failed_dispatch() -> None:
    settings = _settings()
    event = _event()
    user_id = uuid4()
    delivery = _delivery(settings, event, user_id)
    identity = _identity(settings, user_id)
    row = _outbox_row(delivery_id=delivery.notification_delivery_id, attempt_count=2)
    now = datetime(2026, 8, 3, tzinfo=UTC)

    db = _FakeDb(claim_result=[row], scalar_queue=[delivery, identity, event, None])
    provider = _Provider("KAKAO_ALIMTALK", accepted=False)

    result = await drain_notification_outbox(
        db,  # type: ignore[arg-type]
        providers={"KAKAO_ALIMTALK": provider},
        release_gate=_live_gate(),
        settings=settings,
        now=now,
    )

    assert result.published == 0
    assert result.failed == 1
    assert result.given_up == 0
    assert row.status == "FAILED"
    # claim_notification_outbox increments attempt_count (2 -> 3) before this job sees the
    # row, so the backoff is computed from the post-claim count.
    assert row.attempt_count == 3
    assert row.next_attempt_at == now + timedelta(seconds=retry_delay_seconds(3))


@pytest.mark.asyncio
async def test_drain_gives_up_after_max_attempts_without_dispatching_forever() -> None:
    settings = _settings()
    event = _event()
    user_id = uuid4()
    delivery = _delivery(settings, event, user_id)
    identity = _identity(settings, user_id)
    row = _outbox_row(
        delivery_id=delivery.notification_delivery_id, attempt_count=MAX_OUTBOX_ATTEMPTS
    )
    now = datetime(2026, 8, 3, tzinfo=UTC)

    db = _FakeDb(claim_result=[row], scalar_queue=[delivery, identity, event, None])
    provider = _Provider("KAKAO_ALIMTALK", accepted=False)

    result = await drain_notification_outbox(
        db,  # type: ignore[arg-type]
        providers={"KAKAO_ALIMTALK": provider},
        release_gate=_live_gate(),
        settings=settings,
        now=now,
    )

    assert result.given_up == 1
    assert result.failed == 0
    assert row.status == "FAILED"
    assert row.next_attempt_at == now + GIVEN_UP_HORIZON
    # Given-up rows must not be immediately reclaimable by a fresh claim query.
    assert row.next_attempt_at > now + timedelta(days=365)


@pytest.mark.asyncio
async def test_drain_with_no_provider_configured_never_reports_sent() -> None:
    """An empty provider map must never look like a successful send - every channel
    attempt records PROVIDER_NOT_CONFIGURED and the delivery ends FAILED, matching
    dispatch_notification's own existing behaviour, not silently 'published'."""

    settings = _settings()
    event = _event()
    user_id = uuid4()
    delivery = _delivery(settings, event, user_id)
    identity = _identity(settings, user_id)
    row = _outbox_row(delivery_id=delivery.notification_delivery_id, attempt_count=1)
    now = datetime(2026, 8, 3, tzinfo=UTC)

    db = _FakeDb(claim_result=[row], scalar_queue=[delivery, identity, event, None])

    result = await drain_notification_outbox(
        db,  # type: ignore[arg-type]
        release_gate=_live_gate(),
        settings=settings,
        now=now,
    )

    assert result.published == 0
    assert result.failed == 1
    assert row.status == "FAILED"


@pytest.mark.asyncio
async def test_drain_retries_when_delivery_row_is_missing() -> None:
    row = _outbox_row(delivery_id=uuid4(), attempt_count=1)
    now = datetime(2026, 8, 3, tzinfo=UTC)
    db = _FakeDb(claim_result=[row], scalar_queue=[None])  # delivery lookup returns nothing

    result = await drain_notification_outbox(
        db,  # type: ignore[arg-type]
        settings=_settings(),
        now=now,
    )

    assert result.claimed == 1
    assert result.skipped_missing_row == 1
    assert result.failed == 1
    assert row.status == "FAILED"
    # claim_notification_outbox increments attempt_count (1 -> 2) before this job sees it.
    assert row.attempt_count == 2
    assert row.next_attempt_at == now + timedelta(seconds=retry_delay_seconds(2))


@pytest.mark.asyncio
async def test_drain_with_no_claimed_rows_is_a_no_op() -> None:
    db = _FakeDb(claim_result=[])

    result = await drain_notification_outbox(db, settings=_settings())  # type: ignore[arg-type]

    assert result.claimed == 0
    assert result.published == 0
    assert result.failed == 0
    # One flush from claim_notification_outbox itself (unconditional), one from this job.
    assert db.flushes == 2


@pytest.mark.asyncio
async def test_drain_defensively_rejects_unexpected_event_type() -> None:
    """Belt-and-braces: even though claim_notification_outbox already filters by
    event_type, this job must never dispatch a row of a kind it does not understand."""

    row = _outbox_row(delivery_id=uuid4(), attempt_count=1)
    row.event_type = "SOME_OTHER_EVENT"
    now = datetime(2026, 8, 3, tzinfo=UTC)
    db = _FakeDb(claim_result=[row])

    result = await drain_notification_outbox(db, settings=_settings(), now=now)  # type: ignore[arg-type]

    assert result.failed == 1
    assert row.status == "FAILED"
