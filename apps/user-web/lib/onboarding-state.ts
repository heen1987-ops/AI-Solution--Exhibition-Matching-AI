/**
 * 온보딩(U-01~U-07) 화면들이 공유하는 로컬 진행 상태.
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md 6.1절(온보딩 상태모델): "중간 이탈 시 익명 세션에 답변을
 *   저장하고 같은 브라우저에서 재개한다"의 구현 수단. 서버 세션(게스트 쿠키)이 진행답변
 *   자체까지 화면에 즉시 보여주는 조회 API를 아직 제공하지 않으므로, 화면 간 이동에 필요한
 *   최소 정보(세션 식별자, 선택한 사용자 유형, 동의 결과, 이전 단계 응답 요약)를
 *   브라우저 로컬에 함께 보관해 새로고침·뒤로가기에도 잃지 않게 한다.
 * - docs/frontend-backend-ai-interface-spec.md 16.2절: "성명, 전화번호, 이메일, 상담
 *   자유메모 원문은 분석 이벤트에 넣지 않는다"와 같은 취지로, 이 저장소에도 식별정보
 *   원문(휴대전화번호 등)은 담지 않는다.
 *
 * 이 파일은 화면 라우트 파일이 아니라 여러 온보딩 화면이 함께 쓰는 보조 유틸리티다.
 * `frontend/lib/api-client.ts`, `frontend/lib/types.ts`(공용 aggregator, 수정 금지)와는
 * 별개의 새 파일이라 다른 작업 지시와 충돌하지 않는다.
 */

export type OnboardingUserType = "GENERAL_VISITOR" | "BUYER";

export interface OnboardingGoal {
  code: string;
  priority: number;
}

export interface OnboardingState {
  /** U-01에서 발급된 세션 식별자들. 재사용 가능한 인증 토큰이 아니라 화면 표시·재개 판단용. */
  guestSessionId: string | null;
  visitSessionId: string | null;
  profileId: string | null;
  minimumAge: number | null;
  eventStatus: string | null;

  /** U-02 선택 결과. */
  userType: OnboardingUserType | null;

  /** U-03 동의 결과 스냅샷 (7.4절). */
  ageConfirmed: boolean;
  personalizationConsent: boolean;
  behaviorConsent: boolean;
  marketingConsent: boolean;
  consentDocumentVersion: string;
  privacyChoiceRecorded: boolean;

  /** U-04 방문 목적. */
  goals: OnboardingGoal[];
  freeTextGoal: string;
  goalsCompleted: boolean;

  /** U-05/U-06 완료 여부 (역할에 따라 둘 중 하나만 해당). */
  minimumProfileCompleted: boolean;

  /** 서버가 돌려준 최신 프로파일 버전. If-Match 낙관적 잠금에 쓸 수 있다. */
  profileVersion: number | null;

  /** U-07에서 고른 방문일. 기본값 계산에 재사용한다. */
  visitDate: string | null;
}

const STORAGE_KEY = "baekju.onboarding.state.v1";

/** 인터페이스 명세 7.1절 예시 값. 실제 행사 ID는 배포 환경변수로 대체한다. */
export const DEFAULT_EVENT_ID = "evt_backju_2026";
export const EVENT_ID = process.env.NEXT_PUBLIC_EVENT_ID ?? DEFAULT_EVENT_ID;

/** 인터페이스 명세 7.4절 예시의 동의 문서 버전. TODO(운영팀이 실제 약관 버전 관리 체계를
 * 확정하면 배포 설정값으로 교체). */
export const CONSENT_DOCUMENT_VERSION = "2026.1";

const DEFAULT_STATE: OnboardingState = {
  guestSessionId: null,
  visitSessionId: null,
  profileId: null,
  minimumAge: null,
  eventStatus: null,
  userType: null,
  ageConfirmed: false,
  personalizationConsent: false,
  behaviorConsent: false,
  marketingConsent: false,
  consentDocumentVersion: CONSENT_DOCUMENT_VERSION,
  privacyChoiceRecorded: false,
  goals: [],
  freeTextGoal: "",
  goalsCompleted: false,
  minimumProfileCompleted: false,
  profileVersion: null,
  visitDate: null,
};

export function loadOnboardingState(): OnboardingState {
  if (typeof window === "undefined") return { ...DEFAULT_STATE };
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return { ...DEFAULT_STATE };
    const parsed = JSON.parse(raw) as Partial<OnboardingState>;
    return { ...DEFAULT_STATE, ...parsed };
  } catch {
    return { ...DEFAULT_STATE };
  }
}

export function saveOnboardingState(patch: Partial<OnboardingState>): OnboardingState {
  const next = { ...loadOnboardingState(), ...patch };
  if (typeof window !== "undefined") {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(next));
  }
  return next;
}

export function clearOnboardingState(): void {
  if (typeof window === "undefined") return;
  window.localStorage.removeItem(STORAGE_KEY);
}

/** 오늘 날짜를 `YYYY-MM-DD`로 반환한다 (U-07 기본 방문일). */
export function todayIsoDate(): string {
  const now = new Date();
  const year = now.getFullYear();
  const month = String(now.getMonth() + 1).padStart(2, "0");
  const day = String(now.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
