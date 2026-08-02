"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

import { createKioskSession } from "@/lib/api-client";
import { copy, languageLabels } from "@/lib/copy";
import { supportedLanguages, useKioskSession } from "@/lib/kiosk-session-context";
import type { KioskLanguage } from "@/lib/types";

/**
 * K01 언어선택.
 *
 * 지원 언어는 GET /kiosk/config/{kiosk_id}의 supported_languages를 따른다(로딩/오류 시
 * 기본 4개 언어로 보여준다 - 네트워크가 불안정해도 언어 선택 자체는 막지 않는다).
 * 언어를 고르면 그 자리에서 익명 세션을 만든다 - 이름/전화번호/이메일 입력 없음.
 */
export default function LanguagePage() {
  const router = useRouter();
  const { kioskId, config, setLanguage, setSession } = useKioskSession();
  const [pending, setPending] = useState<KioskLanguage | null>(null);

  const languages = supportedLanguages(config);

  async function choose(language: KioskLanguage) {
    if (pending) return;
    setPending(language);
    try {
      const session = await createKioskSession(kioskId, language);
      setLanguage(language);
      setSession(session);
      router.push("/search");
    } catch (error) {
      const message = error instanceof Error ? error.message : "세션을 시작할 수 없습니다.";
      router.push(`/network-error?from=${encodeURIComponent("/language")}&message=${encodeURIComponent(message)}`);
    } finally {
      setPending(null);
    }
  }

  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-10 px-6 py-12">
      <div className="text-center">
        <h1 className="text-4xl font-bold text-stone-900 dark:text-white sm:text-5xl">
          {copy.ko.chooseLanguage}
        </h1>
        <p className="mt-2 text-xl text-stone-500 dark:text-stone-400">Please select your language</p>
      </div>

      <div className="grid w-full max-w-2xl grid-cols-2 gap-5">
        {languages.map((code) => (
          <button
            key={code}
            type="button"
            disabled={pending !== null}
            onClick={() => void choose(code)}
            className="flex min-h-[9rem] flex-col items-center justify-center gap-1 rounded-3xl bg-white p-6 shadow-md ring-1 ring-stone-200 transition active:scale-95 disabled:opacity-60 dark:bg-stone-800 dark:ring-stone-700"
          >
            <span className="text-3xl font-bold text-stone-900 dark:text-white">
              {languageLabels[code].native}
            </span>
            <span className="text-lg text-stone-500 dark:text-stone-400">
              {languageLabels[code].secondary}
            </span>
            {pending === code && <span className="mt-2 text-sm text-brand-600">…</span>}
          </button>
        ))}
      </div>

      <p className="max-w-md text-center text-base text-stone-500 dark:text-stone-400">
        {copy.ko.privacyNote}
      </p>
    </div>
  );
}
