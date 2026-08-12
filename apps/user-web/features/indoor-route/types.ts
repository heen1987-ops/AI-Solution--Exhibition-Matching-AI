/**
 * 실내 동선 평면도·체크포인트 스캔 기능 전용 타입.
 *
 * `RouteItemView`/`RouteResponse`/`CheckpointScan*`는 이미 `@/lib/types`에 정의되어 있으므로
 * (11.2절 경로 계약 1:1 대응) 여기서는 다시 정의하지 않고 그대로 import한다. 이 파일은 이
 * 기능이 화면에 그리기 위해 추가로 필요한, 백엔드 계약에는 없는 파생 타입만 담는다.
 */

import type { RouteItemView, RouteResponse } from "@/lib/types";

/** 부스 평면도 좌표 (`apps/api/app/models/exhibitor.py` Booth.map_x/map_y - Numeric(10,3),
 * 0~100 비율로 정규화되어 있지 않은 임의 축척). */
export interface FloorPlanPoint {
  x: number;
  y: number;
}

/** 지도에 그릴 수 있는, 실제 부스 좌표로 해석된 방문 스탑. */
export interface ResolvedStop {
  item: RouteItemView;
  boothId: string;
  boothNumber: string;
  zoneName: string | null;
  point: FloorPlanPoint;
}

/** 지도에 그릴 수 없는 방문 스탑과 그 이유 - 추측으로 좌표를 지어내지 않고 명시적으로
 * "표시 불가"로 남긴다. */
export type UnresolvedStopReason =
  /** BOOTH도 아니고, 부스로 연결되는 PRODUCT도 아니다 (예: EXHIBITOR/PROGRAM/MEETING 대상). */
  | "NO_BOOTH_MAPPING"
  /** 연결된 부스는 찾았지만 map_x/map_y가 비어 있다. */
  | "NO_COORDINATES"
  /** 조회 자체가 실패했다(네트워크·권한 등). */
  | "LOOKUP_FAILED";

export interface UnresolvedStop {
  item: RouteItemView;
  reason: UnresolvedStopReason;
}

export interface FloorPlanResolution {
  resolved: ResolvedStop[];
  unresolved: UnresolvedStop[];
}

export interface RouteFloorPlanProps {
  /** 순서대로 그릴 경로 항목. `RouteResponse.items`를 그대로 전달한다. */
  items: RouteItemView[];
}

export interface CheckpointScanButtonProps {
  /** 스캔이 성공하면 호출된다. 서버가 이미 재계산한 ACTIVE 경로가 있으면 그 값을,
   * 없으면 `null`을 전달한다 - 호출부는 이 값을 그대로 경로 상태에 반영하면 된다. */
  onScanned: (route: RouteResponse | null) => void;
  disabled?: boolean;
}
