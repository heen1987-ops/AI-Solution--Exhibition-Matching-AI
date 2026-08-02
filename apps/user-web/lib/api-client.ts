/**
 * 백주 AI 셀파 프론트엔드 공용 API 클라이언트.
 *
 * 근거 문서
 * ---------
 * - docs/frontend-backend-ai-interface-spec.md
 *     4.1절(기본 경로 `/api/v1`, 인증 - Secure HttpOnly 세션/게스트 쿠키, 멱등키·If-Match),
 *     4.2절(요청 헤더 - X-Request-ID, Idempotency-Key, Accept-Language, If-Match),
 *     4.3~4.4절(성공/오류 응답 봉투), 6절(화면·API 매핑), 7~17절(각 엔드포인트 경로) -
 *     이 파일에 정의된 모든 함수의 1차 근거.
 * - backend/app/api/v1/routers/{profile,consent,recommendations,meetings}.py - 이미
 *   구현된 실제 라우트 경로. 도메인이 겹치는 함수는 이 라우터들이 실제로 등록한 경로
 *   문자열을 그대로 사용했다 (아래 각 섹션 주석에 라우터 파일 경로를 남겼다).
 *
 * 스코프 메모
 * -----------
 * - 이 파일과 `frontend/lib/types.ts`는 공용 aggregator 파일이다. 다른 화면 에이전트는
 *   여기서 import만 하고 이 두 파일을 직접 수정하지 않는다 (작업 지시 원칙).
 * - 오프라인 큐잉·재전송(11.4절)은 이 클라이언트가 구현하지 않는다. 이 클라이언트는
 *   네트워크 실패를 `ApiClientError(code: "NETWORK_ERROR", retryable: true)`로 일관되게
 *   던지기만 하고, 로컬 큐 적재·재전송 타이밍은 QR 체크인·피드백·상담요청처럼 오프라인
 *   허용이 필요한 화면 훅이 이 클라이언트 위에 얹어 구현한다.
 * - `GET /api/v1/ontology/*` 계열은 (아직) 이 파일이 쓰는 표준 성공/오류 봉투를 따르지
 *   않는 기존 구현(backend/app/api/v1/endpoints/ontology.py, 원시 dict 응답)이라
 *   의도적으로 이 클라이언트 범위 밖에 둔다. 필요한 화면 에이전트는 별도로 얇은 fetch를
 *   작성하거나, 이후 온톨로지 응답이 표준 봉투로 통일되면 이 파일에 추가한다.
 */

import type {
  ApiErrorBody,
  ApiErrorCode,
  ApiSuccessEnvelope,
  AttributesPatchRequest,
  AttributesPatchResponse,
  AvailabilityListResponse,
  AvailabilityQuery,
  BoothDetailQuery,
  BoothDetailResponse,
  BuyerNeedsRequest,
  BuyerNeedsResponse,
  CheckInRequest,
  CheckInResponse,
  CompletenessResponse,
  ConsentsGetResponse,
  ConsentsPutRequest,
  ConsentsPutResponse,
  ConversationMessageRequest,
  ConversationMessageResponse,
  ConversationStartRequest,
  ConversationStartResponse,
  ConsumerPreferencesRequest,
  ConsumerPreferencesResponse,
  CreateSessionRequest,
  CreateSessionResponse,
  FavoriteCreateRequest,
  FavoriteListQuery,
  FavoriteListResponse,
  FavoriteView,
  FeedbackRequest,
  FeedbackResponse,
  FieldError,
  ExtractionDecisionRequest,
  ExtractionDecisionResponse,
  GoalsUpdateRequest,
  GoalsUpdateResponse,
  InteractionBatchResponse,
  InteractionEventIn,
  InteractionEventResult,
  MeetingCreateRequest,
  MeetingListQuery,
  MeetingListResponse,
  MeetingOutcomeRequest,
  MeetingOutcomeResponse,
  MeetingRequestPatch,
  MeetingResponse,
  PartnerBuyerSummaryResponse,
  PartnerDecisionRequest,
  PartnerMeetingListQuery,
  PartnerMeetingListResponse,
  PhoneChallengeRequest,
  PhoneChallengeResponse,
  PhoneChallengeVerifyRequest,
  PhoneChallengeVerifyResponse,
  PrivacyRequestCreate,
  PrivacyRequestListResponse,
  PrivacyRequestView,
  ProductDetailResponse,
  ProfileGeneralPatchRequest,
  ProfileGeneralPatchResponse,
  ProfileVersionsResponse,
  ProfileView,
  RecommendationListQuery,
  RecommendationRequest,
  RecommendationResponse,
  RecommendationSessionItemsResponse,
  RouteCreateRequest,
  RouteResponse,
  SessionMergeRequest,
  SessionMergeResponse,
  UserTypeUpdateRequest,
  UserTypeUpdateResponse,
  VisitPlanRequest,
  VisitPlanResponse,
  WebSearchRequest,
  WebSearchResponse,
} from "./types";

// ---------------------------------------------------------------------------
// 기본 설정
// ---------------------------------------------------------------------------

/** 백엔드 오리진. `/api/v1` 접두사는 이 클라이언트가 덧붙인다 (4.1절). */
const API_ORIGIN = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");
const API_V1_PREFIX = "/api/v1";

type HttpMethod = "GET" | "POST" | "PUT" | "PATCH" | "DELETE";

export interface RequestOptions {
  /** URL 쿼리스트링. `undefined`/`null` 값은 제외된다. */
  query?: Record<string, string | number | boolean | undefined | null>;
  /** 외부 효과가 있는 요청(POST 등)의 중복 방지 키 (4.2절). */
  idempotencyKey?: string;
  /** 동시수정 검사용 낙관적 잠금 값 (4.2절, 예: `"profile-v4"`). */
  ifMatch?: string;
  /** 생략하면 자동 생성된다 (4.2절 `X-Request-ID`). */
  requestId?: string;
  signal?: AbortSignal;
}

// ---------------------------------------------------------------------------
// 오류 타입
// ---------------------------------------------------------------------------

export interface ApiClientErrorInfo {
  code: ApiErrorCode;
  message: string;
  field_errors: FieldError[];
  retryable: boolean;
  retry_after_seconds: number | null;
  http_status: number;
  request_id: string | null;
}

/** 이 클라이언트가 던지는 유일한 오류 타입. 화면은 `error.code`로 19절 표의 UI 처리를
 * 분기하고, `error.field_errors`로 폼 필드별 오류를 표시한다. */
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

// ---------------------------------------------------------------------------
// 내부 유틸리티
// ---------------------------------------------------------------------------

/** `X-Request-ID`, `Idempotency-Key`, `client_event_id` 기본값 등에 두루 쓰는 UUID 생성기.
 * `crypto.randomUUID`가 없는 구형 런타임(구형 iOS Safari 등, 13.1절 반응형 지원 폭 고려)을
 * 위한 대체 구현을 포함한다. */
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
  // API_ORIGIN이 빈 문자열이면(같은 오리진에서 서비스하는 배포 형태) 상대경로로 되돌린다.
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

/** FastAPI 기본 오류 응답(전역 예외 핸들러 도입 전)까지 폭넓게 흡수한다.
 * 지원하는 모양:
 *   1) 4.4절 정식 오류 봉투: `{success:false, error:{code,message,...}}`
 *   2) 이 저장소 라우터들이 실제로 내보내는 `HTTPException(detail={code,message,...})`
 *   3) FastAPI 자체 422 검증 오류: `{detail: [{loc, msg, type}, ...]}`
 *   4) FastAPI 자체 404 등 단순 문자열: `{detail: "Not Found"}`
 */
function extractErrorBody(payload: unknown): Partial<ApiErrorBody> | null {
  if (typeof payload !== "object" || payload === null) return null;
  const record = payload as Record<string, unknown>;
  const candidate = record.error ?? record.detail;
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
  if (options.ifMatch) headers["If-Match"] = options.ifMatch;

  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers,
      // BFF와 같은 오리진에서 Secure HttpOnly 세션/게스트 쿠키를 주고받는다 (4.1절).
      credentials: "include",
      body: body === undefined ? undefined : JSON.stringify(body),
      signal: options.signal,
    });
  } catch {
    throw new ApiClientError({
      code: "NETWORK_ERROR",
      message: "서버에 연결할 수 없습니다. 네트워크 상태를 확인해 주세요.",
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

  const errorBody = extractErrorBody(payload);
  throw new ApiClientError({
    code: (errorBody?.code as ApiErrorCode) ?? "UNKNOWN_ERROR",
    message: errorBody?.message ?? `요청이 실패했습니다. (HTTP ${response.status})`,
    field_errors: errorBody?.field_errors ?? [],
    retryable: errorBody?.retryable ?? response.status >= 500,
    retry_after_seconds: errorBody?.retry_after_seconds ?? null,
    http_status: response.status,
    request_id: extractRequestId(payload),
  });
}

// 화면 에이전트가 이 파일에 없는 엔드포인트를 임시로 호출해야 할 때 쓰는 저수준 헬퍼.
// (신규 엔드포인트는 이 파일에 정식으로 추가하는 것을 우선한다 - 공용 파일 통합 정책 참고.)
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

/** Anonymous GUEST_WEB search. It uses only the approved public catalog and never requires login. */
export function searchApprovedCatalog(
  request: WebSearchRequest,
  options?: RequestOptions,
): Promise<WebSearchResponse> {
  return apiPost<WebSearchResponse>(
    "/search",
    {
      ...request,
      channel: "WEB",
      category_codes: request.category_codes ?? [],
      limit: request.limit ?? 12,
    },
    options,
  );
}

// ===========================================================================
// 7절 세션·인증
// ===========================================================================

/** U-01 시작. 익명 게스트 세션·방문 세션·최소 프로파일을 함께 생성한다 (7.1절).
 * 서버가 서명된 guest cookie를 설정하므로, 응답의 `guest_session_id`는 화면 표시나
 * 로컬 상태 키로만 쓰고 재사용 가능한 인증 토큰처럼 다루지 않는다. */
export function createProfileSession(
  request: CreateSessionRequest,
  options?: RequestOptions,
): Promise<CreateSessionResponse> {
  return apiPost<CreateSessionResponse>("/sessions", request, options);
}

/**
 * 7.2절 휴대전화 인증. TODO(인증 도메인 상세설계 확정 후 대조): 요청·응답 필드는
 * `frontend/lib/types.ts`의 해당 타입 주석대로 잠정 계약이다.
 */
export function requestPhoneChallenge(
  request: PhoneChallengeRequest,
  options?: RequestOptions,
): Promise<PhoneChallengeResponse> {
  return apiPost<PhoneChallengeResponse>("/auth/phone/challenges", request, options);
}

export function verifyPhoneChallenge(
  challengeId: string,
  request: PhoneChallengeVerifyRequest,
  options?: RequestOptions,
): Promise<PhoneChallengeVerifyResponse> {
  return apiPost<PhoneChallengeVerifyResponse>(
    `/auth/phone/challenges/${encodeURIComponent(challengeId)}/verify`,
    request,
    options,
  );
}

/** 휴대전화 인증 성공 후 익명 저장·프로파일·일정을 계정에 합칠지 명시적으로 확인한다. */
export function mergeCurrentSession(
  request: SessionMergeRequest,
  options?: RequestOptions,
): Promise<SessionMergeResponse> {
  return apiPost<SessionMergeResponse>("/sessions/current/merge", request, options);
}

// ===========================================================================
// 7.4절 동의·개인정보 권리 (U-03, U-22)
// backend/app/api/v1/routers/consent.py 실제 경로.
// ===========================================================================

export function putConsents(
  request: ConsentsPutRequest,
  options?: RequestOptions,
): Promise<ConsentsPutResponse> {
  return apiPut<ConsentsPutResponse>("/consents/me", request, options);
}

export function getConsents(options?: RequestOptions): Promise<ConsentsGetResponse> {
  return apiGet<ConsentsGetResponse>("/consents/me", options);
}

export function createPrivacyRequest(
  request: PrivacyRequestCreate,
  options?: RequestOptions,
): Promise<PrivacyRequestView> {
  return apiPost<PrivacyRequestView>("/privacy-requests", request, options);
}

export function listPrivacyRequests(
  query?: { cursor?: string; limit?: number },
  options?: RequestOptions,
): Promise<PrivacyRequestListResponse> {
  return apiGet<PrivacyRequestListResponse>("/privacy-requests", { ...options, query });
}

// ===========================================================================
// 8절·14절·07-26절 프로파일 온보딩 (U-02~U-07, U-20, U-22)
// backend/app/api/v1/routers/profile.py 실제 경로.
// ===========================================================================

/**
 * U-02 사용자 유형 선택. 와이어프레임 5.1절의 `PATCH /profile-sessions/{id}`에 대응하는
 * 실제 계약은 인터페이스 명세 7.3절의 `PATCH /profiles/me/user-type`이다(문서 우선순위:
 * 인터페이스 명세 > 와이어프레임). 함수명은 작업 지시가 지정한 `patchProfileSession`을
 * 그대로 쓴다.
 */
export function patchProfileSession(
  request: UserTypeUpdateRequest,
  options?: RequestOptions,
): Promise<UserTypeUpdateResponse> {
  return apiPatch<UserTypeUpdateResponse>("/profiles/me/user-type", request, options);
}

/**
 * U-04~U-07 온보딩 답변. 와이어프레임 5.1절은 이 네 화면을 모두 `POST /answers`로
 * 뭉뚱그리지만, 인터페이스 명세 8절은 목적·취향·바이어조건·방문계획을 서로 다른 PUT
 * 엔드포인트로 정의한다(우선순위: 인터페이스 명세). 이 함수는 `step` 판별값으로 실제
 * 엔드포인트에 위임하면서도 작업 지시가 지정한 `postAnswers`라는 단일 진입점을 유지한다.
 */
export function postAnswers(
  step: { step: "GOALS"; data: GoalsUpdateRequest },
  options?: RequestOptions,
): Promise<GoalsUpdateResponse>;
export function postAnswers(
  step: { step: "CONSUMER_PREFERENCES"; data: ConsumerPreferencesRequest },
  options?: RequestOptions,
): Promise<ConsumerPreferencesResponse>;
export function postAnswers(
  step: { step: "BUYER_NEEDS"; data: BuyerNeedsRequest },
  options?: RequestOptions,
): Promise<BuyerNeedsResponse>;
export function postAnswers(
  step: { step: "VISIT_PLAN"; data: VisitPlanRequest },
  options?: RequestOptions,
): Promise<VisitPlanResponse>;
export function postAnswers(
  step:
    | { step: "GOALS"; data: GoalsUpdateRequest }
    | { step: "CONSUMER_PREFERENCES"; data: ConsumerPreferencesRequest }
    | { step: "BUYER_NEEDS"; data: BuyerNeedsRequest }
    | { step: "VISIT_PLAN"; data: VisitPlanRequest },
  options: RequestOptions = {},
): Promise<
  GoalsUpdateResponse | ConsumerPreferencesResponse | BuyerNeedsResponse | VisitPlanResponse
> {
  switch (step.step) {
    case "GOALS":
      return apiPut<GoalsUpdateResponse>("/profiles/me/goals", step.data, options);
    case "CONSUMER_PREFERENCES":
      return apiPut<ConsumerPreferencesResponse>(
        "/profiles/me/consumer-preferences",
        step.data,
        options,
      );
    case "BUYER_NEEDS":
      return apiPut<BuyerNeedsResponse>("/profiles/me/buyer-needs", step.data, options);
    case "VISIT_PLAN":
      return apiPut<VisitPlanResponse>("/visit-sessions/current/plan", step.data, options);
    default: {
      const exhaustive: never = step;
      throw new Error(`알 수 없는 온보딩 단계입니다: ${JSON.stringify(exhaustive)}`);
    }
  }
}

/** U-20 추천 조건 수정. 14절 add/remove 패치. */
export function updateProfilePreferences(
  request: ProfileGeneralPatchRequest,
  options?: RequestOptions,
): Promise<ProfileGeneralPatchResponse> {
  return apiPatch<ProfileGeneralPatchResponse>("/profiles/me", request, options);
}

/** 07 26.2절 범용 온톨로지 속성 upsert/remove. */
export function patchProfileAttributes(
  request: AttributesPatchRequest,
  options?: RequestOptions,
): Promise<AttributesPatchResponse> {
  return apiPatch<AttributesPatchResponse>("/profiles/me/attributes", request, options);
}

export function getProfile(options?: RequestOptions): Promise<ProfileView> {
  return apiGet<ProfileView>("/profiles/me", options);
}

export function getProfileCompleteness(options?: RequestOptions): Promise<CompletenessResponse> {
  return apiGet<CompletenessResponse>("/profiles/me/completeness", options);
}

export function getProfileVersions(
  query?: { cursor?: string; limit?: number },
  options?: RequestOptions,
): Promise<ProfileVersionsResponse> {
  return apiGet<ProfileVersionsResponse>("/profiles/me/versions", { ...options, query });
}

// ===========================================================================
// 19단계 대화형 프로파일링
// backend/app/api/v1/routers/conversation.py 실제 경로.
// ===========================================================================

export function startConversation(
  request: ConversationStartRequest = { language: "ko" },
  options?: RequestOptions,
): Promise<ConversationStartResponse> {
  return apiPost<ConversationStartResponse>("/conversations", request, options);
}

export function sendConversationMessage(
  conversationId: string,
  request: ConversationMessageRequest,
  options?: RequestOptions,
): Promise<ConversationMessageResponse> {
  return apiPost<ConversationMessageResponse>(
    `/conversations/${encodeURIComponent(conversationId)}/messages`,
    request,
    options,
  );
}

export function decideConversationExtraction(
  conversationId: string,
  extractionId: string,
  request: ExtractionDecisionRequest,
  options?: RequestOptions,
): Promise<ExtractionDecisionResponse> {
  return apiPost<ExtractionDecisionResponse>(
    `/conversations/${encodeURIComponent(conversationId)}/extractions/${encodeURIComponent(extractionId)}/decision`,
    request,
    options,
  );
}

// ===========================================================================
// 9절 추천 (U-08, U-09)
// backend/app/api/v1/routers/recommendations.py 실제 경로.
// ===========================================================================

/** 새 추천 실행을 명시적으로 생성한다 (9.1절 `POST /recommendations`).
 * 외부 효과가 있는 요청이므로 멱등키를 자동 생성해 중복 생성을 막는다. */
export function createRecommendationSession(
  request: RecommendationRequest,
  options: RequestOptions = {},
): Promise<RecommendationResponse> {
  const idempotencyKey = options.idempotencyKey ?? generateClientId();
  return apiPost<RecommendationResponse>("/recommendations", request, {
    ...options,
    idempotencyKey,
  });
}

/** U-08 홈. 유효한 추천 세션을 재사용하거나 필요 시 서버가 재정렬한다 (9.3절).
 * 9.3절은 홈 전용 필드를 예시로 제공하지 않아, 9.1절과 같은 추천 세션 형태
 * (`RecommendationResponse`)를 반환한다고 본다. */
export function getHomeRecommendations(
  options?: RequestOptions,
): Promise<RecommendationResponse> {
  return apiGet<RecommendationResponse>("/home", options);
}

/** U-09 추천 전체 (9.4절 `GET /recommendation-sessions/{id}/items`). */
export function getRecommendationSessionItems(
  recommendationSessionId: string,
  query?: RecommendationListQuery,
  options?: RequestOptions,
): Promise<RecommendationSessionItemsResponse> {
  return apiGet<RecommendationSessionItemsResponse>(
    `/recommendation-sessions/${encodeURIComponent(recommendationSessionId)}/items`,
    { ...options, query },
  );
}

/**
 * 추천 조회 통합 진입점. `recommendationSessionId`를 주지 않으면 U-08 홈(`GET /home`)을,
 * 주면 U-09 추천 전체 목록(`GET /recommendation-sessions/{id}/items`)을 호출한다.
 */
export function getRecommendations(
  params: { recommendationSessionId: string } & RecommendationListQuery,
  options?: RequestOptions,
): Promise<RecommendationSessionItemsResponse>;
export function getRecommendations(
  params?: undefined,
  options?: RequestOptions,
): Promise<RecommendationResponse>;
export function getRecommendations(
  params?: ({ recommendationSessionId: string } & RecommendationListQuery) | undefined,
  options: RequestOptions = {},
): Promise<RecommendationSessionItemsResponse | RecommendationResponse> {
  if (params?.recommendationSessionId) {
    const { recommendationSessionId, ...query } = params;
    return getRecommendationSessionItems(recommendationSessionId, query, options);
  }
  return getHomeRecommendations(options);
}

// ===========================================================================
// 16절 행동 이벤트 (인터랙션)
// backend/app/api/v1/routers/recommendations.py의 `/interactions/batch`.
// ===========================================================================

/** 여러 이벤트를 한 번에 전송한다 (16.1절). 배치 자체가 외부 효과 저장 요청이므로
 * 멱등키를 자동 생성한다. */
export function postInteractions(
  events: InteractionEventIn[],
  options: RequestOptions = {},
): Promise<InteractionBatchResponse> {
  const idempotencyKey = options.idempotencyKey ?? generateClientId();
  return apiPost<InteractionBatchResponse>(
    "/interactions/batch",
    { events },
    { ...options, idempotencyKey },
  );
}

/** 단일 이벤트 전송 편의 함수. 내부적으로 크기 1인 배치를 호출한다. */
export async function postInteraction(
  event: InteractionEventIn,
  options?: RequestOptions,
): Promise<InteractionEventResult> {
  const response = await postInteractions([event], options);
  const [result] = response.results;
  if (!result) {
    throw new ApiClientError({
      code: "UNKNOWN_ERROR",
      message: "이벤트 처리 결과를 받지 못했습니다.",
      field_errors: [],
      retryable: true,
      retry_after_seconds: null,
      http_status: 0,
      request_id: null,
    });
  }
  return result;
}

// ===========================================================================
// 10절 전시정보 (U-10, U-11)
// TODO(공개 booths/products 라우터 확정 후 대조).
// ===========================================================================

export function getBooth(
  boothId: string,
  query?: BoothDetailQuery,
  options?: RequestOptions,
): Promise<BoothDetailResponse> {
  return apiGet<BoothDetailResponse>(`/booths/${encodeURIComponent(boothId)}`, {
    ...options,
    query: { match_result_id: query?.matchResultId, ...options?.query },
  });
}

export function getProduct(
  productId: string,
  options?: RequestOptions,
): Promise<ProductDetailResponse> {
  return apiGet<ProductDetailResponse>(`/products/${encodeURIComponent(productId)}`, options);
}

// ===========================================================================
// 11절 저장·경로 (U-13, U-19)
// TODO(favorites/routes 라우터 확정 후 대조).
// ===========================================================================

export function createFavorite(
  request: FavoriteCreateRequest,
  options?: RequestOptions,
): Promise<FavoriteView> {
  return apiPost<FavoriteView>("/favorites", request, options);
}

export function deleteFavorite(favoriteId: string, options?: RequestOptions): Promise<void> {
  return apiDelete<void>(`/favorites/${encodeURIComponent(favoriteId)}`, options);
}

export function listFavorites(
  query?: FavoriteListQuery,
  options?: RequestOptions,
): Promise<FavoriteListResponse> {
  return apiGet<FavoriteListResponse>("/favorites", { ...options, query });
}

export function createRoute(
  request: RouteCreateRequest,
  options?: RequestOptions,
): Promise<RouteResponse> {
  return apiPost<RouteResponse>("/routes", request, options);
}

export function recalculateRoute(
  routeId: string,
  options?: RequestOptions,
): Promise<RouteResponse> {
  return apiPost<RouteResponse>(`/routes/${encodeURIComponent(routeId)}/recalculate`, undefined, options);
}

// ===========================================================================
// 12절 상담 (U-14, U-15, E-02~E-04)
// backend/app/api/v1/routers/meetings.py 실제 경로.
// ===========================================================================

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

/** U-14 상담 요청 (12.3절). 외부 상대에게 전달되는 요청이라 멱등키를 자동 생성해
 * 중복 제출을 막는다 - 와이어프레임 U-14절 "전송 중 버튼을 잠그고 멱등 키로 중복 요청을
 * 막는다"와 대응한다. */
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

/**
 * U-15 상담 상태 화면에서 바이어가 수행하는 상태 전이. 와이어프레임 5.1절의
 * `PATCH /meeting-requests/{id}`에 대응하는 실제 엔드포인트는 인터페이스 명세 12절이
 * 정의한 두 개의 POST 엔드포인트(취소/응답)다(우선순위: 인터페이스 명세). 이 함수는
 * `patch.kind`로 실제 엔드포인트에 위임하면서 작업 지시가 지정한 `patchMeetingRequest`
 * 이름을 유지한다.
 */
export function patchMeetingRequest(
  meetingId: string,
  patch: MeetingRequestPatch,
  options?: RequestOptions,
): Promise<MeetingResponse> {
  const id = encodeURIComponent(meetingId);
  if (patch.kind === "CANCEL") {
    return apiPost<MeetingResponse>(`/meetings/${id}/cancel`, patch.data, options);
  }
  return apiPost<MeetingResponse>(`/meetings/${id}/respond`, patch.data, options);
}

// --- 참가업체 포털 (E-02~E-04) ---------------------------------------------

export function listPartnerMeetings(
  query?: PartnerMeetingListQuery,
  options?: RequestOptions,
): Promise<PartnerMeetingListResponse> {
  return apiGet<PartnerMeetingListResponse>("/partner/meetings", { ...options, query });
}

export function getPartnerMeetingBuyerSummary(
  meetingId: string,
  options?: RequestOptions,
): Promise<PartnerBuyerSummaryResponse> {
  return apiGet<PartnerBuyerSummaryResponse>(
    `/partner/meetings/${encodeURIComponent(meetingId)}/buyer-summary`,
    options,
  );
}

/** E-02 상담 요청 목록에서 업체가 수락/거절/시간 재제안한다 (12.4절). */
export function decidePartnerMeeting(
  meetingId: string,
  request: PartnerDecisionRequest,
  options?: RequestOptions,
): Promise<MeetingResponse> {
  return apiPost<MeetingResponse>(
    `/partner/meetings/${encodeURIComponent(meetingId)}/decision`,
    request,
    options,
  );
}

/** E-04 상담결과·후속조치. */
export function submitMeetingOutcome(
  meetingId: string,
  request: MeetingOutcomeRequest,
  options?: RequestOptions,
): Promise<MeetingOutcomeResponse> {
  return apiPost<MeetingOutcomeResponse>(
    `/partner/meetings/${encodeURIComponent(meetingId)}/outcome`,
    request,
    options,
  );
}

// ===========================================================================
// 13절 QR 체크인·피드백 (U-16, U-17)
// TODO(check-ins/feedback 라우터 확정 후 대조).
// ===========================================================================

/** U-16 QR 체크인. 오프라인 재전송을 고려해 멱등키를 자동 생성한다 (13.1절). */
export function postCheckIn(
  request: CheckInRequest,
  options: RequestOptions = {},
): Promise<CheckInResponse> {
  const idempotencyKey = options.idempotencyKey ?? generateClientId();
  return apiPost<CheckInResponse>("/check-ins", request, { ...options, idempotencyKey });
}

/** U-17 피드백. */
export function postFeedback(
  request: FeedbackRequest,
  options?: RequestOptions,
): Promise<FeedbackResponse> {
  return apiPost<FeedbackResponse>("/feedback", request, options);
}
