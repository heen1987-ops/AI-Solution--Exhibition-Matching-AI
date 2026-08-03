"""Provider-neutral informational delivery for the mobile My Event doorway.

Matching creates versioned snapshots. This module may announce an explicitly approved business
event, but it never calculates or reranks recommendations. Provider implementations are injected
by a worker after a Kakao official dealer, SMS/email providers, template codes, callback security,
and credentials have been approved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol
from urllib.parse import quote, urlsplit
from uuid import UUID

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import decrypt_secret, encrypt_secret, issue_personal_access_link
from app.core.config import Settings, get_settings
from app.models.core import Event
from app.models.identity import UserIdentity
from app.models.integration import (
    NotificationAttempt,
    NotificationDelivery,
    OutboxEvent,
)

NotificationChannel = Literal["KAKAO_ALIMTALK", "SMS", "EMAIL"]
NotificationHoldReason = Literal[
    "CATALOG_NOT_READY",
    "OPERATOR_RELEASE_REQUIRED",
    "EXTERNAL_SENDING_DISABLED",
]

CHANNEL_ORDER: tuple[NotificationChannel, ...] = (
    "KAKAO_ALIMTALK",
    "SMS",
    "EMAIL",
)
RECOMMENDATION_READY_TEMPLATE = "RECOMMENDATION_READY_V1"
OUTBOX_SCHEMA_VERSION = "notification-delivery-requested-v1.0"
MAX_ALIMTALK_TEXT_LENGTH = 1_000
MAX_ALIMTALK_BUTTONS = 5

# Rank drift and catalog changes update the web snapshot only. They are deliberately absent.
APPROVED_INFORMATIONAL_TRIGGERS = frozenset(
    {
        "REGISTRATION_COMPLETED",
        "RECOMMENDATION_READY",
        "EVENT_EVE_REMINDER",
        "MEETING_STATUS_CHANGED",
        "MEETING_IMMINENT",
        "POST_EVENT_SUMMARY",
    }
)


@dataclass(frozen=True, slots=True)
class MessageButton:
    button_type: Literal["WL"]
    label: str
    url: str


@dataclass(frozen=True, slots=True)
class ProviderMessage:
    channel: NotificationChannel
    template_code: str
    recipient: str
    body: str
    buttons: tuple[MessageButton, ...]
    subject: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderResult:
    accepted: bool
    provider_message_id: str | None = None
    failure_code: str | None = None


class NotificationProvider(Protocol):
    """Official-dealer/SMS/email adapter boundary implemented outside matching."""

    provider_code: str
    channel: NotificationChannel

    async def send(self, message: ProviderMessage) -> ProviderResult: ...


class NotificationProviderError(Exception):
    """Safe adapter exception whose raw provider response must not be persisted."""


@dataclass(frozen=True, slots=True)
class DispatchOutcome:
    sent: bool
    channel: NotificationChannel | None
    attempts: tuple[NotificationAttempt, ...]
    held_reason: NotificationHoldReason | None = None


@dataclass(frozen=True, slots=True)
class NotificationReleaseGate:
    """Fail-closed release facts supplied by catalog/operations configuration.

    Matching and My Event Snapshot delivery continue while this gate is closed. Notification
    persistence requires both catalog readiness and an explicit operator release. Provider calls
    additionally require the external-sending switch. All defaults deliberately hold delivery.
    """

    catalog_ready: bool = False
    operator_release_approved: bool = False
    external_sending_enabled: bool = False

    def hold_reason(self, *, for_dispatch: bool) -> NotificationHoldReason | None:
        if not self.catalog_ready:
            return "CATALOG_NOT_READY"
        if not self.operator_release_approved:
            return "OPERATOR_RELEASE_REQUIRED"
        if for_dispatch and not self.external_sending_enabled:
            return "EXTERNAL_SENDING_DISABLED"
        return None


def is_notification_trigger(change_type: str) -> bool:
    """Return true only for approved business events, never rank/catalog drift."""

    return change_type in APPROVED_INFORMATIONAL_TRIGGERS


def _validated_public_base_url(value: str) -> str:
    parsed = urlsplit(value)
    local_http = parsed.scheme == "http" and parsed.hostname in {
        "localhost",
        "127.0.0.1",
    }
    if (parsed.scheme != "https" and not local_http) or not parsed.netloc:
        raise ValueError(
            "public_base_url must be HTTPS (HTTP is allowed only for localhost)"
        )
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise ValueError(
            "public_base_url must not contain credentials, query, or fragment"
        )
    return value.rstrip("/")


def _dedupe_key(*, event_id: UUID, user_id: UUID, session_id: UUID) -> str:
    return f"recommendation-ready:{event_id}:{user_id}:{session_id}"


async def enqueue_recommendation_ready(
    db: AsyncSession,
    *,
    tenant_id: UUID,
    event_id: UUID,
    event_code: str,
    user_id: UUID,
    profile_id: UUID,
    recommendation_session_id: UUID,
    recommendation_count: int,
    public_base_url: str,
    release_gate: NotificationReleaseGate | None = None,
    settings: Settings | None = None,
) -> NotificationDelivery | None:
    """Create the delivery, one-time link, and Outbox row in the caller transaction.

    The caller owns commit/rollback. Repeating the same snapshot event returns the existing row and
    does not rotate the personal link or enqueue a second message. A closed release gate returns
    ``None`` before issuing a personal link or writing a delivery/Outbox row.
    """

    if not 1 <= recommendation_count <= 50:
        raise ValueError("recommendation_count must be between 1 and 50")
    if not event_code or len(event_code) > 50:
        raise ValueError("event_code is required and must not exceed 50 characters")
    base_url = _validated_public_base_url(public_base_url)
    release_gate = release_gate or NotificationReleaseGate()
    if release_gate.hold_reason(for_dispatch=False) is not None:
        return None
    settings = settings or get_settings()
    dedupe_key = _dedupe_key(
        event_id=event_id,
        user_id=user_id,
        session_id=recommendation_session_id,
    )
    existing = await db.scalar(
        select(NotificationDelivery).where(
            NotificationDelivery.tenant_id == tenant_id,
            NotificationDelivery.dedupe_key == dedupe_key,
        )
    )
    if existing is not None:
        return existing

    encoded_event_code = quote(event_code, safe="-._~")
    return_path = f"/e/{encoded_event_code}/my"
    link, raw_token = await issue_personal_access_link(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        user_id=user_id,
        profile_id=profile_id,
        recommendation_session_id=recommendation_session_id,
        return_path=return_path,
        settings=settings,
    )
    access_url = f"{base_url}{return_path}?token={quote(raw_token, safe='')}"
    delivery = NotificationDelivery(
        tenant_id=tenant_id,
        event_id=event_id,
        user_id=user_id,
        recommendation_session_id=recommendation_session_id,
        personal_access_link_id=link.personal_access_link_id,
        notification_type="RECOMMENDATION_READY",
        message_class="INFORMATIONAL",
        template_code=RECOMMENDATION_READY_TEMPLATE,
        template_parameters={"recommendation_count": recommendation_count},
        access_url_enc=encrypt_secret(
            access_url, purpose="notification-access-url", settings=settings
        ),
        dedupe_key=dedupe_key,
        status="QUEUED",
    )
    db.add(delivery)
    await db.flush()
    db.add(
        OutboxEvent(
            tenant_id=tenant_id,
            event_id=event_id,
            aggregate_type="NOTIFICATION_DELIVERY",
            aggregate_id=delivery.notification_delivery_id,
            event_type="NOTIFICATION_DELIVERY_REQUESTED",
            schema_version=OUTBOX_SCHEMA_VERSION,
            payload={
                "notification_delivery_id": str(delivery.notification_delivery_id)
            },
            dedupe_key=f"outbox:{dedupe_key}",
            status="PENDING",
        )
    )
    await db.flush()
    return delivery


def _decrypt_optional(
    value: bytes | None, *, purpose: str, settings: Settings
) -> str | None:
    if value is None:
        return None
    try:
        return decrypt_secret(value, purpose=purpose, settings=settings).decode("utf-8")
    except (UnicodeDecodeError, ValueError):
        return None


def render_recommendation_ready_message(
    delivery: NotificationDelivery,
    *,
    identity: UserIdentity,
    event: Event,
    channel: NotificationChannel,
    settings: Settings | None = None,
) -> ProviderMessage | None:
    """Render bounded informational content, decrypting contact only in memory."""

    settings = settings or get_settings()
    if delivery.notification_type != "RECOMMENDATION_READY":
        raise ValueError("unsupported notification_type")
    if delivery.message_class != "INFORMATIONAL":
        raise ValueError("marketing content is not supported")

    if channel in {"KAKAO_ALIMTALK", "SMS"}:
        recipient = _decrypt_optional(
            identity.phone_enc, purpose="identity-phone", settings=settings
        )
    else:
        recipient = _decrypt_optional(
            identity.email_enc, purpose="identity-email", settings=settings
        )
    if not recipient:
        return None

    name = (
        _decrypt_optional(identity.name_enc, purpose="identity-name", settings=settings)
        or "참가자"
    )
    access_url = _decrypt_optional(
        delivery.access_url_enc,
        purpose="notification-access-url",
        settings=settings,
    )
    if not access_url:
        return None
    count = delivery.template_parameters.get("recommendation_count")
    if not isinstance(count, int) or not 1 <= count <= 50:
        raise ValueError("invalid recommendation_count template parameter")

    body = (
        f"[{event.event_name}]\n\n"
        f"{name} 님의 사전등록 정보를 바탕으로\n"
        f"관심 분야와 관련된 업체 {count}곳을 추천했습니다.\n\n"
        "추천 이유, 부스 위치와 상담 가능 정보를\n"
        "나의 행사 페이지에서 확인해 주세요."
    )
    button = MessageButton(
        button_type="WL",
        label="나의 추천 업체 확인",
        url=access_url,
    )
    if len(body) > MAX_ALIMTALK_TEXT_LENGTH:
        raise ValueError("message exceeds Alimtalk text limit")
    buttons = (button,)
    if len(buttons) > MAX_ALIMTALK_BUTTONS:
        raise ValueError("message exceeds Alimtalk button limit")

    return ProviderMessage(
        channel=channel,
        template_code=delivery.template_code,
        recipient=recipient,
        body=body,
        buttons=buttons,
        subject=(
            f"[{event.event_name}] 나의 추천 업체가 준비되었습니다"
            if channel == "EMAIL"
            else None
        ),
    )


async def dispatch_notification(
    db: AsyncSession,
    delivery: NotificationDelivery,
    *,
    identity: UserIdentity,
    event: Event,
    providers: dict[NotificationChannel, NotificationProvider],
    release_gate: NotificationReleaseGate | None = None,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> DispatchOutcome:
    """Try Alimtalk first, then SMS, then email; stop after the first accepted send.

    Provider calls are impossible unless the caller supplies a fully open release gate. This keeps
    production fail-closed even if adapters or credentials are configured ahead of launch.
    """

    release_gate = release_gate or NotificationReleaseGate()
    held_reason = release_gate.hold_reason(for_dispatch=True)
    if held_reason is not None:
        return DispatchOutcome(False, None, (), held_reason)
    settings = settings or get_settings()
    current_time = now or datetime.now(UTC)
    delivery.status = "PROCESSING"
    attempts: list[NotificationAttempt] = []
    sequence_offset = (
        await db.scalar(
            select(func.max(NotificationAttempt.sequence)).where(
                NotificationAttempt.notification_delivery_id
                == delivery.notification_delivery_id
            )
        )
        or 0
    )

    for sequence, channel in enumerate(CHANNEL_ORDER, start=sequence_offset + 1):
        provider = providers.get(channel)
        message = render_recommendation_ready_message(
            delivery,
            identity=identity,
            event=event,
            channel=channel,
            settings=settings,
        )
        if provider is None or message is None:
            attempt = NotificationAttempt(
                notification_delivery_id=delivery.notification_delivery_id,
                sequence=sequence,
                channel=channel,
                provider_code=(
                    provider.provider_code if provider else "NOT_CONFIGURED"
                ),
                status="SKIPPED",
                failure_code=(
                    "RECIPIENT_UNAVAILABLE"
                    if message is None
                    else "PROVIDER_NOT_CONFIGURED"
                ),
                requested_at=current_time,
            )
            db.add(attempt)
            attempts.append(attempt)
            continue
        if provider.channel != channel:
            raise ValueError("provider channel does not match dispatch channel")

        try:
            result = await provider.send(message)
        except NotificationProviderError:
            result = ProviderResult(False, failure_code="PROVIDER_UNAVAILABLE")
        if result.accepted:
            attempt = NotificationAttempt(
                notification_delivery_id=delivery.notification_delivery_id,
                sequence=sequence,
                channel=channel,
                provider_code=provider.provider_code,
                status="SENT",
                provider_message_id=(result.provider_message_id or "")[:200] or None,
                requested_at=current_time,
                sent_at=current_time,
            )
            db.add(attempt)
            attempts.append(attempt)
            delivery.status = "SENT"
            delivery.sent_at = current_time
            await db.flush()
            return DispatchOutcome(True, channel, tuple(attempts))

        attempt = NotificationAttempt(
            notification_delivery_id=delivery.notification_delivery_id,
            sequence=sequence,
            channel=channel,
            provider_code=provider.provider_code,
            status="FAILED",
            failure_code=(result.failure_code or "PROVIDER_REJECTED")[:100],
            requested_at=current_time,
            failed_at=current_time,
        )
        db.add(attempt)
        attempts.append(attempt)

    delivery.status = "FAILED"
    delivery.failed_at = current_time
    await db.flush()
    return DispatchOutcome(False, None, tuple(attempts))


async def claim_notification_outbox(
    db: AsyncSession,
    *,
    limit: int = 100,
    lease_seconds: int = 60,
    now: datetime | None = None,
) -> list[OutboxEvent]:
    """Claim due notification Outbox rows without blocking another worker."""

    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    if not 15 <= lease_seconds <= 600:
        raise ValueError("lease_seconds must be between 15 and 600")
    current_time = now or datetime.now(UTC)
    rows = list(
        (
            await db.scalars(
                select(OutboxEvent)
                .where(
                    OutboxEvent.event_type == "NOTIFICATION_DELIVERY_REQUESTED",
                    or_(
                        and_(
                            OutboxEvent.status.in_(("PENDING", "FAILED")),
                            or_(
                                OutboxEvent.next_attempt_at.is_(None),
                                OutboxEvent.next_attempt_at <= current_time,
                            ),
                        ),
                        and_(
                            OutboxEvent.status == "PROCESSING",
                            OutboxEvent.locked_until <= current_time,
                        ),
                    ),
                )
                .order_by(
                    OutboxEvent.created_at.asc(), OutboxEvent.outbox_event_id.asc()
                )
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).all()
    )
    for row in rows:
        row.status = "PROCESSING"
        row.attempt_count += 1
        row.locked_until = current_time + timedelta(seconds=lease_seconds)
    await db.flush()
    return rows


def mark_outbox_published(row: OutboxEvent, *, now: datetime | None = None) -> None:
    row.status = "PUBLISHED"
    row.published_at = now or datetime.now(UTC)
    row.next_attempt_at = None
    row.locked_until = None


def mark_outbox_failed(row: OutboxEvent, *, retry_at: datetime) -> None:
    row.status = "FAILED"
    row.next_attempt_at = retry_at
    row.locked_until = None
