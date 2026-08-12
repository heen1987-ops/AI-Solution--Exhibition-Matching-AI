"""AI 추천 방문 동선(U-13) API - docs/frontend-backend-ai-interface-spec.md 11.2절.

이 라우터가 구현하는 실제 공개 경로:

    POST /api/v1/routes                                    - 경로 생성
    GET  /api/v1/routes/{route_id}                          - 경로 조회
    POST /api/v1/routes/{route_id}/recalculate               - 현재 상태로 재계산
    POST /api/v1/routes/{route_id}/items/{item_id}/status    - 개별 스탑 상태 갱신
    POST /api/v1/routes/checkpoint-scans                     - 부스 QR 체크포인트 스캔

주체(subject) 해석
--------------------
경로는 REGISTERED_WEB/BUYER_WEB 전용 개인화 기능이다(작업 지시: "이 라우터가 필요한 건 실제
로그인된 사용자 - 게스트가 아니다"). 그래서 app/api/v1/routers/recommendations.py의
``resolve_subject_context``(principal 또는 guest 모두 허용)가 아니라
``app.core.auth.get_verified_principal``(인증된 사용자만)을 직접 쓴다. tenant_id/event_id는
검증된 principal에서만 파생하고(클라이언트가 보낸 헤더/바디 값은 신뢰하지 않는다),
profile_id는 ``app.core.router_auth.get_buyer_profile_id``를 그대로 재사용한다 - 이름과 달리
바이어 전용이 아니라 "검증된 사용자의 현재 행사 프로파일을 파생"하는 범용 헬퍼다(그 함수
자체의 docstring 참고).

visit_session은 요청 바디에 없다(RouteCreateRequest는 start_location/targets/constraints만
가진다 - apps/user-web/lib/types.ts). 그래서 이 라우터가 "이 사용자의 최신 방문 세션을 찾고,
없으면 새로 만든다"(``service.resolve_or_create_visit_session``, app/api/v1/routers/sessions.py의
VisitSession 생성 패턴과 동일)까지 책임진다.

접근 통제
----------
``get_verified_principal``이 인증되지 않은 호출을 401로 막는다. 소유권(자신의 경로만
읽기/재계산/갱신 가능)은 ``service.get_owned_route``가 tenant/event/visit_session의 소유자
user_id까지 확인해 403으로 통일한다(recommendations.py list_recommendation_session_items와
동일한 "존재 여부를 노출하지 않는다" 관례 - 그 라우터의 인라인 주석 참고).
"""

from __future__ import annotations

import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routers.profile import build_envelope, get_request_id
from app.core.auth import VerifiedPrincipal, get_verified_principal
from app.core.config import Settings, get_settings
from app.core.router_auth import get_buyer_profile_id
from app.db.session import get_db
from app.schemas.route import (
    CheckpointScanRequest,
    CheckpointScanResponse,
    RouteCreateRequest,
    RouteItemStatusUpdateRequest,
)
from app.services.routing import service

DbSession = Annotated[AsyncSession, Depends(get_db)]
SettingsDep = Annotated[Settings, Depends(get_settings)]
RequestIdDep = Annotated[str, Depends(get_request_id)]
PrincipalDep = Annotated[VerifiedPrincipal, Depends(get_verified_principal)]
# 이름은 "buyer"지만 실제로는 범용 "현재 행사 프로파일" 파생 헬퍼다 (모듈 docstring 참고).
ProfileIdDep = Annotated[uuid.UUID | None, Depends(get_buyer_profile_id)]


def _require_event_scope(principal: VerifiedPrincipal) -> tuple[uuid.UUID, uuid.UUID, uuid.UUID]:
    """검증된 principal에서 tenant_id/event_id/user_id를 뽑는다.

    event_id가 없는 principal(행사 컨텍스트 밖 세션)은 이 기능을 쓸 수 없다 -
    recommendations.py resolve_subject_context와 동일한 방어.
    """

    event_id = principal.principal.event_id
    if event_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "code": "AUTH_REQUIRED",
                "message": "행사 세션 컨텍스트가 없습니다.",
                "field_errors": [],
                "retryable": False,
                "retry_after_seconds": None,
            },
        )
    return principal.principal.tenant_id, event_id, principal.user_id


def _service_error(exc: service.RouteServiceError) -> HTTPException:
    return HTTPException(
        status_code=exc.http_status,
        detail={
            "code": exc.code,
            "message": exc.message,
            "field_errors": [],
            "retryable": False,
            "retry_after_seconds": None,
        },
    )


def build_route_router() -> APIRouter:
    router = APIRouter(prefix="/routes")

    # ------------------------------------------------------------------
    # 체크포인트 QR 스캔 - "/routes/{route_id}"보다 먼저 등록해야 한다. 두 경로 모두
    # "/routes/<한 세그먼트>" 모양이라, {route_id}가 먼저 등록되면 uuid.UUID 파싱 실패로
    # 422가 나기 전에 이 리터럴 경로로 넘어오지 못한다(FastAPI/Starlette는 등록 순서대로
    # 같은 모양의 경로를 매칭한다).
    # ------------------------------------------------------------------

    @router.post("/checkpoint-scans")
    async def scan_checkpoint(
        payload: CheckpointScanRequest,
        principal: PrincipalDep,
        profile_id: ProfileIdDep,
        db: DbSession,
        settings: SettingsDep,
        request_id: RequestIdDep,
    ) -> dict[str, Any]:
        tenant_id, event_id, user_id = _require_event_scope(principal)
        visit_session = await service.resolve_or_create_visit_session(
            db, tenant_id=tenant_id, event_id=event_id, user_id=user_id, profile_id=profile_id
        )
        try:
            scan, route = await service.record_checkpoint_scan(
                db,
                tenant_id=tenant_id,
                event_id=event_id,
                visit_session_id=visit_session.visit_session_id,
                qr_token=payload.qr_token,
                settings=settings,
            )
        except service.RouteServiceError as exc:
            raise _service_error(exc) from exc

        route_response = await service.to_route_response(db, route) if route is not None else None
        response = CheckpointScanResponse(
            indoor_checkpoint_scan_id=scan.indoor_checkpoint_scan_id,
            booth_id=scan.booth_id,
            scanned_at=scan.scanned_at,
            route=route_response,
        )
        return build_envelope(response, request_id)

    @router.post("", status_code=status.HTTP_201_CREATED)
    async def create_route_endpoint(
        payload: RouteCreateRequest,
        principal: PrincipalDep,
        profile_id: ProfileIdDep,
        db: DbSession,
        request_id: RequestIdDep,
    ) -> dict[str, Any]:
        tenant_id, event_id, user_id = _require_event_scope(principal)
        visit_session = await service.resolve_or_create_visit_session(
            db, tenant_id=tenant_id, event_id=event_id, user_id=user_id, profile_id=profile_id
        )
        try:
            route = await service.create_route(
                db,
                tenant_id=tenant_id,
                event_id=event_id,
                profile_id=profile_id,
                visit_session_id=visit_session.visit_session_id,
                payload=payload,
            )
        except service.RouteServiceError as exc:
            raise _service_error(exc) from exc

        response = await service.to_route_response(db, route)
        return build_envelope(response, request_id)

    @router.get("/{route_id}")
    async def get_route_endpoint(
        route_id: uuid.UUID,
        principal: PrincipalDep,
        db: DbSession,
        request_id: RequestIdDep,
    ) -> dict[str, Any]:
        tenant_id, event_id, user_id = _require_event_scope(principal)
        try:
            route = await service.get_owned_route(
                db, route_id=route_id, tenant_id=tenant_id, event_id=event_id, user_id=user_id
            )
        except service.RouteServiceError as exc:
            raise _service_error(exc) from exc
        response = await service.to_route_response(db, route)
        return build_envelope(response, request_id)

    @router.post("/{route_id}/recalculate")
    async def recalculate_route_endpoint(
        route_id: uuid.UUID,
        principal: PrincipalDep,
        db: DbSession,
        request_id: RequestIdDep,
    ) -> dict[str, Any]:
        tenant_id, event_id, user_id = _require_event_scope(principal)
        try:
            route = await service.get_owned_route(
                db, route_id=route_id, tenant_id=tenant_id, event_id=event_id, user_id=user_id
            )
        except service.RouteServiceError as exc:
            raise _service_error(exc) from exc
        route = await service.recalculate_route(db, route=route)
        response = await service.to_route_response(db, route)
        return build_envelope(response, request_id)

    @router.post("/{route_id}/items/{item_id}/status")
    async def update_route_item_status_endpoint(
        route_id: uuid.UUID,
        item_id: uuid.UUID,
        payload: RouteItemStatusUpdateRequest,
        principal: PrincipalDep,
        db: DbSession,
        request_id: RequestIdDep,
    ) -> dict[str, Any]:
        tenant_id, event_id, user_id = _require_event_scope(principal)
        try:
            route = await service.get_owned_route(
                db, route_id=route_id, tenant_id=tenant_id, event_id=event_id, user_id=user_id
            )
            item = service.get_owned_item(route, item_id)
            await service.update_item_status(
                db,
                route=route,
                item=item,
                new_status=payload.status,
                occurred_at=payload.occurred_at,
            )
        except service.RouteServiceError as exc:
            raise _service_error(exc) from exc
        response = await service.to_route_response(db, route)
        return build_envelope(response, request_id)

    return router


__all__ = ["build_route_router"]
