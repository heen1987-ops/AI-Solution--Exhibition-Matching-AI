/**
 * 키오스크 전용 API 클라이언트.
 *
 * 근거: apps/api/app/api/v1/routers/kiosk.py, apps/api/app/schemas/kiosk.py (정본 계약).
 * apps/user-web/lib/api-client.ts를 참고했지만 복사하지 않았다 - 키오스크에 필요한
 * 최소 함수(createKioskSession, kioskSearch, kioskHandoff, kioskClose, getKioskConfig)만
 * 둔다. 이 파일은 익명 세션만 다룬다: 쿠키/인증 헤더, 이름/전화번호/이메일 같은 개인
 * 식별 필드는 어디에도 없다.
 *
 * 백엔드가 아직 라우팅에 등록되지 않았더라도(apps/api/app/api/v1/api.py는 공유 파일이라
 * 이 트랙이 건드리지 않는다) 이 클라이언트는 문서화된 계약대로 실제 fetch 호출 코드를
 * 담는다 - Mock 없음.
 */

import type {
  ApiErrorBody,
  ApiSuccessEnvelope,
  KioskCloseResponse,
  KioskConfig,
  KioskHandoffResponse,
  KioskLanguage,
  KioskSearchResponse,
  KioskSession,
} from "./types";

const API_ORIGIN = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");
const API_V1_PREFIX = "/api/v1";

/** 이 클라이언트가 던지는 유일한 오류 타입. 화면은 `code`/`retryable`로 분기한다
 * (예: KIOSK_SESSION_EXPIRED -> /session-ended, 그 외 재시도 가능 오류 -> /network-error). */
export class KioskApiError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly retry_after_seconds: number | null;
  readonly http_status: number;

  constructor(info: {
    message: string;
    code: string;
    retryable: boolean;
    retry_after_seconds: number | null;
    http_status: number;
  }) {
    super(info.message);
    this.name = "KioskApiError";
    this.code = info.code;
    this.retryable = info.retryable;
    this.retry_after_seconds = info.retry_after_seconds;
    this.http_status = info.http_status;
  }
}

function buildUrl(path: string): string {
  const url = new URL(`${API_ORIGIN}${API_V1_PREFIX}${path}`, "http://localhost");
  return API_ORIGIN ? url.toString() : `${url.pathname}${url.search}`;
}

function extractErrorBody(payload: unknown): Partial<ApiErrorBody> | null {
  if (typeof payload !== "object" || payload === null) return null;
  const record = payload as Record<string, unknown>;
  const candidate = record.error ?? record.detail;
  if (candidate === undefined || candidate === null) return null;

  if (typeof candidate === "string") {
    return { code: "UNKNOWN_ERROR", message: candidate, field_errors: [] };
  }
  if (typeof candidate === "object") {
    const row = candidate as Record<string, unknown>;
    return {
      code: typeof row.code === "string" ? row.code : "UNKNOWN_ERROR",
      message: typeof row.message === "string" ? row.message : "요청을 처리하지 못했습니다.",
      retryable: typeof row.retryable === "boolean" ? row.retryable : false,
      retry_after_seconds:
        typeof row.retry_after_seconds === "number" ? row.retry_after_seconds : null,
    };
  }
  return null;
}

function isSuccessEnvelope<T>(payload: unknown): payload is ApiSuccessEnvelope<T> {
  return (
    typeof payload === "object" &&
    payload !== null &&
    (payload as Record<string, unknown>).success === true &&
    "data" in payload
  );
}

async function kioskRequest<T>(
  method: "GET" | "POST",
  path: string,
  body?: unknown,
): Promise<T> {
  const url = buildUrl(path);
  let response: Response;
  try {
    response = await fetch(url, {
      method,
      headers: {
        Accept: "application/json",
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      // 키오스크는 로그인 쿠키를 주고받지 않는다 - 완전 익명 세션이다.
      credentials: "omit",
      cache: "no-store",
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new KioskApiError({
      code: "NETWORK_ERROR",
      message: "행사 안내 서버에 연결할 수 없습니다. 네트워크 상태를 확인해 주세요.",
      retryable: true,
      retry_after_seconds: null,
      http_status: 0,
    });
  }

  const text = await response.text();
  let payload: unknown = null;
  if (text.length > 0) {
    try {
      payload = JSON.parse(text);
    } catch {
      payload = null;
    }
  }

  if (response.ok && isSuccessEnvelope<T>(payload)) {
    return payload.data;
  }

  const errorBody = extractErrorBody(payload);
  throw new KioskApiError({
    code: errorBody?.code ?? "UNKNOWN_ERROR",
    message: errorBody?.message ?? `요청을 처리하지 못했습니다. (HTTP ${response.status})`,
    retryable: errorBody?.retryable ?? response.status >= 500,
    retry_after_seconds: errorBody?.retry_after_seconds ?? null,
    http_status: response.status,
  });
}

/** K01 언어선택 이전에도 호출 가능 - 지원 언어·세션 타임아웃·테마를 읽어온다. */
export function getKioskConfig(kioskId: string): Promise<KioskConfig> {
  return kioskRequest<KioskConfig>("GET", `/kiosk/config/${encodeURIComponent(kioskId)}`);
}

/** K01 언어선택 확정 시 익명 세션을 새로 만든다. 이름/연락처를 받지 않는다. */
export function createKioskSession(
  kioskId: string,
  language: KioskLanguage,
): Promise<KioskSession> {
  return kioskRequest<KioskSession>("POST", "/kiosk/sessions", {
    kiosk_id: kioskId,
    language,
  });
}

/** K02/K04 자연어 또는 카테고리 검색. 세션이 만료되었으면 KioskApiError(code:
 * "KIOSK_SESSION_EXPIRED")를 던진다 - 호출측은 /session-ended로 이동해야 한다. */
export function kioskSearch(
  sessionId: string,
  params: { query?: string; categoryCodes?: string[]; limit?: number },
): Promise<KioskSearchResponse> {
  return kioskRequest<KioskSearchResponse>(
    "POST",
    `/kiosk/sessions/${encodeURIComponent(sessionId)}/search`,
    {
      query: params.query ?? "",
      category_codes: params.categoryCodes ?? [],
      limit: params.limit ?? 12,
    },
  );
}

/** 결과 중 선택한 업체를 서명된 QR 인계 토큰으로 만든다. 페이로드에 개인정보가 없다. */
export function kioskHandoff(
  sessionId: string,
  selectedResultIds: string[],
): Promise<KioskHandoffResponse> {
  return kioskRequest<KioskHandoffResponse>(
    "POST",
    `/kiosk/sessions/${encodeURIComponent(sessionId)}/handoff`,
    { selected_result_ids: selectedResultIds },
  );
}

/** 이용 종료·자동 초기화 시 서버 세션을 명시적으로 닫는다(베스트에포트 - 실패해도
 * 클라이언트는 항상 로컬 상태를 지운다). */
export function kioskClose(sessionId: string): Promise<KioskCloseResponse> {
  return kioskRequest<KioskCloseResponse>(
    "POST",
    `/kiosk/sessions/${encodeURIComponent(sessionId)}/close`,
  );
}
