"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { useKioskSession } from "@/lib/kiosk-session-context";

const ACTIVITY_EVENTS = ["pointerdown", "touchstart", "keydown", "wheel"] as const;

/**
 * 90~120초 무입력 자동 초기화 (docs/vibe-coding-master-spec-v1.md 24절).
 *
 * 모든 화면에 공통으로 걸리는 클라이언트 타이머다. 이용자의 입력(터치/키 입력/스크롤)이
 * 있을 때마다 타이머를 리셋하고, 타임아웃이 지나면 검색어·결과·선택업체·언어설정·QR토큰·
 * sessionStorage를 전부 지운 뒤 세션 종료 화면(/session-ended)을 거쳐 대기화면(/)으로
 * 돌아간다. 대기화면과 세션종료 화면 자체에서는 초기화할 것이 없으므로 타이머를 걸지
 * 않는다.
 */
export default function IdleGuard() {
  const { idleTimeoutSeconds, resetAll, session } = useKioskSession();
  const router = useRouter();
  const pathname = usePathname();
  const timerRef = useRef<number | null>(null);

  useEffect(() => {
    if (pathname === "/" || pathname === "/session-ended") {
      if (timerRef.current) window.clearTimeout(timerRef.current);
      return;
    }

    const armTimer = () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
      timerRef.current = window.setTimeout(() => {
        resetAll({ notifyServer: Boolean(session) });
        router.replace("/session-ended");
      }, idleTimeoutSeconds * 1000);
    };

    armTimer();
    for (const eventName of ACTIVITY_EVENTS) {
      window.addEventListener(eventName, armTimer, { passive: true });
    }
    return () => {
      if (timerRef.current) window.clearTimeout(timerRef.current);
      for (const eventName of ACTIVITY_EVENTS) {
        window.removeEventListener(eventName, armTimer);
      }
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pathname, idleTimeoutSeconds]);

  return null;
}
