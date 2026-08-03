"""Favorites API backed by profile.saved_recommendable."""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import (
    ApiRequestContext,
    get_request_context,
    require_persistent_profile,
)
from app.api.v1.errors import api_error
from app.db.session import get_db
from app.models.matching import Recommendable
from app.models.profile import SavedRecommendable

router = APIRouter()


class PageMeta(BaseModel):
    page: int
    page_size: int
    total_count: int


class AddFavoriteRequest(BaseModel):
    recommendable_id: uuid.UUID
    saved_context_json: dict[str, Any] | None = Field(default=None)


class FavoriteResponse(BaseModel):
    saved_recommendable_id: uuid.UUID
    recommendable_id: uuid.UUID
    saved_at: datetime


class FavoriteListResponse(BaseModel):
    items: list[FavoriteResponse]
    page: PageMeta


async def _ensure_active_recommendable(
    db: AsyncSession, recommendable_id: uuid.UUID
) -> None:
    active = await db.scalar(
        select(Recommendable.active).where(
            Recommendable.recommendable_id == recommendable_id
        )
    )
    if active is not True:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
        )


def _to_response(saved: SavedRecommendable) -> FavoriteResponse:
    return FavoriteResponse(
        saved_recommendable_id=saved.saved_recommendable_id,
        recommendable_id=saved.recommendable_id,
        saved_at=saved.saved_at,
    )


@router.get("", response_model=FavoriteListResponse, operation_id="listFavorites")
async def list_favorites(
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> FavoriteListResponse:
    profile_id = require_persistent_profile(context)
    offset = (page - 1) * page_size

    base_filter = SavedRecommendable.profile_id == profile_id
    total_count = await db.scalar(
        select(func.count()).select_from(SavedRecommendable).where(base_filter)
    )
    result = await db.scalars(
        select(SavedRecommendable)
        .where(base_filter)
        .order_by(SavedRecommendable.saved_at.desc())
        .offset(offset)
        .limit(page_size)
    )

    return FavoriteListResponse(
        items=[_to_response(saved) for saved in result.all()],
        page=PageMeta(
            page=page,
            page_size=page_size,
            total_count=int(total_count or 0),
        ),
    )


@router.post(
    "",
    response_model=FavoriteResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="addFavorite",
)
async def add_favorite(
    payload: AddFavoriteRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> FavoriteResponse:
    profile_id = require_persistent_profile(context)
    await _ensure_active_recommendable(db, payload.recommendable_id)

    saved = SavedRecommendable(
        profile_id=profile_id,
        recommendable_id=payload.recommendable_id,
        saved_context_json=payload.saved_context_json,
    )
    db.add(saved)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise api_error(
            "RESOURCE_CONFLICT",
            "요청이 현재 상태와 충돌합니다.",
            status_code=409,
            details={"resource": "favorite"},
        ) from exc
    await db.refresh(saved)
    return _to_response(saved)


@router.delete(
    "/{saved_recommendable_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="removeFavorite",
)
async def remove_favorite(
    saved_recommendable_id: uuid.UUID,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    profile_id = require_persistent_profile(context)
    await db.execute(
        delete(SavedRecommendable).where(
            SavedRecommendable.saved_recommendable_id == saved_recommendable_id,
            SavedRecommendable.profile_id == profile_id,
        )
    )
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
