/**
 * 브라우저 로컬 인증 상태 힌트.
 *
 * 근거 문서
 * ---------
 * - docs/frontend-backend-ai-interface-spec.md 5절(권한·스코프) - "로컬 저장 | GUEST 가능",
 *   "서버 저장·일정 | PHONE_VERIFIED" - GUEST와 PHONE_VERIFIED/ACCOUNT_AUTHENTICATED를 구분해야
 *   하는 화면(U-18 일정, U-19 저장, U-22 동의·권리)의 1차 근거.
 * - frontend/lib/types.ts의 `PhoneChallengeVerifyResponse.authentication_state`
 *   ("GUEST" | "PHONE_VERIFIED" | "ACCOUNT_AUTHENTICATED") 값 정의를 그대로 재사용한다.
 *
 * 이 모듈이 하는 일과 하지 않는 일
 * --------------------------------
 * 실제 인증 판정은 서버가 Secure HttpOnly 세션/게스트 쿠키로 수행한다(이 저장소 범위 밖).
 * 이 모듈은 그 판정 결과를 브라우저에 "힌트"로만 캐시해 화면이 매번 API를 호출해보지 않고도
 * 인증 유도 UI를 먼저 보여줄지 판단하게 돕는다 - 신뢰의 원천이 아니다. 그래서 화면은 이 값과
 * 무관하게 API가 실제로 `AUTH_REQUIRED`/`SESSION_EXPIRED`를 반환하면 이 힌트를 GUEST로
 * 되돌리고 인증 유도 UI를 다시 보여줘야 한다(각 화면의 오류 처리 참고).
 */

export type AuthenticationState = "GUEST" | "PHONE_VERIFIED" | "ACCOUNT_AUTHENTICATED";

export interface StoredAuthState {
  state: AuthenticationState;
  user_id: string | null;
  updated_at: string;
}

const STORAGE_KEY = "backju:auth_state:v1";
const EVENT_NAME = "backju:auth-state-changed";

const DEFAULT_STATE: StoredAuthState = {
  state: "GUEST",
  user_id: null,
  updated_at: new Date(0).toISOString(),
};

type VerifiedServerSession = {
  csrf_token: string;
  principal: { subject_id: string };
};

let runtimeCsrfToken: string | null = null;
let csrfRefresh: Promise<string | null> | null = null;
const API_ORIGIN = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");

function authApiUrl(path: string): string {
  return `${API_ORIGIN}/api/v1${path}`;
}

export function isAuthenticationState(value: unknown): value is AuthenticationState {
  return value === "GUEST" || value === "PHONE_VERIFIED" || value === "ACCOUNT_AUTHENTICATED";
}

function safeParse(raw: string | null): StoredAuthState | null {
  if (!raw) return null;
  try {
    const parsed = JSON.parse(raw) as Partial<StoredAuthState>;
    if (!isAuthenticationState(parsed.state)) return null;
    return {
      state: parsed.state,
      user_id: typeof parsed.user_id === "string" ? parsed.user_id : null,
      updated_at: typeof parsed.updated_at === "string" ? parsed.updated_at : new Date().toISOString(),
    };
  } catch {
    return null;
  }
}

export function getAuthState(): StoredAuthState {
  if (typeof window === "undefined") return DEFAULT_STATE;
  return safeParse(window.localStorage.getItem(STORAGE_KEY)) ?? DEFAULT_STATE;
}

export function setAuthState(state: AuthenticationState, userId?: string | null): void {
  if (typeof window === "undefined") return;
  const previous = getAuthState();
  const value: StoredAuthState = {
    state,
    user_id: userId !== undefined ? userId : previous.user_id,
    updated_at: new Date().toISOString(),
  };
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(value));
  window.dispatchEvent(new Event(EVENT_NAME));
}

export function getRuntimeCsrfToken(): string | null {
  return runtimeCsrfToken;
}

export function setRuntimeCsrfToken(token: string | null): void {
  runtimeCsrfToken = token;
}

export function applyVerifiedSession(session: VerifiedServerSession): void {
  runtimeCsrfToken = session.csrf_token;
  setAuthState("ACCOUNT_AUTHENTICATED", session.principal.subject_id);
}

/** Rehydrate the non-persistent CSRF token from the verified HttpOnly session. */
export async function ensureRuntimeCsrfToken(): Promise<string | null> {
  if (runtimeCsrfToken) return runtimeCsrfToken;
  if (typeof window === "undefined" || getAuthState().state !== "ACCOUNT_AUTHENTICATED") {
    return null;
  }
  if (!csrfRefresh) {
    csrfRefresh = fetch(authApiUrl("/auth/session"), {
      credentials: "include",
      headers: { Accept: "application/json" },
      cache: "no-store",
    })
      .then(async (response) => {
        if (!response.ok) {
          resetAuthStateToGuest();
          return null;
        }
        const session = (await response.json()) as VerifiedServerSession;
        applyVerifiedSession(session);
        return runtimeCsrfToken;
      })
      .catch(() => null)
      .finally(() => {
        csrfRefresh = null;
      });
  }
  return csrfRefresh;
}

/** API가 `AUTH_REQUIRED`/`SESSION_EXPIRED`를 반환했을 때 로컬 힌트를 되돌리기 위한 헬퍼. */
export function resetAuthStateToGuest(): void {
  if (typeof window === "undefined") return;
  runtimeCsrfToken = null;
  window.localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify({ state: "GUEST", user_id: null, updated_at: new Date().toISOString() }),
  );
  window.dispatchEvent(new Event(EVENT_NAME));
}

export function isAtLeastPhoneVerified(state: AuthenticationState): boolean {
  return state === "PHONE_VERIFIED" || state === "ACCOUNT_AUTHENTICATED";
}

/** 같은 탭(커스텀 이벤트) + 다른 탭(storage 이벤트) 변경을 모두 구독한다. */
export function subscribeAuthState(callback: () => void): () => void {
  if (typeof window === "undefined") return () => {};
  window.addEventListener("storage", callback);
  window.addEventListener(EVENT_NAME, callback);
  return () => {
    window.removeEventListener("storage", callback);
    window.removeEventListener(EVENT_NAME, callback);
  };
}
