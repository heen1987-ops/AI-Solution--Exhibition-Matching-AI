"""바이어 매칭 API 라우터 - ``POST /buyer/matches``, ``GET /buyer/matches/{id}``,
``POST /buyer/compare``.

트랙: BACKEND-BUYER-MATCH (WAVE 2C). app/models/buyer_match.py 모듈 docstring의
"기존 코드와의 관계에 대한 중요한 메모"(DECISION-005와의 충돌)를 함께 참고한다.

이 파일은 ``app.api.v1.api``(공용 라우터 애그리게이터)를 직접 수정하지 않는다. 대신
``build_buyer_match_router()``를 노출해서 통합 담당자가 다음처럼 등록하도록 한다::

    from app.api.v1.routers.buyer_match import build_buyer_match_router
    api_router.include_router(build_buyer_match_router(), tags=["buyer-match"])

인증 (통합 STEP 21)
--------------------
원본은 ``X-Profile-Id`` 헤더를 그대로 바이어 주체로 신뢰하는 ``_require_buyer_profile_id``를
갖고 있었다. 삭제했다. 이제 주체는 ``app/core/router_auth.py``의
``get_buyer_profile_id``(=``routers/meetings.py``의 ``_buyer_profile_header``)가 검증된
principal에서 파생한 현재 행사 프로파일이다.

그 함수는 세션에 행사 컨텍스트가 없거나 해당 행사 프로파일이 없으면 ``None``을 돌려주므로,
아래 ``require_buyer_profile_id``가 ``None`` -> 401 AUTH_REQUIRED 가드를 유지한다 - 원본과
동일한 ``ErrorBody`` 응답 형태를 그대로 보존한다(클라이언트 계약 유지). 아예 인증되지 않은
호출은 ``get_verified_principal``이 먼저 401 AUTH_REQUIRED로 끊는다.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.router_auth import get_buyer_profile_id
from app.db.session import get_db
from app.models.buyer_match import BuyerMatchSession
from app.schemas.buyer_match import (
    BuyerCompareItem,
    BuyerCompareRequest,
    BuyerCompareResponse,
    BuyerMatchCandidateView,
    BuyerMatchCreateRequest,
    BuyerMatchFilters,
    BuyerMatchSessionResponse,
    CompareField,
    Envelope,
    ErrorBody,
    Meta,
)
from app.services.buyer_match.access import BuyerAccessDenied, resolve_buyer_context
from app.services.buyer_match.compare import MAX_COMPARE_EXHIBITORS, load_compare_rows
from app.services.buyer_match.eligibility import BuyerCriteria
from app.services.buyer_match.orchestrator import (
    BuyerMatchSessionNotAccessible,
    create_buyer_match_session,
    get_buyer_match_session_for_buyer,
)

router = APIRouter()
DbSession = Annotated[AsyncSession, Depends(get_db)]


def build_buyer_match_router() -> APIRouter:
    """통합 담당자가 ``app.api.v1.api``에 등록할 수 있도록 라우터를 노출한다."""

    return router


# ---------------------------------------------------------------------------
# 인증/주체 해석 (모듈 docstring "인증" 참고)
# ---------------------------------------------------------------------------


async def require_buyer_profile_id(
    buyer_profile_id: Annotated[uuid.UUID | None, Depends(get_buyer_profile_id)],
) -> uuid.UUID:
    """검증된 principal에서 파생한 현재 행사 바이어 프로파일. 없으면 401."""

    if buyer_profile_id is None:
        raise HTTPException(
            status_code=401,
            detail=ErrorBody(
                code="AUTH_REQUIRED", message="현재 행사의 바이어 프로파일을 찾을 수 없습니다."
            ).model_dump(),
        )
    return buyer_profile_id


def _meta(request_id: str | None) -> Meta:
    return Meta(request_id=request_id or f"req_{uuid.uuid4().hex}", server_time=datetime.now(UTC))


def _raise_access_denied(error: BuyerAccessDenied) -> None:
    raise HTTPException(
        status_code=403,
        detail=ErrorBody(code=error.code, message=error.message).model_dump(),
    )


def _filters_to_criteria(filters: BuyerMatchFilters) -> BuyerCriteria:
    return BuyerCriteria(
        categories=frozenset(filters.categories),
        channels=frozenset(filters.channels),
        regions=frozenset(filters.regions),
        price_min=filters.price_min,
        price_max=filters.price_max,
        monthly_units_min=filters.monthly_units_min,
        monthly_units_max=filters.monthly_units_max,
        oem_required=filters.oem_required,
        private_label_required=filters.private_label_required,
        export_required=filters.export_required,
    )


def _session_response(
    session: BuyerMatchSession, filters: BuyerMatchFilters
) -> BuyerMatchSessionResponse:
    return BuyerMatchSessionResponse(
        buyer_match_session_id=session.buyer_match_session_id,
        buyer_profile_id=session.buyer_profile_id,
        profile_version=session.profile_version,
        policy_version=session.policy_version,
        verification_tier=session.verification_tier,
        filters=filters,
        candidate_count=session.candidate_count,
        filtered_count=session.filtered_count,
        result_count=session.result_count,
        generated_at=session.generated_at,
        expires_at=session.expires_at,
        candidates=[
            BuyerMatchCandidateView(
                exhibitor_id=candidate.exhibitor_id,
                participation_id=candidate.participation_id,
                rank=candidate.rank,
                score=float(candidate.score),
                grade=candidate.grade,
                reason_codes=list(candidate.reason_codes or []),
                unknown_fields=list(candidate.unknown_fields or []),
            )
            for candidate in session.candidates
        ],
    )


# ---------------------------------------------------------------------------
# POST /buyer/matches
# ---------------------------------------------------------------------------


@router.post("/buyer/matches", response_model=Envelope[BuyerMatchSessionResponse])
async def create_match(
    payload: BuyerMatchCreateRequest,
    db: DbSession,
    profile_id: Annotated[uuid.UUID, Depends(require_buyer_profile_id)],
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> Envelope[BuyerMatchSessionResponse]:
    try:
        buyer = await resolve_buyer_context(db, profile_id)
    except BuyerAccessDenied as error:
        _raise_access_denied(error)
        raise  # pragma: no cover

    session = await create_buyer_match_session(
        db,
        buyer=buyer,
        filters=_filters_to_criteria(payload.filters),
        limit=payload.limit,
    )
    return Envelope(
        data=_session_response(session, payload.filters), meta=_meta(x_request_id)
    )


# ---------------------------------------------------------------------------
# GET /buyer/matches/{buyer_match_session_id}
# ---------------------------------------------------------------------------


@router.get(
    "/buyer/matches/{buyer_match_session_id}",
    response_model=Envelope[BuyerMatchSessionResponse],
)
async def get_match(
    buyer_match_session_id: uuid.UUID,
    db: DbSession,
    profile_id: Annotated[uuid.UUID, Depends(require_buyer_profile_id)],
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> Envelope[BuyerMatchSessionResponse]:
    try:
        await resolve_buyer_context(db, profile_id)
    except BuyerAccessDenied as error:
        _raise_access_denied(error)
        raise  # pragma: no cover

    try:
        session = await get_buyer_match_session_for_buyer(
            db,
            buyer_match_session_id=buyer_match_session_id,
            buyer_profile_id=profile_id,
        )
    except BuyerMatchSessionNotAccessible as error:
        raise HTTPException(
            status_code=403,
            detail=ErrorBody(code=error.code, message=error.message).model_dump(),
        ) from error

    filters = BuyerMatchFilters(
        categories=list((session.filters_json or {}).get("categories") or []),
        channels=list((session.filters_json or {}).get("channels") or []),
        regions=list((session.filters_json or {}).get("regions") or []),
        price_min=(session.filters_json or {}).get("price_min"),
        price_max=(session.filters_json or {}).get("price_max"),
        monthly_units_min=(session.filters_json or {}).get("monthly_units_min"),
        monthly_units_max=(session.filters_json or {}).get("monthly_units_max"),
        oem_required=(session.filters_json or {}).get("oem_required"),
        private_label_required=(session.filters_json or {}).get("private_label_required"),
        export_required=(session.filters_json or {}).get("export_required"),
    )
    return Envelope(data=_session_response(session, filters), meta=_meta(x_request_id))


# ---------------------------------------------------------------------------
# POST /buyer/compare
# ---------------------------------------------------------------------------


@router.post("/buyer/compare", response_model=Envelope[BuyerCompareResponse])
async def compare_exhibitors_endpoint(
    payload: BuyerCompareRequest,
    db: DbSession,
    profile_id: Annotated[uuid.UUID, Depends(require_buyer_profile_id)],
    x_request_id: Annotated[str | None, Header(alias="X-Request-ID")] = None,
) -> Envelope[BuyerCompareResponse]:
    try:
        buyer = await resolve_buyer_context(db, profile_id)
    except BuyerAccessDenied as error:
        _raise_access_denied(error)
        raise  # pragma: no cover

    # 스키마 max_length=4가 이미 강제하지만, 서비스 계층에서도 방어적으로 다시 확인한다.
    if len(payload.exhibitor_ids) > MAX_COMPARE_EXHIBITORS:
        raise HTTPException(
            status_code=422,
            detail=ErrorBody(
                code="TOO_MANY_EXHIBITOR_IDS",
                message=f"비교는 최대 {MAX_COMPARE_EXHIBITORS}개 업체까지 가능합니다.",
            ).model_dump(),
        )

    rows = await load_compare_rows(
        db,
        tenant_id=buyer.tenant_id,
        event_id=buyer.event_id,
        exhibitor_ids=payload.exhibitor_ids,
    )

    def _field(data) -> CompareField:
        return CompareField(known=data.known, value=data.value)

    items = [
        BuyerCompareItem(
            exhibitor_id=row.exhibitor_id,
            available=row.available,
            company_name=row.company_name,
            product_tech=_field(row.product_tech),
            channel=_field(row.channel),
            order_scale=_field(row.order_scale),
            region=_field(row.region),
            oem=_field(row.oem),
            private_label=_field(row.private_label),
            export=_field(row.export),
            meeting_availability=_field(row.meeting_availability),
        )
        for row in rows
    ]
    return Envelope(
        data=BuyerCompareResponse(items=items), meta=_meta(x_request_id)
    )
