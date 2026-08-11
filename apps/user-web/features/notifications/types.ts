/**
 * 알림함(`/notifications`) 도메인 - 로컬 타입.
 *
 * 왜 `apps/user-web/lib/types.ts`를 확장하지 않는가
 * ---------------------------------------------------
 * 이 작업 지시(WAVE 2E USER-WEB-NOTIFICATION)는 `apps/user-web/lib/api-client.ts`,
 * `apps/user-web/lib/types.ts`를 편집 범위 밖으로 명시한다. 저수준 fetch/응답봉투 파싱/
 * 오류 변환(`apiGet`/`apiPost`/`apiPut`/`ApiClientError`)은 이미 검증된 `lib/api-client.ts`
 * export를 그대로 재사용하되(제네릭이라 알림 전용 타입에 묶여 있지 않다), 값 타입은 이
 * 파일이 정본으로 둔다 - `features/meeting/types.ts`와 같은 패턴.
 *
 * 백엔드 계약 공백에 대한 메모 (중요 - Blocker Score 평가)
 * ---------------------------------------------------------
 * `.harness/contracts/openapi.json`, `apps/api/app/api/v1/routers/**`,
 * `apps/api/app/models/**` 어디에도 알림(notification) 도메인이 아직 없다(승인된 트랙:
 * BACKEND-007/009, AISEARCH-002, QA-003만 활성 - notifications는 백로그에 없음). 이
 * 화면은 CONTRACTS/BACKEND 트랙이 아직 만들지 않은 API를 소비해야 하는데, 이 세션은
 * `apps/api/**`를 소유하지 않아(locks.yaml) 새 라우터/모델을 만들 수 없다.
 *
 * 판단(Blocker Score < 7 - 예상 가능한 CRUD 계약, 실제 개인정보·보안 리스크는 "서버가
 * 최종 판단"으로 방어되어 있음, 되돌리기 쉬움): 이 파일이 아래 "가정 계약"을 정본으로 두고
 * 화면을 완성한 뒤, 실제 백엔드가 나오면 필드명만 맞추면 되도록 서버 응답을 그대로 신뢰하는
 * 방식(클라이언트가 값을 추론/보정하지 않음)으로 구현한다. 특히 target_type/target_id는
 * 절대 신뢰하지 않고 `target.ts`의 화이트리스트를 통과한 값만 내부 경로로 변환한다(서버가
 * 임의의 외부 URL이나 열린 경로 문자열을 내려줘도 그대로 렌더링하지 않는다).
 *
 * 가정 계약 (백엔드 확정 시 대조 필요)
 * -------------------------------------
 *   GET  /api/v1/notifications?cursor=&limit=&unread_only=   -> NotificationListResponse
 *   POST /api/v1/notifications/{id}/read                      -> NotificationItem
 *   POST /api/v1/notifications/read-all                       -> MarkAllReadResponse
 * (알림 환경설정 계약은 `features/notification-preferences/types.ts` 참고.)
 */

/** 알려진 리터럴을 자동완성으로 제시하되 임의 문자열도 허용하는 개방형 코드 타입
 * (`lib/types.ts`의 `OpenEnum`과 동일한 패턴 - 새 알림 유형이 서버 시드로 늘어나도 타입이
 * 깨지지 않게 한다). */
export type OpenEnum<Known extends string> = Known | (string & {});

export type QueryValue = string | number | boolean | undefined | null;
export interface QueryParams {
  [key: string]: QueryValue;
}

export type NotificationType = OpenEnum<
  | "RECOMMENDATION_READY"
  | "MEETING_REQUESTED"
  | "MEETING_ACCEPTED"
  | "MEETING_COUNTER_PROPOSED"
  | "MEETING_REJECTED"
  | "MEETING_CANCELLED"
  | "MEETING_REMINDER"
  | "EVENT_DAY_REMINDER"
  | "POST_EVENT_INFO"
  | "PROFILE_INCOMPLETE"
  | "OPERATIONAL_NOTICE"
>;

export type NotificationPriority = "URGENT" | "HIGH" | "NORMAL" | "LOW";

/** 알림이 가리키는 대상의 종류 - 이 앱에 실제로 존재하는 라우트로만 화이트리스트 매핑한다
 * (`target.ts`). 서버가 이 목록에 없는 값을 보내면 링크를 만들지 않는다(임의 URL 렌더링
 * 금지 원칙). */
export const NOTIFICATION_TARGET_TYPES = [
  "RECOMMENDATION",
  "MEETING",
  "PROFILE",
  "EXHIBITOR",
  "BOOTH",
  "PRODUCT",
  "BUYER_MATCHES",
] as const;
export type NotificationTargetType = (typeof NOTIFICATION_TARGET_TYPES)[number];

export interface NotificationTarget {
  target_type: OpenEnum<NotificationTargetType>;
  target_id: string | null;
  /** 서버가 "이 알림이 가리키던 레코드가 더 이상 없다/접근할 수 없다"를 미리 알려줄 때
   * true. 목록 화면에서 깨진 링크 대신 안내 문구를 보여주는 데 쓴다. */
  target_deleted?: boolean;
}

export interface NotificationItem {
  notification_id: string;
  type: NotificationType;
  title: string;
  summary: string;
  priority: NotificationPriority;
  read: boolean;
  created_at: string;
  target: NotificationTarget | null;
}

export interface NotificationListQuery extends QueryParams {
  cursor?: string;
  limit?: number;
  unread_only?: boolean;
}

export interface NotificationListResponse {
  items: NotificationItem[];
  next_cursor: string | null;
  unread_count: number;
}

export interface MarkAllReadResponse {
  updated_count: number;
}
