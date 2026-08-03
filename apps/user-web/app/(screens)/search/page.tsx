import { CompanyCard } from "@/components/CompanyCard";
import { DataSourceBanner } from "@/components/MockDataBanner";
import { EmptyState } from "@/components/StateViews";
import { searchCompanies } from "@/lib/api-client";
import type { SearchMode } from "@/lib/types";

export const dynamic = "force-dynamic";

/**
 * S-3. 자연어 검색. POST /search를 우선 사용하며, GUEST_WEB 모드는 /guest/sessions
 * 세션 생성 후 검색한다.
 */
export default async function SearchPage({
  searchParams,
}: {
  searchParams: Promise<{ q?: string; mode?: SearchMode }>;
}) {
  const { q = "", mode = "REGISTERED_WEB" } = await searchParams;
  const results = q ? await searchCompanies(q, mode) : null;

  return (
    <div className="flex flex-col gap-6">
      {results ? (
        <DataSourceBanner source={results.source} notice={results.notice} />
      ) : null}
      <header>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">자연어 검색</h1>
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
          등록 사용자, 현장 게스트, 바이어 모드가 같은 검색 파사드를 사용합니다.
        </p>
      </header>

      <form
        className="flex gap-2"
        action="/search"
      >
        <label htmlFor="search-keyword" className="sr-only">
          검색어
        </label>
        <input
          id="search-keyword"
          name="q"
          type="text"
          defaultValue={q}
          placeholder="예: 친환경 소재, 아웃도어 장비"
          className="flex-1 rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
        <label htmlFor="search-mode" className="sr-only">
          검색 모드
        </label>
        <select
          id="search-mode"
          name="mode"
          defaultValue={mode}
          className="rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        >
          <option value="REGISTERED_WEB">등록</option>
          <option value="GUEST_WEB">게스트</option>
          <option value="BUYER_WEB">바이어</option>
        </select>
        <button
          type="submit"
          className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
        >
          검색
        </button>
      </form>

      {!results ? null : results.data.length === 0 ? (
        <EmptyState
          title={`'${q}'에 대한 검색 결과가 없습니다`}
          description="다른 키워드를 시도하거나 카테고리 목록에서 둘러보세요."
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {results.data.map((result) => (
            <CompanyCard
              key={`${result.company.id}-${result.matchedKeyword}`}
              company={result.company}
              meta={
                <div className="text-xs text-zinc-500 dark:text-zinc-400">
                  {typeof result.score === "number" ? (
                    <p>검색 점수: {Math.round(result.score * 100)}점</p>
                  ) : null}
                  {result.reasons?.length ? <p>{result.reasons.join(", ")}</p> : null}
                </div>
              }
            />
          ))}
        </ul>
      )}
    </div>
  );
}
