"""Event-message CRUD + workflow orchestration - WAVE 2E ADMIN-NOTIFICATION.

Ties together ``content.py`` (safe-subset validation), ``targeting.py`` (segment resolution +
preview metrics), and ``workflow.py`` (state machine) around the ``EventMessage``/
``EventMessageRecipient`` ORM models. Routers must call only these functions - never build
queries against ``app/models/event_message.py`` directly (same "single composition point" rule
``app/services/exhibitor_preference/service.py`` documents for its own domain).

Downstream delivery integration - explicit TODO, not implemented here
---------------------------------------------------------------------------
``publish_event_message`` resolves the target audience and writes ``EventMessageRecipient``
rows in this track's own schema. It does not call into
``app/services/notification/service.py`` / insert into ``notification.notifications`` / send an
actual email - no integration contract between the two tracks exists yet in this batch (see
``app/models/event_message.py``'s module docstring). The obvious integration point, once one
exists, is right after the ``db.add_all(recipient_rows)`` below: for each resolved recipient,
call BACKEND-NOTIFICATION's equivalent of ``handle_business_event`` with
business_event_code="EVENT_MESSAGE_PUBLISHED" (or whatever that track's contract names it) so
the message actually reaches ``notification.notifications``/email. Flagged in this track's final
report, not silently assumed.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.event_message import EventMessage, EventMessageRecipient
from app.schemas.event_message import (
    EventMessageCreateRequest,
    EventMessagePreview,
    EventMessageUpdateRequest,
)
from app.services.event_message import content, targeting, workflow


class EventMessageServiceError(Exception):
    """Base class for this module's typed errors."""


class VersionConflictError(EventMessageServiceError):
    """Optimistic-lock failure - the caller's row_version does not match the current row."""


def _require_version(event_message: EventMessage, expected_row_version: int) -> None:
    if event_message.row_version != expected_row_version:
        raise VersionConflictError(
            f"row_version 불일치: 요청={expected_row_version}, 현재={event_message.row_version}"
        )


def _validate_content_and_targeting(
    *,
    body: str,
    destination_screen: str,
    target_segment: str,
    target_role_code: str | None,
) -> None:
    content.validate_content(body)
    content.validate_destination_screen(destination_screen)
    targeting.validate_target_segment(target_segment, target_role_code)


async def create_event_message(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    actor_user_id: uuid.UUID | None,
    payload: EventMessageCreateRequest,
) -> EventMessage:
    _validate_content_and_targeting(
        body=payload.body,
        destination_screen=payload.destination_screen,
        target_segment=payload.target_segment,
        target_role_code=payload.target_role_code,
    )

    event_message = EventMessage(
        tenant_id=tenant_id,
        event_id=payload.event_id,
        message_type=payload.message_type,
        status="DRAFT",
        title=payload.title,
        body=payload.body,
        channels_json=list(payload.channels),
        target_segment=payload.target_segment,
        target_role_code=payload.target_role_code,
        destination_screen=payload.destination_screen,
        scheduled_at=payload.scheduled_at,
        created_by_user_id=actor_user_id,
        row_version=1,
    )
    db.add(event_message)
    await db.flush()
    return event_message


async def update_event_message(
    db: AsyncSession,
    event_message: EventMessage,
    payload: EventMessageUpdateRequest,
) -> EventMessage:
    _require_version(event_message, payload.row_version)
    workflow.require_editable(event_message.status)

    next_body = payload.body if payload.body is not None else event_message.body
    next_destination = (
        payload.destination_screen
        if payload.destination_screen is not None
        else event_message.destination_screen
    )
    next_segment = (
        payload.target_segment if payload.target_segment is not None else event_message.target_segment
    )
    next_role = (
        payload.target_role_code
        if payload.target_segment is not None
        else event_message.target_role_code
    )
    if payload.target_segment is not None and payload.target_segment != "SPECIFIC_ROLE":
        next_role = None

    _validate_content_and_targeting(
        body=next_body,
        destination_screen=next_destination,
        target_segment=next_segment,
        target_role_code=next_role,
    )

    if payload.message_type is not None:
        event_message.message_type = payload.message_type
    if payload.title is not None:
        event_message.title = payload.title
    event_message.body = next_body
    if payload.channels is not None:
        event_message.channels_json = list(payload.channels)
    event_message.target_segment = next_segment
    event_message.target_role_code = next_role
    event_message.destination_screen = next_destination
    if payload.scheduled_at is not None:
        event_message.scheduled_at = payload.scheduled_at

    event_message.status = workflow.status_after_edit(event_message.status)
    if event_message.status == "DRAFT":
        event_message.preview_target_count = None
        event_message.preview_consent_excluded_count = None
        event_message.preview_duplicate_warning = None
        event_message.previewed_at = None

    event_message.row_version += 1
    await db.flush()
    return event_message


async def preview_event_message(
    db: AsyncSession,
    event_message: EventMessage,
    *,
    now: datetime | None = None,
) -> EventMessagePreview:
    """Compute + persist the preview snapshot and transition DRAFT -> PREVIEWED (or recompute
    in place while already PREVIEWED - re-previewing is always allowed, it is not itself a
    content edit)."""

    if event_message.status not in ("DRAFT", "PREVIEWED"):
        workflow.require_transition(event_message.status, "PREVIEWED")

    now = now or datetime.now(UTC)

    target_count = (
        await db.execute(
            targeting.target_count_stmt(
                tenant_id=event_message.tenant_id,
                event_id=event_message.event_id,
                target_segment=event_message.target_segment,
                target_role_code=event_message.target_role_code,
            )
        )
    ).scalar_one()

    consent_excluded_count = 0
    if "EMAIL" in event_message.channels_json:
        consent_excluded_count = (
            await db.execute(
                targeting.email_consent_excluded_count_stmt(
                    tenant_id=event_message.tenant_id,
                    event_id=event_message.event_id,
                    target_segment=event_message.target_segment,
                    target_role_code=event_message.target_role_code,
                    now=now,
                )
            )
        ).scalar_one()

    duplicate_count = (
        await db.execute(
            targeting.duplicate_message_count_stmt(
                tenant_id=event_message.tenant_id,
                event_id=event_message.event_id,
                message_type=event_message.message_type,
                exclude_event_message_id=event_message.event_message_id,
            )
        )
    ).scalar_one()

    event_message.preview_target_count = target_count
    event_message.preview_consent_excluded_count = consent_excluded_count
    event_message.preview_duplicate_warning = duplicate_count > 0
    event_message.previewed_at = now
    if event_message.status == "DRAFT":
        event_message.status = "PREVIEWED"
    event_message.row_version += 1
    await db.flush()

    exact_count, display, warning = targeting.display_target_count(target_count)
    return EventMessagePreview(
        event_message_id=event_message.event_message_id,
        title=event_message.title,
        body=event_message.body,
        channels=list(event_message.channels_json),
        target_segment=event_message.target_segment,
        target_role_code=event_message.target_role_code,
        target_count=exact_count,
        target_count_display=display,
        small_audience_warning=warning,
        destination_screen=event_message.destination_screen,
        scheduled_at=event_message.scheduled_at,
        duplicate_target_warning=duplicate_count > 0,
        duplicate_target_message_count=duplicate_count,
        consent_excluded_count=consent_excluded_count,
        previewed_at=now,
    )


async def approve_event_message(
    db: AsyncSession,
    event_message: EventMessage,
    *,
    actor_user_id: uuid.UUID | None,
    row_version: int,
) -> EventMessage:
    _require_version(event_message, row_version)
    workflow.require_transition(event_message.status, "APPROVED")
    event_message.status = "APPROVED"
    event_message.approved_by_user_id = actor_user_id
    event_message.row_version += 1
    await db.flush()
    return event_message


async def schedule_event_message(
    db: AsyncSession,
    event_message: EventMessage,
    *,
    row_version: int,
    scheduled_at: datetime,
) -> EventMessage:
    _require_version(event_message, row_version)
    workflow.require_transition(event_message.status, "SCHEDULED")
    event_message.status = "SCHEDULED"
    event_message.scheduled_at = scheduled_at
    event_message.row_version += 1
    await db.flush()
    return event_message


async def publish_event_message(
    db: AsyncSession,
    event_message: EventMessage,
    *,
    row_version: int,
    now: datetime | None = None,
) -> tuple[EventMessage, int, int]:
    """Resolve the audience fresh (never trusts the preview snapshot alone - defense in depth,
    see EventMessage class docstring) and write EventMessageRecipient rows. Returns
    (event_message, resolved_recipient_count, email_consent_excluded_count)."""

    _require_version(event_message, row_version)
    workflow.require_transition(event_message.status, "PUBLISHED")
    now = now or datetime.now(UTC)

    user_ids = (
        (
            await db.execute(
                targeting.target_user_ids_stmt(
                    tenant_id=event_message.tenant_id,
                    event_id=event_message.event_id,
                    target_segment=event_message.target_segment,
                    target_role_code=event_message.target_role_code,
                )
            )
        )
        .scalars()
        .all()
    )

    email_excluded_ids: set[uuid.UUID] = set()
    if "EMAIL" in event_message.channels_json and user_ids:
        email_excluded_ids = set(
            (
                await db.execute(
                    targeting.email_consent_excluded_user_ids_stmt(
                        tenant_id=event_message.tenant_id,
                        event_id=event_message.event_id,
                        target_segment=event_message.target_segment,
                        target_role_code=event_message.target_role_code,
                        now=now,
                    )
                )
            )
            .scalars()
            .all()
        )
    email_excluded_count = len(email_excluded_ids)

    recipient_rows = [
        EventMessageRecipient(
            event_message_id=event_message.event_message_id,
            recipient_user_id=user_id,
            email_consent_excluded=user_id in email_excluded_ids,
        )
        for user_id in user_ids
    ]
    db.add_all(recipient_rows)

    event_message.status = "PUBLISHED"
    event_message.published_at = now
    event_message.row_version += 1
    await db.flush()
    return event_message, len(user_ids), email_excluded_count


async def cancel_event_message(
    db: AsyncSession,
    event_message: EventMessage,
    *,
    row_version: int,
    reason: str,
    now: datetime | None = None,
) -> EventMessage:
    _require_version(event_message, row_version)
    workflow.require_transition(event_message.status, "CANCELLED")
    del reason  # persisted as an audit_log entry once that write path is wired for this track
    event_message.status = "CANCELLED"
    event_message.cancelled_at = now or datetime.now(UTC)
    event_message.row_version += 1
    await db.flush()
    return event_message


async def complete_event_message(
    db: AsyncSession,
    event_message: EventMessage,
    *,
    row_version: int,
    now: datetime | None = None,
) -> EventMessage:
    _require_version(event_message, row_version)
    workflow.require_transition(event_message.status, "COMPLETED")
    event_message.status = "COMPLETED"
    event_message.completed_at = now or datetime.now(UTC)
    event_message.row_version += 1
    await db.flush()
    return event_message


async def get_event_message(
    db: AsyncSession, *, tenant_id: uuid.UUID, event_message_id: uuid.UUID
) -> EventMessage | None:
    stmt = select(EventMessage).where(
        EventMessage.tenant_id == tenant_id, EventMessage.event_message_id == event_message_id
    )
    return (await db.execute(stmt)).scalar_one_or_none()


async def list_event_messages(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    status: str | None = None,
) -> list[EventMessage]:
    stmt = select(EventMessage).where(
        EventMessage.tenant_id == tenant_id, EventMessage.event_id == event_id
    )
    if status is not None:
        stmt = stmt.where(EventMessage.status == status)
    stmt = stmt.order_by(EventMessage.created_at.desc())
    return list((await db.execute(stmt)).scalars().all())
