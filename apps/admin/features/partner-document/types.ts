/**
 * 참가업체 포털 - 문서함(A-DOC) 타입.
 *
 * 근거 문서/코드
 * ---------------
 * - apps/api/app/schemas/document.py: DocumentRead, DocumentListResponse, DocumentDetailResponse,
 *   DocumentFileVersionRead, ProcessingJobRead, DeleteResponse, DeleteBlockedDetail,
 *   DuplicateDocumentDetail - 실제로 정의된 백엔드 응답 스키마 정본. 이 타입들은 그 파일과
 *   필드를 1:1로 맞췄다.
 * - apps/api/app/models/document.py: DOCUMENT_TYPES(6종), DOCUMENT_STATUSES(4종),
 *   PROCESSING_JOB_STATUSES(4종) - 실제 DB CHECK 제약이 허용하는 값의 정본.
 *
 * 계약 공백(중요 - WAVE 2D BACKEND-DOCUMENT 트랙과 조율 필요)
 * ----------------------------------------------------------
 * apps/api/app/schemas/document.py와 app/models/document.py는 이미 존재하지만, 그 스키마를
 * 실제로 서비스하는 라우터 파일이 이 저장소 어디에도 없다(확인:
 * `apps/api/app/api/v1/routers/**`에 document 관련 파일 없음, `apps/api/app/services/document/`
 * 에는 hashing.py만 있고 아직 upload/list 엔드포인트 조립 코드가 없음). 즉 스키마는 "계약으로
 * 확정"되어 있지만 "호출 가능한 API"는 아직 없다. 이 파일의 경로 문자열
 * (`GET /partner/documents`, `GET /partner/documents/{id}`)은 08 문서·db-erd에 없는 새 도메인이라
 * REST 관례로 추정한 것이다 - 라우터가 실제로 등록되면 경로를 대조해야 한다.
 *
 * 인증 모델: apps/api/app/models/document.py의 DocumentAccessLog.actor_user_id가
 * profile.user_account 기준 식별자를 쓰고 있어(exhibition.exhibitor_staff 기준이 아님),
 * partner.py의 프로필/제품 API와 같은 `X-Actor-User-Id` 주체 모델을 그대로 따른다고 가정한다
 * (apps/admin/features/partner-meeting/**이 쓰는 별도의 `X-Staff-Id` 모델과는 다르다 - 그
 * 트랙은 exhibition.exhibitor_staff.staff_id를 직접 쓰는 meetings.py 라우터 때문에 독립
 * 클라이언트를 뒀지만, document 도메인은 그 근거가 없다). 그래서 이 기능은
 * apps/admin/lib/api-client.ts(X-Actor-User-Id 자동첨부)를 그대로 재사용한다 - api.ts 참고.
 */

/** 개방형 코드 타입 - apps/admin/lib/types.ts OpenEnum과 동일 규약(이 파일은 그 파일을
 * import하지 않고 로컬로 재정의한다 - owned path 밖 공유 파일을 건드리지 않기 위함). */
export type OpenEnum<Known extends string> = Known | (string & {});

export type IsoDateTime = string;

/** app/models/document.py DOCUMENT_TYPES. */
export type DocumentType = OpenEnum<
  "CATALOG" | "CERTIFICATE" | "PRICE_LIST" | "COMPANY_PROFILE" | "PRODUCT_SPEC" | "OTHER"
>;

export const DOCUMENT_TYPES: DocumentType[] = [
  "CATALOG",
  "CERTIFICATE",
  "PRICE_LIST",
  "COMPANY_PROFILE",
  "PRODUCT_SPEC",
  "OTHER",
];

/** app/models/document.py DOCUMENT_STATUSES. */
export type DocumentStatus = OpenEnum<"UPLOADED" | "PROCESSING" | "PROCESSED" | "PROCESSING_FAILED">;

/** app/models/document.py PROCESSING_JOB_STATUSES. */
export type ProcessingJobStatus = OpenEnum<"PENDING" | "RUNNING" | "COMPLETED" | "FAILED">;

// ---------------------------------------------------------------------------
// apps/api/app/schemas/document.py와 1:1 (라우터는 아직 없음 - 모듈 docstring 참고)
// ---------------------------------------------------------------------------

export interface DocumentRead {
  document_id: string;
  exhibitor_id: string;
  event_id: string | null;
  document_type: DocumentType;
  status: DocumentStatus;
  filename: string | null;
  mime_type: string | null;
  size_bytes: number | null;
  content_hash: string | null;
  version_count: number;
  is_published: boolean;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export interface DocumentFileVersionRead {
  file_id: string;
  version_no: number;
  filename: string;
  mime_type: string;
  size_bytes: number;
  content_hash: string;
  uploaded_at: IsoDateTime;
  is_current: boolean;
  is_published: boolean;
}

export interface DocumentListResponse {
  items: DocumentRead[];
}

export interface ProcessingJobRead {
  processing_job_id: string;
  document_id: string;
  status: ProcessingJobStatus;
  created_at: IsoDateTime;
}

export interface DocumentDetailResponse {
  document: DocumentRead;
  versions: DocumentFileVersionRead[];
  /** 계약 공백: apps/api/app/schemas/document.py DocumentDetailResponse에는 processing_jobs
   * 필드가 없다(현재는 versions만 있음). 목록 화면의 "처리작업/추출진행률/오류" 표시 요구를
   * 만족하려면 이 필드가 필요해 잠정으로 추가했다 - 백엔드 확정 시 대조 필요. */
  processing_jobs?: ProcessingJobRead[];
}

export interface DeleteResponse {
  document_id: string;
  deleted: boolean;
}

export interface DeleteBlockedDetail {
  code: "DOCUMENT_DELETE_BLOCKED_PUBLISHED";
  message: string;
  document_id: string;
  published_file_id: string;
}

// ---------------------------------------------------------------------------
// 목록 조회 쿼리 (잠정 - 라우터 미구현)
// ---------------------------------------------------------------------------

export interface DocumentListQuery {
  exhibitor_id: string;
  event_id?: string;
  document_type?: DocumentType;
  status?: DocumentStatus;
  cursor?: string;
  limit?: number;
}
