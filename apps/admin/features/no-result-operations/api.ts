/**
 * 무응답 검색 운영 API 함수.
 *
 * `apps/admin/lib/api-client.ts`(apiGet/apiPost, X-Actor-User-Id 세션 자동첨부, 표준화된
 * ApiClientError)를 그대로 재사용한다(그 파일 자체는 소유 경로 밖이라 수정하지 않는다 -
 * `../ai-review/api.ts`와 동일 관례).
 *
 * 경로 근거
 * ---------
 * - `GET /admin/analytics/no-results`: BACKEND-ANALYTICS가 이미 확정한 실제 스키마
 *   (`apps/api/app/schemas/analytics.py::NoResultQueryResponse`). 단 라우터
 *   (`app/api/v1/routers/analytics.py`)가 아직 등록되지 않았다 - 등록 전 호출은
 *   NOT_IMPLEMENTED(전역 404)로 던져지고 화면이 그대로 보여준다.
 * - `/admin/operations/no-result-tasks*`: 운영 태스크 백엔드는 어느 트랙에도 아직 없다
 *   (`./types.ts` 계약 공백 3번). REST 관례 추정 경로 - 백엔드 확정 후 대조 필요
 *   (재조정 플래그, 최종 보고에 명시).
 */

import { ApiClientError, apiGet, apiPost, type RequestOptions } from "@/lib/api-client";

import type {
  ImprovementActionCode,
  NoResultCause,
  NoResultQueryResponse,
  OperationsTask,
  OperationsTaskStatus,
} from "./types";

/** BACKEND-ANALYTICS 확정 스키마, 라우터 미등록 (모듈 docstring). */
export function listNoResultQueries(
  eventId: string,
  options?: RequestOptions,
): Promise<NoResultQueryResponse> {
  return apiGet<NoResultQueryResponse>("/admin/analytics/no-results", {
    ...options,
    query: { event_id: eventId },
  });
}

export interface OperationsTaskListResponse {
  items: OperationsTask[];
}

/** TODO(백엔드 미확정 - 재조정 필요): GET /admin/operations/no-result-tasks. */
export function listOperationsTasks(
  eventId: string,
  status?: OperationsTaskStatus,
  options?: RequestOptions,
): Promise<OperationsTaskListResponse> {
  return apiGet<OperationsTaskListResponse>("/admin/operations/no-result-tasks", {
    ...options,
    query: { event_id: eventId, status },
  });
}

/** TODO(백엔드 미확정 - 재조정 필요): POST /admin/operations/no-result-tasks - 무응답
 * 질의 1건을 운영 태스크로 승격. */
export function createOperationsTask(
  body: { event_id: string; query_norm: string; cause?: NoResultCause },
  options?: RequestOptions,
): Promise<OperationsTask> {
  return apiPost<OperationsTask>("/admin/operations/no-result-tasks", body, options);
}

/** TODO(백엔드 미확정 - 재조정 필요): POST /admin/operations/no-result-tasks/{id}/transition.
 * 서버 확정 전에도 클라이언트 상태머신(`./logic.ts`)과 동일 규칙을 네트워크 호출 이전에
 * 강제한다(사유 필수 전이 이중 방어 - `../ai-review/api.ts`와 동일 패턴). */
export function transitionOperationsTask(
  taskId: string,
  body: { to_status: OperationsTaskStatus; reason?: string | null },
  options?: RequestOptions,
): Promise<OperationsTask> {
  if (body.to_status === "IGNORED" && !(body.reason && body.reason.trim())) {
    throw new ApiClientError({
      code: "REASON_REQUIRED",
      message: "무시 처리에는 사유 입력이 필요합니다.",
      field_errors: [{ field: "reason", reason: "required" }],
      retryable: false,
      retry_after_seconds: null,
      http_status: 0,
      request_id: null,
    });
  }
  return apiPost<OperationsTask>(
    `/admin/operations/no-result-tasks/${encodeURIComponent(taskId)}/transition`,
    body,
    options,
  );
}

/** TODO(백엔드 미확정 - 재조정 필요): POST /admin/operations/no-result-tasks/{id}/actions.
 * 개선 액션은 서버에서도 "사람 액션 요청 기록"으로만 저장되어야 하며 온톨로지·업체 데이터를
 * 직접 수정해서는 안 된다(스펙 명시 금지 - 백엔드 구현 시 이 계약을 반드시 유지할 것). */
export function requestImprovementAction(
  taskId: string,
  body: { action: ImprovementActionCode; note?: string | null },
  options?: RequestOptions,
): Promise<OperationsTask> {
  return apiPost<OperationsTask>(
    `/admin/operations/no-result-tasks/${encodeURIComponent(taskId)}/actions`,
    body,
    options,
  );
}
