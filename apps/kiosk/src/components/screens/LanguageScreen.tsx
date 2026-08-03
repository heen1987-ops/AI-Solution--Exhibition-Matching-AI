"use client";

import Link from "next/link";
import { MOCK_KIOSK_LANGUAGES } from "@/lib/mock/exhibitors";

/**
 * K-S2 언어 선택 화면 골격.
 *
 * K-3-screen-ia.md §3: 세션당 1회만 노출된다(도중 언어 변경은 세션 재시작 필요,
 * 이번 웨이브 범위 밖). 버튼 선택만 있을 뿐 텍스트 입력 필드는 없다.
 */
export function LanguageScreen() {
  return (
    <main
      data-testid="screen-language"
      className="flex min-h-screen flex-col gap-10 bg-slate-950 px-8 py-16 text-white"
    >
      <header className="text-center">
        <h1 className="text-kiosk-lg font-bold">언어를 선택하세요</h1>
        <p className="mt-2 text-kiosk text-slate-300">Select your language</p>
      </header>

      <div className="grid flex-1 grid-cols-2 gap-6">
        {MOCK_KIOSK_LANGUAGES.map((language) => (
          <Link
            key={language.code}
            href="/search"
            className="flex min-h-touch items-center justify-center rounded-2xl bg-slate-800 text-kiosk-lg font-semibold active:scale-[0.98]"
          >
            {language.label}
          </Link>
        ))}
      </div>
    </main>
  );
}
