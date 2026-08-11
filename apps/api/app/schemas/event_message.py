"""Event-message API contract - WAVE 2E ADMIN-NOTIFICATION.

Model reference: ``app/models/event_message.py`` (full design rationale there). Literal value
lists here are re-declared rather than imported from the model module, following this repo's
established "router/schema layer intentionally re-lists values instead of importing another
layer's module" convention (see app/schemas/notification.py's own docstring for the identical
choice, and its ``assert set(...) == set(...)`` drift-guard test convention, mirrored in
``apps/api/tests/test_event_message_api.py``).
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

MessageType = Literal[
    "EVENT_OPERATION_NOTICE",
    "EVENT_START_REMINDER",
    "PROFILE_CONFIRMATION_REMINDER",
    "RECOMMENDATION_READY_NOTICE",
    "POST_EVENT_RESOURCE_NOTICE",
]

MessageStatus = Literal[
    "DRAFT", "PREVIEWED", "APPROVED", "SCHEDULED", "PUBLISHED", "COMPLETED", "CANCELLED"
]

Channel = Literal["IN_APP", "EMAIL"]

TargetSegment = Literal[
    "ALL_REGISTERED_USERS",
    "PROFILE_UNCONFIRMED",
    "RECOMMENDATION_READY",
    "BUYERS",
    "EXHIBITOR_STAFF",
    "SPECIFIC_ROLE",
]

TargetRoleCode = Literal["VISITOR", "BUYER", "EXHIBITOR", "OPERATOR", "ADMIN"]


class EventMessageTargeting(BaseModel):
    """Shared targeting shape between create/update requests and the read model. SPECIFIC_ROLE
    requires target_role_code; every other segment must leave it null (mirrors the DB CHECK
    ``target_role_code_matches_segment`` - the model_validator below is the same rule enforced
    one layer earlier, before a request ever reaches the database)."""

    target_segment: TargetSegment
    target_role_code: TargetRoleCode | None = None

    @model_validator(mode="after")
    def _check_role_matches_segment(self) -> EventMessageTargeting:
        if self.target_segment == "SPECIFIC_ROLE" and self.target_role_code is None:
            raise ValueError("SPECIFIC_ROLE 타겟팅에는 target_role_code가 필요합니다.")
        if self.target_segment != "SPECIFIC_ROLE" and self.target_role_code is not None:
            raise ValueError("SPECIFIC_ROLE이 아닌 세그먼트에는 target_role_code를 지정할 수 없습니다.")
        return self


# ---------------------------------------------------------------------------
# POST /admin/event-messages
# ---------------------------------------------------------------------------


class EventMessageCreateRequest(EventMessageTargeting):
    event_id: UUID
    message_type: MessageType
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1)
    channels: list[Channel] = Field(min_length=1)
    destination_screen: str = Field(min_length=1, max_length=200)
    scheduled_at: datetime | None = None


# ---------------------------------------------------------------------------
# PATCH /admin/event-messages/{id}
# ---------------------------------------------------------------------------


class EventMessageUpdateRequest(BaseModel):
    """All fields optional (partial update). Any non-null field here is one of the "content or
    targeting" fields that resets a PREVIEWED/APPROVED message back to DRAFT (task-spec-adjacent
    invariant, see app/services/event_message/workflow.py)."""

    message_type: MessageType | None = None
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1)
    channels: list[Channel] | None = Field(default=None, min_length=1)
    target_segment: TargetSegment | None = None
    target_role_code: TargetRoleCode | None = None
    destination_screen: str | None = Field(default=None, min_length=1, max_length=200)
    scheduled_at: datetime | None = None
    row_version: int = Field(description="낙관적 잠금 - If-Match 대용 바디 필드.")


# ---------------------------------------------------------------------------
# Read model
# ---------------------------------------------------------------------------


class EventMessageRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    event_message_id: UUID
    event_id: UUID
    message_type: MessageType
    status: MessageStatus
    title: str
    body: str
    channels: list[Channel] = Field(validation_alias="channels_json")
    target_segment: TargetSegment
    target_role_code: TargetRoleCode | None
    destination_screen: str
    scheduled_at: datetime | None
    published_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
    previewed_at: datetime | None
    created_by_user_id: UUID | None
    approved_by_user_id: UUID | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class EventMessageListResponse(BaseModel):
    items: list[EventMessageRead]


# ---------------------------------------------------------------------------
# POST /admin/event-messages/{id}/preview
# ---------------------------------------------------------------------------


class EventMessagePreview(BaseModel):
    """Everything the task spec requires the preview to show: title, body, target count,
    channels, scheduled time, destination screen, duplicate-target warning, consent-excluded
    count.

    ``target_count`` is null and ``target_count_display`` reads "5명 미만" whenever the real
    count is below the repo-wide small-group suppression threshold
    (app/services/event_message/targeting.py::SMALL_AUDIENCE_THRESHOLD) - never add a field
    that echoes the exact sub-threshold number elsewhere in this schema.
    """

    event_message_id: UUID
    title: str
    body: str
    channels: list[Channel]
    target_segment: TargetSegment
    target_role_code: TargetRoleCode | None
    target_count: int | None
    target_count_display: str
    small_audience_warning: bool
    destination_screen: str
    scheduled_at: datetime | None
    duplicate_target_warning: bool
    duplicate_target_message_count: int
    consent_excluded_count: int
    previewed_at: datetime


# ---------------------------------------------------------------------------
# POST /admin/event-messages/{id}/{approve,schedule,publish,cancel,complete}
# ---------------------------------------------------------------------------


class EventMessageApproveRequest(BaseModel):
    row_version: int


class EventMessageScheduleRequest(BaseModel):
    row_version: int
    scheduled_at: datetime


class EventMessagePublishRequest(BaseModel):
    row_version: int


class EventMessageCancelRequest(BaseModel):
    row_version: int
    reason: str = Field(min_length=1)


class EventMessageCompleteRequest(BaseModel):
    row_version: int


class PublishResult(BaseModel):
    event_message: EventMessageRead
    resolved_recipient_count: int
    email_consent_excluded_count: int
