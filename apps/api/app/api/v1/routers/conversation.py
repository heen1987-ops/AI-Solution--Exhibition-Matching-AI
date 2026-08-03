"""Stage-19 conversational profiling endpoints.

Only masked message text is persisted.  Extracted values remain proposals until
the user confirms them, and only ontology-backed proposals are applied to the
canonical profile store.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated, TypeVar

from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routers.profile import (
    _bump_version,
    _invalidate_active_recommendations,
)
from app.api.v1.routers.recommendations import VerifiedSubject, resolve_subject_context
from app.db.session import get_db
from app.models.conversation import (
    ConversationMessage,
    ConversationSession,
    EntityExtraction,
)
from app.models.profile import ProfileAttribute, UserProfile
from app.schemas.conversation import (
    ClarificationView,
    ConversationMessageRequest,
    ConversationMessageResponse,
    ConversationStartRequest,
    ConversationStartResponse,
    ExtractionDecisionRequest,
    ExtractionDecisionResponse,
    ExtractionView,
)
from app.schemas.recommendation import Envelope, Meta
from app.services.conversation_policy import (
    CONVERSATION_POLICY_VERSION,
    content_fingerprint,
    interpret_message,
    mask_sensitive_text,
)
from meet_ai.ontology import load_catalog
from meet_ai.ontology.catalog import stable_uuid

router = APIRouter()
DbSession = Annotated[AsyncSession, Depends(get_db)]
ResponseT = TypeVar("ResponseT")


def _envelope(data: ResponseT, request: Request) -> Envelope[ResponseT]:
    return Envelope(
        data=data,
        meta=Meta(
            request_id=request.headers.get("X-Request-ID") or str(uuid.uuid4()),
            server_time=datetime.now(UTC),
        ),
    )


def _forbidden() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="conversation does not belong to the signed site context",
    )


async def _scoped_conversation(
    db: AsyncSession,
    conversation_id: uuid.UUID,
    request: Request,
    verified: VerifiedSubject,
) -> tuple[ConversationSession, UserProfile]:
    subject = await resolve_subject_context(request, db, verified)
    conversation = await db.get(ConversationSession, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="conversation not found",
        )
    if (
        conversation.tenant_id != subject.tenant_id
        or conversation.event_id != subject.event_id
        or conversation.profile_id != subject.profile_id
    ):
        raise _forbidden()
    profile = await db.get(UserProfile, subject.profile_id)
    if profile is None or profile.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="profile not found",
        )
    return conversation, profile


@router.post(
    "/conversations",
    response_model=Envelope[ConversationStartResponse],
)
async def start_conversation(
    payload: ConversationStartRequest,
    request: Request,
    db: DbSession,
    verified: VerifiedSubject,
) -> Envelope[ConversationStartResponse]:
    subject = await resolve_subject_context(request, db, verified)
    profile = await db.get(UserProfile, subject.profile_id)
    if profile is None or profile.deleted_at is not None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="profile not found",
        )
    existing = (
        await db.execute(
            select(ConversationSession)
            .where(
                ConversationSession.tenant_id == subject.tenant_id,
                ConversationSession.event_id == subject.event_id,
                ConversationSession.profile_id == subject.profile_id,
                ConversationSession.status == "ACTIVE",
            )
            .order_by(ConversationSession.last_activity_at.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    conversation = existing or ConversationSession(
        tenant_id=subject.tenant_id,
        event_id=subject.event_id,
        profile_id=subject.profile_id,
        visit_session_id=subject.visit_session_id,
        user_type=profile.user_type,
        language=payload.language,
        dialog_state="COLLECT_GOAL",
        status="ACTIVE",
        policy_version=CONVERSATION_POLICY_VERSION,
        state_json={},
        last_activity_at=subject.server_time,
    )
    if existing is None:
        db.add(conversation)
        await db.commit()
        await db.refresh(conversation)
    return _envelope(
        ConversationStartResponse(
            conversation_id=conversation.conversation_id,
            profile_id=conversation.profile_id,
            user_type=conversation.user_type,  # type: ignore[arg-type]
            dialog_state=conversation.dialog_state,
            status=conversation.status,
            policy_version=conversation.policy_version,
        ),
        request,
    )


@router.post(
    "/conversations/{conversation_id}/messages",
    response_model=Envelope[ConversationMessageResponse],
)
async def add_conversation_message(
    conversation_id: uuid.UUID,
    payload: ConversationMessageRequest,
    request: Request,
    db: DbSession,
    verified: VerifiedSubject,
) -> Envelope[ConversationMessageResponse]:
    conversation, profile = await _scoped_conversation(
        db, conversation_id, request, verified
    )
    if conversation.status != "ACTIVE":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="conversation is not active",
        )
    existing_codes = frozenset(
        (
            await db.execute(
                select(ProfileAttribute.attribute_code).where(
                    ProfileAttribute.profile_id == profile.profile_id,
                    ProfileAttribute.active.is_(True),
                )
            )
        ).scalars()
    )
    masked = mask_sensitive_text(payload.message.strip())
    decision = interpret_message(
        masked,
        user_type=profile.user_type,
        existing_codes=existing_codes,
    )
    message = ConversationMessage(
        conversation_id=conversation_id,
        sender_type="USER",
        masked_text=masked,
        content_hash=content_fingerprint(masked),
        message_type="TEXT",
    )
    db.add(message)
    await db.flush()

    rows: list[EntityExtraction] = []
    for entity in decision.entities:
        row = EntityExtraction(
            message_id=message.message_id,
            attribute_code=entity.attribute_code,
            operator_code=entity.operator,
            value_json=entity.value,
            unit_code=entity.unit,
            requirement_level=entity.requirement_level,
            source_text=entity.source_text,
            confidence=entity.confidence,
            status=entity.status,
            policy_version=decision.policy_version,
            input_fingerprint=decision.input_fingerprint,
        )
        db.add(row)
        rows.append(row)

    db.add(
        ConversationMessage(
            conversation_id=conversation_id,
            sender_type="ASSISTANT",
            masked_text=decision.assistant_message,
            content_hash=content_fingerprint(decision.assistant_message),
            message_type="TEXT",
        )
    )
    conversation.dialog_state = decision.next_action
    conversation.state_json = {
        "last_intent": decision.intent_code,
        "ambiguities": list(decision.ambiguities),
        "recommendation_ready": decision.recommendation_ready,
        "input_fingerprint": decision.input_fingerprint,
    }
    conversation.last_activity_at = datetime.now(UTC)
    await db.commit()

    question = decision.next_question
    return _envelope(
        ConversationMessageResponse(
            conversation_id=conversation_id,
            message_id=message.message_id,
            assistant_message=decision.assistant_message,
            intent_code=decision.intent_code,
            intent_confidence=decision.intent_confidence,
            extractions=[
                ExtractionView(
                    extraction_id=row.extraction_id,
                    attribute_code=row.attribute_code,
                    operator=row.operator_code,
                    value=row.value_json,
                    unit=row.unit_code,
                    requirement_level=row.requirement_level,
                    source_text=row.source_text,
                    confidence=float(row.confidence),
                    status=row.status,
                )
                for row in rows
            ],
            ambiguities=list(decision.ambiguities),
            next_action=decision.next_action,
            next_question=(
                ClarificationView(
                    code=question.code,
                    text=question.text,
                    options=list(question.options),
                )
                if question is not None
                else None
            ),
            recommendation_ready=decision.recommendation_ready,
            policy_version=decision.policy_version,
            input_fingerprint=decision.input_fingerprint,
        ),
        request,
    )


@router.post(
    "/conversations/{conversation_id}/extractions/{extraction_id}/decision",
    response_model=Envelope[ExtractionDecisionResponse],
)
async def decide_extraction(
    conversation_id: uuid.UUID,
    extraction_id: uuid.UUID,
    payload: ExtractionDecisionRequest,
    request: Request,
    db: DbSession,
    verified: VerifiedSubject,
) -> Envelope[ExtractionDecisionResponse]:
    conversation, profile = await _scoped_conversation(
        db, conversation_id, request, verified
    )
    extraction = await db.get(EntityExtraction, extraction_id)
    if extraction is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="extraction not found",
        )
    message = await db.get(ConversationMessage, extraction.message_id)
    if message is None or message.conversation_id != conversation.conversation_id:
        raise _forbidden()
    if extraction.status != "PROPOSED":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="extraction has already been decided",
        )
    if profile.current_version != payload.expected_profile_version:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="profile version conflict",
        )

    extraction.decided_at = datetime.now(UTC)
    if payload.action == "REJECT":
        extraction.status = "REJECTED"
        await db.commit()
        return _envelope(
            ExtractionDecisionResponse(
                extraction_id=extraction_id,
                status="REJECTED",
                application_status="NOT_APPLIED",
                profile_version=profile.current_version,
                recommendation_refresh_required=False,
            ),
            request,
        )

    catalog = load_catalog()
    if extraction.attribute_code not in catalog.by_code:
        extraction.status = "CONFIRMED"
        await db.commit()
        return _envelope(
            ExtractionDecisionResponse(
                extraction_id=extraction_id,
                status="CONFIRMED",
                application_status="STRUCTURED_FIELD_REQUIRED",
                profile_version=profile.current_version,
                recommendation_refresh_required=False,
            ),
            request,
        )

    taxonomy_version_id = stable_uuid("taxonomy-version", catalog.version)
    concept_id = stable_uuid("concept", extraction.attribute_code)
    prior_rows = (
        (
            await db.execute(
                select(ProfileAttribute).where(
                    ProfileAttribute.profile_id == profile.profile_id,
                    ProfileAttribute.attribute_code == extraction.attribute_code,
                    ProfileAttribute.active.is_(True),
                )
            )
        )
        .scalars()
        .all()
    )
    for prior in prior_rows:
        prior.active = False
        prior.valid_until = extraction.decided_at

    attribute = ProfileAttribute(
        profile_id=profile.profile_id,
        taxonomy_version_id=taxonomy_version_id,
        concept_id=concept_id,
        attribute_code=extraction.attribute_code,
        value_json=extraction.value_json,
        requirement_level=extraction.requirement_level,
        source_type="USER_TYPED",
        source_reference_id=extraction.extraction_id,
        confidence=1,
        valid_from=extraction.decided_at,
        active=True,
    )
    db.add(attribute)
    await db.flush()
    extraction.status = "CONFIRMED"
    extraction.applied_profile_attribute_id = attribute.profile_attribute_id
    await _bump_version(db, profile, "AI_CONFIRMATION")
    await _invalidate_active_recommendations(db, profile)
    await db.commit()
    return _envelope(
        ExtractionDecisionResponse(
            extraction_id=extraction_id,
            status="CONFIRMED",
            application_status="APPLIED",
            profile_version=profile.current_version,
            recommendation_refresh_required=True,
        ),
        request,
    )
