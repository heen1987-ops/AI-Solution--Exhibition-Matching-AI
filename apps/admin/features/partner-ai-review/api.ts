/**
 * 참가업체 포털 - AI 검수 화면 API 함수.
 *
 * 2026-08-03 재조정: BACKEND-EXTRACTION의 `apps/api/app/api/v1/routers/extraction.py`
 * (`build_extraction_router()`)가 실제로 착지해 아래 4개 exhibitor-facing 경로가 진짜 계약이
 * 됐다(`./types.ts` 모듈 docstring 참고). 이 파일의 이전 버전은 라우터가 없던 시점의 잠정
 * 경로(`/ai-review/{id}/confirm` 등, `AiReviewAttribute` 모양)를 대상으로 했었는데 `types.ts`가
 * 먼저 갱신되면서 더 이상 존재하지 않는 타입을 import하고 있었다 - 이 파일도 실제 계약에 맞춰
 * 다시 썼다.
 *
 * `apps/admin/lib/api-client.ts`의 공용 요청 헬퍼(apiGet/apiPost/apiPatch, 성공봉투 언랩,
 * X-Actor-User-Id 자동첨부, 표준화된 ApiClientError)를 재사용하되 그 파일 자체는 수정하지
 * 않는다(owned path 밖 공유 파일).
 *
 * 라우터는 착지했지만 `apps/api/app/api/v1/api.py`에 아직 include되지 않았다(integrator
 * 단계, `./types.ts` 참고). 마운트 전 호출은 FastAPI 전역 404 -> `ApiClientError(code:
 * "NOT_IMPLEMENTED")`로 화면에 그대로 표시된다(가짜 성공 금지).
 *
 * 백엔드 상태전이 규칙(`apps/api/app/services/extraction/review.py` confirm_extraction)이
 * 중요하다: "AI 제안값을 그대로 확인"과 "값을 고쳐서 확정"이 서로 다른 엔드포인트가 아니라
 * 같은 `POST .../confirm`이다 - `edited_by_exhibitor` 플래그(먼저 PATCH를 호출했는지 여부)로
 * 결과 review_status가 CONFIRMED_BY_EXHIBITOR/MODIFIED_BY_EXHIBITOR로 갈린다. 그래서 "수정값
 * 저장"은 이 파일에서 PATCH 다음에 confirm(decision="confirm")을 순차 호출하는 조합으로
 * 구현한다(`saveModifiedValue`) - 화면(컴포넌트)은 이 조합을 몰라도 된다.
 *
 * UNKNOWN->YES 가드는 `saveModifiedValue`에만 있다(`confirmProposedValue`에는 없음)는 점이
 * 중요하다: confirm 요청 본문에는 값이 없다 - 이미 행에 있는 `normalized_value`(없으면
 * `proposed_value`)를 그대로 확정할 뿐이라, "그대로 확인"의 baseline과 resultingValue는
 * 항상 같은 값이라 가드가 수학적으로 절대 발동할 수 없다(`./logic.ts` 모듈 docstring 참고).
 * 실제로 값이 바뀌는 유일한 지점(PATCH)에만 가드를 걸어야 침묵 토글을 막으면서도 불필요한
 * 사유 입력을 요구하지 않는다.
 */

import { ApiClientError, apiGet, apiPatch, apiPost, type RequestOptions } from "@/lib/api-client";

import { requiresExplicitUnknownToYesConfirmation, validateUnknownToYesJustification } from "./logic";
import type {
  ExtractedAttributeRead,
  ExtractionConfirmRequest,
  ExtractionListResponse,
  ExtractionPatchRequest,
  JsonValue,
  SubmitReviewRequest,
  SubmitReviewResponse,
  Visibility,
} from "./types";

function justificationError(message: string): never {
  throw new ApiClientError({
    code: "JUSTIFICATION_REQUIRED",
    message,
    field_errors: [{ field: "justification", reason: "required" }],
    retryable: false,
    retry_after_seconds: null,
    http_status: 0,
    request_id: null,
  });
}

// ---------------------------------------------------------------------------
// 실제 착지한 계약 - apps/api/app/api/v1/routers/extraction.py의 exhibitor-facing 경로
// ---------------------------------------------------------------------------

/** GET /partner/documents/{document_id}/extractions - 문서 1건의 AI 제안 속성 전체 목록
 * (근거·신뢰도·온톨로지 코드 포함). own-company 격리는 백엔드
 * `_require_exhibitor_access`(403 RESOURCE_FORBIDDEN)가 강제한다. */
export function listExtractions(
  documentId: string,
  options?: RequestOptions,
): Promise<ExtractionListResponse> {
  return apiGet<ExtractionListResponse>(
    `/partner/documents/${encodeURIComponent(documentId)}/extractions`,
    options,
  );
}

/** PATCH /partner/extractions/{extraction_id} - review_status를 절대 바꾸지 않는 순수 편집
 * (`normalized_value`/`visibility`). 화면에서 직접 부를 일은 적고 보통 `saveModifiedValue`를
 * 통해 confirm과 묶어서 호출한다. */
export function patchExtraction(
  extractionId: string,
  body: ExtractionPatchRequest,
  options?: RequestOptions,
): Promise<ExtractedAttributeRead> {
  return apiPatch<ExtractedAttributeRead>(
    `/partner/extractions/${encodeURIComponent(extractionId)}`,
    body,
    options,
  );
}

/** POST /partner/extractions/{extraction_id}/confirm - decision: "confirm" | "reject".
 * PROPOSED -> CONFIRMED_BY_EXHIBITOR | MODIFIED_BY_EXHIBITOR | REJECTED_BY_EXHIBITOR. */
export function confirmExtraction(
  extractionId: string,
  body: ExtractionConfirmRequest,
  options?: RequestOptions,
): Promise<ExtractedAttributeRead> {
  return apiPost<ExtractedAttributeRead>(
    `/partner/extractions/${encodeURIComponent(extractionId)}/confirm`,
    body,
    options,
  );
}

/** POST /partner/extractions/submit-review - 문서 전체를 검수요청으로 제출한다. 백엔드가
 * PROPOSED/CONFLICTED 잔여 항목·근거 누락·공개범위 미설정을 422(checks 배열)로 막는다
 * (`apps/api/app/services/extraction/review.py::_pending_checks`). */
export function submitDocumentForReview(
  body: SubmitReviewRequest,
  options?: RequestOptions,
): Promise<SubmitReviewResponse> {
  return apiPost<SubmitReviewResponse>("/partner/extractions/submit-review", body, options);
}

// ---------------------------------------------------------------------------
// 화면용 조합 함수 - UNKNOWN->YES 침묵 토글 방어를 네트워크 호출 전에 강제한다(작업 지시).
// ---------------------------------------------------------------------------

/** "AI 제안값 확인" 버튼 - 값을 고치지 않고 이미 행에 있는 값(`normalized_value` 없으면
 * `proposed_value`)을 그대로 확정한다. `reason`은 선택 메모일 뿐 게이트 조건이 아니다 -
 * UNKNOWN->YES 가드는 여기서 절대 발동하지 않는다(모듈 docstring 참고, `saveModifiedValue`가
 * 유일한 게이트 지점이다). */
export function confirmProposedValue(
  attribute: ExtractedAttributeRead,
  reason: string | undefined,
  options?: RequestOptions,
): Promise<ExtractedAttributeRead> {
  return confirmExtraction(attribute.extraction_id, { decision: "confirm", reason: reason ?? null }, options);
}

/** "수정값 저장" 버튼 - PATCH(normalized_value[, visibility])로 값을 고친 뒤 곧바로
 * confirm(decision="confirm")을 호출해 MODIFIED_BY_EXHIBITOR로 확정한다(백엔드는 PATCH 단독
 * 호출로는 review_status를 절대 바꾸지 않는다 - 이 함수가 그 2단계 계약을 감춘다). PATCH가
 * 성공했는데 confirm이 실패하면 `normalized_value`는 이미 저장된 채로 남는다(review_status는
 * 여전히 PROPOSED) - 재시도 시 PATCH를 다시 보내도 멱등하므로 안전하다. */
export async function saveModifiedValue(
  attribute: ExtractedAttributeRead,
  newValue: JsonValue,
  options: { visibility?: Visibility; justification?: string } = {},
  requestOptions?: RequestOptions,
): Promise<ExtractedAttributeRead> {
  if (requiresExplicitUnknownToYesConfirmation(attribute, newValue)) {
    const error = validateUnknownToYesJustification(options.justification);
    if (error) justificationError(error);
  }
  await patchExtraction(
    attribute.extraction_id,
    { normalized_value: newValue, visibility: options.visibility, reason: options.justification ?? null },
    requestOptions,
  );
  return confirmExtraction(
    attribute.extraction_id,
    { decision: "confirm", reason: options.justification ?? null },
    requestOptions,
  );
}

/** "삭제(채택 안함)" 버튼 - AI 제안을 기각한다(decision="reject"). 원본 문서·근거는 남고 이
 * 속성만 채택하지 않는다는 결정을 REJECTED_BY_EXHIBITOR로 기록한다. UNKNOWN->YES 가드와는
 * 무관하다(긍정값으로의 전이가 아니므로). */
export function rejectProposedValue(
  extractionId: string,
  reason: string | undefined,
  options?: RequestOptions,
): Promise<ExtractedAttributeRead> {
  return confirmExtraction(extractionId, { decision: "reject", reason: reason ?? null }, options);
}
