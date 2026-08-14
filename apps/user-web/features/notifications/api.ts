/**
 * 알림함 API 호출 - 로컬 클라이언트.
 *
 * `apps/user-web/lib/api-client.ts`/`lib/types.ts`는 편집 범위 밖(작업 지시)이라 이
 * 파일을 새로 둔다. 저수준 fetch/응답봉투 파싱/오류 변환(`apiGet`/`apiPost`/
 * `generateClientId`/`RequestOptions`)은 이미 검증된 `lib/api-client.ts` export를 그대로
 * 재사용한다 - 제네릭이라 알림 전용 타입에 묶여 있지 않으므로 안전하다.
 *
 * 실제 라우트 경로: apps/api/app/api/v1/routers/notification.py build_notification_router() -
 * `/me/notifications`, `/me/notifications/{id}/read`, `/me/notifications/read-all`(모두
 * 세션 principal 기준, 통합 시점에 확정된 경로로 갱신했다 - 포팅 당시 초안이던
 * `/notifications*`는 실제로 등록되지 않는다).
 * 서버 인증은 다른 화면과 동일하게 `credentials: "include"` 세션 쿠키로만 이뤄진다(이
 * 파일은 사용자 ID를 요청 본문/쿼리에 절대 싣지 않는다) - 다른 사용자의 알림을 ID
 * 조작으로 조회하는 것은 서버가 세션 소유자와 notification_id의 소유권을 대조해 거부해야
 * 하는 서버 책임이고, 이 클라이언트는 그 거부(`RESOURCE_FORBIDDEN`/404)를 일반 오류로
 * 그대로 전파한다(다른 사용자의 데이터가 있는 것처럼 보이는 대체 콘텐츠를 만들지 않는다).
 */

import { apiGet, apiPost, type RequestOptions } from "@/lib/api-client";

import type {
  MarkAllReadResponse,
  NotificationItem,
  NotificationListQuery,
  NotificationListResponse,
} from "./types";

export function listNotifications(
  query?: NotificationListQuery,
  options?: RequestOptions,
): Promise<NotificationListResponse> {
  return apiGet<NotificationListResponse>("/me/notifications", { ...options, query });
}

/** 알림 하나를 읽음 처리한다. 요청 대상은 항상 URL의 `notificationId`뿐이고, 어느 사용자
 * 소유인지는 서버가 세션으로 판단한다(클라이언트가 사용자 ID를 함께 보내지 않는다). */
export function markNotificationRead(
  notificationId: string,
  options?: RequestOptions,
): Promise<NotificationItem> {
  return apiPost<NotificationItem>(
    `/me/notifications/${encodeURIComponent(notificationId)}/read`,
    undefined,
    options,
  );
}

export function markAllNotificationsRead(options?: RequestOptions): Promise<MarkAllReadResponse> {
  return apiPost<MarkAllReadResponse>("/me/notifications/read-all", undefined, options);
}
