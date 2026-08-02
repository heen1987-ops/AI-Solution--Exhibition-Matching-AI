"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { copy } from "@/lib/copy";
import { useKioskSession } from "@/lib/kiosk-session-context";

const AUTO_RETURN_SECONDS = 4;

/**
 * K11 세션 종료.
 *
 * 90~120초 무입력 자동 초기화(components/IdleGuard.tsx)와 백엔드가 보고하는
 * KIOSK_SESSION_EXPIRED(410) 둘 다 이 화면으로 온다. 도착 시점에 검색어·결과·선택업체·
 * 언어설정·QR토큰·sessionStorage는 이미 모두 지워져 있어야 한다(idle 타이머가 이동 전에
 * resetAll을 호출한다) - 이 화면도 안전하게 한 번 더 초기화한 뒤, 잠시 후 대기화면으로
 * 자동 복귀한다.
 */
export default function SessionEndedPage() {
  const router = useRouter();
  const { resetAll, language } = useKioskSession();
  const t = copy[language];
  const [secondsLeft, setSecondsLeft] = useState(AUTO_RETURN_SECONDS);
  const resetOnce = useRef(false);

  useEffect(() => {
    if (resetOnce.current) return;
    resetOnce.current = true;
    resetAll({ notifyServer: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (secondsLeft <= 0) {
      router.replace("/");
      return;
    }
    const timer = window.setTimeout(() => setSecondsLeft((s) => s - 1), 1000);
    return () => window.clearTimeout(timer);
  }, [secondsLeft, router]);

  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-8 px-6 text-center">
      <div className="flex h-24 w-24 items-center justify-center rounded-full bg-stone-200 text-4xl dark:bg-stone-800">
        ✓
      </div>
      <div>
        <h1 className="text-3xl font-bold text-stone-900 dark:text-white sm:text-4xl">
          {t.sessionEndedTitle}
        </h1>
        <p className="mt-3 max-w-md text-lg text-stone-500 dark:text-stone-400">{t.sessionEndedHint}</p>
      </div>

      <button
        type="button"
        onClick={() => router.replace("/")}
        className="flex min-h-tap-min items-center justify-center rounded-2xl bg-brand-600 px-8 text-xl font-bold text-white shadow-md active:scale-95"
      >
        {t.backToStart} ({secondsLeft})
      </button>
    </div>
  );
}
