import Link from "next/link";

import type { KioskLanguage, SearchResult } from "@/lib/types";
import { copy } from "@/lib/copy";

interface ResultCardProps {
  result: SearchResult;
  language: KioskLanguage;
}

/** K05 검색결과 카드. 근거: docs/vibe-coding-master-spec-v1.md 21절 - 업체명, 부스번호,
 * 대표 제품·서비스, 질의와 관련된 이유, 관련 카테고리, 운영 상태를 보여준다. 색상만으로
 * 운영상태를 구분하지 않도록 항상 텍스트 배지를 함께 쓴다. */
export default function ResultCard({ result, language }: ResultCardProps) {
  const t = copy[language];
  const isOpen = result.operating_status === "OPEN";

  return (
    <article className="flex flex-col gap-3 rounded-2xl bg-white p-5 shadow-sm ring-1 ring-stone-200 dark:bg-stone-800 dark:ring-stone-700 sm:p-6">
      <div className="flex flex-wrap items-center gap-2 text-sm">
        <span
          className={`rounded-full px-3 py-1 font-semibold ${
            isOpen
              ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-100"
              : "bg-stone-200 text-stone-700 dark:bg-stone-700 dark:text-stone-200"
          }`}
        >
          {isOpen ? t.openNow : t.paused}
        </span>
        <span className="text-stone-500 dark:text-stone-400">
          {result.zone_name ? `${result.zone_name} · ` : ""}
          {result.booth_number}
        </span>
        {result.estimated_wait_minutes !== null && (
          <span className="text-stone-500 dark:text-stone-400">
            {t.waitMinutes(result.estimated_wait_minutes)}
          </span>
        )}
      </div>

      <h2 className="text-2xl font-bold text-stone-900 dark:text-white">{result.name}</h2>

      {result.summary && (
        <p className="text-lg text-stone-600 dark:text-stone-300">{result.summary}</p>
      )}

      <p className="rounded-xl bg-brand-50 px-4 py-3 text-base text-brand-700 dark:bg-stone-900 dark:text-brand-300">
        {result.reason}
      </p>

      {result.product_names.length > 0 && (
        <div className="flex flex-wrap gap-2">
          {result.product_names.map((product) => (
            <span
              key={product}
              className="rounded-full bg-stone-100 px-3 py-1 text-sm text-stone-700 dark:bg-stone-700 dark:text-stone-200"
            >
              {product}
            </span>
          ))}
        </div>
      )}

      <Link
        href={`/exhibitors/${result.exhibitor_id}`}
        className="mt-auto flex min-h-tap-min items-center justify-center rounded-xl bg-brand-600 px-5 py-3 text-lg font-bold text-white shadow-sm active:scale-95"
      >
        {t.viewDetails}
      </Link>
    </article>
  );
}
