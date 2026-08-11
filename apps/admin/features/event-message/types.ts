/**
 * 이벤트 메시지(운영자 작성 캠페인) 화면 - 원시 데이터 계약 (ADMIN-NOTIFICATION, WAVE 2E).
 *
 * 근거: `apps/api/app/schemas/event_message.py` (같은 트랙이 이번 배치에서 함께 구현한
 * 백엔드 계약 - 1:1로 맞춘다). 라우터(`apps/api/app/api/v1/routers/event_message.py`)는
 * `build_event_message_router()`만 노출하고 `app/api/v1/api.py`(통합 담당자 소유)에는 아직
 * mount되지 않았다 - 등록 전까지 이 화면의 모든 호출은 `../ai-review/types.ts`와 동일하게
 * `ApiClientError(code: "NOT_IMPLEMENTED")`로 실패하고, 화면은 그 오류를 있는 그대로 보여준다
 * (가짜 성공 표시 금지).
 *
 * 이 트랙(ADMIN-NOTIFICATION)이 다루는 메시지 유형은 "회의/상담 상태 변경 알림"을 명시적으로
 * 제외한 운영 공지 5종뿐이다(모듈 하단 MESSAGE_TYPES 참고) - 상담 상태 알림은
 * BACKEND-NOTIFICATION이 실제 비즈니스 이벤트로부터 자동 생성하는 별도 도메인
 * (`notification.notifications`)이며 이 화면에서 작성할 수 없다.
 */

export type OpenEnum<Known extends string> = Known | (string & {});

export type IsoDateTime = string;
export type Uuid = string;

// ---------------------------------------------------------------------------
// 메시지 유형 / 상태 / 채널 / 타겟 세그먼트 - apps/api/app/schemas/event_message.py 1:1
// ---------------------------------------------------------------------------

export type MessageType =
  | "EVENT_OPERATION_NOTICE"
  | "EVENT_START_REMINDER"
  | "PROFILE_CONFIRMATION_REMINDER"
  | "RECOMMENDATION_READY_NOTICE"
  | "POST_EVENT_RESOURCE_NOTICE";

export const MESSAGE_TYPES: MessageType[] = [
  "EVENT_OPERATION_NOTICE",
  "EVENT_START_REMINDER",
  "PROFILE_CONFIRMATION_REMINDER",
  "RECOMMENDATION_READY_NOTICE",
  "POST_EVENT_RESOURCE_NOTICE",
];

export const MESSAGE_TYPE_LABEL_KO: Record<MessageType, string> = {
  EVENT_OPERATION_NOTICE: "행사 운영 공지",
  EVENT_START_REMINDER: "행사 시작 리마인더",
  PROFILE_CONFIRMATION_REMINDER: "프로필 확인 리마인더",
  RECOMMENDATION_READY_NOTICE: "추천 준비 완료 안내",
  POST_EVENT_RESOURCE_NOTICE: "행사 종료 후 자료 안내",
};

export type MessageStatus =
  | "DRAFT"
  | "PREVIEWED"
  | "APPROVED"
  | "SCHEDULED"
  | "PUBLISHED"
  | "COMPLETED"
  | "CANCELLED";

export const MESSAGE_STATUSES: MessageStatus[] = [
  "DRAFT",
  "PREVIEWED",
  "APPROVED",
  "SCHEDULED",
  "PUBLISHED",
  "COMPLETED",
  "CANCELLED",
];

export type Channel = "IN_APP" | "EMAIL";

export const CHANNELS: Channel[] = ["IN_APP", "EMAIL"];

export const CHANNEL_LABEL_KO: Record<Channel, string> = {
  IN_APP: "앱 내 알림",
  EMAIL: "이메일",
};

/**
 * 허용된 6개 세그먼트만 - 작업 지시: "세밀한 속성/행동 기반 타겟팅 UI 어포던스는 제공하지
 * 않는다". `../logic.ts`의 `TARGET_SEGMENTS`가 이 목록의 유일한 정본이며, 화면 어디에도
 * 이 목록 밖의 값을 입력할 수 있는 자유 텍스트 필드를 두지 않는다.
 */
export type TargetSegment =
  | "ALL_REGISTERED_USERS"
  | "PROFILE_UNCONFIRMED"
  | "RECOMMENDATION_READY"
  | "BUYERS"
  | "EXHIBITOR_STAFF"
  | "SPECIFIC_ROLE";

export type TargetRoleCode = "VISITOR" | "BUYER" | "EXHIBITOR" | "OPERATOR" | "ADMIN";

export const TARGET_ROLE_CODES: TargetRoleCode[] = [
  "VISITOR",
  "BUYER",
  "EXHIBITOR",
  "OPERATOR",
  "ADMIN",
];

// ---------------------------------------------------------------------------
// 읽기 모델
// ---------------------------------------------------------------------------

export interface EventMessage {
  event_message_id: Uuid;
  event_id: Uuid;
  message_type: MessageType;
  status: MessageStatus;
  title: string;
  body: string;
  channels: Channel[];
  target_segment: TargetSegment;
  target_role_code: TargetRoleCode | null;
  destination_screen: string;
  scheduled_at: IsoDateTime | null;
  published_at: IsoDateTime | null;
  completed_at: IsoDateTime | null;
  cancelled_at: IsoDateTime | null;
  previewed_at: IsoDateTime | null;
  created_by_user_id: Uuid | null;
  approved_by_user_id: Uuid | null;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface EventMessageListResponse {
  items: EventMessage[];
}

// ---------------------------------------------------------------------------
// 미리보기 - 작업 지시가 요구하는 필드 전부 (제목/본문/대상수/채널/예약시각/대상화면/
// 중복대상경고/동의제외수)
// ---------------------------------------------------------------------------

export interface EventMessagePreview {
  event_message_id: Uuid;
  title: string;
  body: string;
  channels: Channel[];
  target_segment: TargetSegment;
  target_role_code: TargetRoleCode | null;
  /** 소규모 그룹 억제 규칙 적용 시 null (`small_audience_warning`이 true일 때만 null - 화면은
   * 이 필드가 아니라 항상 target_count_display를 보여준다). */
  target_count: number | null;
  target_count_display: string;
  small_audience_warning: boolean;
  destination_screen: string;
  scheduled_at: IsoDateTime | null;
  duplicate_target_warning: boolean;
  duplicate_target_message_count: number;
  consent_excluded_count: number;
  previewed_at: IsoDateTime;
}

// ---------------------------------------------------------------------------
// 요청 바디
// ---------------------------------------------------------------------------

export interface EventMessageCreateRequest {
  event_id: Uuid;
  message_type: MessageType;
  title: string;
  body: string;
  channels: Channel[];
  target_segment: TargetSegment;
  target_role_code: TargetRoleCode | null;
  destination_screen: string;
  scheduled_at: IsoDateTime | null;
}

export interface EventMessageUpdateRequest {
  row_version: number;
  message_type?: MessageType;
  title?: string;
  body?: string;
  channels?: Channel[];
  target_segment?: TargetSegment;
  target_role_code?: TargetRoleCode | null;
  destination_screen?: string;
  scheduled_at?: IsoDateTime | null;
}

export interface PublishResult {
  event_message: EventMessage;
  resolved_recipient_count: number;
  email_consent_excluded_count: number;
}
