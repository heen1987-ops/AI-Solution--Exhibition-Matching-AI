/**
 * 참가업체 포털 - 상담(미팅) 요청함 API 타입.
 *
 * 근거 문서/코드
 * ---------------
 * - apps/api/app/schemas/meeting.py: PartnerMeetingListItem, PartnerBuyerSummaryResponse,
 *   PartnerDecisionRequest, MeetingOutcomeRequest/Response, SlotCandidate, BuyerNeedSummary -
 *   실제로 동작하는 백엔드 스키마 정본. 이 타입들은 그 스키마와 1:1로 맞췄다.
 * - apps/api/app/api/v1/routers/meetings.py: `/partner/meetings*` 라우트. `apps/admin/lib/`가
 *   쓰는 `X-Actor-User-Id`(partner.py, UserAccount 기준) 인증과는 다른 주체 모델
 *   (`X-Staff-Id`, exhibition.exhibitor_staff.staff_id)을 쓴다 - api.ts/staff-session.ts 참고.
 *
 * 알려진 계약 공백 (BACKEND-MEETING 쪽 후속 필요, 이 작업 범위에서는 고칠 수 없음 -
 * apps/api/**는 내 owned path가 아니다):
 *
 * 1. `PartnerMeetingListItem`/`PartnerBuyerSummaryResponse` 둘 다 `row_version`을
 *    노출하지 않는데, `POST /partner/meetings/{id}/decision`(PartnerDecisionRequest)은
 *    낙관적 잠금을 위해 정확한 `version: number`를 요구한다(불일치 시 409
 *    MEETING_VERSION_CONFLICT). 이 화면은 그 값을 자동으로 채울 방법이 없어 수동 입력
 *    필드로 우회한다(components/DecisionPanel.tsx 참고). 제안: 두 응답에 row_version 추가.
 * 2. 참가업체 포털에는 단건 상담 조회(`GET /partner/meetings/{id}`) 엔드포인트가 없다.
 *    바이어의 후보 시간(candidate_slots)은 목록 응답(PartnerMeetingListItem)에만 있어,
 *    상세 화면은 목록을 스캔해 찾는다(api.ts `findPartnerMeetingListItem`). 제안: 단건
 *    조회 API를 추가하거나 buyer-summary 응답에 candidate_slots를 포함.
 * 3. `PartnerDecisionRequest.slot_id`는 단일 값이라 한 번의 COUNTER_PROPOSE 호출은 시간
 *    하나만 제안할 수 있다("1~3개 대안 시간 제안"이라는 작업 지시 문구와 달리 실제
 *    백엔드는 단일 슬롯 계약이다) - 이 화면은 후보 목록에서 하나를 고르게 하고, 재제안이
 *    거절되면 buyer 쪽 응답 후 다시 별도 COUNTER_PROPOSE를 호출하는 방식으로 맞춘다.
 */

export type MeetingStatus =
  | "draft"
  | "requested"
  | "accepted"
  | "counter_proposed"
  | "rejected"
  | "cancelled"
  | "completed"
  | "no_show";

export interface SlotCandidate {
  slot_id: string;
  start_at: string;
  end_at: string;
  preference_order: number | null;
  /** meeting_slot_request.status: PENDING | SELECTED | DECLINED | WITHDRAWN */
  request_status: string | null;
}

export interface PartnerMeetingListItem {
  meeting_id: string;
  status: MeetingStatus | (string & {});
  topic_code: string | null;
  candidate_slots: SlotCandidate[];
  confirmed_start: string | null;
  confirmed_end: string | null;
  viewed_at: string | null;
  created_at: string;
}

export interface PartnerMeetingListResponse {
  items: PartnerMeetingListItem[];
  next_cursor: string | null;
}

export interface BuyerNeedSummary {
  organization_type: string | null;
  target_price_min_amount: number | null;
  target_price_max_amount: number | null;
  currency: string | null;
  monthly_units_min: number | null;
  monthly_units_max: number | null;
  decision_timeline: string | null;
}

export interface PartnerBuyerSummaryResponse {
  meeting_id: string;
  status: MeetingStatus | (string & {});
  topic_code: string | null;
  message_preview: string | null;
  buyer_need: BuyerNeedSummary | null;
  /** 확정(accepted) + 공유동의 + 열람권한을 모두 만족할 때만 서버가 채워 보낸다
   * (meetings.py get_partner_buyer_summary). null이면 절대 화면에 연락처를 만들어내지
   * 않는다 - components/logic.ts `shouldRevealContact` 참고. */
  contact: Record<string, string> | null;
  contact_disclosed: boolean;
}

export type PartnerDecisionAction = "ACCEPT" | "REJECT" | "COUNTER_PROPOSE";

export interface PartnerDecisionRequest {
  action: PartnerDecisionAction;
  slot_id?: string | null;
  version: number;
  reason_code?: string | null;
}

/** POST /partner/meetings/{id}/decision 응답 (meetings.py `_build_meeting_response`가
 * 반환하는 MeetingResponse 그대로 - 바이어용 스키마와 형태가 같다). */
export interface MeetingDecisionResult {
  meeting_id: string;
  status: MeetingStatus | (string & {});
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
}

export interface FollowUpRequest {
  action_code: string;
  due_date?: string | null;
  note?: string | null;
}

export interface MeetingOutcomeRequest {
  outcome_code: string;
  is_qualified_lead: boolean;
  expected_amount?: number | null;
  currency?: string;
  expected_probability_percent?: number | null;
  memo?: string | null;
  follow_up?: FollowUpRequest | null;
}

export interface MeetingOutcomeResponse {
  meeting_id: string;
  meeting_outcome_id: string;
  meeting_status: string;
  is_qualified_lead: boolean;
  follow_up_action_id: string | null;
}
