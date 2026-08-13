from __future__ import annotations

import base64
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from app.api.v1.routers.auth import _record_notification_click
from app.core.auth import decrypt_secret, encrypt_secret
from app.core.config import Settings
from app.models.auth import PersonalAccessLink
from app.models.core import Event
from app.models.identity import UserIdentity
from app.models.integration import (
    NotificationAttempt,
    NotificationDelivery,
    OutboxEvent,
)
from app.services.notification_delivery import (
    MAX_ALIMTALK_BUTTONS,
    MAX_ALIMTALK_TEXT_LENGTH,
    NotificationChannel,
    NotificationReleaseGate,
    ProviderMessage,
    ProviderResult,
    claim_notification_outbox,
    dispatch_notification,
    enqueue_recommendation_ready,
    is_notification_trigger,
    mark_outbox_failed,
    mark_outbox_published,
    render_recommendation_ready_message,
)


def _settings() -> Settings:
    return Settings(
        SECRET_KEY="notification-test-secret-key",
        AUTH_TOKEN_PEPPER="notification-test-token-pepper",
        AUTH_ENCRYPTION_KEY_B64=base64.urlsafe_b64encode(b"n" * 32).decode(),
    )


def _enqueue_gate() -> NotificationReleaseGate:
    return NotificationReleaseGate(
        catalog_ready=True,
        operator_release_approved=True,
    )


def _live_gate() -> NotificationReleaseGate:
    return NotificationReleaseGate(
        catalog_ready=True,
        operator_release_approved=True,
        external_sending_enabled=True,
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


def _identity(settings: Settings, user_id: UUID) -> UserIdentity:
    return UserIdentity(
        identity_id=uuid4(),
        user_id=user_id,
        name_enc=encrypt_secret("김희섭", purpose="identity-name", settings=settings),
        phone_enc=encrypt_secret(
            "01012345678", purpose="identity-phone", settings=settings
        ),
        email_enc=encrypt_secret(
            "visitor@example.com", purpose="identity-email", settings=settings
        ),
    )


def _delivery(settings: Settings, event: Event, user_id: UUID) -> NotificationDelivery:
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
        template_parameters={"recommendation_count": 10},
        access_url_enc=encrypt_secret(
            "https://match.example/e/baekdudaegan-2026/my?token=opaque",
            purpose="notification-access-url",
            settings=settings,
        ),
        dedupe_key="recommendation-ready:test",
        status="QUEUED",
    )


class _RecordingDb:
    def __init__(
        self, scalar_result=None, scalar_rows: list[object] | None = None
    ) -> None:
        self.rows: list[object] = []
        self.executions: list[object] = []
        self.flushes = 0
        self.scalar_result = scalar_result
        self.scalar_rows = scalar_rows or []

    async def scalar(self, statement):
        self.executions.append(statement)
        return self.scalar_result

    async def execute(self, statement):
        self.executions.append(statement)

    async def scalars(self, statement):
        self.executions.append(statement)

        class _Rows:
            def __init__(self, rows: list[object]) -> None:
                self._rows = rows

            def all(self) -> list[object]:
                return self._rows

        return _Rows(self.scalar_rows)

    def add(self, row: object) -> None:
        self.rows.append(row)

    async def flush(self) -> None:
        self.flushes += 1
        id_fields = (
            "personal_access_link_id",
            "notification_delivery_id",
            "notification_attempt_id",
            "outbox_event_id",
        )
        for row in self.rows:
            for field in id_fields:
                if hasattr(row, field) and getattr(row, field) is None:
                    setattr(row, field, uuid4())


class _ConsentGatedRecordingDb(_RecordingDb):
    """Like ``_RecordingDb`` but returns queued ``scalar()`` results in call order.

    ``dispatch_notification`` issues at most two ``db.scalar`` calls when only the EMAIL
    channel has a configured provider: the sequence-offset lookup (first), then the
    NOTIFICATION_EMAIL consent check immediately before the EMAIL attempt (second). Consent
    behavior in this repo has no live-Postgres test path (see test_notification_api.py's own
    docstring on the project's testing convention), so this mirrors the existing
    ``_RecordingDb`` mock-based pattern already used throughout this file.
    """

    def __init__(self, scalar_queue: list[object]) -> None:
        super().__init__()
        self._scalar_queue = list(scalar_queue)

    async def scalar(self, statement):
        self.executions.append(statement)
        if self._scalar_queue:
            return self._scalar_queue.pop(0)
        return None


class _Provider:
    def __init__(
        self,
        channel: NotificationChannel,
        *,
        accepted: bool,
        failure_code: str | None = None,
    ) -> None:
        self.channel = channel
        self.provider_code = f"TEST_{channel}"
        self.accepted = accepted
        self.failure_code = failure_code
        self.messages: list[ProviderMessage] = []

    async def send(self, message: ProviderMessage) -> ProviderResult:
        self.messages.append(message)
        return ProviderResult(
            self.accepted,
            provider_message_id=("provider-message-1" if self.accepted else None),
            failure_code=self.failure_code,
        )


def test_only_approved_business_events_trigger_notifications() -> None:
    assert is_notification_trigger("RECOMMENDATION_READY") is True
    assert is_notification_trigger("MEETING_STATUS_CHANGED") is True
    assert is_notification_trigger("RANK_CHANGED") is False
    assert is_notification_trigger("EXHIBITOR_ADDED") is False
    assert is_notification_trigger("SAVED_ITEM_CHANGED") is False


@pytest.mark.asyncio
async def test_enqueue_persists_only_encrypted_link_and_id_only_outbox_payload() -> (
    None
):
    settings = _settings()
    db = _RecordingDb()
    event = _event()
    user_id = uuid4()
    delivery = await enqueue_recommendation_ready(
        db,  # type: ignore[arg-type]
        tenant_id=event.tenant_id,
        event_id=event.event_id,
        event_code=event.event_code,
        user_id=user_id,
        profile_id=uuid4(),
        recommendation_session_id=uuid4(),
        recommendation_count=10,
        public_base_url="https://match.example",
        release_gate=_enqueue_gate(),
        settings=settings,
    )

    assert delivery is not None

    link = next(row for row in db.rows if isinstance(row, PersonalAccessLink))
    outbox = next(row for row in db.rows if isinstance(row, OutboxEvent))
    assert delivery.personal_access_link_id == link.personal_access_link_id
    assert outbox.payload == {
        "notification_delivery_id": str(delivery.notification_delivery_id)
    }
    assert set(outbox.payload) == {"notification_delivery_id"}
    access_url = decrypt_secret(
        delivery.access_url_enc,
        purpose="notification-access-url",
        settings=settings,
    ).decode()
    assert access_url.startswith("https://match.example/e/baekdudaegan-2026/my?token=")
    assert access_url.encode() not in delivery.access_url_enc
    persisted_columns = set(NotificationDelivery.__table__.columns.keys())
    assert {"phone", "email", "name", "raw_token", "access_url"}.isdisjoint(
        persisted_columns
    )


@pytest.mark.asyncio
async def test_enqueue_is_idempotent_for_the_same_snapshot() -> None:
    existing = _delivery(_settings(), _event(), uuid4())
    db = _RecordingDb(scalar_result=existing)
    result = await enqueue_recommendation_ready(
        db,  # type: ignore[arg-type]
        tenant_id=existing.tenant_id,
        event_id=existing.event_id,
        event_code="baekdudaegan-2026",
        user_id=existing.user_id,
        profile_id=uuid4(),
        recommendation_session_id=existing.recommendation_session_id,  # type: ignore[arg-type]
        recommendation_count=10,
        public_base_url="https://match.example",
        release_gate=_enqueue_gate(),
        settings=_settings(),
    )

    assert result is existing
    assert db.rows == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("release_gate", "expected_reason"),
    [
        (NotificationReleaseGate(), "CATALOG_NOT_READY"),
        (
            NotificationReleaseGate(catalog_ready=True),
            "OPERATOR_RELEASE_REQUIRED",
        ),
    ],
)
async def test_enqueue_is_held_until_catalog_and_operator_release(
    release_gate: NotificationReleaseGate,
    expected_reason: str,
) -> None:
    db = _RecordingDb()
    event = _event()

    assert release_gate.hold_reason(for_dispatch=False) == expected_reason
    delivery = await enqueue_recommendation_ready(
        db,  # type: ignore[arg-type]
        tenant_id=event.tenant_id,
        event_id=event.event_id,
        event_code=event.event_code,
        user_id=uuid4(),
        profile_id=uuid4(),
        recommendation_session_id=uuid4(),
        recommendation_count=3,
        public_base_url="https://match.example",
        release_gate=release_gate,
        settings=_settings(),
    )

    assert delivery is None
    assert db.rows == []
    assert db.flushes == 0


def test_alimtalk_content_is_bounded_informational_and_web_first() -> None:
    settings = _settings()
    event = _event()
    user_id = uuid4()
    message = render_recommendation_ready_message(
        _delivery(settings, event, user_id),
        identity=_identity(settings, user_id),
        event=event,
        channel="KAKAO_ALIMTALK",
        settings=settings,
    )

    assert message is not None
    assert len(message.body) <= MAX_ALIMTALK_TEXT_LENGTH
    assert len(message.buttons) <= MAX_ALIMTALK_BUTTONS
    assert len(message.buttons) == 1
    assert message.buttons[0].label == "나의 추천 업체 확인"
    assert message.buttons[0].url.startswith("https://match.example/")
    assert "10곳" in message.body
    assert "할인" not in message.body
    assert "스폰서" not in message.body
    assert "추천 점수" not in message.body


@pytest.mark.asyncio
async def test_dispatch_falls_back_to_sms_and_stops_before_email() -> None:
    settings = _settings()
    event = _event()
    user_id = uuid4()
    delivery = _delivery(settings, event, user_id)
    db = _RecordingDb()
    alimtalk = _Provider(
        "KAKAO_ALIMTALK", accepted=False, failure_code="ALIMTALK_REJECTED"
    )
    sms = _Provider("SMS", accepted=True)
    email = _Provider("EMAIL", accepted=True)

    outcome = await dispatch_notification(
        db,  # type: ignore[arg-type]
        delivery,
        identity=_identity(settings, user_id),
        event=event,
        providers={"KAKAO_ALIMTALK": alimtalk, "SMS": sms, "EMAIL": email},
        release_gate=_live_gate(),
        settings=settings,
        now=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert outcome.sent is True
    assert outcome.channel == "SMS"
    assert [attempt.channel for attempt in outcome.attempts] == [
        "KAKAO_ALIMTALK",
        "SMS",
    ]
    assert [attempt.status for attempt in outcome.attempts] == ["FAILED", "SENT"]
    assert len(alimtalk.messages) == 1
    assert len(sms.messages) == 1
    assert email.messages == []
    assert delivery.status == "SENT"


@pytest.mark.asyncio
async def test_successful_alimtalk_does_not_send_sms_or_email() -> None:
    settings = _settings()
    event = _event()
    user_id = uuid4()
    delivery = _delivery(settings, event, user_id)
    db = _RecordingDb()
    alimtalk = _Provider("KAKAO_ALIMTALK", accepted=True)
    sms = _Provider("SMS", accepted=True)
    email = _Provider("EMAIL", accepted=True)

    outcome = await dispatch_notification(
        db,  # type: ignore[arg-type]
        delivery,
        identity=_identity(settings, user_id),
        event=event,
        providers={"KAKAO_ALIMTALK": alimtalk, "SMS": sms, "EMAIL": email},
        release_gate=_live_gate(),
        settings=settings,
    )

    assert outcome.channel == "KAKAO_ALIMTALK"
    assert len(outcome.attempts) == 1
    assert len(alimtalk.messages) == 1
    assert sms.messages == []
    assert email.messages == []


@pytest.mark.asyncio
async def test_dispatch_without_external_switch_calls_no_provider() -> None:
    settings = _settings()
    event = _event()
    user_id = uuid4()
    delivery = _delivery(settings, event, user_id)
    db = _RecordingDb()
    alimtalk = _Provider("KAKAO_ALIMTALK", accepted=True)
    sms = _Provider("SMS", accepted=True)
    email = _Provider("EMAIL", accepted=True)

    outcome = await dispatch_notification(
        db,  # type: ignore[arg-type]
        delivery,
        identity=_identity(settings, user_id),
        event=event,
        providers={"KAKAO_ALIMTALK": alimtalk, "SMS": sms, "EMAIL": email},
        release_gate=_enqueue_gate(),
        settings=settings,
    )

    assert outcome.sent is False
    assert outcome.held_reason == "EXTERNAL_SENDING_DISABLED"
    assert outcome.attempts == ()
    assert delivery.status == "QUEUED"
    assert alimtalk.messages == []
    assert sms.messages == []
    assert email.messages == []


@pytest.mark.asyncio
async def test_dispatch_sends_email_when_notification_email_consent_is_effective() -> None:
    """A user with a currently-effective, accepted NOTIFICATION_EMAIL consent gets the EMAIL
    attempt created normally (NOTIFY-002 acceptance: consent-granted path)."""

    settings = _settings()
    event = _event()
    user_id = uuid4()
    delivery = _delivery(settings, event, user_id)
    db = _ConsentGatedRecordingDb(scalar_queue=[None, True])
    email = _Provider("EMAIL", accepted=True)

    outcome = await dispatch_notification(
        db,  # type: ignore[arg-type]
        delivery,
        identity=_identity(settings, user_id),
        event=event,
        providers={"EMAIL": email},
        release_gate=_live_gate(),
        settings=settings,
        now=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert outcome.sent is True
    assert outcome.channel == "EMAIL"
    email_attempt = next(a for a in outcome.attempts if a.channel == "EMAIL")
    assert email_attempt.status == "SENT"
    assert email_attempt.failure_code is None
    assert len(email.messages) == 1


@pytest.mark.asyncio
async def test_dispatch_skips_email_when_notification_email_consent_was_withdrawn() -> None:
    """A user who explicitly withdrew NOTIFICATION_EMAIL consent (append-only history per
    app/models/consent.py - the latest UserConsent row has accepted=False) never gets an EMAIL
    attempt sent, even though the outbound delivery/attempt rows for earlier channels in the
    Alimtalk -> SMS -> EMAIL chain are unaffected by this gate (NOTIFY-002 acceptance:
    consent-withdrawn path). ``email_processing_basis_stmt`` returning a falsy/absent row is
    exactly what a withdrawal or a never-granted consent both look like to the caller."""

    settings = _settings()
    event = _event()
    user_id = uuid4()
    delivery = _delivery(settings, event, user_id)
    db = _ConsentGatedRecordingDb(scalar_queue=[None, False])
    email = _Provider("EMAIL", accepted=True)

    outcome = await dispatch_notification(
        db,  # type: ignore[arg-type]
        delivery,
        identity=_identity(settings, user_id),
        event=event,
        providers={"EMAIL": email},
        release_gate=_live_gate(),
        settings=settings,
        now=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert outcome.sent is False
    email_attempt = next(a for a in outcome.attempts if a.channel == "EMAIL")
    assert email_attempt.status == "SKIPPED"
    assert email_attempt.failure_code == "CONSENT_MISSING"
    assert email.messages == []
    assert delivery.status == "FAILED"


@pytest.mark.asyncio
async def test_dispatch_skips_unconfigured_email_without_a_consent_query() -> None:
    """When no EMAIL provider is configured at all (the common pre-launch state - see this
    module's own docstring), the skip must be labeled PROVIDER_NOT_CONFIGURED, not
    CONSENT_MISSING, and must never spend a DB round trip on a consent lookup whose answer
    can't change the outcome either way."""

    settings = _settings()
    event = _event()
    user_id = uuid4()
    delivery = _delivery(settings, event, user_id)
    # Only one scalar() call expected: the sequence-offset lookup. No providers configured at
    # all, so every channel (including EMAIL) hits the provider-is-None branch, never the
    # consent-check branch.
    db = _ConsentGatedRecordingDb(scalar_queue=[None])

    outcome = await dispatch_notification(
        db,  # type: ignore[arg-type]
        delivery,
        identity=_identity(settings, user_id),
        event=event,
        providers={},
        release_gate=_live_gate(),
        settings=settings,
        now=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert outcome.sent is False
    email_attempt = next(a for a in outcome.attempts if a.channel == "EMAIL")
    assert email_attempt.status == "SKIPPED"
    assert email_attempt.failure_code == "PROVIDER_NOT_CONFIGURED"
    assert delivery.status == "FAILED"


@pytest.mark.asyncio
async def test_dispatch_does_not_consent_gate_alimtalk_or_sms() -> None:
    """The NOTIFICATION_EMAIL consent gate applies only to the EMAIL step - Alimtalk/SMS are
    untouched, matching this repo's existing (lack of) consent gating on those channels."""

    settings = _settings()
    event = _event()
    user_id = uuid4()
    delivery = _delivery(settings, event, user_id)
    # Only one scalar() call expected: the sequence-offset lookup. No EMAIL provider is
    # configured, so the channel loop never reaches the consent-check branch.
    db = _ConsentGatedRecordingDb(scalar_queue=[None])
    alimtalk = _Provider("KAKAO_ALIMTALK", accepted=True)

    outcome = await dispatch_notification(
        db,  # type: ignore[arg-type]
        delivery,
        identity=_identity(settings, user_id),
        event=event,
        providers={"KAKAO_ALIMTALK": alimtalk},
        release_gate=_live_gate(),
        settings=settings,
        now=datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert outcome.sent is True
    assert outcome.channel == "KAKAO_ALIMTALK"
    assert len(db.executions) == 1


@pytest.mark.asyncio
async def test_click_is_recorded_by_personal_link_reference() -> None:
    db = _RecordingDb()
    link_id = uuid4()
    await _record_notification_click(
        db,  # type: ignore[arg-type]
        link_id,
        datetime(2026, 8, 3, tzinfo=UTC),
    )

    assert len(db.executions) == 1
    sql = str(db.executions[0])
    assert "notification_delivery" in sql
    assert "personal_access_link_id" in sql
    assert "clicked_at" in sql


@pytest.mark.asyncio
async def test_expired_outbox_lease_can_be_reclaimed_and_terminal_states_clear_it() -> (
    None
):
    now = datetime(2026, 8, 3, tzinfo=UTC)
    row = OutboxEvent(
        outbox_event_id=uuid4(),
        tenant_id=uuid4(),
        event_id=uuid4(),
        aggregate_type="NOTIFICATION_DELIVERY",
        aggregate_id=uuid4(),
        event_type="NOTIFICATION_DELIVERY_REQUESTED",
        schema_version="notification-delivery-requested-v1.0",
        payload={"notification_delivery_id": str(uuid4())},
        dedupe_key="outbox:test",
        status="PROCESSING",
        attempt_count=2,
        locked_until=now - timedelta(seconds=1),
        created_at=now - timedelta(minutes=1),
    )
    db = _RecordingDb(scalar_rows=[row])

    claimed = await claim_notification_outbox(
        db,  # type: ignore[arg-type]
        now=now,
        lease_seconds=60,
    )

    assert claimed == [row]
    assert row.status == "PROCESSING"
    assert row.attempt_count == 3
    assert row.locked_until == now + timedelta(seconds=60)

    retry_at = now + timedelta(minutes=5)
    mark_outbox_failed(row, retry_at=retry_at)
    assert row.status == "FAILED"
    assert row.next_attempt_at == retry_at
    assert row.locked_until is None

    mark_outbox_published(row, now=retry_at)
    assert row.status == "PUBLISHED"
    assert row.published_at == retry_at
    assert row.next_attempt_at is None
    assert row.locked_until is None


def test_attempt_schema_has_no_provider_body_or_recipient_columns() -> None:
    persisted_columns = set(NotificationAttempt.__table__.columns.keys())
    assert {"phone", "email", "recipient", "request_body", "response_body"}.isdisjoint(
        persisted_columns
    )
