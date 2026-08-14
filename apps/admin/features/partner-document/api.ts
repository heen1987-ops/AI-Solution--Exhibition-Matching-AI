/**
 * 참가업체 포털 - 문서함 API 함수.
 *
 * `apps/admin/lib/api-client.ts`의 공용 요청 헬퍼(apiGet/apiDelete, 성공봉투 언랩,
 * X-Actor-User-Id 자동첨부, 표준화된 ApiClientError)를 재사용하되 그 파일 자체는 수정하지
 * 않는다(owned path 밖 공유 파일 - `./types.ts` 모듈 docstring의 "인증 모델" 절 참고, WAVE
 * 2C buyer-verification 트랙과 동일한 재사용 패턴). 아래 모든 경로는 아직 백엔드 라우터가
 * 없는 잠정 계약이다 - 호출하면 FastAPI가 전역 404를 반환하고 apiRequest가 그것을
 * `ApiClientError(code: "NOT_IMPLEMENTED")`로 변환해, 화면은 그 상태를 명확히 보여준다(가짜
 * 성공 금지 원칙).
 */

import { apiDelete, apiGet, type RequestOptions } from "@/lib/api-client";

import type {
  DeleteResponse,
  DocumentDetailResponse,
  DocumentListQuery,
  DocumentListResponse,
} from "./types";

/** TODO(BACKEND-DOCUMENT): GET /partner/documents - 자사 문서 목록.
 * exhibitor_id는 호출부(화면)가 세션(own-company-only 스코프, apps/admin/lib/auth-state.ts
 * AdminSession.exhibitorId)에서 채워 넣는다 - 이 함수 자체는 그 값을 검증하지 않는다(백엔드가
 * partner.py `_require_exhibitor_access`와 동일한 검사를 해야 한다, 통합 시 확인 필요). */
export function listPartnerDocuments(
  query: DocumentListQuery,
  options?: RequestOptions,
): Promise<DocumentListResponse> {
  return apiGet<DocumentListResponse>("/partner/documents", {
    ...options,
    query: { ...query },
  });
}

/** TODO(BACKEND-DOCUMENT): GET /partner/documents/{document_id} - 버전·처리작업 상세. */
export function getPartnerDocument(
  documentId: string,
  options?: RequestOptions,
): Promise<DocumentDetailResponse> {
  return apiGet<DocumentDetailResponse>(
    `/partner/documents/${encodeURIComponent(documentId)}`,
    options,
  );
}

/** TODO(BACKEND-DOCUMENT): DELETE /partner/documents/{document_id}/versions/{file_id}.
 * app/models/document.py 모듈 docstring 결정 2번: 게시된 콘텐츠가 참조 중인 버전은
 * DOCUMENT_DELETE_BLOCKED_PUBLISHED(409로 추정)로 거부된다 - 화면은 그 오류의
 * `field_errors`가 아니라 `ApiClientError` 자체의 detail 모양을 그대로 보여줘야 한다. */
export function deletePartnerDocumentVersion(
  documentId: string,
  fileId: string,
  options?: RequestOptions,
): Promise<DeleteResponse> {
  return apiDelete<DeleteResponse>(
    `/partner/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(fileId)}`,
    options,
  );
}
