/** 이 브라우저(키오스크 단말)의 고정 설정. 개인정보를 포함하지 않는다. */
export const KIOSK_ID = process.env.NEXT_PUBLIC_KIOSK_ID ?? "kiosk_a01";

/** 90~120초 무입력 자동 초기화 (docs/vibe-coding-master-spec-v1.md 24절). 서버 설정
 * (`session_timeout_seconds`, 60~120초 범위)을 우선하되 이 창 밖이면 클램프한다. */
export const IDLE_TIMEOUT_MIN_SECONDS = 60;
export const IDLE_TIMEOUT_MAX_SECONDS = 120;
export const IDLE_TIMEOUT_DEFAULT_SECONDS = 90;

export function clampIdleTimeoutSeconds(sessionTimeoutSeconds: number | undefined): number {
  if (!sessionTimeoutSeconds || Number.isNaN(sessionTimeoutSeconds)) {
    return IDLE_TIMEOUT_DEFAULT_SECONDS;
  }
  return Math.min(
    IDLE_TIMEOUT_MAX_SECONDS,
    Math.max(IDLE_TIMEOUT_MIN_SECONDS, Math.round(sessionTimeoutSeconds)),
  );
}

/** 세션 만료 임박 경고를 보여줄 남은 초 (사용자에게 "계속 이용하기"를 제안). */
export const IDLE_WARNING_SECONDS = 15;

export const DEFAULT_SUPPORTED_LANGUAGES = ["ko", "en", "ja", "zh"] as const;
