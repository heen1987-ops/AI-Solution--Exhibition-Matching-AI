/**
 * 순수 로직 - React/브라우저 API 없이 단위테스트하기 위해 UI 컴포넌트와 분리한다
 * (`features/meeting/logic.ts`와 같은 패턴).
 */

import type { NotificationItem, NotificationPriority, NotificationType } from "./types";

export const NOTIFICATION_TYPE_LABEL: Record<string, string> = {
  RECOMMENDATION_READY: "새 추천",
  MEETING_REQUESTED: "상담 요청",
  MEETING_ACCEPTED: "상담 확정",
  MEETING_COUNTER_PROPOSED: "시간 변경 제안",
  MEETING_REJECTED: "상담 거절",
  MEETING_CANCELLED: "상담 취소",
  MEETING_REMINDER: "상담 알림",
  EVENT_DAY_REMINDER: "행사 안내",
  POST_EVENT_INFO: "행사 후 안내",
  PROFILE_INCOMPLETE: "프로필 안내",
  OPERATIONAL_NOTICE: "운영 공지",
};

/** 알려지지 않은(향후 서버 추가) 유형도 코드 그대로 보여줘 알림을 숨기지 않는다. */
export function notificationTypeLabel(type: NotificationType): string {
  return NOTIFICATION_TYPE_LABEL[type] ?? type;
}

export const NOTIFICATION_PRIORITY_LABEL: Record<NotificationPriority, string> = {
  URGENT: "긴급",
  HIGH: "중요",
  NORMAL: "일반",
  LOW: "참고",
};

/** `Intl.DateTimeFormat`은 jsdom에서도 안정적으로 동작하지만, 잘못된 날짜 문자열이 오면
 * 원본을 그대로 보여줘(빈 문자열 대신) 디버깅 가능한 상태를 유지한다. */
export function formatNotificationTimestamp(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("ko-KR", {
    month: "long",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

/** 목록에서 알림 하나를 읽음 처리한 새 배열을 반환한다(불변 갱신 - 낙관적 업데이트용). */
export function markItemRead(items: NotificationItem[], notificationId: string): NotificationItem[] {
  return items.map((item) => (item.notification_id === notificationId ? { ...item, read: true } : item));
}

/** 목록 전체를 읽음 처리한다. */
export function markAllItemsRead(items: NotificationItem[]): NotificationItem[] {
  return items.map((item) => (item.read ? item : { ...item, read: true }));
}

/** 미확인 개수를 목록에서 직접 파생시킨다 - 서버가 내려준 `unread_count`가 낙관적 갱신
 * 이후 어긋날 수 있어(다른 탭에서의 변경 등) 화면 표시는 항상 로컬 목록 기준으로 다시
 * 계산한다. */
export function countUnread(items: NotificationItem[]): number {
  return items.filter((item) => !item.read).length;
}
