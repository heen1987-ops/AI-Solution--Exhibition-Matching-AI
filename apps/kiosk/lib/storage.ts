import type { StoredKioskState } from "./types";

/**
 * sessionStorage 전용 저장소.
 *
 * - localStorage는 절대 쓰지 않는다 (탭/브라우저를 넘어 남아있을 수 있는 저장소이므로).
 * - sessionStorage는 이 브라우저 탭이 닫히면 사라지고, 여기 담기는 값(세션 ID, 선택한
 *   언어, 검색어, 검색결과)은 익명 키오스크 이용 중에만 의미가 있는 휘발성 상태다.
 *   이름/전화번호/이메일 등 개인 식별 정보는 이 상태에 애초에 들어오지 않는다
 *   (StoredKioskState 타입 참고).
 */
const STORAGE_KEY = "kiosk.session.v1";

export function loadKioskState(): StoredKioskState | null {
  if (typeof window === "undefined") return null;
  try {
    const raw = window.sessionStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    return JSON.parse(raw) as StoredKioskState;
  } catch {
    return null;
  }
}

export function saveKioskState(state: StoredKioskState): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
  } catch {
    // 저장 공간이 없거나 접근이 막혀도 키오스크 흐름 자체는 계속 동작해야 한다.
  }
}

/** 세션 종료·자동 초기화 시 호출한다. 검색어·결과·선택업체·언어·QR 토큰을 전부 지운다. */
export function clearKioskState(): void {
  if (typeof window === "undefined") return;
  try {
    window.sessionStorage.removeItem(STORAGE_KEY);
  } catch {
    // no-op
  }
}
