"""AI 추천 방문 동선(U-13) API 계약 - Pydantic 스키마.

이 파일의 필드명·구조는 새로 설계하지 않는다. 이미 프론트가 이 계약에 맞춰 구현되어 있다
(apps/user-web/app/route/page.tsx, apps/user-web/lib/api-client.ts createRoute/
recalculateRoute) - 근거는 apps/user-web/lib/types.ts의 다음 타입들이며, 이 파일은 그 타입을
1:1로 Pydantic으로 옮긴 것이다:

    RouteStartLocation, RouteTargetInput, RouteConstraints, RouteCreateRequest,
    RouteItemView, RouteResponse

``object_type``/``status`` 계열은 프론트에서 ``OpenEnum``(자동완성 + 임의 문자열 허용)으로
열어 두었지만, db-erd-table-spec.md CHECK 제약이 이미 고정한 구조적 상태값이므로(11.1절
"근거 문서... 코드값 표기 원칙" - CHECK 제약이 있는 값은 Literal로 좁힌다) 여기서는
``Literal``로 좁힌다. app/models/route.py의 ``ROUTE_STATUSES``/``ROUTE_ITEM_STATUSES``가
단일 진실 공급원이며 이 파일의 Literal은 그 값과 반드시 같이 유지해야 한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 11.2절 경로 생성 요청
# ---------------------------------------------------------------------------

#: apps/user-web/app/route/page.tsx ZONE_PRESETS와 반드시 같이 유지한다 (positioning.py의
#: ZoneCentroidLookup이 이 문자열들을 exhibition.event_zone.zone_name과 매칭한다).
RouteStartLocationType = Literal["ZONE", "BOOTH", "GPS"]

#: RecommendableObjectType(BOOTH/PRODUCT/EXHIBITOR/PROGRAM) + "MEETING".
RouteTargetObjectType = Literal["BOOTH", "PRODUCT", "EXHIBITOR", "PROGRAM", "MEETING"]

RouteStatus = Literal["ACTIVE", "COMPLETED", "CANCELLED"]
RouteItemStatus = Literal["PENDING", "ARRIVED", "SKIPPED", "COMPLETED"]

#: 프론트가 한 번에 보낼 수 있는 최대 방문 후보 수 (apps/user-web/app/route/page.tsx
#: MAX_ROUTE_TARGETS=5). 서버는 악의적/버그성 대량 요청을 막기 위해 조금 더 넉넉하게 20으로
#: 상한을 둔다 - 온라인 지오메트리 최적화(nearest-neighbor + 2-opt)가 O(n^2) 이상이라
#: 무제한 허용은 DoS 벡터가 된다.
MAX_ROUTE_TARGETS = 20


class RouteStartLocation(BaseModel):
    type: RouteStartLocationType
    id: str


class RouteTargetInput(BaseModel):
    object_type: RouteTargetObjectType
    object_id: str
    # 07 문서·기존 추천/슬레이트 코드 관례: 숫자가 작을수록 우선순위가 높다(1=최우선).
    # app/services/routing/pathfinding.py의 드롭 순서가 이 관례를 그대로 따른다.
    priority: int | None = Field(default=None, ge=1)
    expected_duration_minutes: int | None = Field(default=None, ge=0, le=240)


class RouteConstraints(BaseModel):
    available_minutes: int | None = Field(default=None, ge=0)
    avoid_congestion: bool = False
    minimize_walking: bool = False
    accessible_route: bool = False


class RouteCreateRequest(BaseModel):
    start_location: RouteStartLocation
    targets: list[RouteTargetInput] = Field(min_length=1, max_length=MAX_ROUTE_TARGETS)
    constraints: RouteConstraints = Field(default_factory=RouteConstraints)


# ---------------------------------------------------------------------------
# 응답
# ---------------------------------------------------------------------------


class RouteItemView(BaseModel):
    sequence: int
    object_type: RouteTargetObjectType | None
    object_id: str | None
    expected_arrival_at: datetime | None
    expected_stay_minutes: int | None
    actual_arrival_at: datetime | None
    status: RouteItemStatus


class RouteResponse(BaseModel):
    route_id: uuid.UUID
    visit_session_id: uuid.UUID
    route_preference: str | None
    total_minutes: int | None
    walking_minutes: int | None
    status: RouteStatus
    items: list[RouteItemView]


# ---------------------------------------------------------------------------
# 개별 스탑 상태 갱신 (프론트가 이미 RouteItemView.status로 기대하는 값 - ARRIVED/SKIPPED/
# COMPLETED만 클라이언트가 능동적으로 설정할 수 있다. PENDING은 서버가 생성 시점에만 쓴다.)
# ---------------------------------------------------------------------------


class RouteItemStatusUpdateRequest(BaseModel):
    status: Literal["ARRIVED", "SKIPPED", "COMPLETED"]
    occurred_at: datetime | None = None


# ---------------------------------------------------------------------------
# 체크포인트 QR 스캔 - exhibition.booth_qr 재사용 (모듈 docstring 없음, 라우터 참고)
# ---------------------------------------------------------------------------


class CheckpointScanRequest(BaseModel):
    qr_token: str = Field(min_length=1, max_length=2048)


class CheckpointScanResponse(BaseModel):
    indoor_checkpoint_scan_id: uuid.UUID
    booth_id: uuid.UUID
    scanned_at: datetime
    # 스캔 시점에 이 방문 세션 소유의 ACTIVE 경로가 있으면 그 경로를 새 위치로 재계산해
    # 함께 반환한다(작업 지시 4번: "recalculates their active route's remaining ordering from
    # that new position"). 없으면 null - 스캔 자체는 항상 기록된다.
    route: RouteResponse | None


__all__ = [
    "MAX_ROUTE_TARGETS",
    "CheckpointScanRequest",
    "CheckpointScanResponse",
    "RouteConstraints",
    "RouteCreateRequest",
    "RouteItemStatus",
    "RouteItemStatusUpdateRequest",
    "RouteItemView",
    "RouteResponse",
    "RouteStartLocation",
    "RouteStartLocationType",
    "RouteStatus",
    "RouteTargetInput",
    "RouteTargetObjectType",
]
