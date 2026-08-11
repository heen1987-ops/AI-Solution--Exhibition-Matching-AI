/**
 * 바이어 검증 큐 + 상담 운영 뷰 API 함수.
 *
 * `../partner-meeting/api.ts`와 달리 이 트랙은 별도 인증 스텁을 두지 않는다: 검증
 * 승인/제한/반려/정지/만료 처리는 운영자(EVENT_ADMIN/DATA_REVIEWER)가 §28 업체 승인·반려와
 * 동일한 `X-Actor-User-Id` 주체 모델로 수행하므로, `apps/admin/lib/api-client.ts`의 공용
 * 요청 헬퍼(apiGet/apiPost, 세션 actorUserId 자동 첨부, 성공봉투 언랩, 표준화된
 * ApiClientError)를 그대로 재사용한다 - 그 파일 자체는 수정하지 않는다(소유 경로 밖의
 * 공유 파일이라 다른 트랙과 동시 편집 충돌 위험이 있어 건드리지 않음).
 *
 * 이 파일의 모든 경로는 아직 백엔드에 없는 잠정 계약이다 - `./types.ts` 모듈 docstring
 * 참고. 호출하면 FastAPI가 전역 404를 반환하고, apiRequest가 그것을
 * `ApiClientError(code: "NOT_IMPLEMENTED")`로 변환한다 - 화면은 그 상태를 그대로 보여준다
 * (가짜 성공 금지 원칙, `apps/admin/components/ErrorBanner.tsx`와 동일).
 */

import { ApiClientError, apiGet, apiPost, type RequestOptions } from "@/lib/api-client";

import type {
  AdminMeetingOpsListQuery,
  AdminMeetingOpsListResponse,
  BuyerVerificationDecisionRequest,
  BuyerVerificationDecisionResponse,
  BuyerVerificationQueueQuery,
  BuyerVerificationQueueResponse,
} from "./types";

/** TODO(BACKEND-BUYER-PROFILE): GET /admin/buyers/verification-queue.
 * 잠정 경로 - CONTRACTS-BUYER 문서가 없어 §28 업체 검수 큐(GET /admin/exhibitors/review)와
 * 대칭되는 이름으로 추정했다. 백엔드 확정 후 대조 필요. */
export function listBuyerVerificationQueue(
  query: BuyerVerificationQueueQuery = {},
  options?: RequestOptions,
): Promise<BuyerVerificationQueueResponse> {
  return apiGet<BuyerVerificationQueueResponse>("/admin/buyers/verification-queue", {
    ...options,
    query: { ...query },
  });
}

/** TODO(BACKEND-BUYER-PROFILE): POST /admin/buyers/{buyer_profile_id}/verification-decision.
 * 작업 지시 필수 요구사항 "reason 필수"를 네트워크 호출 이전에 클라이언트에서부터 강제한다
 * (`apps/admin/lib/api-client.ts`의 rejectExhibitor와 동일한 패턴 - tests/api.test.ts가
 * fetch가 아예 호출되지 않는다는 것까지 검증한다). */
export function decideBuyerVerification(
  buyerProfileId: string,
  body: BuyerVerificationDecisionRequest,
  options?: RequestOptions,
): Promise<BuyerVerificationDecisionResponse> {
  if (!body.reason || !body.reason.trim()) {
    throw new ApiClientError({
      code: "REASON_REQUIRED",
      message: "사유를 입력해 주세요.",
      field_errors: [{ field: "reason", reason: "required" }],
      retryable: false,
      retry_after_seconds: null,
      http_status: 0,
      request_id: null,
    });
  }
  return apiPost<BuyerVerificationDecisionResponse>(
    `/admin/buyers/${encodeURIComponent(buyerProfileId)}/verification-decision`,
    body,
    options,
  );
}

/** TODO(BACKEND-BUYER-PROFILE 또는 BACKEND-MEETING): GET /admin/meetings/ops.
 * `./types.ts`의 AdminMeetingOpsItem docstring 참고 - 연락처 필드를 아예 갖지 않는 스코프된
 * 계약으로 설계했다. */
export function listAdminMeetingOps(
  query: AdminMeetingOpsListQuery = {},
  options?: RequestOptions,
): Promise<AdminMeetingOpsListResponse> {
  return apiGet<AdminMeetingOpsListResponse>("/admin/meetings/ops", {
    ...options,
    query: { ...query },
  });
}
