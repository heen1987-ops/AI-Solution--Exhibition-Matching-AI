"""Unauthenticated public catalog routes: event, exhibitor, product, booth, map.

목적: 승인·게시된 행사/업체/제품/부스 정보를 인증 없이 조회하는 공개 API (작업 지시 "임무"
절 참고). 아키텍처는 Router(이 파일) -> Application Service
(``app.services.exhibition_public``) -> Repository
(``app.services.exhibition_public_repository``) -> SQLAlchemy Model로 분리한다. 이 파일은
HTTP 관심사(경로/쿼리 파라미터 파싱, 404/400 매핑, 응답 봉투 조립)만 다루고, 승인상태
필터링이나 SQL 조인은 절대 여기에 두지 않는다 - 그건 서비스/리포지토리 계층 책임이다.

등록 방식에 대한 메모 (중요)
------------------------------
이 라우터는 ``app.api.v1.api``(다른 에이전트가 소유, 이 작업 범위 밖)에 아직 등록하지 않는다.
통합 단계에서 아래처럼 prefix 없이 등록해야 한다(모든 경로가 이미 ``/events``, ``/exhibitors``,
``/booths`` 절대경로다):

    from app.api.v1.routers import exhibition_public
    api_router.include_router(exhibition_public.router, tags=["exhibition-public"])
"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routers.profile import api_error, build_envelope, get_request_id
from app.db.session import get_db
from app.schemas.exhibition_public import (
    PublicBoothDetail,
    PublicBoothListResponse,
    PublicEventDetail,
    PublicExhibitorDetail,
    PublicExhibitorListResponse,
    PublicMapResponse,
    PublicProductDetail,
)
from app.schemas.profile import Envelope
from app.services import exhibition_public as service

router = APIRouter()
DbDep = Annotated[AsyncSession, Depends(get_db)]
RequestIdDep = Annotated[str, Depends(get_request_id)]


def _event_not_found() -> HTTPException:
    return api_error(404, "EVENT_NOT_FOUND", "공개 중인 행사를 찾을 수 없습니다.")


def _exhibitor_not_found() -> HTTPException:
    return api_error(
        404, "EXHIBITOR_NOT_FOUND", "공개 중인 업체 정보를 찾을 수 없습니다."
    )


def _booth_not_found() -> HTTPException:
    return api_error(404, "BOOTH_NOT_FOUND", "운영 중인 공개 부스를 찾을 수 없습니다.")


def _product_not_found() -> HTTPException:
    return api_error(
        404, "PRODUCT_NOT_FOUND", "존재하지 않거나 승인되지 않은 업체 소속 제품입니다."
    )


def _decode_cursor_or_400(cursor: str | None) -> None:
    """Cursor validity is only checked here so a bad cursor 400s before any query runs;
    the actual decode/compare happens again inside the service (single source of truth for
    the cursor format) - this call exists purely to translate
    ``service.InvalidCursorError`` into the catalogued ``INVALID_CURSOR`` HTTP error."""

    if cursor is None:
        return
    try:
        service.decode_cursor(cursor)
    except service.InvalidCursorError as exc:
        raise api_error(400, "INVALID_CURSOR", str(exc)) from exc


@router.get("/events/{event_id}", response_model=Envelope[PublicEventDetail])
async def get_event(
    event_id: uuid.UUID, db: DbDep, request_id: RequestIdDep
) -> dict[str, object]:
    detail = await service.get_event_detail(db, event_id=event_id)
    if detail is None:
        raise _event_not_found()
    return build_envelope(detail, request_id)


@router.get(
    "/events/{event_id}/exhibitors",
    response_model=Envelope[PublicExhibitorListResponse],
)
async def list_event_exhibitors(
    event_id: uuid.UUID,
    db: DbDep,
    request_id: RequestIdDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    _decode_cursor_or_400(cursor)
    result = await service.list_exhibitors(db, event_id=event_id, limit=limit, cursor=cursor)
    if result is None:
        raise _event_not_found()
    return build_envelope(result, request_id)


@router.get("/exhibitors/{exhibitor_id}", response_model=Envelope[PublicExhibitorDetail])
async def get_exhibitor(
    exhibitor_id: uuid.UUID,
    db: DbDep,
    request_id: RequestIdDep,
    event_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, object]:
    detail = await service.get_exhibitor_detail(
        db, exhibitor_id=exhibitor_id, event_id=event_id
    )
    if detail is None:
        raise _exhibitor_not_found()
    return build_envelope(detail, request_id)


@router.get(
    "/exhibitors/{exhibitor_id}/products",
    response_model=Envelope[list[PublicProductDetail]],
)
async def list_exhibitor_products(
    exhibitor_id: uuid.UUID,
    db: DbDep,
    request_id: RequestIdDep,
    event_id: Annotated[uuid.UUID | None, Query()] = None,
) -> dict[str, object]:
    products = await service.get_exhibitor_products(
        db, exhibitor_id=exhibitor_id, event_id=event_id
    )
    if products is None:
        raise _exhibitor_not_found()
    return build_envelope(products, request_id)


@router.get(
    "/events/{event_id}/booths",
    response_model=Envelope[PublicBoothListResponse],
)
async def list_event_booths(
    event_id: uuid.UUID,
    db: DbDep,
    request_id: RequestIdDep,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    cursor: Annotated[str | None, Query()] = None,
) -> dict[str, object]:
    _decode_cursor_or_400(cursor)
    result = await service.list_booths(db, event_id=event_id, limit=limit, cursor=cursor)
    if result is None:
        raise _event_not_found()
    return build_envelope(result, request_id)


@router.get("/booths/{booth_id}", response_model=Envelope[PublicBoothDetail])
async def get_booth(
    booth_id: uuid.UUID, db: DbDep, request_id: RequestIdDep
) -> dict[str, object]:
    detail = await service.get_booth_detail(db, booth_id=booth_id)
    if detail is None:
        raise _booth_not_found()
    return build_envelope(detail, request_id)


@router.get("/products/{product_id}", response_model=Envelope[PublicProductDetail])
async def get_product(
    product_id: uuid.UUID, db: DbDep, request_id: RequestIdDep
) -> dict[str, object]:
    detail = await service.get_product_detail(db, product_id=product_id)
    if detail is None:
        raise _product_not_found()
    return build_envelope(detail, request_id)


@router.get("/events/{event_id}/map", response_model=Envelope[PublicMapResponse])
async def get_event_map(
    event_id: uuid.UUID, db: DbDep, request_id: RequestIdDep
) -> dict[str, object]:
    result = await service.get_map(db, event_id=event_id)
    if result is None:
        raise _event_not_found()
    return build_envelope(result, request_id)
