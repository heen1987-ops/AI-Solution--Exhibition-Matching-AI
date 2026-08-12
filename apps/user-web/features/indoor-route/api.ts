/**
 * 실내 동선 평면도용 부스 좌표 조회.
 *
 * 새 부스 조회 엔드포인트를 만들지 않는다 - `apps/user-web/lib/api-client.ts`가 이미 갖고
 * 있는 `getBooth`/`getProduct`(둘 다 `apps/user-web/app/route/page.tsx`가 이미 쓰고 있다)를
 * 그대로 재사용해, 경로 항목(`RouteItemView`)을 실제 부스 map_x/map_y로 풀어낸다.
 *
 * 부스로 연결되지 않는 대상(EXHIBITOR/PROGRAM/MEETING)이나 좌표가 없는 부스는 좌표를
 * 지어내지 않고 `unresolved`로 남긴다 - `RouteFloorPlan`이 "일부는 지도에 표시하지 못했다"고
 * 정직하게 안내하는 근거가 된다.
 */

import { getBooth, getProduct } from "@/lib/api-client";
import type { RouteItemView } from "@/lib/types";

import type { FloorPlanResolution, ResolvedStop, UnresolvedStop } from "./types";

async function resolveOneStop(item: RouteItemView): Promise<ResolvedStop | UnresolvedStop> {
  if (!item.object_type || !item.object_id) {
    return { item, reason: "NO_BOOTH_MAPPING" };
  }

  let boothId: string;
  if (item.object_type === "BOOTH") {
    boothId = item.object_id;
  } else if (item.object_type === "PRODUCT") {
    try {
      const product = await getProduct(item.object_id);
      if (!product.booth_id) return { item, reason: "NO_BOOTH_MAPPING" };
      boothId = product.booth_id;
    } catch {
      return { item, reason: "LOOKUP_FAILED" };
    }
  } else {
    // EXHIBITOR/PROGRAM/MEETING - 이 코드베이스에는 이들을 부스 좌표로 연결하는 조회가
    // 없다. 추측하지 않고 "표시 불가"로 남긴다.
    return { item, reason: "NO_BOOTH_MAPPING" };
  }

  try {
    const booth = await getBooth(boothId);
    if (booth.map_x == null || booth.map_y == null) {
      return { item, reason: "NO_COORDINATES" };
    }
    return {
      item,
      boothId: booth.booth_id,
      boothNumber: booth.booth_number,
      zoneName: booth.zone_name,
      point: { x: booth.map_x, y: booth.map_y },
    };
  } catch {
    return { item, reason: "LOOKUP_FAILED" };
  }
}

function isResolved(stop: ResolvedStop | UnresolvedStop): stop is ResolvedStop {
  return "point" in stop;
}

/** 경로 항목들을 실제 부스 좌표로 병렬 조회한다. 반환 순서는 보장하지 않으므로 그리는
 * 쪽에서 `item.sequence` 기준으로 다시 정렬해야 한다. */
export async function resolveFloorPlanStops(items: RouteItemView[]): Promise<FloorPlanResolution> {
  const settled = await Promise.all(items.map(resolveOneStop));
  const resolved: ResolvedStop[] = [];
  const unresolved: UnresolvedStop[] = [];
  for (const stop of settled) {
    if (isResolved(stop)) resolved.push(stop);
    else unresolved.push(stop);
  }
  return { resolved, unresolved };
}
