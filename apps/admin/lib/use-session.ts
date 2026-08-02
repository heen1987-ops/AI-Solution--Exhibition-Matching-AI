"use client";

/**
 * `lib/auth-state.ts`의 localStorage 세션을 React 상태로 구독하는 클라이언트 훅.
 * 여러 컴포넌트(TopBar의 SessionSwitcher, 각 화면의 RoleGate)가 같은 세션을 실시간으로
 * 공유해야 해서 커스텀 이벤트(`backju-admin-session-changed`)로 동기화한다.
 */

import { useCallback, useEffect, useState } from "react";

import { getDefaultSession, getStoredSession, saveSession } from "./auth-state";
import type { AdminSession } from "./types";

export function useSession(): [AdminSession, (next: AdminSession) => void] {
  const [session, setSessionState] = useState<AdminSession>(getDefaultSession());
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    const stored = getStoredSession();
    if (stored) setSessionState(stored);
    setHydrated(true);

    const onChange = () => {
      const latest = getStoredSession();
      setSessionState(latest ?? getDefaultSession());
    };
    window.addEventListener("backju-admin-session-changed", onChange);
    window.addEventListener("storage", onChange);
    return () => {
      window.removeEventListener("backju-admin-session-changed", onChange);
      window.removeEventListener("storage", onChange);
    };
  }, []);

  const setSession = useCallback((next: AdminSession) => {
    saveSession(next);
    setSessionState(next);
  }, []);

  // 하이드레이션 전에는 기본값을 그대로 반환한다(SSR과 첫 클라이언트 렌더가 일치해야
  // hydration mismatch가 나지 않는다).
  void hydrated;
  return [session, setSession];
}
