/**
 * 운영자 AI 검수 큐/검수 API 함수.
 *
 * `apps/admin/lib/api-client.ts`(apiGet/apiPost, X-Actor-User-Id 세션 자동첨부, 표준화된
 * ApiClientError)를 그대로 재사용한다 - `../partner-ai-review/api.ts`, `../buyer-verification/api.ts`와
 * 동일한 이유(그 파일 자체는 소유 경로 밖이라 수정하지 않는다).
 *
 * 경로 확정 근거 (라우터 자체는 아직 없음 - `./types.ts` 모듈 docstring 참고)
 * ------------------------------------------------------------------------
 * `apps/api/app/services/extraction/review.py`의 각 서비스 함수가 무엇을 파라미터로 받는지로
 * `{id}`가 `extraction_id`인지 `review_request_id`인지 확정했다:
 *   - `approve_extraction(extraction_id, ...)`, `reject_extraction(extraction_id, ...)` ->
 *     `POST /admin/ai-review/{extraction_id}/approve|reject`
 *   - `request_changes(review_request_id, ...)` ->
 *     `POST /admin/ai-review/{review_request_id}/request-changes`
 *   - `claim_review_requests(review_request_ids: list[UUID], ...)` ->
 *     `POST /admin/ai-review`(`AdminReviewClaimRequest`) - document-structuring.md §9가 "문서/
 *     추출 id에 묶이지 않은 운영자 액션" 용도로 예약해 둔 바로 그 엔드포인트.
 *   - 큐 목록은 `GET /admin/ai-review` (`AdminReviewQueueResponse`).
 * 문서 1건의 추출 목록 조회(`GET .../extractions`)는 admin 전용 스키마가 별도로 없다 -
 * `apps/api/app/api/v1/routers/document.py`의 `_require_exhibitor_access`가 이미
 * EXHIBITOR/OPERATOR/ADMIN 역할을 모두 허용하는 동일 패턴을 쓰고 있어(그 라우터의 조회·삭제
 * 엔드포인트 전부), 참가업체용 `GET /partner/documents/{document_id}/extractions`가 운영자
 * 역할에도 동일하게 열려 있을 것으로 가정하고 재사용한다 - 라우터가 실제로 등록되면 이 가정을
 * 대조해야 한다(계약 공백, `./types.ts` 참고).
 *
 * 사유코드/공개범위 확장 필드에 대해서는 `./types.ts` 모듈 docstring 계약 공백 2·3번 참고 -
 * `../content-approval/logic.ts`의 `composeReasonPayload`가 로컬 사유코드를 백엔드가 실제로
 * 갖고 있는 자유서술 필드(`reason`/`comment`)에 합성해 넣는다.
 */

import { ApiClientError, apiGet, apiPost, type RequestOptions } from "@/lib/api-client";

import type {
  AdminDecisionResponse,
  AdminRequestChangesResponse,
  AdminReviewClaimRequest,
  AdminReviewClaimResponse,
  AdminReviewQueueQuery,
  AdminReviewQueueResponse,
  ApproveAttributeRequest,
  ExtractionListResponse,
  RejectAttributeRequest,
  RequestChangesRequest,
} from "./types";

function requiredError(field: string, message: string): never {
  throw new ApiClientError({
    code: "REASON_REQUIRED",
    message,
    field_errors: [{ field, reason: "required" }],
    retryable: false,
    retry_after_seconds: null,
    http_status: 0,
    request_id: null,
  });
}

// ---------------------------------------------------------------------------
// 큐
// ---------------------------------------------------------------------------

/** TODO(BACKEND-EXTRACTION): GET /admin/ai-review. */
export function listAiReviewQueue(
  query: AdminReviewQueueQuery = {},
  options?: RequestOptions,
): Promise<AdminReviewQueueResponse> {
  return apiGet<AdminReviewQueueResponse>("/admin/ai-review", { ...options, query: { ...query } });
}

/** TODO(BACKEND-EXTRACTION): POST /admin/ai-review - 일괄 클레임.
 * `app/services/extraction/review.py::claim_review_requests`와 1:1. */
export function claimReviewRequests(
  reviewRequestIds: string[],
  options?: RequestOptions,
): Promise<AdminReviewClaimResponse> {
  const body: AdminReviewClaimRequest = { review_request_ids: reviewRequestIds };
  return apiPost<AdminReviewClaimResponse>("/admin/ai-review", body, options);
}

// ---------------------------------------------------------------------------
// 문서 1건의 추출(속성) 목록 - 참가업체용 엔드포인트 재사용 (모듈 docstring 참고)
// ---------------------------------------------------------------------------

/** TODO(BACKEND-EXTRACTION): GET /partner/documents/{document_id}/extractions - 운영자
 * 역할로도 호출 가능하다고 가정(모듈 docstring). */
export function getDocumentExtractions(
  documentId: string,
  options?: RequestOptions,
): Promise<ExtractionListResponse> {
  return apiGet<ExtractionListResponse>(
    `/partner/documents/${encodeURIComponent(documentId)}/extractions`,
    options,
  );
}

// ---------------------------------------------------------------------------
// 속성 단위 승인/반려
// ---------------------------------------------------------------------------

/** TODO(BACKEND-EXTRACTION): POST /admin/ai-review/{extraction_id}/approve.
 * `app/services/extraction/review.py::approve_extraction`과 1:1
 * (`APPROVABLE_REVIEW_STATUSES`에 없는 상태에서 호출하면 `INVALID_REVIEW_TRANSITION` 409). */
export function approveExtraction(
  extractionId: string,
  body: ApproveAttributeRequest = {},
  options?: RequestOptions,
): Promise<AdminDecisionResponse> {
  return apiPost<AdminDecisionResponse>(
    `/admin/ai-review/${encodeURIComponent(extractionId)}/approve`,
    body,
    options,
  );
}

/** TODO(BACKEND-EXTRACTION): POST /admin/ai-review/{extraction_id}/reject.
 * 작업 지시 필수 요구사항 "반려 시 사유코드 필수" - 백엔드 스키마 자체는 `reason`을
 * 선택값으로 두지만(`./types.ts` 계약 공백 3번), 이 화면은 항상 비어있지 않은 문자열을
 * 네트워크 호출 이전에 요구한다(`../content-approval/logic.ts`의 `composeReasonPayload`가
 * 사유코드+코멘트를 합성해 이 필드를 채운다 - 호출부가 그 합성 결과를 넘겨야 한다). */
export async function rejectExtraction(
  extractionId: string,
  body: RejectAttributeRequest,
  options?: RequestOptions,
): Promise<AdminDecisionResponse> {
  if (!body.reason || !body.reason.trim()) {
    requiredError("reason", "반려 사유(사유코드 포함)를 입력해 주세요.");
  }
  return apiPost<AdminDecisionResponse>(
    `/admin/ai-review/${encodeURIComponent(extractionId)}/reject`,
    body,
    options,
  );
}

// ---------------------------------------------------------------------------
// 문서(검수요청) 단위 보완요청
// ---------------------------------------------------------------------------

/** TODO(BACKEND-EXTRACTION): POST /admin/ai-review/{review_request_id}/request-changes.
 * `app/services/extraction/review.py::request_changes`와 1:1 - 실제 스키마도 `comment`를
 * 필수(`min_length=1`)로 이미 강제하지만, 사유코드까지 포함해야 한다는 이 화면의 추가 요건을
 * 네트워크 호출 이전에 한 번 더 검증한다(`ApiClientError`를 그대로 던져 방어선을 이중화). */
export async function requestChangesOnDocument(
  reviewRequestId: string,
  body: RequestChangesRequest,
  options?: RequestOptions,
): Promise<AdminRequestChangesResponse> {
  if (!body.comment || !body.comment.trim()) {
    requiredError("comment", "보완요청 사유(사유코드 포함)를 입력해 주세요.");
  }
  return apiPost<AdminRequestChangesResponse>(
    `/admin/ai-review/${encodeURIComponent(reviewRequestId)}/request-changes`,
    body,
    options,
  );
}
