"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import ResultCard from "@/components/ResultCard";
import { copy } from "@/lib/copy";
import { useKioskSession } from "@/lib/kiosk-session-context";

/** K05 검색결과. 정렬은 서버(kiosk 검색 API)가 이미 관련성 순으로 내려준 rank를 그대로
 * 따른다 - 행동이력·장기 프로파일을 쓰지 않는다(docs/vibe-coding-master-spec-v1.md 21절). */
export default function ResultsPage() {
  const router = useRouter();
  const { session, language, results, resetAll } = useKioskSession();
  const t = copy[language];

  useEffect(() => {
    if (!session) {
      router.replace("/language");
      return;
    }
    if (results.length === 0) {
      router.replace("/no-results");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session, results]);

  if (results.length === 0) return null;

  return (
    <div className="mx-auto flex min-h-[100dvh] max-w-screen-content flex-col gap-6 px-5 py-8 sm:px-8">
      <header className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h1 className="text-3xl font-bold text-stone-900 dark:text-white sm:text-4xl">
            {t.resultsTitle}
          </h1>
          <p className="mt-1 text-lg text-stone-500 dark:text-stone-400">
            {t.resultsCount(results.length)}
          </p>
        </div>
        <div className="flex gap-3">
          <Link
            href="/search"
            className="flex min-h-tap-min items-center justify-center rounded-xl bg-white px-5 text-lg font-semibold text-stone-700 shadow-sm ring-1 ring-stone-300 active:scale-95 dark:bg-stone-800 dark:text-stone-100 dark:ring-stone-700"
          >
            {t.searchAgain}
          </Link>
          <button
            type="button"
            onClick={() => {
              resetAll({ notifyServer: true });
              router.push("/");
            }}
            className="flex min-h-tap-min items-center justify-center rounded-xl bg-brand-600 px-5 text-lg font-semibold text-white shadow-sm active:scale-95"
          >
            {t.startOver}
          </button>
        </div>
      </header>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        {results.map((result) => (
          <ResultCard key={result.result_id} result={result} language={language} />
        ))}
      </div>
    </div>
  );
}
