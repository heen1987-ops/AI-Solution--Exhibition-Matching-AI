"use client";

import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";
import { MOCK_CATEGORIES } from "@/lib/mock/exhibitors";

/**
 * K-S3 검색 진입 화면 골격(카테고리 / 자연어 검색).
 *
 * 허용되는 유일한 텍스트 입력은 "현재 자연어 질의"뿐이다
 * (K-1-service-scope.md §2: 키오스크의 유일한 입력은 (a) 자연어 질의,
 * (b) 디바이스 설치 위치, (c) 언어 선택). 이름/연락처/로그인 계정 등
 * 개인정보 입력 필드는 두지 않는다 - `type="search"`이고 검색어 그 자체만
 * 다루며 서버로 전송하지도 않는다(이번 웨이브는 Mock, 실제 검색 API 미연동).
 */
export function SearchScreen() {
  const router = useRouter();
  const [query, setQuery] = useState("");

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    // 이번 웨이브는 실제 자연어 검색 API(C-4)를 호출하지 않는다 - Mock 결과 화면으로만 이동.
    router.push("/results");
  };

  return (
    <main
      data-testid="screen-search"
      className="flex min-h-screen flex-col gap-10 bg-slate-950 px-8 py-16 text-white"
    >
      <header className="text-center">
        <h1 className="text-kiosk-lg font-bold">무엇을 찾고 계신가요?</h1>
        <p className="mt-2 text-kiosk text-slate-300">
          카테고리를 선택하거나 자연어로 검색해보세요
        </p>
      </header>

      <form onSubmit={handleSubmit} className="flex gap-3">
        <label htmlFor="kiosk-search-query" className="sr-only">
          검색어
        </label>
        <input
          id="kiosk-search-query"
          type="search"
          name="q"
          inputMode="search"
          autoComplete="off"
          placeholder="예: 아이와 함께 체험할 수 있는 전통공예 부스"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="min-h-touch flex-1 rounded-2xl bg-slate-800 px-6 text-kiosk placeholder:text-slate-500"
        />
        <button
          type="submit"
          className="min-h-touch rounded-2xl bg-emerald-500 px-8 text-kiosk-lg font-semibold text-slate-950"
        >
          검색
        </button>
      </form>

      <div>
        <p className="mb-3 text-sm uppercase tracking-widest text-slate-400">
          인기 카테고리
        </p>
        <div className="flex flex-wrap gap-3">
          {MOCK_CATEGORIES.map((category) => (
            <Link
              key={category}
              href="/results"
              className="min-h-touch rounded-full bg-slate-800 px-6 py-3 text-kiosk font-medium"
            >
              {category}
            </Link>
          ))}
        </div>
      </div>
    </main>
  );
}
