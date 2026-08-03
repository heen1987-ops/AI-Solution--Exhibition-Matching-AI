"""Public exhibitor and booth lookup endpoints."""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.errors import api_error
from app.db.session import get_db
from app.models.exhibitor import (
    Booth,
    Exhibitor,
    ExhibitorBusinessType,
    ExhibitorParticipation,
)
from app.models.ontology_refs import concept

router = APIRouter()


class ExhibitorDetailResponse(BaseModel):
    exhibitor_id: uuid.UUID
    exhibitor_name: str
    business_types: list[str]
    booths: list[uuid.UUID]


class BoothDetailResponse(BaseModel):
    booth_id: uuid.UUID
    exhibitor_id: uuid.UUID
    operating_status: str
    congestion_level: str
    row_version: int


async def _approved_exhibitor_or_404(
    db: AsyncSession, exhibitor_id: uuid.UUID
) -> Exhibitor:
    exhibitor = await db.get(Exhibitor, exhibitor_id)
    if (
        exhibitor is None
        or exhibitor.deleted_at is not None
        or exhibitor.master_approval_status != "APPROVED"
    ):
        raise api_error(
            "EXHIBITOR_NOT_PUBLISHED",
            "요청한 업체 정보를 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "exhibitor"},
        )
    return exhibitor


async def _business_type_codes(
    db: AsyncSession, exhibitor_id: uuid.UUID
) -> list[str]:
    rows = await db.scalars(
        select(concept.c.concept_code)
        .join(
            ExhibitorBusinessType,
            ExhibitorBusinessType.concept_id == concept.c.concept_id,
        )
        .where(ExhibitorBusinessType.exhibitor_id == exhibitor_id)
        .order_by(concept.c.concept_code.asc())
    )
    return list(rows.all())


async def _approved_booth_ids(
    db: AsyncSession, exhibitor_id: uuid.UUID
) -> list[uuid.UUID]:
    rows = await db.scalars(
        select(Booth.booth_id)
        .join(
            ExhibitorParticipation,
            Booth.participation_id == ExhibitorParticipation.participation_id,
        )
        .where(
            ExhibitorParticipation.exhibitor_id == exhibitor_id,
            ExhibitorParticipation.participation_status == "APPROVED",
        )
        .order_by(Booth.booth_number.asc())
    )
    return list(rows.all())


async def booth_detail_or_404(
    db: AsyncSession, booth_id: uuid.UUID
) -> BoothDetailResponse:
    row = (
        await db.execute(
            select(
                Booth.booth_id,
                ExhibitorParticipation.exhibitor_id,
                Booth.operating_status,
                Booth.congestion_level,
                Booth.row_version,
            )
            .join(
                ExhibitorParticipation,
                Booth.participation_id == ExhibitorParticipation.participation_id,
            )
            .join(Exhibitor, Exhibitor.exhibitor_id == ExhibitorParticipation.exhibitor_id)
            .where(
                Booth.booth_id == booth_id,
                Exhibitor.deleted_at.is_(None),
                Exhibitor.master_approval_status == "APPROVED",
                ExhibitorParticipation.participation_status == "APPROVED",
            )
            .limit(1)
        )
    ).one_or_none()
    if row is None:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "booth"},
        )
    return BoothDetailResponse(
        booth_id=row.booth_id,
        exhibitor_id=row.exhibitor_id,
        operating_status=row.operating_status,
        congestion_level=row.congestion_level,
        row_version=int(row.row_version),
    )


@router.get(
    "/exhibitors/{exhibitor_id}",
    response_model=ExhibitorDetailResponse,
    operation_id="getExhibitor",
)
async def get_exhibitor(
    exhibitor_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ExhibitorDetailResponse:
    exhibitor = await _approved_exhibitor_or_404(db, exhibitor_id)
    business_types = await _business_type_codes(db, exhibitor_id)
    booths = await _approved_booth_ids(db, exhibitor_id)
    return ExhibitorDetailResponse(
        exhibitor_id=exhibitor.exhibitor_id,
        exhibitor_name=exhibitor.company_name,
        business_types=business_types,
        booths=booths,
    )


@router.get(
    "/booths/{booth_id}",
    response_model=BoothDetailResponse,
    operation_id="getBooth",
)
async def get_booth(
    booth_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> BoothDetailResponse:
    return await booth_detail_or_404(db, booth_id)
