"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

/**
 * K-S1 대기화면(waiting screen) 골격.
 *
 * - 웹 대응 화면 없음(키오스크 고유, K-3-screen-ia.md §1).
 * - 유일하게 요구되는 상호작용은 "터치하여 시작" - 회원가입/로그인/개인정보
 *   입력 필드는 절대 두지 않는다(AGENTS.md §8, PROJECT_SCOPE.md 제외범위).
 * - 언어 문구를 순환 표시하는 것은 이번 웨이브에서는 정적 배열을 도는 스텁이고,
 *   실제 언어 선택은 다음 화면(K-S2, /language)에서 이루어진다.
 */

const CYCLING_PROMPTS = [
  "화면을 터치하여 시작하세요",
  "Touch the screen to start",
  "画面にタッチしてください",
  "触摸屏幕开始",
];

const CYCLE_INTERVAL_MS = 4000;

export function WaitingScreen() {
  const [promptIndex, setPromptIndex] = useState(0);

  useEffect(() => {
    const timer = setInterval(() => {
      setPromptIndex((current) => (current + 1) % CYCLING_PROMPTS.length);
    }, CYCLE_INTERVAL_MS);
    return () => clearInterval(timer);
  }, []);

  return (
    <main
      data-testid="screen-waiting"
      className="flex min-h-screen flex-col items-center justify-between bg-slate-950 px-8 py-16 text-white"
    >
      <div className="flex flex-1 flex-col items-center justify-center gap-6 text-center">
        <p className="text-sm uppercase tracking-[0.3em] text-slate-400">
          백주대간 전시 안내 키오스크
        </p>
        <h1
          aria-live="polite"
          className="max-w-3xl text-kiosk-lg font-bold"
        >
          {CYCLING_PROMPTS[promptIndex]}
        </h1>
        <p className="max-w-xl text-kiosk text-slate-300">
          누구나 회원가입 없이 바로 이용할 수 있습니다. 검색이 끝나면 화면은
          자동으로 초기화되어 이전 이용자의 정보가 남지 않습니다.
        </p>
      </div>

      <Link
        href="/language"
        className="flex min-h-touch w-full max-w-md items-center justify-center rounded-2xl bg-emerald-500 px-10 py-6 text-kiosk-lg font-semibold text-slate-950 shadow-lg active:scale-[0.98]"
      >
        시작하기 · Start
      </Link>
    </main>
  );
}
