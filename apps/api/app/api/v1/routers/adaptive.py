"""Portable stage-16/17 APIs mounted below /api/v1.

The public site or `/adm/` adapter supplies the same signed site-context headers
used by recommendations.  No backju.kr database or PHP session is imported.
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routers.recommendations import resolve_subject_context
from app.db.session import get_db
from app.models.cold_start import QuestionDefinition, QuestionResponse
from app.models.learning import ProfileInference
from app.models.profile import UserProfile
from app.schemas.adaptive import (
    BehaviorProcessRequest,
    BehaviorProcessResponse,
    ColdStartAnswersRequest,
    ColdStartAnswersResponse,
    ColdStartStatusView,
    InferenceActionResponse,
    NextBestQuestionView,
)
from app.services.behavior_learning import (
    ProcessBehaviorCommand,
    process_behavior_event,
)
from app.services.learning_policy import AttributeTarget
from app.services.matching.cold_start_policy import (
    COLD_START_POLICY_VERSION,
    evaluate_cold_start,
)
from app.services.matching.cold_start_runtime import resolve_evidence
from app.services.matching.profile_resolver import resolve_profile

router = APIRouter()
DbSession = Annotated[AsyncSession, Depends(get_db)]


def _assert_profile_scope(profile_id: uuid.UUID, request: Request):
    subject = resolve_subject_context(request)
    if profile_id != subject.profile_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="profile_id must match the signed site context",
        )
    return subject


@router.get("/profiles/{profile_id}/cold-start", response_model=ColdStartStatusView)
async def get_cold_start_status(profile_id: uuid.UUID, request: Request, db: DbSession):
    subject = _assert_profile_scope(profile_id, request)
    profile = await resolve_profile(db, subject=subject)
    evidence = await resolve_evidence(db, subject=subject, profile=profile)
    decision = evaluate_cold_start(profile, evidence)
    return ColdStartStatusView(
        profile_id=profile_id,
        status=decision.state,
        type_codes=list(decision.type_codes),
        stability_score=decision.stability_score,
        exploration_ratio=decision.exploration_ratio,
        recommendation_confidence_cap=decision.recommendation_confidence_cap,
        next_question_codes=list(decision.next_question_codes),
        policy_version=decision.policy_version,
        input_fingerprint=decision.input_fingerprint,
    )


@router.post("/profiles/{profile_id}/cold-start/answers", response_model=ColdStartAnswersResponse)
async def submit_cold_start_answers(
    profile_id: uuid.UUID,
    payload: ColdStartAnswersRequest,
    request: Request,
    db: DbSession,
):
    _assert_profile_scope(profile_id, request)
    profile = await db.get(UserProfile, profile_id)
    if profile is None or profile.current_version != payload.profile_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="profile version conflict",
        )
    question_ids = [item.question_id for item in payload.answers]
    rows = await db.execute(
        select(QuestionDefinition.question_id).where(
            QuestionDefinition.question_id.in_(question_ids),
            QuestionDefinition.active.is_(True),
            QuestionDefinition.user_type == profile.user_type,
        )
    )
    known = {row[0] for row in rows}
    if known != set(question_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="unknown or inactive cold-start question",
        )
    for item in payload.answers:
        db.add(
            QuestionResponse(
                profile_id=profile_id,
                question_id=item.question_id,
                profile_version=payload.profile_version,
                answer_json=item.answer,
                response_source=item.response_source,
                information_gain=item.information_gain,
            )
        )
    await db.commit()
    return ColdStartAnswersResponse(
        profile_id=profile_id,
        accepted_question_ids=question_ids,
        profile_version=profile.current_version,
    )


@router.get("/profiles/{profile_id}/next-best-question", response_model=NextBestQuestionView)
async def get_next_best_question(profile_id: uuid.UUID, request: Request, db: DbSession):
    _assert_profile_scope(profile_id, request)
    profile = await db.get(UserProfile, profile_id)
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="profile not found",
        )
    answered_rows = await db.execute(
        select(QuestionResponse.question_id).where(QuestionResponse.profile_id == profile_id)
    )
    answered = {row[0] for row in answered_rows}
    question = (
        await db.execute(
            select(QuestionDefinition)
            .where(
                QuestionDefinition.user_type == profile.user_type,
                QuestionDefinition.active.is_(True),
                QuestionDefinition.question_id.not_in(answered),
            )
            .order_by(QuestionDefinition.base_priority)
            .limit(1)
        )
    ).scalar_one_or_none()
    if question is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="no next question",
        )
    return NextBestQuestionView(
        question_id=question.question_id,
        attribute_code=question.attribute_code,
        question=question.question_text,
        options=question.option_json,
        expected_information_gain=0.0,
        policy_version=COLD_START_POLICY_VERSION,
    )


@router.post("/internal/learning/events/process", response_model=BehaviorProcessResponse)
async def process_learning_event(payload: BehaviorProcessRequest, request: Request, db: DbSession):
    subject = resolve_subject_context(request)
    result = await process_behavior_event(
        db,
        subject=subject,
        command=ProcessBehaviorCommand(
            event_date=payload.event_date,
            interaction_event_id=payload.interaction_event_id,
            learning_consent=payload.learning_consent,
            cause_code=payload.cause_code,
            attribute_targets=tuple(
                AttributeTarget(item.code, item.target_level, item.propagation_weight)
                for item in payload.attribute_targets
            ),
            actual_impression=payload.actual_impression,
            is_bot=payload.is_bot,
            is_employee=payload.is_employee,
            is_test=payload.is_test,
            is_advertising=payload.is_advertising,
            duplicate=payload.duplicate,
            independent_evidence_count=payload.independent_evidence_count,
            position_propensity=payload.position_propensity,
        ),
    )
    await db.commit()
    decision = result.decision
    return BehaviorProcessResponse(
        processing_id=result.processing_id,
        event_id=payload.interaction_event_id,
        validation_status=decision.validation_status,
        signal_type=decision.signal_type,
        signal_strength=decision.signal_strength,
        decayed_signal=decision.decayed_signal,
        cause_scope=decision.cause_scope,
        affected_attributes=list(result.affected_attributes),
        profile_update_required=decision.profile_update_required,
        recommendation_refresh_required=decision.recommendation_refresh_required,
        processing_mode=decision.processing_mode,
        profile_version=result.profile_version,
        policy_version=decision.policy_version,
        input_fingerprint=decision.input_fingerprint,
        invalid_reason_codes=list(decision.invalid_reason_codes),
        idempotent_replay=result.idempotent_replay,
    )


@router.post("/profiles/{profile_id}/inferences/{inference_id}/confirm", response_model=InferenceActionResponse)
async def confirm_inference(profile_id: uuid.UUID, inference_id: uuid.UUID, request: Request, db: DbSession):
    _assert_profile_scope(profile_id, request)
    inference = await db.get(ProfileInference, inference_id)
    if inference is None or inference.profile_id != profile_id or inference.status == "DELETED":
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="inference not found",
        )
    inference.status = "CONFIRMED"
    inference.user_confirmed = True
    await db.commit()
    return InferenceActionResponse(inference_id=inference_id, status=inference.status, user_confirmed=True)


@router.delete("/profiles/{profile_id}/inferences/{inference_id}", response_model=InferenceActionResponse)
async def delete_inference(profile_id: uuid.UUID, inference_id: uuid.UUID, request: Request, db: DbSession):
    subject = _assert_profile_scope(profile_id, request)
    inference = await db.get(ProfileInference, inference_id)
    if inference is None or inference.profile_id != profile_id:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="inference not found",
        )
    inference.status = "DELETED"
    inference.user_confirmed = False
    inference.deleted_at = subject.server_time
    await db.commit()
    return InferenceActionResponse(inference_id=inference_id, status="DELETED", user_confirmed=False)
