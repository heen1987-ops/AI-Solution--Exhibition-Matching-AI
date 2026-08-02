import Link from "next/link";
import type { Company } from "@/lib/types";

export function CompanyCard({
  company,
  meta,
}: {
  company: Company;
  /** 추천 이유, 매칭 점수 등 카드 하단에 덧붙일 부가 정보 */
  meta?: React.ReactNode;
}) {
  return (
    <li className="rounded-lg border border-zinc-200 p-4 dark:border-zinc-800">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="text-xs text-zinc-500 dark:text-zinc-400">
            {company.categoryLabel} · {company.zone} {company.boothNumber}
          </p>
          <Link
            href={`/companies/${company.id}`}
            className="text-base font-semibold text-zinc-900 underline-offset-2 hover:underline dark:text-zinc-50"
          >
            {company.name}
          </Link>
        </div>
      </div>
      <p className="mt-2 text-sm text-zinc-600 dark:text-zinc-300">{company.summary}</p>
      <ul className="mt-2 flex flex-wrap gap-1">
        {company.tags.map((tag) => (
          <li
            key={tag}
            className="rounded-full bg-zinc-100 px-2 py-0.5 text-xs text-zinc-600 dark:bg-zinc-800 dark:text-zinc-300"
          >
            #{tag}
          </li>
        ))}
      </ul>
      {meta ? <div className="mt-3 border-t border-zinc-100 pt-2 dark:border-zinc-800">{meta}</div> : null}
    </li>
  );
}
