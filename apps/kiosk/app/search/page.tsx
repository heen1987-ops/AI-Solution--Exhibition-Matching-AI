"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import OnScreenKeyboard from "@/components/OnScreenKeyboard";
import { KioskApiError, kioskSearch } from "@/lib/api-client";
import { QUICK_CATEGORIES } from "@/lib/categories";
import { copy, suggestedQueries } from "@/lib/copy";
import { useKioskSession } from "@/lib/kiosk-session-context";

/**
 * K02 검색홈. 입력방식 3가지(docs/vibe-coding-master-spec-v1.md 20절): 화면 키보드,
 * 추천 검색문, 카테고리 버튼. 키오스크는 사용자 행동이력·장기 프로파일을 쓰지 않으므로
 * 이 화면은 매번 같은 추천 검색문/카테고리를 보여준다.
 */
export default function SearchHomePage() {
  const router = useRouter();
  const { session, language, query, setQuery, applySearchResults } = useKioskSession();
  const [busy, setBusy] = useState(false);
  const t = copy[language];

  useEffect(() => {
    if (!session) {
      router.replace("/language");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  async function runSearch(nextQuery: string, categoryCodes: string[] = []) {
    if (!session || busy) return;
    const normalized = nextQuery.trim();
    if (!normalized && categoryCodes.length === 0) return;
    setBusy(true);
    try {
      const response = await kioskSearch(session.session_id, {
        query: normalized,
        categoryCodes,
      });
      setQuery(normalized);
      applySearchResults(response.results, response.interpreted_query.concepts);
      router.push(response.results.length > 0 ? "/results" : "/no-results");
    } catch (error) {
      if (error instanceof KioskApiError && error.code === "KIOSK_SESSION_EXPIRED") {
        router.push("/session-ended");
        return;
      }
      const message = error instanceof Error ? error.message : "검색을 처리하지 못했습니다.";
      router.push(`/network-error?from=${encodeURIComponent("/search")}&message=${encodeURIComponent(message)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-[100dvh] max-w-screen-content flex-col gap-8 px-5 py-8 sm:px-8">
      <header className="text-center">
        <p className="text-lg font-semibold uppercase tracking-wide text-brand-600 dark:text-brand-300">
          {t.searchEyebrow}
        </p>
        <h1 className="mt-1 text-3xl font-bold text-stone-900 dark:text-white sm:text-4xl">
          {t.searchTitle}
        </h1>
      </header>

      <div className="mx-auto w-full max-w-3xl rounded-2xl bg-white p-4 shadow-sm ring-1 ring-stone-200 dark:bg-stone-800 dark:ring-stone-700 sm:p-6">
        <div className="flex items-center gap-3 rounded-xl border-2 border-stone-300 bg-stone-50 px-4 py-4 dark:border-stone-600 dark:bg-stone-900">
          <span aria-hidden="true" className="text-2xl">🔍</span>
          <p className="min-h-[2rem] flex-1 text-xl text-stone-900 dark:text-white">
            {query || <span className="text-stone-400">{t.searchPlaceholder}</span>}
          </p>
        </div>

        <div className="mt-4">
          <OnScreenKeyboard
            language={language}
            value={query}
            onChange={setQuery}
            onSubmit={() => void runSearch(query)}
          />
        </div>
      </div>

      <section className="mx-auto w-full max-w-3xl">
        <h2 className="mb-3 text-xl font-semibold text-stone-800 dark:text-stone-100">
          {t.suggestedTitle}
        </h2>
        <div className="flex flex-wrap gap-3">
          {suggestedQueries[language].map((phrase) => (
            <button
              key={phrase}
              type="button"
              disabled={busy}
              onClick={() => void runSearch(phrase)}
              className="min-h-tap-min rounded-full bg-brand-50 px-5 py-3 text-lg text-brand-700 ring-1 ring-brand-200 active:scale-95 disabled:opacity-60 dark:bg-stone-800 dark:text-brand-300 dark:ring-stone-700"
            >
              “{phrase}”
            </button>
          ))}
        </div>
      </section>

      <section className="mx-auto w-full max-w-3xl">
        <div className="mb-3 flex items-center justify-between">
          <h2 className="text-xl font-semibold text-stone-800 dark:text-stone-100">
            {t.categoryQuickTitle}
          </h2>
          <Link
            href="/categories"
            className="min-h-tap-min rounded-lg px-3 py-2 text-lg font-semibold text-brand-600 underline underline-offset-4 dark:text-brand-300"
          >
            {t.moreCategories}
          </Link>
        </div>
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
          {QUICK_CATEGORIES.map((category) => (
            <button
              key={category.code}
              type="button"
              disabled={busy}
              onClick={() => void runSearch("", [category.code])}
              className="min-h-tap-min rounded-2xl bg-white p-4 text-lg font-semibold text-stone-800 shadow-sm ring-1 ring-stone-200 active:scale-95 disabled:opacity-60 dark:bg-stone-800 dark:text-stone-100 dark:ring-stone-700"
            >
              {category.labels[language]}
            </button>
          ))}
        </div>
      </section>
    </div>
  );
}
