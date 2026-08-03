"""Buyer matching and meeting endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Depends, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import (
    ApiRequestContext,
    get_request_context,
    require_buyer,
    require_operator,
    require_persistent_profile,
)
from app.api.v1.errors import api_error
from app.db.session import get_db
from app.models.exhibitor import Exhibitor, ExhibitorParticipation
from app.models.matching import MatchReason, MatchResult, RecommendationSession

if TYPE_CHECKING:
    from app.models.meeting import Meeting

buyer_router = APIRouter()
meetings_router = APIRouter()


class PageMeta(BaseModel):
    page: int
    page_size: int
    total_count: int


class RecommendationReasonItem(BaseModel):
    reason_code: str
    reason_text: str


class RecommendationResultItem(BaseModel):
    match_result_id: uuid.UUID
    recommendable_id: uuid.UUID
    rank: int
    normalized_score: float
    recommended_action: str | None = None
    reasons: list[RecommendationReasonItem]


class RecommendationListResponse(BaseModel):
    recommendation_session_id: uuid.UUID | None = None
    results: list[RecommendationResultItem]
    page: PageMeta


class CreateMeetingRequest(BaseModel):
    message: str = Field(min_length=1, max_length=1000)


MeetingStatus = Literal[
    "REQUESTED",
    "VIEWED",
    "COUNTER_PROPOSED",
    "CONFIRMED",
    "COMPLETED",
    "FOLLOW_UP",
    "REJECTED",
    "CANCELLED_BY_BUYER",
    "CANCELLED_BY_EXHIBITOR",
    "NO_SHOW",
]
MeetingStatusUpdate = Literal[
    "CONFIRMED",
    "REJECTED",
    "CANCELLED_BY_BUYER",
    "CANCELLED_BY_EXHIBITOR",
]


class MeetingResponse(BaseModel):
    meeting_id: uuid.UUID
    status: MeetingStatus
    contact_disclosed: bool


class UpdateMeetingStatusRequest(BaseModel):
    status: MeetingStatusUpdate


def _score(value: Decimal | float) -> float:
    return float(value)


async def _latest_buyer_session(
    db: AsyncSession, profile_id: uuid.UUID
) -> RecommendationSession | None:
    return await db.scalar(
        select(RecommendationSession)
        .where(RecommendationSession.profile_id == profile_id)
        .order_by(RecommendationSession.generated_at.desc())
        .limit(1)
    )


async def _result_reasons(
    db: AsyncSession, result_ids: list[uuid.UUID]
) -> dict[uuid.UUID, list[RecommendationReasonItem]]:
    if not result_ids:
        return {}
    rows = await db.execute(
        select(MatchReason)
        .where(MatchReason.match_result_id.in_(result_ids))
        .order_by(MatchReason.match_result_id, MatchReason.display_order)
    )
    reasons_by_result: dict[uuid.UUID, list[RecommendationReasonItem]] = {}
    for reason in rows.scalars():
        reasons_by_result.setdefault(reason.match_result_id, []).append(
            RecommendationReasonItem(
                reason_code=reason.reason_code,
                reason_text=reason.reason_text,
            )
        )
    return reasons_by_result


@buyer_router.get(
    "/matches",
    response_model=RecommendationListResponse,
    operation_id="listBuyerMatches",
)
async def list_buyer_matches(
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> RecommendationListResponse:
    profile_id = require_buyer(context)
    session = await _latest_buyer_session(db, profile_id)
    if session is None:
        return RecommendationListResponse(
            results=[],
            page=PageMeta(page=page, page_size=page_size, total_count=0),
        )

    base_filter = MatchResult.recommendation_session_id == session.recommendation_session_id
    total_count = await db.scalar(
        select(func.count()).select_from(MatchResult).where(base_filter)
    )
    result_rows = await db.scalars(
        select(MatchResult)
        .where(base_filter)
        .order_by(MatchResult.rank.asc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    )
    results = result_rows.all()
    reasons_by_result = await _result_reasons(
        db, [result.match_result_id for result in results]
    )

    return RecommendationListResponse(
        recommendation_session_id=session.recommendation_session_id,
        results=[
            RecommendationResultItem(
                match_result_id=result.match_result_id,
                recommendable_id=result.recommendable_id,
                rank=result.rank,
                normalized_score=_score(result.normalized_score),
                recommended_action=result.recommended_action,
                reasons=reasons_by_result.get(result.match_result_id, []),
            )
            for result in results
        ],
        page=PageMeta(
            page=page,
            page_size=page_size,
            total_count=int(total_count or 0),
        ),
    )


async def _find_meeting_participation(
    db: AsyncSession, exhibitor_id: uuid.UUID
) -> ExhibitorParticipation:
    participation = await db.scalar(
        select(ExhibitorParticipation)
        .join(Exhibitor, Exhibitor.exhibitor_id == ExhibitorParticipation.exhibitor_id)
        .where(
            Exhibitor.exhibitor_id == exhibitor_id,
            Exhibitor.master_approval_status == "APPROVED",
            ExhibitorParticipation.participation_status == "APPROVED",
            ExhibitorParticipation.consultation_enabled.is_(True),
        )
        .order_by(ExhibitorParticipation.approved_at.desc().nullslast())
        .limit(1)
    )
    if participation is None:
        raise api_error(
            "EXHIBITOR_NOT_PUBLISHED",
            "요청한 업체 정보를 찾을 수 없습니다.",
            status_code=404,
        )
    return participation


def _meeting_response(meeting: Meeting, *, contact_disclosed: bool = False) -> MeetingResponse:
    return MeetingResponse(
        meeting_id=meeting.meeting_id,
        status=meeting.status,  # type: ignore[arg-type]
        contact_disclosed=contact_disclosed,
    )


@buyer_router.post(
    "/matches/{exhibitor_id}/meetings",
    response_model=MeetingResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createMeetingRequest",
)
async def create_meeting_request(
    exhibitor_id: uuid.UUID,
    payload: CreateMeetingRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MeetingResponse:
    from app.models.meeting import Meeting, MeetingStatusHistory

    buyer_profile_id = require_buyer(context)
    participation = await _find_meeting_participation(db, exhibitor_id)

    meeting = Meeting(
        tenant_id=participation.tenant_id,
        event_id=participation.event_id,
        buyer_profile_id=buyer_profile_id,
        participation_id=participation.participation_id,
        message_enc=None,
        status="REQUESTED",
    )
    db.add(meeting)
    await db.flush()
    db.add(
        MeetingStatusHistory(
            meeting_id=meeting.meeting_id,
            previous_status=None,
            new_status="REQUESTED",
            changed_by=context.user_id,
            reason_code="BUYER_REQUESTED",
        )
    )
    await db.commit()
    await db.refresh(meeting)
    return _meeting_response(meeting)


async def _get_meeting(db: AsyncSession, meeting_id: uuid.UUID) -> Meeting:
    from app.models.meeting import Meeting

    meeting = await db.get(Meeting, meeting_id)
    if meeting is None:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "meeting"},
        )
    return meeting


def _authorize_status_update(context: ApiRequestContext, meeting: Meeting) -> uuid.UUID | None:
    if context.actor_role in {"OPERATOR", "ADMIN"}:
        return require_operator(context)
    profile_id = require_persistent_profile(context)
    if profile_id != meeting.buyer_profile_id:
        raise api_error(
            "PERMISSION_DENIED",
            "이 작업을 수행할 권한이 없습니다.",
            status_code=403,
        )
    return context.user_id


def _validate_transition(current_status: str, next_status: str) -> None:
    if current_status != "REQUESTED":
        raise api_error(
            "INVALID_STATE_TRANSITION",
            "현재 상태에서는 이 작업을 수행할 수 없습니다.",
            status_code=409,
        )
    if next_status not in {
        "CONFIRMED",
        "REJECTED",
        "CANCELLED_BY_BUYER",
        "CANCELLED_BY_EXHIBITOR",
    }:
        raise api_error(
            "INVALID_STATE_TRANSITION",
            "현재 상태에서는 이 작업을 수행할 수 없습니다.",
            status_code=409,
        )


async def _ensure_contact_share(
    db: AsyncSession,
    meeting: Meeting,
    *,
    disclosed_to_user_id: uuid.UUID | None,
) -> bool:
    from app.models.meeting import MeetingContactShare

    now = datetime.now(UTC)
    share = await db.scalar(
        select(MeetingContactShare).where(
            MeetingContactShare.meeting_id == meeting.meeting_id
        )
    )
    if share is None:
        share = MeetingContactShare(
            meeting_id=meeting.meeting_id,
            shared_fields={"fields": ["NAME", "PHONE", "BUSINESS_EMAIL"]},
            accepted_at=now,
            disclosed_at=now,
            disclosed_to_user_id=disclosed_to_user_id,
        )
        db.add(share)
    elif share.disclosed_at is None:
        share.disclosed_at = now
        share.disclosed_to_user_id = disclosed_to_user_id
    return True


@meetings_router.patch(
    "/{meeting_id}/status",
    response_model=MeetingResponse,
    operation_id="updateMeetingStatus",
)
async def update_meeting_status(
    meeting_id: uuid.UUID,
    payload: UpdateMeetingStatusRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> MeetingResponse:
    from app.models.meeting import MeetingStatusHistory

    if context.actor_role in {"OPERATOR", "ADMIN"}:
        require_operator(context)
    else:
        require_persistent_profile(context)

    meeting = await _get_meeting(db, meeting_id)
    actor_user_id = _authorize_status_update(context, meeting)
    _validate_transition(meeting.status, payload.status)

    previous_status = meeting.status
    meeting.status = payload.status
    contact_disclosed = False
    if payload.status == "CONFIRMED":
        contact_disclosed = await _ensure_contact_share(
            db, meeting, disclosed_to_user_id=actor_user_id
        )
    db.add(
        MeetingStatusHistory(
            meeting_id=meeting.meeting_id,
            previous_status=previous_status,
            new_status=payload.status,
            changed_by=actor_user_id,
            reason_code=f"STATUS_{payload.status}",
        )
    )
    await db.commit()
    await db.refresh(meeting)
    return _meeting_response(meeting, contact_disclosed=contact_disclosed)
