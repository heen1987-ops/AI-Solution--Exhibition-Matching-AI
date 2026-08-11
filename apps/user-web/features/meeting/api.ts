/**
 * 상담(미팅) API 호출 - 바이어 화면 전용 로컬 클라이언트.
 *
 * `apps/user-web/lib/api-client.ts`/`lib/types.ts`는 편집 범위 밖(작업 지시)이라 이
 * 파일을 새로 둔다. 다만 저수준 fetch/응답봉투 파싱/오류 변환(`apiGet`/`apiPost`/
 * `ApiClientError`/`generateClientId`/`RequestOptions`)은 이미 검증된 `lib/api-client.ts`
 * export를 그대로 재사용한다 - 이 함수들은 제네릭이라 Meeting 전용 타입에 묶여 있지
 * 않으므로 그대로 써도 안전하다. 실제 라우트 경로는
 * `apps/api/app/api/v1/routers/meetings.py`를 그대로 따른다.
 */

import { apiGet, apiPost, generateClientId, type RequestOptions } from "@/lib/api-client";

import type {
  AvailabilityListResponse,
  AvailabilityQuery,
  MeetingCancelRequest,
  MeetingCreateRequest,
  MeetingListQuery,
  MeetingListResponse,
  MeetingRespondRequest,
  MeetingResponse,
} from "./types";

export function getExhibitorAvailability(
  exhibitorId: string,
  query: AvailabilityQuery,
  options?: RequestOptions,
): Promise<AvailabilityListResponse> {
  return apiGet<AvailabilityListResponse>(
    `/exhibitors/${encodeURIComponent(exhibitorId)}/availability`,
    { ...options, query },
  );
}

/** 상담 요청 생성 (12.3절). 외부 상대에게 전달되는 요청이라 멱등키를 자동 생성한다. */
export function postMeetingRequest(
  request: MeetingCreateRequest,
  options: RequestOptions = {},
): Promise<MeetingResponse> {
  const idempotencyKey = options.idempotencyKey ?? generateClientId();
  return apiPost<MeetingResponse>("/meetings", request, { ...options, idempotencyKey });
}

export function listMeetings(
  query?: MeetingListQuery,
  options?: RequestOptions,
): Promise<MeetingListResponse> {
  return apiGet<MeetingListResponse>("/meetings", { ...options, query });
}

export function getMeeting(meetingId: string, options?: RequestOptions): Promise<MeetingResponse> {
  return apiGet<MeetingResponse>(`/meetings/${encodeURIComponent(meetingId)}`, options);
}

export function cancelMeeting(
  meetingId: string,
  request: MeetingCancelRequest,
  options: RequestOptions = {},
): Promise<MeetingResponse> {
  const idempotencyKey = options.idempotencyKey ?? generateClientId();
  return apiPost<MeetingResponse>(`/meetings/${encodeURIComponent(meetingId)}/cancel`, request, {
    ...options,
    idempotencyKey,
  });
}

export function respondToCounterProposal(
  meetingId: string,
  request: MeetingRespondRequest,
  options: RequestOptions = {},
): Promise<MeetingResponse> {
  const idempotencyKey = options.idempotencyKey ?? generateClientId();
  return apiPost<MeetingResponse>(`/meetings/${encodeURIComponent(meetingId)}/respond`, request, {
    ...options,
    idempotencyKey,
  });
}
