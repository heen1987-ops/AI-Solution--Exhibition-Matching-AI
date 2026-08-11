"""Notification API contract - GET/POST /me/notifications*, GET/PATCH /me/notification-preferences.

WAVE 2E BACKEND-NOTIFICATION. Model reference: ``app/models/notification.py`` (that module's
docstring has the full design rationale for the dedup key, schema choice, etc). Redeclares
``NotificationType``/``NotificationChannel`` as ``Literal`` here rather than importing the
CHECK-constraint tuples directly from the model module, following this repo's established
"router/schema layer intentionally re-lists values instead of importing another layer's module"
convention (see app/schemas/exhibitor_preference.py's own docstring for the same choice) - it
keeps FastAPI's generated OpenAPI enum accurate even if someone changes import order later, at
the cost of the two lists needing to be kept in sync by hand (a `assert set(NotificationType.__args__) == set(NOTIFICATION_TYPES)` sanity test in
test_notification_api.py guards against drift).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

NotificationType = Literal[
    "MEETING_ACCEPTED",
    "MEETING_TIME_PROPOSED",
    "CONTENT_REVIEW_REQUESTED",
    "CONTENT_REVIEW_RESULT",
    "RECOMMENDATION_READY",
    "EVENT_DAY_REMINDER",
    "OPERATOR_NOTICE",
]

NotificationChannel = Literal["IN_APP", "EMAIL"]
NotificationDeliveryStatus = Literal["PENDING", "SENT", "FAILED", "SKIPPED"]


# ---------------------------------------------------------------------------
# GET /me/notifications
# ---------------------------------------------------------------------------


class NotificationDeliveryView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    channel: NotificationChannel
    status: NotificationDeliveryStatus
    skipped_reason: str | None = None
    failure_reason: str | None = None
    sent_at: datetime | None = None


class NotificationView(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    notification_id: UUID
    notification_type: NotificationType
    object_type: str | None = None
    object_id: UUID | None = None
    title: str
    body: str
    data: dict[str, Any] | None = Field(default=None, validation_alias="data_json")
    is_read: bool
    read_at: datetime | None = None
    created_at: datetime


class NotificationListResponse(BaseModel):
    items: list[NotificationView]
    next_cursor: str | None = None


class UnreadCountResponse(BaseModel):
    unread_count: int


# ---------------------------------------------------------------------------
# POST /me/notifications/{id}/read, POST /me/notifications/read-all
# ---------------------------------------------------------------------------


class MarkReadResponse(BaseModel):
    notification_id: UUID
    read_at: datetime


class MarkAllReadResponse(BaseModel):
    marked_count: int


# ---------------------------------------------------------------------------
# GET/PATCH /me/notification-preferences
# ---------------------------------------------------------------------------


class NotificationPreferenceItem(BaseModel):
    notification_type: NotificationType
    email_enabled: bool


class NotificationPreferencesResponse(BaseModel):
    items: list[NotificationPreferenceItem]


class NotificationPreferencesPatchRequest(BaseModel):
    items: list[NotificationPreferenceItem] = Field(min_length=1)
