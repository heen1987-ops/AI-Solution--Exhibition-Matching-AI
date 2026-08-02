"use client";

import { useMemo, useState } from "react";
import { CompanyCard } from "@/components/CompanyCard";
import { MockDataBanner } from "@/components/MockDataBanner";
import { EmptyState } from "@/components/StateViews";
import { searchCompaniesByKeyword } from "@/lib/mock-api";

/**
 * S-3. 자연어 검색. GENERAL_REGISTERED/BUYER_REGISTERED만 활성 - GUEST_WEB은
 * W-3 §S-3 결정에 따라 기본 비활성화된다(마스터 스펙 §23.3 미언급, MVP 기본값
 * "비활성"). 이번 Wave는 실제 자연어 의도 추출(C-2/C-4) 없이 태그·이름 기준
 * 클라이언트 필터링만 흉내낸다.
 */
export default function SearchPage() {
  const [keyword, setKeyword] = useState("");
  const [submitted, setSubmitted] = useState("");

  const results = useMemo(() => searchCompaniesByKeyword(submitted), [submitted]);

  return (
    <div className="flex flex-col gap-6">
      <MockDataBanner />
      <header>
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">자연어 검색</h1>
        <p className="mt-1 text-xs text-zinc-500 dark:text-zinc-400">
          GUEST_WEB 사용자에게는 이 화면이 기본적으로 비활성화됩니다(W-3 §S-3). 실제 자연어
          의도 추출은 공통 AI 플랫폼(C-2) 연동 후 제공됩니다 - 지금은 이름·카테고리·태그
          일치만 검색합니다.
        </p>
      </header>

      <form
        className="flex gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          setSubmitted(keyword);
        }}
      >
        <label htmlFor="search-keyword" className="sr-only">
          검색어
        </label>
        <input
          id="search-keyword"
          name="keyword"
          type="text"
          value={keyword}
          onChange={(event) => setKeyword(event.target.value)}
          placeholder="예: 친환경 소재, 아웃도어 장비"
          className="flex-1 rounded-md border border-zinc-300 px-3 py-2 text-sm dark:border-zinc-700 dark:bg-zinc-900"
        />
        <button
          type="submit"
          className="rounded-md bg-zinc-900 px-4 py-2 text-sm font-medium text-white dark:bg-zinc-100 dark:text-zinc-900"
        >
          검색
        </button>
      </form>

      {submitted === "" ? null : results.length === 0 ? (
        <EmptyState
          title={`'${submitted}'에 대한 검색 결과가 없습니다`}
          description="다른 키워드를 시도하거나 카테고리 목록에서 둘러보세요."
        />
      ) : (
        <ul className="flex flex-col gap-3">
          {results.map((result) => (
            <CompanyCard key={result.company.id} company={result.company} />
          ))}
        </ul>
      )}
    </div>
  );
}
