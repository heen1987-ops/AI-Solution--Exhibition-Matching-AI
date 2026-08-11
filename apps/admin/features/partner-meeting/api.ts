/**
 * 참가업체 포털 - 상담 요청함 API 클라이언트.
 *
 * 통합 시점 재작성 메모(SECURITY)
 * --------------------------------
 * 이 파일은 원래 `apps/admin/lib/api-client.ts`를 우회하는 독립 fetch 클라이언트였다:
 * 담당자가 브라우저의 `localStorage`에 직접 입력한 `staffId`를 `X-Staff-Id` 헤더로
 * 실어 보냈는데, 백엔드(`meetings.py`)는 그 헤더를 애초에 인가에 쓰지 않는다
 * (`X-Profile-Id`/`X-Staff-Id`는 인가 근거가 아니다) - 즉 그 값을 바꿔 입력하기만 하면
 * 다른 회사의 상담함을 그대로 열람할 수 있었고, POST 두 개(decision/outcome)는
 * `X-CSRF-Token`도 아예 붙이지 않았다. `staff-session.ts`/`use-staff-session.ts`/
 * `components/StaffSessionBar.tsx`/`tests/staff-session.test.ts`는 삭제했다.
 *
 * 지금은 다른 관리자 화면과 동일하게 `@/lib/api-client`의 `apiGet`/`apiPost`를 그대로
 * 쓴다 - 인가는 Secure/HttpOnly 세션 쿠키 + `X-CSRF-Token`(그 클라이언트가 자동으로
 * 붙인다)으로만 이뤄지고, 회사 범위는 백엔드가 세션의 principal → 소속 참가업체로
 * 강제한다(meetings.py list_partner_meetings). 아래 네 함수의 시그니처는 호출부
 * (컴포넌트) 변경을 피하기 위해 그대로 유지했다.
 */

import { apiGet, apiPost } from "@/lib/api-client";

import type {
  MeetingDecisionResult,
  MeetingOutcomeRequest,
  MeetingOutcomeResponse,
  PartnerBuyerSummaryResponse,
  PartnerDecisionRequest,
  PartnerMeetingListItem,
  PartnerMeetingListResponse,
} from "./types";

// ---------------------------------------------------------------------------
// 15절 참가업체 포털 - E-02 목록, E-03 바이어 상세, 12.4 업체 응답, E-04 결과·후속조치
// (apps/api/app/api/v1/routers/meetings.py, 실제 구현·등록됨)
// ---------------------------------------------------------------------------

/** GET /partner/meetings - "자기 회사 요청만" 목록. 회사 범위는 백엔드가 세션
 * principal → 소속 참가업체로 강제한다(meetings.py list_partner_meetings) - 이 함수는
 * 의도적으로 exhibitor_id/participation_id 같은 스코프 파라미터를 받지 않는다. 그런
 * 파라미터를 추가하면 다른 회사 데이터를 요청할 수 있는 길을 여는 것이므로 프론트
 * 계약에서부터 막는다(tests/api.test.ts가 이 계약을 검증한다). */
export function listPartnerMeetings(
  params: { status?: string; cursor?: string; limit?: number } = {},
): Promise<PartnerMeetingListResponse> {
  return apiGet<PartnerMeetingListResponse>("/partner/meetings", {
    query: { status: params.status, cursor: params.cursor, limit: params.limit },
  });
}

/** types.ts 모듈 docstring의 계약 공백 2 참고: 참가업체 포털에는 단건 상담 조회 API가
 * 없어, 상세 화면에 필요한 candidate_slots를 목록에서 스캔해 찾는다. 최근 5페이지
 * (기본 페이지당 50건, 최대 250건)까지만 찾고 포기한다 - 그 이상은
 * `GET /partner/meetings/{id}`(TODO, BACKEND-MEETING) 없이는 실용적으로 찾을 수 없다. */
export async function findPartnerMeetingListItem(
  meetingId: string,
): Promise<PartnerMeetingListItem | null> {
  let cursor: string | undefined;
  for (let page = 0; page < 5; page += 1) {
    const res = await listPartnerMeetings({ cursor, limit: 50 });
    const found = res.items.find((item) => item.meeting_id === meetingId);
    if (found) return found;
    if (!res.next_cursor) return null;
    cursor = res.next_cursor;
  }
  return null;
}

/** GET /partner/meetings/{id}/buyer-summary - 확정 전에는 `contact`가 null로 온다
 * (meetings.py 주석: "확정 + 공유동의 + 열람권한 조건을 모두 만족할 때만 채워진다"). */
export function getPartnerBuyerSummary(meetingId: string): Promise<PartnerBuyerSummaryResponse> {
  return apiGet<PartnerBuyerSummaryResponse>(
    `/partner/meetings/${encodeURIComponent(meetingId)}/buyer-summary`,
  );
}

/** POST /partner/meetings/{id}/decision - 수락/거절/시간재제안. `body.version`은
 * types.ts 계약 공백 1 참고 - 지금은 화면에서 수동 입력을 받는다. */
export function decidePartnerMeeting(
  meetingId: string,
  body: PartnerDecisionRequest,
  idempotencyKey: string,
): Promise<MeetingDecisionResult> {
  return apiPost<MeetingDecisionResult>(
    `/partner/meetings/${encodeURIComponent(meetingId)}/decision`,
    body,
    { idempotencyKey },
  );
}

/** POST /partner/meetings/{id}/outcome - 상담 결과 기록(accepted -> completed 자동 전이). */
export function recordMeetingOutcome(
  meetingId: string,
  body: MeetingOutcomeRequest,
): Promise<MeetingOutcomeResponse> {
  return apiPost<MeetingOutcomeResponse>(
    `/partner/meetings/${encodeURIComponent(meetingId)}/outcome`,
    body,
  );
}
