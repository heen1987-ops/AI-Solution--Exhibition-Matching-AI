/**
 * WAVE 2C ADMIN-BUYER 트랙 - 바이어 검증 큐 + 상담 운영 뷰 타입.
 *
 * 이 계약이 잠정인 이유 (중요)
 * ----------------------------
 * 작업 지시는 이 트랙이 "BACKEND-BUYER-PROFILE이 노출하는 is_meeting_eligible / 검증
 * 상태변경 엔드포인트"를 호출하되, 계약이 없으면 "CONTRACTS-BUYER 문서를 기준으로 만들고
 * 재조정(reconciliation) 필요성을 보고하라"고 명시한다. 실제로는 이 저장소 전체
 * (`.harness/contracts/**`, `docs/**`)에 CONTRACTS-BUYER 문서가 존재하지 않고,
 * `apps/api/app/models/profile.py`의 `profile.buyer_need`에는 `verification_status`도
 * `applied_at`도 없으며, admin 전용 승인/반려 API 자체가 아직 없다(확인:
 * `apps/api/app/api/v1/routers/profile.py` 전체, `.harness/contracts/error-codes.yaml`의
 * `not_yet_cataloged: "admin router (BACKEND-007 대기)"`). `apps/api/app/api/v1/routers/
 * meetings.py`에도 운영자가 행사 전체 상담을 조회하는 admin 전용 엔드포인트가 없다 -
 * `GET /meetings`는 바이어 본인 소유만, `GET /partner/meetings`는 참가업체 담당자 소유만
 * 스코프한다(둘 다 확인함, 형제 트랙 `../partner-meeting/types.ts`가 후자를 그대로 씀).
 *
 * 그래서 이 파일은 `apps/admin/app/exhibitors/**`(§28 업체 승인 흐름)가 이미 쓰는 "TODO:
 * 미구현" 패턴을 그대로 따라 이 트랙 범위 안에서 직접 잠정 계약을 정의한다. 백엔드가 실제로
 * 이 경로들을 구현하면(BACKEND-BUYER-PROFILE, BACKEND-MEETING) 이 파일과 `./api.ts`의 경로
 * 문자열을 대조해 조정해야 한다 - 이 파일 전체가 그 재조정 대상이다.
 *
 * 필드 근거
 * ---------
 * - buyer_type: `apps/api/app/models/profile.py`의 `BuyerNeed.organization_type`
 *   ("프로파일 유형이 아니라 조직 분류값" 주석 참고)에 대응한다. 작업 지시 필드명을 그대로
 *   쓰되 실제 DB 컬럼명과 다르다는 점을 주석으로 남긴다.
 * - business_email_verified: `BuyerNeed.business_email_verified`와 동일한 이름·의미.
 * - completeness_percent: `profile.user_profile.completeness_score`(07 22.1)에 대응.
 * - verification_status: 현재 DB에 없는 신규 개념. 작업 지시가 지정한 6개 값(PENDING이
 *   초기값)을 그대로 채택한다.
 * - applied_at: 바이어가 "검증 대기열에 올라간" 시점. 현재 가장 가까운 근사값은
 *   `user_profile.created_at`이나 정확히 같은 의미는 아니다 - TODO(BACKEND-BUYER-PROFILE):
 *   전용 컬럼 필요.
 */

export type IsoDateTime = string;

/** 작업 지시가 지정한 6개 상태값. 초기값은 PENDING. */
export type BuyerVerificationStatus =
  | "PENDING"
  | "VERIFIED"
  | "LIMITED"
  | "REJECTED"
  | "SUSPENDED"
  | "EXPIRED";

/** 작업 지시가 지정한 5개 전이 동작. `./logic.ts`의 상태머신이 각 동작의 출발/도착 상태를
 * 강제한다. */
export type BuyerVerificationAction = "VERIFY" | "LIMIT" | "REJECT" | "SUSPEND" | "EXPIRE";

export interface BuyerVerificationQueueItem {
  buyer_profile_id: string;
  /** 업무상 표시용 이름. identity 스키마의 실명(name_enc)을 그대로 노출하지 않는다는
   * 원칙(§45 개인정보 원칙)에 따라 백엔드가 이미 마스킹/표시용으로 가공해 내려준다는
   * 전제다 - 이 화면은 추가로 신뢰하지 않고 `./logic.ts`의 redactPotentialContactInfo로
   * 한 번 더 방어적으로 걸러 렌더링한다. */
  display_name: string;
  company_name: string | null;
  /** BuyerNeed.organization_type의 표시용 별칭(모듈 docstring 참고). */
  buyer_type: string | null;
  business_email_verified: boolean;
  event_id: string;
  event_name: string | null;
  completeness_percent: number;
  verification_status: BuyerVerificationStatus | string;
  applied_at: IsoDateTime | null;
  /** BACKEND-BUYER-PROFILE이 문서화한 is_meeting_eligible 파생값(있다면) 참고 표시용.
   * 이 화면이 계산하지 않고 백엔드 응답을 그대로 보여준다. */
  is_meeting_eligible: boolean | null;
}

export interface BuyerVerificationQueueResponse {
  items: BuyerVerificationQueueItem[];
  next_cursor: string | null;
}

export interface BuyerVerificationQueueQuery {
  event_id?: string;
  verification_status?: BuyerVerificationStatus;
  cursor?: string;
  limit?: number;
}

export interface BuyerVerificationDecisionRequest {
  action: BuyerVerificationAction;
  /** 작업 지시 필수 요구사항: 모든 전이는 사유가 있어야 한다. 빈 문자열/공백만 있는 값은
   * `./logic.ts`의 validateReason이 네트워크 호출 전에 막는다(§28 업체 반려의
   * `apps/admin/lib/api-client.ts` rejectExhibitor와 동일한 패턴). */
  reason: string;
}

export interface BuyerVerificationDecisionResponse {
  buyer_profile_id: string;
  verification_status: BuyerVerificationStatus | string;
  decided_at: IsoDateTime;
  decided_by: string | null;
  reason: string;
  is_meeting_eligible: boolean | null;
}

// ---------------------------------------------------------------------------
// 상담 운영 뷰 (요구: "운영 뷰만, 상담 흐름 자체를 다시 만들지 않음")
// ---------------------------------------------------------------------------

/**
 * TODO(BACKEND-BUYER-PROFILE 또는 BACKEND-MEETING, 이 트랙 범위 밖): 운영자가 행사 전체
 * 상담을 조회하는 관리자 전용 엔드포인트가 아직 없다. 실제로 구현된 것은
 * `apps/api/app/api/v1/routers/meetings.py`의 `GET /meetings`(바이어 본인 소유만),
 * `GET /partner/meetings`(참가업체 담당자 소유만) 두 개뿐이다 - 둘 다 X-Profile-Id /
 * X-Staff-Id 헤더로 스코프가 좁혀져 있어 운영자가 행사 전체를 조회하는 용도로 쓸 수 없다
 * (형제 트랙 `../partner-meeting/`이 후자를 그대로 쓰는 것을 확인함 - 그 트랙도 admin 전용
 * 목록 API가 없다고 types.ts에 남겨두었다). 그래서 이 목록도 잠정 계약이다.
 *
 * 계약을 이렇게 설계한 핵심 이유(작업 지시 필수 요구사항 "no raw contact-info leak"): 이
 * 응답 모양에는 연락처 필드(name/phone/email)가 아예 없다 - 백엔드가 그런 필드를 절대
 * 내려주지 않는 것이 1차 방어선이고(계약 자체가 스코프됨), 프론트는 그 위에 추가로
 * buyer_display_ref/exhibitor_name을 redactPotentialContactInfo로 한 번 더 거른다(2차
 * 방어선, 화면이 백엔드 실수를 무조건 신뢰하지 않는다는 작업 지시 원칙 - "the backend call
 * you make must already be scoped" 요구를 만족하기 위해 이 화면은 연락처를 조건부로
 * 공개하는 `/partner/meetings/{id}/buyer-summary` 같은 엔드포인트를 절대 호출하지 않는다).
 */
export interface AdminMeetingOpsItem {
  meeting_id: string;
  /** interaction.meeting.status - MEETING_STATUSES (apps/api/app/models/meeting.py 참고). */
  status: string;
  exhibitor_id: string;
  exhibitor_name: string | null;
  /** 업무상 식별용 참조자일 뿐 실명·연락처가 아니다(모듈 docstring 참고). 예:
   * "바이어 #a3f1" 같은 표시용 문자열을 백엔드가 만들어 내려준다는 전제. */
  buyer_display_ref: string;
  topic_code: string | null;
  preferred_time_summary: string | null;
  confirmed_start: IsoDateTime | null;
  confirmed_end: IsoDateTime | null;
  /** 현재 DB에는 "분쟁/오류" 전용 컬럼이 없다(meeting.py 확인됨). 작업 지시의 "dispute/error
   * state" 요구를 만족하기 위해, 백엔드가 이 파생 플래그를 계산해 내려준다고 가정한다
   * (예: rejected/cancelled/no_show이거나 counter_proposed 상태가 장시간 정체된 경우).
   * TODO(BACKEND-MEETING): 실제 분쟁 사유 코드가 생기면 문자열 사유로 교체. */
  attention: "NONE" | "NEEDS_ATTENTION";
  updated_at: IsoDateTime;
}

export interface AdminMeetingOpsListResponse {
  items: AdminMeetingOpsItem[];
  next_cursor: string | null;
}

export interface AdminMeetingOpsListQuery {
  event_id?: string;
  status?: string;
  cursor?: string;
  limit?: number;
}
