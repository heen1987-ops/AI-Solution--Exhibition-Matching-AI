/**
 * 업체별 데이터 품질 API 함수.
 *
 * `apps/admin/lib/api-client.ts`(apiGet, X-Actor-User-Id 세션 자동첨부, 표준화된
 * ApiClientError)를 그대로 재사용한다(그 파일은 소유 경로 밖이라 수정하지 않는다 -
 * `../ai-review/api.ts`와 동일 관례).
 *
 * 경로 근거
 * ---------
 * - `GET /admin/analytics/data-quality`: BACKEND-ANALYTICS가 확정한 실제 스키마
 *   (`apps/api/app/schemas/analytics.py::DataQualityAnalyticsResponse`). 라우터
 *   (`app/api/v1/routers/analytics.py`)가 아직 등록되지 않았다 - 등록 전 호출은
 *   NOT_IMPLEMENTED로 던져지고 화면이 그대로 보여준다.
 * - `GET /admin/analytics/data-quality/exhibitors`: 업체별 상세 행은 어느 트랙에도 아직
 *   없다 - REST 관례 추정 경로(`../types.ts` 계약 공백 2번, 재조정 플래그).
 */

import { apiGet, type RequestOptions } from "@/lib/api-client";

import type { DataQualityAnalyticsResponse, ExhibitorDataQualityListResponse } from "./types";

/** GET /admin/analytics/data-quality */
export function getDataQualityAnalytics(
  eventId: string,
  options?: RequestOptions,
): Promise<DataQualityAnalyticsResponse> {
  return apiGet<DataQualityAnalyticsResponse>("/admin/analytics/data-quality", {
    ...options,
    query: { event_id: eventId },
  });
}

/** TODO(백엔드 미확정 - 재조정 필요): GET /admin/analytics/data-quality/exhibitors. */
export function listExhibitorDataQuality(
  eventId: string,
  options?: RequestOptions,
): Promise<ExhibitorDataQualityListResponse> {
  return apiGet<ExhibitorDataQualityListResponse>("/admin/analytics/data-quality/exhibitors", {
    ...options,
    query: { event_id: eventId },
  });
}
