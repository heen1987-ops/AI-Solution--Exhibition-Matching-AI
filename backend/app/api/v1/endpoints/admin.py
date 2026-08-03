"""Admin operation endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import (
    ApiRequestContext,
    get_request_context,
    require_operator,
)
from app.api.v1.endpoints.exhibitors import BoothDetailResponse, booth_detail_or_404
from app.api.v1.errors import api_error
from app.db.session import get_db
from app.models.exhibitor import Booth, BoothStatusHistory, Exhibitor

if TYPE_CHECKING:
    from app.models.ai import SourceDocument

router = APIRouter()

Decision = Literal["APPROVED", "REJECTED"]
BoothOperatingStatus = Literal["OPEN", "PAUSED", "CLOSED"]
BoothCongestionLevel = Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]


class CreateContentApprovalRequest(BaseModel):
    exhibitor_id: uuid.UUID
    decision: Decision
    note: str | None = Field(default=None, max_length=1000)


class ContentApprovalResponse(BaseModel):
    content_approval_id: uuid.UUID
    exhibitor_id: uuid.UUID
    decision: Decision
    approved_at: datetime


class UpdateBoothStatusRequest(BaseModel):
    operating_status: BoothOperatingStatus
    congestion_level: BoothCongestionLevel | None = None
    row_version: int | None = Field(default=None, ge=1)


async def _get_exhibitor(db: AsyncSession, exhibitor_id: uuid.UUID) -> Exhibitor:
    exhibitor = await db.get(Exhibitor, exhibitor_id)
    if exhibitor is None:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "exhibitor"},
        )
    return exhibitor


async def _get_latest_source_document(
    db: AsyncSession, exhibitor_id: uuid.UUID
) -> SourceDocument:
    from app.models.ai import SourceDocument

    document = await db.scalar(
        select(SourceDocument)
        .where(SourceDocument.exhibitor_id == exhibitor_id)
        .order_by(SourceDocument.created_at.desc())
        .limit(1)
    )
    if document is None:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "source_document"},
        )
    return document


@router.post(
    "/content-approvals",
    response_model=ContentApprovalResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="createContentApproval",
)
async def create_content_approval(
    payload: CreateContentApprovalRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ContentApprovalResponse:
    from app.models.ai import ContentApproval

    operator_user_id = require_operator(context)
    exhibitor = await _get_exhibitor(db, payload.exhibitor_id)
    document = await _get_latest_source_document(db, payload.exhibitor_id)

    previous_status = exhibitor.master_approval_status
    exhibitor.master_approval_status = payload.decision

    approval = ContentApproval(
        tenant_id=document.tenant_id,
        event_id=document.event_id,
        source_document_id=document.source_document_id,
        exhibitor_id=payload.exhibitor_id,
        approval_scope="DOCUMENT",
        approval_decision=payload.decision,
        previous_master_approval_status=previous_status,
        new_master_approval_status=payload.decision,
        approved_by_user_id=operator_user_id,
        approval_note=payload.note,
    )
    db.add(approval)
    await db.commit()
    await db.refresh(approval)

    return ContentApprovalResponse(
        content_approval_id=approval.content_approval_id,
        exhibitor_id=payload.exhibitor_id,
        decision=payload.decision,
        approved_at=approval.approved_at,
    )


@router.patch(
    "/booths/{booth_id}/status",
    response_model=BoothDetailResponse,
    operation_id="updateBoothStatus",
)
async def update_booth_status(
    booth_id: uuid.UUID,
    payload: UpdateBoothStatusRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BoothDetailResponse:
    operator_user_id = require_operator(context)
    booth = await db.get(Booth, booth_id)
    if booth is None:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "booth"},
        )
    if payload.row_version is not None and booth.row_version != payload.row_version:
        raise api_error(
            "RESOURCE_CONFLICT",
            "요청이 현재 상태와 충돌합니다.",
            status_code=409,
            details={"resource": "booth", "field": "row_version"},
        )

    previous_status = booth.operating_status
    booth.operating_status = payload.operating_status
    if payload.congestion_level is not None:
        booth.congestion_level = payload.congestion_level
    booth.status_observed_at = datetime.now(UTC)
    booth.row_version += 1

    db.add(
        BoothStatusHistory(
            booth_id=booth.booth_id,
            previous_status=previous_status,
            new_status=payload.operating_status,
            changed_by_user_id=operator_user_id,
            reason_code="ADMIN_STATUS_UPDATE",
        )
    )
    await db.commit()

    return await booth_detail_or_404(db, booth_id)
