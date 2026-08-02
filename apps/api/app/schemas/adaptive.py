"""Stage-16 cold-start and stage-17 behavior-learning API schemas."""

from __future__ import annotations

import uuid
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field


class ColdStartStatusView(BaseModel):
    profile_id: uuid.UUID
    status: Literal["COLD", "WARMING", "STABLE", "RESET"]
    type_codes: list[str]
    stability_score: float
    exploration_ratio: float
    recommendation_confidence_cap: float | None
    next_question_codes: list[str]
    policy_version: str
    input_fingerprint: str


class ColdStartAnswer(BaseModel):
    question_id: str = Field(min_length=1, max_length=60)
    answer: dict[str, Any]
    response_source: Literal["MINIMUM_PROFILE", "NEXT_BEST_QUESTION", "PAIRWISE"] = "MINIMUM_PROFILE"
    information_gain: float | None = Field(default=None, ge=0, le=1)


class ColdStartAnswersRequest(BaseModel):
    profile_version: int = Field(ge=1)
    answers: list[ColdStartAnswer] = Field(min_length=1, max_length=10)


class ColdStartAnswersResponse(BaseModel):
    profile_id: uuid.UUID
    accepted_question_ids: list[str]
    profile_version: int
    recommendation_refresh_required: bool = True


class NextBestQuestionView(BaseModel):
    question_id: str
    attribute_code: str
    question: str
    options: list[Any]
    expected_information_gain: float
    policy_version: str


class LearningAttributeTargetIn(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    target_level: str = Field(min_length=1, max_length=30)
    propagation_weight: float = Field(ge=0, le=1)


class BehaviorProcessRequest(BaseModel):
    event_date: date
    interaction_event_id: uuid.UUID
    learning_consent: bool
    cause_code: str | None = Field(default=None, max_length=60)
    attribute_targets: list[LearningAttributeTargetIn] = Field(default_factory=list, max_length=30)
    actual_impression: bool = True
    is_bot: bool = False
    is_employee: bool = False
    is_test: bool = False
    is_advertising: bool = False
    duplicate: bool = False
    independent_evidence_count: int = Field(default=1, ge=1, le=100)
    position_propensity: float | None = Field(default=None, gt=0, le=1)


class AffectedAttributeView(BaseModel):
    code: str
    adjustment: float
    status: str


class BehaviorProcessResponse(BaseModel):
    processing_id: uuid.UUID
    event_id: uuid.UUID
    validation_status: str
    signal_type: str
    signal_strength: float
    decayed_signal: float
    cause_scope: str
    affected_attributes: list[AffectedAttributeView]
    profile_update_required: bool
    recommendation_refresh_required: bool
    processing_mode: str
    profile_version: int
    policy_version: str
    input_fingerprint: str
    invalid_reason_codes: list[str]
    idempotent_replay: bool = False


class InferenceActionResponse(BaseModel):
    inference_id: uuid.UUID
    status: str
    user_confirmed: bool
