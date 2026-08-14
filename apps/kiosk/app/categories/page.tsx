"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { ALL_CATEGORIES } from "@/lib/categories";
import { KioskApiError, kioskSearch } from "@/lib/api-client";
import { copy } from "@/lib/copy";
import { useKioskSession } from "@/lib/kiosk-session-context";

/** K04 카테고리 선택. 여러 개를 함께 고를 수 있고, 하단 고정 버튼으로 한 번에 검색한다. */
export default function CategoriesPage() {
  const router = useRouter();
  const { session, language, setQuery, applySearchResults, setCategoryCodes } = useKioskSession();
  const [selected, setSelected] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);
  const t = copy[language];

  useEffect(() => {
    if (!session) router.replace("/language");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  function toggle(code: string) {
    setSelected((current) =>
      current.includes(code) ? current.filter((c) => c !== code) : [...current, code],
    );
  }

  async function search() {
    if (!session || selected.length === 0 || busy) return;
    setBusy(true);
    try {
      const response = await kioskSearch(session.session_id, { categoryCodes: selected });
      setQuery("");
      setCategoryCodes(selected);
      applySearchResults(response.results, response.interpreted_query.concepts);
      router.push(response.results.length > 0 ? "/results" : "/no-results");
    } catch (error) {
      if (error instanceof KioskApiError && error.code === "KIOSK_SESSION_EXPIRED") {
        router.push("/session-ended");
        return;
      }
      const message = error instanceof Error ? error.message : "검색을 처리하지 못했습니다.";
      router.push(`/network-error?from=${encodeURIComponent("/categories")}&message=${encodeURIComponent(message)}`);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-[100dvh] max-w-screen-content flex-col gap-6 px-5 pb-32 pt-8 sm:px-8">
      <header className="text-center">
        <h1 className="text-3xl font-bold text-stone-900 dark:text-white sm:text-4xl">
          {t.categoriesTitle}
        </h1>
        <p className="mt-2 text-lg text-stone-500 dark:text-stone-400">{t.categoriesHint}</p>
      </header>

      <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
        {ALL_CATEGORIES.map((category) => {
          const isSelected = selected.includes(category.code);
          return (
            <button
              key={category.code}
              type="button"
              aria-pressed={isSelected}
              onClick={() => toggle(category.code)}
              className={`min-h-tap-min rounded-2xl p-4 text-lg font-semibold shadow-sm ring-2 transition active:scale-95 ${
                isSelected
                  ? "bg-brand-600 text-white ring-brand-600"
                  : "bg-white text-stone-800 ring-stone-200 dark:bg-stone-800 dark:text-stone-100 dark:ring-stone-700"
              }`}
            >
              {category.labels[language]}
            </button>
          );
        })}
      </div>

      <div className="fixed inset-x-0 bottom-0 border-t border-stone-200 bg-white/95 p-4 pb-safe-bottom backdrop-blur dark:border-stone-700 dark:bg-stone-900/95">
        <button
          type="button"
          disabled={selected.length === 0 || busy}
          onClick={() => void search()}
          className="mx-auto block min-h-tap-min w-full max-w-xl rounded-2xl bg-brand-600 py-4 text-xl font-bold text-white shadow-md disabled:opacity-50"
        >
          {busy ? "…" : t.searchWithSelected(selected.length)}
        </button>
      </div>
    </div>
  );
}
