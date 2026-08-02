"""Stage-19 conversational profiling API contracts."""

from __future__ import annotations

import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field


class ConversationStartRequest(BaseModel):
    language: str = Field(default="ko", min_length=2, max_length=10)


class ConversationStartResponse(BaseModel):
    conversation_id: uuid.UUID
    profile_id: uuid.UUID
    user_type: Literal["GENERAL_VISITOR", "BUYER"]
    dialog_state: str
    status: str
    policy_version: str


class ConversationMessageRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)


class ExtractionView(BaseModel):
    extraction_id: uuid.UUID
    attribute_code: str
    operator: str
    value: dict[str, Any]
    unit: str | None
    requirement_level: str
    source_text: str
    confidence: float
    status: str


class ClarificationView(BaseModel):
    code: str
    text: str
    options: list[str]


class ConversationMessageResponse(BaseModel):
    conversation_id: uuid.UUID
    message_id: uuid.UUID
    assistant_message: str
    intent_code: str
    intent_confidence: float
    extractions: list[ExtractionView]
    ambiguities: list[str]
    next_action: str
    next_question: ClarificationView | None
    recommendation_ready: bool
    policy_version: str
    input_fingerprint: str


class ExtractionDecisionRequest(BaseModel):
    action: Literal["CONFIRM", "REJECT"]
    expected_profile_version: int = Field(ge=1)


class ExtractionDecisionResponse(BaseModel):
    extraction_id: uuid.UUID
    status: str
    application_status: str
    profile_version: int
    recommendation_refresh_required: bool
