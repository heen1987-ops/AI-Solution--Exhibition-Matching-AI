"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef } from "react";

import { useKioskSession } from "@/lib/kiosk-session-context";
import { copy } from "@/lib/copy";

/**
 * K00 대기화면.
 *
 * 이 화면에 도달하는 모든 경로(최초 진입, 세션 종료, 자동 초기화, "처음으로" 버튼)는
 * 이전 이용자의 검색어·결과·선택업체·언어설정·QR토큰이 전혀 남지 않아야 한다 - 그래서
 * 마운트될 때마다 안전하게 한 번 더 초기화한다(이미 비어 있으면 아무 효과 없음).
 * 로그인/회원가입 관련 UI는 이 화면을 포함해 키오스크 어디에도 없다.
 */
export default function IdleScreen() {
  const router = useRouter();
  const { resetAll, config } = useKioskSession();
  const resetOnce = useRef(false);

  useEffect(() => {
    if (resetOnce.current) return;
    resetOnce.current = true;
    resetAll({ notifyServer: false });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const eventName = config?.event_name ?? copy.ko.eventFallbackName;

  function start() {
    router.push("/language");
  }

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={start}
      onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") start();
      }}
      className="flex min-h-[100dvh] cursor-pointer flex-col items-center justify-center gap-8 bg-gradient-to-b from-brand-50 to-white px-6 text-center dark:from-stone-950 dark:to-stone-900"
    >
      <p className="text-lg font-semibold uppercase tracking-widest text-brand-600 dark:text-brand-300">
        {eventName}
      </p>

      <h1 className="text-5xl font-black text-stone-900 dark:text-white sm:text-6xl">
        백주 AI 셀파
      </h1>

      <div className="mt-4 flex flex-col items-center gap-4">
        <div className="flex h-40 w-40 animate-pulse items-center justify-center rounded-full bg-brand-600 text-white shadow-lg sm:h-48 sm:w-48">
          <span className="text-2xl font-bold sm:text-3xl">TOUCH</span>
        </div>
        <p className="text-2xl font-semibold text-stone-800 dark:text-stone-100 sm:text-3xl">
          화면을 눌러 시작하세요
        </p>
        <p className="text-lg text-stone-600 dark:text-stone-300 sm:text-xl">
          Touch to start · タッチして開始 · 触摸屏幕开始
        </p>
      </div>

      <p className="mt-8 max-w-md text-base text-stone-500 dark:text-stone-400">
        회원가입 없이 이용 · 종료 후 검색 내용이 자동으로 사라져요
      </p>
    </div>
  );
}
