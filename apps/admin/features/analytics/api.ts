/**
 * ADMIN-ANALYTICS API 함수 — `/admin/analytics/*`.
 *
 * `apps/admin/lib/api-client.ts`(apiGet, X-Actor-User-Id 세션 자동첨부, 표준화된
 * ApiClientError)를 그대로 재사용한다. 그 파일 자체는 이 트랙 소유 경로 밖이라
 * 수정하지 않는다 — 다른 feature(ai-review 등)와 동일한 관례.
 *
 * 경로·쿼리 계약 근거
 * -------------------
 * BACKEND-ANALYTICS(WAVE 2E)의 `apps/api/app/schemas/analytics.py` +
 * `app/services/analytics/access.py` 문서화 기준. 라우터가 아직 api.py에 등록되지
 * 않았으므로(통합자 단계 대기) 호출 시 FastAPI 전역 404 → lib/api-client가
 * `NOT_IMPLEMENTED` ApiClientError로 변환한다. 화면은 그 오류를 그대로 표시한다.
 *
 * TODO(BACKEND-ANALYTICS 라우터 등록 후 대조):
 *   - period_start/period_end/channel 쿼리 파라미터 이름
 *   - 계약 공백 필드(features/analytics/types.ts 모듈 docstring 목록)
 *
 * PII 이중 방어: 모든 응답은 sanitizeAnalyticsPayload를 거쳐 반환된다 —
 * 백엔드에 결함이 있어 연락처류 필드/텍스트가 섞여 와도 UI에 도달하지 않는다.
 */

import { apiGet, type RequestOptions } from "@/lib/api-client";

import { sanitizeAnalyticsPayload } from "./logic";
import type {
  AnalyticsFilter,
  BuyerAnalyticsResponse,
  KioskAnalyticsResponse,
  NoResultQueryResponse,
  OverviewAnalyticsResponse,
  ResolvedDateRange,
  SearchInsightsResponse,
  WebAnalyticsResponse,
} from "./types";

function analyticsQuery(
  filter: Pick<AnalyticsFilter, "eventId" | "channel">,
  range: ResolvedDateRange,
): Record<string, string | undefined> {
  return {
    event_id: filter.eventId,
    period_start: range.periodStart,
    period_end: range.periodEnd,
    // "ALL"은 필터 미적용 — 파라미터를 아예 보내지 않는다.
    channel: filter.channel === "ALL" ? undefined : filter.channel,
  };
}

/** GET /admin/analytics/overview */
export async function getOverviewAnalytics(
  filter: AnalyticsFilter,
  range: ResolvedDateRange,
  options?: RequestOptions,
): Promise<OverviewAnalyticsResponse> {
  const data = await apiGet<OverviewAnalyticsResponse>("/admin/analytics/overview", {
    ...options,
    query: analyticsQuery(filter, range),
  });
  return sanitizeAnalyticsPayload(data);
}

/** GET /admin/analytics/web */
export async function getWebAnalytics(
  filter: AnalyticsFilter,
  range: ResolvedDateRange,
  options?: RequestOptions,
): Promise<WebAnalyticsResponse> {
  const data = await apiGet<WebAnalyticsResponse>("/admin/analytics/web", {
    ...options,
    query: analyticsQuery(filter, range),
  });
  return sanitizeAnalyticsPayload(data);
}

/** GET /admin/analytics/kiosk */
export async function getKioskAnalytics(
  filter: AnalyticsFilter,
  range: ResolvedDateRange,
  options?: RequestOptions,
): Promise<KioskAnalyticsResponse> {
  const data = await apiGet<KioskAnalyticsResponse>("/admin/analytics/kiosk", {
    ...options,
    query: analyticsQuery(filter, range),
  });
  return sanitizeAnalyticsPayload(data);
}

/** GET /admin/analytics/buyer — exhibitor_id 필터는 EVENT_ADMIN 전용
 * (EXHIBITOR_ADMIN은 서버가 자사 exhibitor_id를 강제하므로 보내지 않는다 —
 * app/services/analytics/access.py 참고). */
export async function getBuyerAnalytics(
  filter: AnalyticsFilter,
  range: ResolvedDateRange,
  exhibitorId?: string | null,
  options?: RequestOptions,
): Promise<BuyerAnalyticsResponse> {
  const data = await apiGet<BuyerAnalyticsResponse>("/admin/analytics/buyer", {
    ...options,
    query: { ...analyticsQuery(filter, range), exhibitor_id: exhibitorId ?? undefined },
  });
  return sanitizeAnalyticsPayload(data);
}

/** GET /admin/analytics/searches?detail=full — 확장 검색 인사이트.
 * (detail 플래그 없는 최소 응답은 기존 dashboard/page.tsx가 이미 사용 중) */
export async function getSearchInsights(
  filter: AnalyticsFilter,
  range: ResolvedDateRange,
  options?: RequestOptions,
): Promise<SearchInsightsResponse> {
  const data = await apiGet<SearchInsightsResponse>("/admin/analytics/searches", {
    ...options,
    query: { ...analyticsQuery(filter, range), detail: "full" },
  });
  return sanitizeAnalyticsPayload(data);
}

/** GET /admin/analytics/no-results */
export async function getNoResultQueries(
  filter: AnalyticsFilter,
  range: ResolvedDateRange,
  options?: RequestOptions,
): Promise<NoResultQueryResponse> {
  const data = await apiGet<NoResultQueryResponse>("/admin/analytics/no-results", {
    ...options,
    query: analyticsQuery(filter, range),
  });
  return sanitizeAnalyticsPayload(data);
}
