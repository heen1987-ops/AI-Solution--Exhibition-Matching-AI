/**
 * 관리자 앱 공용 API 클라이언트.
 *
 * apps/user-web/lib/api-client.ts와 동일한 요청/오류 처리 골격(성공 봉투 언랩, 다양한
 * FastAPI 오류 모양 흡수)을 따른다. 관리자 인증은 HttpOnly 서버 세션으로만
 * 수행하며 브라우저가 사용자 ID/역할 헤더를 만들지 않는다.
 *
 * 이 파일은 두 그룹으로 나뉜다:
 *   1. "실제 구현됨" - apps/api/app/api/v1/routers/{exhibitors,partner}.py가 이미 등록한
 *      경로. 정상적으로 호출·응답된다.
 *   2. "TODO: 미구현" - docs/vibe-coding-master-spec-v1.md §40.9절에 경로만 문서화되어 있고
 *      실제 라우터가 아직 없다(.harness/decisions.md DECISION-005, backlog BACKEND-007).
 *      호출하면 FastAPI가 전역 404(Not Found)를 반환한다 - 이 클라이언트는 그 실패를 있는
 *      그대로 ApiClientError로 던진다. 화면은 성공한 것처럼 표시하지 않고 명확한 오류
 *      상태를 보여줘야 한다(작업 지시 "가짜 성공 표시 금지").
 */

import { getRuntimeSession } from "./auth-state";
import type {
  AdminBoothCreateRequest,
  AdminBoothListItem,
  AdminBoothListResponse,
  AdminEventCreateRequest,
  AdminEventListResponse,
  AdminExhibitorDetail,
  AdminExhibitorListQuery,
  AdminExhibitorListResponse,
  ApiErrorBody,
  ApiErrorCode,
  ApiSuccessEnvelope,
  ApproveExhibitorRequest,
  AuditLogListQuery,
  AuditLogListResponse,
  BoothStatusUpdateRequest,
  ExhibitorDecisionResponse,
  ExhibitorProfileRead,
  ExhibitorProfileUpdate,
  FieldError,
  NoResultQueryResponse,
  ProductCreateRequest,
  ProductRead,
  PublicBoothDetail,
  PublicExhibitorDetail,
  PublicExhibitorListResponse,
  PublicProductSummary,
  RejectExhibitorRequest,
  SearchAnalyticsSummary,
  SubmitResponse,
  TradeConditionRead,
  TradeConditionUpsert,
} from "./types";

// ---------------------------------------------------------------------------
// 기본 설정
// ---------------------------------------------------------------------------

const API_ORIGIN = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");
const API_V1_PREFIX = "/api/v1";

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  query?: Record<string, string | number | boolean | undefined | null>;
  idempotencyKey?: string;
  requestId?: string;
  signal?: AbortSignal;
  /** 하위 호환 필드. 인증 헤더는 더 이상 첨부하지 않는다. */
  attachActor?: boolean;
}

export interface ApiClientErrorInfo {
  code: ApiErrorCode;
  message: string;
  field_errors: FieldError[];
  retryable: boolean;
  retry_after_seconds: number | null;
  http_status: number;
  request_id: string | null;
}

export class ApiClientError extends Error implements ApiClientErrorInfo {
  readonly code: ApiErrorCode;
  readonly field_errors: FieldError[];
  readonly retryable: boolean;
  readonly retry_after_seconds: number | null;
  readonly http_status: number;
  readonly request_id: string | null;

  constructor(info: ApiClientErrorInfo) {
    super(info.message);
    this.name = "ApiClientError";
    this.code = info.code;
    this.field_errors = info.field_errors;
    this.retryable = info.retryable;
    this.retry_after_seconds = info.retry_after_seconds;
    this.http_status = info.http_status;
    this.request_id = info.request_id;
  }
}

export function generateClientId(): string {
  const globalCrypto = typeof crypto !== "undefined" ? crypto : undefined;
  if (globalCrypto && typeof globalCrypto.randomUUID === "function") {
    return globalCrypto.randomUUID();
  }
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (char) => {
    const random = (Math.random() * 16) | 0;
    const value = char === "x" ? random : (random & 0x3) | 0x8;
    return value.toString(16);
  });
}

function buildUrl(path: string, query?: RequestOptions["query"]): string {
  const url = new URL(`${API_ORIGIN}${API_V1_PREFIX}${path}`, "http://localhost");
  if (query) {
    for (const [key, value] of Object.entries(query)) {
      if (value === undefined || value === null) continue;
      url.searchParams.set(key, String(value));
    }
  }
  return API_ORIGIN ? url.toString() : `${url.pathname}${url.search}`;
}

function isSuccessEnvelope<T>(payload: unknown): payload is ApiSuccessEnvelope<T> {
  return (
    typeof payload === "object" &&
    payload !== null &&
    (payload as Record<string, unknown>).success === true &&
    "data" in payload
  );
}

function extractErrorBody(payload: unknown): Partial<ApiErrorBody> | null {
  if (typeof payload !== "object" || payload === null) return null;
  const record = payload as Record<string, unknown>;
  const candidate =
    record.error ?? record.detail ?? (typeof record.code === "string" ? record : undefined);
  if (candidate === undefined || candidate === null) return null;

  if (typeof candidate === "string") {
    return { code: "UNKNOWN_ERROR", message: candidate, field_errors: [] };
  }

  if (Array.isArray(candidate)) {
    const field_errors: FieldError[] = candidate.map((item) => {
      const row = item as Record<string, unknown>;
      const loc = Array.isArray(row.loc) ? row.loc.join(".") : "unknown";
      return { field: loc, reason: typeof row.msg === "string" ? row.msg : "invalid" };
    });
    return {
      code: "VALIDATION_FAILED",
      message: "입력값을 확인해 주세요.",
      field_errors,
      retryable: false,
      retry_after_seconds: null,
    };
  }

  if (typeof candidate === "object") {
    const row = candidate as Record<string, unknown>;
    return {
      code: typeof row.code === "string" ? row.code : "UNKNOWN_ERROR",
      message: typeof row.message === "string" ? row.message : "요청을 처리하지 못했습니다.",
      field_errors: Array.isArray(row.field_errors) ? (row.field_errors as FieldError[]) : [],
      retryable: typeof row.retryable === "boolean" ? row.retryable : false,
      retry_after_seconds:
        typeof row.retry_after_seconds === "number" ? row.retry_after_seconds : null,
    };
  }

  return null;
}

function extractRequestId(payload: unknown): string | null {
  if (typeof payload !== "object" || payload === null) return null;
  const meta = (payload as Record<string, unknown>).meta;
  if (typeof meta !== "object" || meta === null) return null;
  const requestId = (meta as Record<string, unknown>).request_id;
  return typeof requestId === "string" ? requestId : null;
}

async function apiRequest<T>(
  method: HttpMethod,
  path: string,
  body: unknown,
  options: RequestOptions = {},
): Promise<T> {
  const url = buildUrl(path, options.query);
  const headers: Record<string, string> = {
    Accept: "application/json",
    "Accept-Language": "ko-KR",
    "X-Request-ID": options.requestId ?? generateClientId(),
  };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (options.idempotencyKey) headers["Idempotency-Key"] = options.idempotencyKey;

  if (method !== "GET") {
    const csrf = getRuntimeSession().csrfToken;
    if (csrf) headers["X-CSRF-Token"] = csrf;
  }

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: options.signal,
    });
  } catch {
    throw new ApiClientError({
      code: "NETWORK_ERROR",
      message: "서버에 연결할 수 없습니다. NEXT_PUBLIC_API_BASE_URL 설정과 네트워크 상태를 확인해 주세요.",
      field_errors: [],
      retryable: true,
      retry_after_seconds: null,
      http_status: 0,
      request_id: null,
    });
  }

  const text = await response.text();

  if (response.status === 204 || text.length === 0) {
    if (response.ok) {
      return undefined as T;
    }
    throw new ApiClientError({
      code: "UNKNOWN_ERROR",
      message: `요청이 실패했습니다. (HTTP ${response.status})`,
      field_errors: [],
      retryable: response.status >= 500,
      retry_after_seconds: null,
      http_status: response.status,
      request_id: null,
    });
  }

  let payload: unknown;
  try {
    payload = JSON.parse(text);
  } catch {
    payload = null;
  }

  if (response.ok && isSuccessEnvelope<T>(payload)) {
    return payload.data;
  }
  // 일부 실제 구현 라우터(partner.py)는 표준 봉투 없이 Pydantic 모델을 그대로 반환한다.
  if (response.ok) {
    return payload as T;
  }

  const errorBody = extractErrorBody(payload);
  // FastAPI가 매칭되는 라우트를 아예 찾지 못하면 앱 오류코드 없이 `{"detail":"Not Found"}`만
  // 돌려준다(app-level 404, 예: EXHIBITOR_NOT_FOUND와 구별됨) - 이 경우가 "관리자 API가 아직
  // 라우터로 등록되지 않았다"는 신호다. payload가 아예 없을 때(HTML 오류 페이지 등)도 같이 잡는다.
  const notImplemented =
    response.status === 404 &&
    (payload === null || (errorBody?.code === "UNKNOWN_ERROR" && errorBody.message === "Not Found"));
  throw new ApiClientError({
    code: notImplemented
      ? "NOT_IMPLEMENTED"
      : ((errorBody?.code as ApiErrorCode) ?? "UNKNOWN_ERROR"),
    message: notImplemented
      ? "이 관리자 API는 아직 백엔드에 구현되지 않았습니다."
      : (errorBody?.message ?? `요청이 실패했습니다. (HTTP ${response.status})`),
    field_errors: errorBody?.field_errors ?? [],
    retryable: errorBody?.retryable ?? response.status >= 500,
    retry_after_seconds: errorBody?.retry_after_seconds ?? null,
    http_status: response.status,
    request_id: extractRequestId(payload),
  });
}

export const apiGet = <T>(path: string, options?: RequestOptions): Promise<T> =>
  apiRequest<T>("GET", path, undefined, options);
export const apiPost = <T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> =>
  apiRequest<T>("POST", path, body, options);
export const apiPut = <T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> =>
  apiRequest<T>("PUT", path, body, options);
export const apiPatch = <T>(path: string, body?: unknown, options?: RequestOptions): Promise<T> =>
  apiRequest<T>("PATCH", path, body, options);
export const apiDelete = <T>(path: string, options?: RequestOptions): Promise<T> =>
  apiRequest<T>("DELETE", path, undefined, options);

// ===========================================================================
// 실제 구현됨 - apps/api/app/api/v1/routers/exhibitors.py (공개, 승인된 업체만)
// ===========================================================================

export function listPublicExhibitors(
  eventId: string,
  options?: RequestOptions,
): Promise<PublicExhibitorListResponse> {
  return apiGet<PublicExhibitorListResponse>(`/events/${encodeURIComponent(eventId)}/exhibitors`, {
    ...options,
    attachActor: false,
  });
}

export function getPublicExhibitor(
  exhibitorId: string,
  eventId?: string,
  options?: RequestOptions,
): Promise<PublicExhibitorDetail> {
  return apiGet<PublicExhibitorDetail>(`/exhibitors/${encodeURIComponent(exhibitorId)}`, {
    ...options,
    query: { event_id: eventId },
    attachActor: false,
  });
}

export function listPublicExhibitorProducts(
  exhibitorId: string,
  eventId?: string,
  options?: RequestOptions,
): Promise<PublicProductSummary[]> {
  return apiGet<PublicProductSummary[]>(
    `/exhibitors/${encodeURIComponent(exhibitorId)}/products`,
    { ...options, query: { event_id: eventId }, attachActor: false },
  );
}

export function getPublicBooth(
  boothId: string,
  options?: RequestOptions,
): Promise<PublicBoothDetail> {
  return apiGet<PublicBoothDetail>(`/booths/${encodeURIComponent(boothId)}`, {
    ...options,
    attachActor: false,
  });
}

// ===========================================================================
// 실제 구현됨 - apps/api/app/api/v1/routers/partner.py (08 28절)
// 보호 API는 Secure/HttpOnly 서버 세션으로 인증하며 호출자가 identity 헤더를 붙이지 않는다.
// ===========================================================================

/** 08 28.1절 - 공개(PUBLIC 등급) 프로파일 조회. 인증 불필요. */
export function getExhibitorProfile(
  exhibitorId: string,
  options?: RequestOptions,
): Promise<ExhibitorProfileRead> {
  return apiGet<ExhibitorProfileRead>(`/exhibitors/${encodeURIComponent(exhibitorId)}/profile`, {
    ...options,
    attachActor: false,
  });
}

/** 08 28.2절 - 업체 프로파일 수정. EXHIBITOR/OPERATOR/ADMIN 역할 검사가 백엔드에서 실제로
 * 수행된다(actor_user_id가 해당 업체 소속이어야 함, RESOURCE_FORBIDDEN 가능). */
export function updateExhibitorProfile(
  exhibitorId: string,
  body: ExhibitorProfileUpdate,
  options?: RequestOptions,
): Promise<ExhibitorProfileRead> {
  return apiPatch<ExhibitorProfileRead>(
    `/partner/exhibitors/${encodeURIComponent(exhibitorId)}/profile`,
    body,
    options,
  );
}

/** 08 28.3절 - 제품 등록. */
export function createProduct(
  body: ProductCreateRequest,
  options?: RequestOptions,
): Promise<ProductRead> {
  return apiPost<ProductRead>("/partner/products", body, options);
}

/** 08 28.4절 - 거래조건 등록 (전체 교체). */
export function upsertTradeConditions(
  productId: string,
  body: TradeConditionUpsert,
  options?: RequestOptions,
): Promise<TradeConditionRead> {
  return apiPut<TradeConditionRead>(
    `/partner/products/${encodeURIComponent(productId)}/trade-conditions`,
    body,
    options,
  );
}

/** 08 28.6절 - 검수 제출. 업체 담당자가 초안을 확정해 검수 대기열로 올린다. */
export function submitExhibitorForReview(
  exhibitorId: string,
  options?: RequestOptions,
): Promise<SubmitResponse> {
  return apiPost<SubmitResponse>(
    `/partner/exhibitors/${encodeURIComponent(exhibitorId)}/submit`,
    undefined,
    options,
  );
}

// ===========================================================================
// TODO: 미구현 - master-spec §40.9절 문서화된 경로, 백엔드 라우터 없음
// (.harness/decisions.md DECISION-005, backlog BACKEND-007 status: READY).
// 호출 시 FastAPI 전역 404 → ApiClientError(code: "NOT_IMPLEMENTED")로 던져진다.
// 화면은 이 오류를 그대로 사용자에게 보여줘야 한다(가짜 성공 표시 금지).
// ===========================================================================

/** TODO(BACKEND-007): GET /admin/exhibitors/review - 업체 검수 대기열 목록.
 * §44절 필수정보·승인상태 기준 필터를 지원해야 한다(review_status, event_id). */
export function listExhibitorsForReview(
  query: AdminExhibitorListQuery = {},
  options?: RequestOptions,
): Promise<AdminExhibitorListResponse> {
  return apiGet<AdminExhibitorListResponse>("/admin/exhibitors/review", {
    ...options,
    query: { ...query },
  });
}

/** TODO(BACKEND-007): 검수 대상 업체 1건의 상세(변경 전후 값·AI 추출 근거 포함) 조회.
 * §40.9절은 review 목록 경로만 명시하고 상세 경로는 문서화하지 않아 REST 관례를 따라
 * `/admin/exhibitors/review/{id}`로 추정했다 - 백엔드 확정 후 대조 필요. */
export function getExhibitorReviewDetail(
  exhibitorId: string,
  options?: RequestOptions,
): Promise<AdminExhibitorDetail> {
  return apiGet<AdminExhibitorDetail>(
    `/admin/exhibitors/review/${encodeURIComponent(exhibitorId)}`,
    options,
  );
}

/** TODO(BACKEND-007): POST /admin/exhibitors/{id}/approve */
export function approveExhibitor(
  exhibitorId: string,
  body: ApproveExhibitorRequest = {},
  options?: RequestOptions,
): Promise<ExhibitorDecisionResponse> {
  return apiPost<ExhibitorDecisionResponse>(
    `/admin/exhibitors/${encodeURIComponent(exhibitorId)}/approve`,
    body,
    options,
  );
}

/** TODO(BACKEND-007): POST /admin/exhibitors/{id}/reject. 작업 지시: "반려 시 사유 필수
 * 입력" - reason이 빈 문자열이면 네트워크 호출 전에 클라이언트에서 막는다(호출부 참고). */
export function rejectExhibitor(
  exhibitorId: string,
  body: RejectExhibitorRequest,
  options?: RequestOptions,
): Promise<ExhibitorDecisionResponse> {
  if (!body.reason || !body.reason.trim()) {
    throw new ApiClientError({
      code: "REJECT_REASON_REQUIRED",
      message: "반려 사유를 입력해 주세요.",
      field_errors: [{ field: "reason", reason: "required" }],
      retryable: false,
      retry_after_seconds: null,
      http_status: 0,
      request_id: null,
    });
  }
  return apiPost<ExhibitorDecisionResponse>(
    `/admin/exhibitors/${encodeURIComponent(exhibitorId)}/reject`,
    body,
    options,
  );
}

/** TODO(BACKEND-007): PATCH /admin/booths/{id}/status - 부스 운영상태 변경(OPEN/PAUSED/CLOSED).
 * apps/api/app/models/exhibitor.py의 booth.row_version 낙관적 잠금과 맞물릴 가능성이 높다 -
 * 백엔드 확정 후 If-Match 또는 row_version 필드 추가 여부 대조 필요. */
export function updateBoothStatus(
  boothId: string,
  body: BoothStatusUpdateRequest,
  options?: RequestOptions,
): Promise<AdminBoothListItem> {
  return apiPatch<AdminBoothListItem>(
    `/admin/booths/${encodeURIComponent(boothId)}/status`,
    body,
    options,
  );
}

/** TODO(BACKEND-007 범위 밖 - 문서화조차 안 됨): 부스 목록/등록. §40.9절에는 상태변경
 * 경로만 있다. REST 관례로 `/admin/booths`를 추정했다 - 백엔드 확정 후 대조 필요. */
export function listAdminBooths(
  eventId: string,
  options?: RequestOptions,
): Promise<AdminBoothListResponse> {
  return apiGet<AdminBoothListResponse>("/admin/booths", { ...options, query: { event_id: eventId } });
}

export function createAdminBooth(
  body: AdminBoothCreateRequest,
  options?: RequestOptions,
): Promise<AdminBoothListItem> {
  return apiPost<AdminBoothListItem>("/admin/booths", body, options);
}

/** TODO(BACKEND-007): GET /admin/analytics/searches */
export function getSearchAnalytics(
  eventId: string,
  options?: RequestOptions,
): Promise<SearchAnalyticsSummary> {
  return apiGet<SearchAnalyticsSummary>("/admin/analytics/searches", {
    ...options,
    query: { event_id: eventId },
  });
}

/** TODO(BACKEND-007): GET /admin/analytics/no-results */
export function getNoResultQueries(
  eventId: string,
  options?: RequestOptions,
): Promise<NoResultQueryResponse> {
  return apiGet<NoResultQueryResponse>("/admin/analytics/no-results", {
    ...options,
    query: { event_id: eventId },
  });
}

/** TODO(문서화조차 안 됨): A15 감사로그. audit.audit_log(apps/api/app/models/consent.py)
 * 테이블은 존재하지만 조회 API가 아직 없다 - 경로는 REST 관례 추정치다. */
export function listAuditLogs(
  query: AuditLogListQuery = {},
  options?: RequestOptions,
): Promise<AuditLogListResponse> {
  return apiGet<AuditLogListResponse>("/admin/audit-logs", { ...options, query: { ...query } });
}

/** TODO(문서화조차 안 됨): A01 행사 관리. core.event CRUD API가 아직 없다 - 경로는 REST
 * 관례 추정치다. */
export function listAdminEvents(options?: RequestOptions): Promise<AdminEventListResponse> {
  return apiGet<AdminEventListResponse>("/admin/events", options);
}

export function createAdminEvent(
  body: AdminEventCreateRequest,
  options?: RequestOptions,
): Promise<AdminEventListResponse> {
  return apiPost<AdminEventListResponse>("/admin/events", body, options);
}
