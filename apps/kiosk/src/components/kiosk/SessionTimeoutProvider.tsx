"use client";

import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect } from "react";
import {
  resolveIdleTimeoutMs,
} from "@/lib/session/session-machine";
import {
  useSessionTimeout,
  type UseSessionTimeoutResult,
} from "@/lib/session/use-session-timeout";

/**
 * 세션 타임아웃 상태기계를 앱 전역에 연결하는 Provider - 골격(Skeleton).
 *
 * K-3-screen-ia.md §3: 대기화면(K-S1)으로는 (a) 완료 버튼 (b) 타임아웃
 * (c) QR 스캔 완료 세 트리거로만 도달한다. 이 컴포넌트는 타임아웃(b) 트리거를
 * 감지해 자동으로 "/"(대기화면)로 되돌리고, 되돌리는 시점에 클라이언트에 남은
 * 세션 데이터(sessionStorage)를 지워 다음 이용자에게 이전 이용자의 정보가
 * 전혀 노출되지 않도록 한다(AGENTS.md §8, K-1-service-scope.md §4).
 *
 * 실제 백엔드 GuestSession.expires_at 연동은 이후 웨이브 - 이번 웨이브는
 * 순수 프런트엔드 타이머 골격만 제공한다.
 */

const SessionTimeoutContext = createContext<UseSessionTimeoutResult | null>(
  null
);

export function useKioskSession(): UseSessionTimeoutResult {
  const ctx = useContext(SessionTimeoutContext);
  if (!ctx) {
    throw new Error(
      "useKioskSession은 SessionTimeoutProvider 내부에서만 사용할 수 있습니다."
    );
  }
  return ctx;
}

function clearClientSessionData() {
  if (typeof window === "undefined") {
    return;
  }
  // 이전 이용자의 검색어/결과 등이 다음 이용자에게 남지 않도록 세션 스토리지를 비운다.
  window.sessionStorage.clear();
}

export function SessionTimeoutProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const idleTimeoutMs = resolveIdleTimeoutMs(
    process.env.NEXT_PUBLIC_KIOSK_IDLE_TIMEOUT_MS
  );

  const session = useSessionTimeout({
    idleTimeoutMs,
    onClearSessionData: clearClientSessionData,
    onReturnToIdle: () => router.push("/"),
  });

  // 대기화면 자체 진입 시(경로 "/")에는 세션이 굳이 "active"일 필요가 없다 -
  // 실제 세션 시작은 WaitingScreen의 "시작하기" 버튼(SESSION_START)에서 트리거된다.
  useEffect(() => {
    // 골격 단계에서는 별도 초기화 로직 없음 - 훅 내부 idle 초기 상태를 그대로 사용.
  }, []);

  return (
    <SessionTimeoutContext.Provider value={session}>
      {children}
    </SessionTimeoutContext.Provider>
  );
}
