/**
 * 알림 설정 API 호출 - 로컬 클라이언트. 저수준 fetch/오류 변환은 `lib/api-client.ts`의
 * 범용 export를 재사용한다(`features/notifications/api.ts`와 같은 패턴).
 *
 * 실제 라우트: apps/api/app/api/v1/routers/notification.py의
 * `GET/PATCH /me/notification-preferences` (통합 시점에 확정된 경로·메서드로 갱신했다 -
 * 포팅 당시 초안이던 `/notifications/preferences` PUT은 실제로 등록되지 않는다).
 */

import { apiGet, apiPatch, type RequestOptions } from "@/lib/api-client";

import type { NotificationPreferencesPatchRequest, NotificationPreferencesResponse } from "./types";

export function getNotificationPreferences(
  options?: RequestOptions,
): Promise<NotificationPreferencesResponse> {
  return apiGet<NotificationPreferencesResponse>("/me/notification-preferences", options);
}

export function updateNotificationPreferences(
  request: NotificationPreferencesPatchRequest,
  options?: RequestOptions,
): Promise<NotificationPreferencesResponse> {
  return apiPatch<NotificationPreferencesResponse>(
    "/me/notification-preferences",
    request,
    options,
  );
}
