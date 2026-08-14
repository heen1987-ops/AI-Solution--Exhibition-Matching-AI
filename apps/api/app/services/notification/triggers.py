"""Business-event -> ``BusinessEvent`` builders for this track's seven notification types.

WAVE 2E BACKEND-NOTIFICATION. Referenced from ``app/services/notification/service.py``'s
module docstring ("callers are state transitions - see triggers.py"). These are the seven
business events named verbatim in this track's task spec: "meeting accepted/time-proposed,
content-review-requested/result, recommendation-ready, event-day reminders, operator notices".

Why this module only builds events and does not call the state-transition code itself
------------------------------------------------------------------------------------------
The actual state transitions (accepting a meeting, approving reviewed content, generating a
recommendation batch, ...) live in other tracks' owned files
(``app/api/v1/routers/meetings.py``, the content-review/document track, the
recommendation/matching track, an event-day scheduler). This track's OWNED PATHS do not
include any of those - per the harness's "expose a registration function ... so the
integrator can wire it later" rule, this module is the wiring surface: each function below
takes the already-known business facts (ids, the resolved recipient, the version that makes
the event distinct) and returns the ``NotificationOutcome`` from firing it through
``NotificationService.handle_business_event``. A future integration step calls one of these
functions from inside the real transition instead of constructing a ``BusinessEvent`` by hand.

Idempotency / "only fire on an actual state change" is the caller's responsibility
------------------------------------------------------------------------------------------
``handle_business_event`` itself is naturally idempotent per the dedup key (calling
``notify_meeting_accepted`` twice for the same meeting at the same ``row_version`` produces
one notification, not two - see service.py). But nothing in this module stops a caller from
invoking, say, ``notify_meeting_accepted`` from a code path that runs on every read; per the
task spec ("status-change notifications only fire on an actual state change, never on
re-reads") the *caller* must only invoke these from inside an actual transition (e.g. after
``meeting.status`` is set to ``"accepted"`` and committed), passing that transition's new
``row_version`` as ``relevant_version`` so a later transition (a different row_version)
correctly produces a new notification instead of being deduped away.

title/body text
------------------
Plain Korean strings (this track has no localization system to depend on, matching every
other router's inline Korean message strings, e.g. ``app/api/v1/routers/meetings.py``).
Every string here is generated from already-known structured facts (never inferred from a
document/AI-extracted field), so this module carries no "AI must never assert unknown data"
risk.
"""

from __future__ import annotations

from datetime import date
from uuid import UUID

from app.services.notification.service import (
    BusinessEvent,
    NotificationOutcome,
    NotificationService,
)


async def notify_meeting_accepted(
    service: NotificationService,
    *,
    tenant_id: UUID,
    event_id: UUID,
    recipient_user_id: UUID,
    meeting_id: UUID,
    row_version: int,
    exhibitor_name: str | None = None,
) -> NotificationOutcome:
    counterparty = f"{exhibitor_name} " if exhibitor_name else ""
    return await service.handle_business_event(
        BusinessEvent(
            business_event_code="MEETING_STATUS_CHANGED",
            notification_type="MEETING_ACCEPTED",
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            event_id=event_id,
            object_type="interaction.meeting",
            object_id=meeting_id,
            relevant_version=str(row_version),
            title="상담 요청이 수락되었습니다",
            body=f"{counterparty}상담 요청이 수락되었습니다. 확정된 시간을 확인해 주세요.",
        )
    )


async def notify_meeting_time_proposed(
    service: NotificationService,
    *,
    tenant_id: UUID,
    event_id: UUID,
    recipient_user_id: UUID,
    meeting_id: UUID,
    row_version: int,
    exhibitor_name: str | None = None,
) -> NotificationOutcome:
    counterparty = f"{exhibitor_name} " if exhibitor_name else ""
    return await service.handle_business_event(
        BusinessEvent(
            business_event_code="MEETING_STATUS_CHANGED",
            notification_type="MEETING_TIME_PROPOSED",
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            event_id=event_id,
            object_type="interaction.meeting",
            object_id=meeting_id,
            relevant_version=str(row_version),
            title="상담 시간이 새로 제안되었습니다",
            body=f"{counterparty}업체가 다른 상담 시간을 제안했습니다. 확인 후 응답해 주세요.",
        )
    )


async def notify_content_review_requested(
    service: NotificationService,
    *,
    tenant_id: UUID,
    event_id: UUID | None,
    recipient_user_id: UUID,
    document_id: UUID,
    version_no: int,
) -> NotificationOutcome:
    return await service.handle_business_event(
        BusinessEvent(
            business_event_code="CONTENT_REVIEW_REQUESTED",
            notification_type="CONTENT_REVIEW_REQUESTED",
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            event_id=event_id,
            object_type="document.document",
            object_id=document_id,
            relevant_version=str(version_no),
            title="검수가 필요한 콘텐츠가 있습니다",
            body="AI가 구조화한 콘텐츠가 검수 대기 중입니다. 확인 후 승인해 주세요.",
        )
    )


async def notify_content_review_result(
    service: NotificationService,
    *,
    tenant_id: UUID,
    event_id: UUID | None,
    recipient_user_id: UUID,
    document_id: UUID,
    version_no: int,
    approved: bool,
) -> NotificationOutcome:
    return await service.handle_business_event(
        BusinessEvent(
            business_event_code="CONTENT_REVIEW_COMPLETED",
            notification_type="CONTENT_REVIEW_RESULT",
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            event_id=event_id,
            object_type="document.document",
            # relevant_version includes the decision so a later re-review (e.g. rejected then
            # re-submitted and approved) is a distinct notification rather than deduped away.
            object_id=document_id,
            relevant_version=f"{version_no}:{'APPROVED' if approved else 'REJECTED'}",
            title="콘텐츠 검수 결과가 도착했습니다",
            body="승인되었습니다." if approved else "반려되었습니다. 사유를 확인해 주세요.",
        )
    )


async def notify_recommendation_ready(
    service: NotificationService,
    *,
    tenant_id: UUID,
    event_id: UUID,
    recipient_user_id: UUID,
    recommendation_session_id: UUID,
    batch_date: date,
) -> NotificationOutcome:
    """Frequency-capped at 1/recipient/day by default (DEFAULT_FREQUENCY_CAPS in service.py) -
    ``relevant_version`` is the calendar date so multiple sessions on the same day dedup to
    one notification even before the frequency cap is consulted."""

    return await service.handle_business_event(
        BusinessEvent(
            business_event_code="RECOMMENDATION_GENERATED",
            notification_type="RECOMMENDATION_READY",
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            event_id=event_id,
            object_type="matching.recommendation_session",
            object_id=recommendation_session_id,
            relevant_version=batch_date.isoformat(),
            title="새로운 추천이 도착했습니다",
            body="회원님을 위한 새로운 업체 추천을 확인해 보세요.",
        )
    )


async def notify_event_day_reminder(
    service: NotificationService,
    *,
    tenant_id: UUID,
    event_id: UUID,
    recipient_user_id: UUID,
    event_day_id: UUID,
    reminder_date: date,
) -> NotificationOutcome:
    return await service.handle_business_event(
        BusinessEvent(
            business_event_code="EVENT_DAY_REMINDER_DUE",
            notification_type="EVENT_DAY_REMINDER",
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            event_id=event_id,
            object_type="exhibition.event_day",
            object_id=event_day_id,
            relevant_version=reminder_date.isoformat(),
            title="행사 당일 안내",
            body="오늘 행사가 진행됩니다. 방문 계획과 상담 일정을 확인해 주세요.",
        )
    )


async def notify_operator_notice(
    service: NotificationService,
    *,
    tenant_id: UUID,
    event_id: UUID | None,
    recipient_user_id: UUID,
    notice_id: UUID,
    notice_version: int,
    title: str,
    body: str,
) -> NotificationOutcome:
    """``is_operational`` (frequency-cap-exempt) is resolved from ``notification_rules`` by
    ``NotificationService._resolve_rule`` - ``DEFAULT_OPERATIONAL_TYPES`` already marks
    ``OPERATOR_NOTICE`` operational even with no persisted rule row, so this always bypasses
    the cap regardless of how many other notice types a recipient already received today."""

    return await service.handle_business_event(
        BusinessEvent(
            business_event_code="OPERATOR_NOTICE_PUBLISHED",
            notification_type="OPERATOR_NOTICE",
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            event_id=event_id,
            object_type="core.operator_notice",
            object_id=notice_id,
            relevant_version=str(notice_version),
            title=title,
            body=body,
        )
    )
