"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { copy } from "@/lib/copy";
import { useKioskSession } from "@/lib/kiosk-session-context";

/** K09 검색 결과 없음. 필수조건을 임의로 완화하지 않고, 다른 검색어나 카테고리를
 * 시도하도록 안내한다 (docs/vibe-coding-master-spec-v1.md 21절 "필수조건은 바꾸지
 * 않는다"에 해당하는 안내). */
export default function NoResultsPage() {
  const router = useRouter();
  const { session, language } = useKioskSession();
  const t = copy[language];

  useEffect(() => {
    if (!session) router.replace("/language");
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session]);

  return (
    <div className="flex min-h-[100dvh] flex-col items-center justify-center gap-8 px-6 text-center">
      <div className="flex h-24 w-24 items-center justify-center rounded-full bg-stone-200 text-4xl dark:bg-stone-800">
        🔍
      </div>
      <div>
        <h1 className="text-3xl font-bold text-stone-900 dark:text-white sm:text-4xl">
          {t.noResultsTitle}
        </h1>
        <p className="mt-3 max-w-md text-lg text-stone-500 dark:text-stone-400">{t.noResultsHint}</p>
      </div>

      <div className="flex flex-col gap-4 sm:flex-row">
        <Link
          href="/search"
          className="flex min-h-tap-min items-center justify-center rounded-2xl bg-brand-600 px-8 text-xl font-bold text-white shadow-md active:scale-95"
        >
          {t.tryDifferentSearch}
        </Link>
        <Link
          href="/categories"
          className="flex min-h-tap-min items-center justify-center rounded-2xl bg-white px-8 text-xl font-bold text-stone-800 shadow-md ring-1 ring-stone-300 active:scale-95 dark:bg-stone-800 dark:text-stone-100 dark:ring-stone-700"
        >
          {t.browseCategories}
        </Link>
      </div>
    </div>
  );
}
