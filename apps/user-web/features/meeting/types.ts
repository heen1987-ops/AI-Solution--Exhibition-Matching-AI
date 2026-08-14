/**
 * 상담(미팅) 도메인 - 웹 바이어 화면 전용 로컬 타입.
 *
 * 왜 `frontend/lib/types.ts`의 Meeting* 타입을 재사용하지 않는가
 * ----------------------------------------------------------------
 * 이 작업 지시(WAVE 2C USER-WEB-MEETING)는 `apps/user-web/lib/api-client.ts`,
 * `apps/user-web/lib/types.ts`를 편집 범위 밖으로 명시한다("정의된 값은 그대로 쓰고
 * 병합 필요성만 보고하라"). 그런데 실제 구현된 백엔드 정본
 * (`apps/api/app/models/meeting.py` MEETING_STATUSES, `apps/api/app/schemas/meeting.py`
 * MeetingResponse.status: str)은 상담 상태값을 소문자
 * `draft/requested/accepted/counter_proposed/rejected/cancelled/completed/no_show`
 * (docs/user-ia-wireframes.md 6.2절 그대로)로 반환하는 반면, `lib/types.ts`의
 * `MeetingStatus`는 대문자 `DRAFT/REQUESTED/CONFIRMED/COMPLETED/COUNTER_PROPOSED/
 * REJECTED/CANCELLED_BY_BUYER/CANCELLED_BY_EXHIBITOR/NO_SHOW`(다른 문서 초안 표기)로
 * 정의되어 있어 실제 API 응답과 값이 전혀 겹치지 않는다(`CONFIRMED`는 실제로 안 오고
 * `accepted`가 온다 등). `lib/types.ts`의 그 타입을 그대로 쓰면 상태 분기가 런타임에
 * 항상 falsy가 되어 화면이 깨진다.
 *
 * 그래서 이 도메인(상담)만 소유 경로(`features/meeting/**`) 안에 실제 백엔드 정본과
 * 1:1로 맞춘 로컬 타입을 새로 둔다. 낮은 수준의 fetch/오류봉투 파싱(`apiGet`/`apiPost`/
 * `ApiClientError`/`generateClientId`)은 이미 검증된 `lib/api-client.ts`의 범용 export를
 * 그대로 재사용한다(제네릭이라 Meeting 전용 타입에 묶여있지 않다) - 로직 중복 없이 값
 * 타입만 이 파일이 정본으로 둔다.
 *
 * 통합 담당자에게: `lib/types.ts`의 `MeetingStatus`/`MeetingResponse`/
 * `MeetingListResponse`/`PartnerMeetingListItem`/`PartnerBuyerSummaryResponse`를 이 파일
 * 기준(실제 백엔드 정본)으로 교체하고, 이 파일은 그때 삭제하고 공용 파일 import로 되돌릴
 * 수 있다.
 */

/** docs/user-ia-wireframes.md 6.2절 + apps/api/app/models/meeting.py MEETING_STATUSES. */
export const MEETING_STATUSES = [
  "draft",
  "requested",
  "accepted",
  "counter_proposed",
  "rejected",
  "cancelled",
  "completed",
  "no_show",
] as const;

export type MeetingStatus = (typeof MEETING_STATUSES)[number];

/** apps/api/app/schemas/meeting.py ALLOWED_CONTACT_SHARE_FIELDS. */
export const ALLOWED_CONTACT_SHARE_FIELDS = ["NAME", "PHONE", "BUSINESS_EMAIL", "EMAIL"] as const;
export type ContactShareField = (typeof ALLOWED_CONTACT_SHARE_FIELDS)[number];

export interface ContactShareRequest {
  accepted: boolean;
  document_version?: string | null;
  fields: ContactShareField[];
}

export interface MeetingCreateRequest {
  exhibitor_id: string;
  /** 온톨로지 concept_code (예: `DISTRIBUTION`). */
  topic: string;
  /** 백엔드 검증(schemas/meeting.py): 1~5개, 중복 금지. 이 화면은 UX상 최대 3개로 더
   * 좁혀서 받는다(작업 지시 "up to 3 preferred time slots"). */
  requested_slot_ids: string[];
  message?: string | null;
  contact_share?: ContactShareRequest | null;
  match_result_id?: string | null;
}

export interface SlotCandidate {
  slot_id: string;
  start_at: string;
  end_at: string;
  preference_order: number | null;
  request_status: string | null;
}

export interface MeetingResponse {
  meeting_id: string;
  status: MeetingStatus;
  exhibitor_id: string;
  participation_id: string;
  topic_code: string | null;
  message_preview: string | null;
  candidate_slots: SlotCandidate[];
  confirmed_start: string | null;
  confirmed_end: string | null;
  contact_share_accepted: boolean;
  contact_share_fields: string[];
  viewed_at: string | null;
  row_version: number;
  created_at: string;
  updated_at: string;
  /**
   * 정방향 호환 필드 - 아직 백엔드 계약(schemas/meeting.py MeetingResponse)에 없다.
   * 이 화면이 구현해야 하는 "확정 상태에서만 노출되는 연락처 카드(이름/업무용
   * 이메일/업무용 전화/소속/상담시간)"는 실제로는 "확정된 상담에서 바이어가 업체
   * 담당자의 연락처를 보는" 방향인데, 현재 구현된 연락처 공유 모델
   * (interaction.meeting_contact_share, MeetingContactShare)은 반대 방향(바이어가 동의한
   * 자신의 연락처를 업체가 보는 것, `GET /partner/meetings/{id}/buyer-summary`)만
   * 구현되어 있고 바이어용 GET /meetings/{id} 응답에는 업체 담당자 연락처를 돌려주는
   * 필드가 없다. 이 gap은 이 트랙(USER-WEB-MEETING) 소유 경로 밖(백엔드
   * schemas/models/routers)이라 여기서 새 엔드포인트/필드를 만들 수 없다.
   *
   * Blocker Score 평가: 영향은 크지만(바이어가 확정 후 업체에 연락할 방법이 없음)
   * 되돌리기 쉽고(필드 하나 추가) 이 세션 범위 밖의 변경이 필요해 "안전한 기본값
   * 적용 후 계속 진행"(오케스트레이터 지침)을 따른다. 안전한 기본값: 이 필드가 없으면
   * (지금 상태) 연락처 카드는 아무것도 렌더링하지 않는다(깨진 것처럼 보이는 빈
   * placeholder 대신) - 작업 지시에 명시된 동작 그대로다. 백엔드가 이 필드를 채워
   * 보내기 시작하면 화면이 즉시 그 값을 렌더링한다(코드 변경 불필요).
   *
   * 백엔드 담당 트랙에 제안: `MeetingResponse`에 `contact: dict[str, str] | None`을
   * 추가하고, `status == 'accepted'`이고 참가업체측 연락처 공유 설정이 켜져 있을 때만
   * 채운다(`PartnerBuyerSummaryResponse.contact`와 대칭 패턴).
   */
  contact?: Record<string, string> | null;
}

export interface MeetingListResponse {
  items: MeetingResponse[];
  next_cursor: string | null;
}

/** `lib/api-client.ts`의 `RequestOptions.query`가 요구하는 인덱스 시그니처를 만족시키기
 * 위한 공용 베이스(그 파일의 `QueryParams`와 동일한 모양). */
export type QueryValue = string | number | boolean | undefined | null;
export interface QueryParams {
  [key: string]: QueryValue;
}

export interface MeetingListQuery extends QueryParams {
  status?: MeetingStatus;
  cursor?: string;
  limit?: number;
}

export interface MeetingCancelRequest {
  version: number;
  reason_code?: string | null;
}

export interface MeetingRespondRequest {
  action: "ACCEPT_COUNTER" | "DECLINE";
  version: number;
  reason_code?: string | null;
}

export interface AvailabilitySlotItem {
  slot_id: string;
  start_at: string;
  end_at: string;
  capacity: number;
  reserved_count: number;
  topic_code: string | null;
  version: number;
}

export interface AvailabilityListResponse {
  items: AvailabilitySlotItem[];
}

export interface AvailabilityQuery extends QueryParams {
  date: string;
  topic?: string;
}

/** 상담주제 칩(온톨로지 concept_code + 표시 라벨)의 최소 구조. 기본값
 * (`constants.ts` DEFAULT_TOPICS)과 온톨로지 API에서 최선 노력으로 파싱한 값 모두 이 모양을
 * 따른다. */
export interface TopicOptionLike {
  code: string;
  label: string;
}
