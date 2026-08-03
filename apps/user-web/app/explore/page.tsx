"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { ApiClientError, searchApprovedCatalog } from "@/lib/api-client";
import { EVENT_ID, EVENT_ID_IS_CONFIGURED } from "@/lib/onboarding-state";
import type { WebSearchClarification, WebSearchResult } from "@/lib/types";

const QUICK_SEARCHES = ["선물용 전통주", "막걸리 시음", "증류주", "수출 가능한 양조장"];

type SearchState = "idle" | "loading" | "loaded" | "empty" | "error";

function statusLabel(status: WebSearchResult["operating_status"]): string {
  return status === "OPEN" ? "운영 중" : "일시 중단";
}

function SearchResultCard({ result }: { result: WebSearchResult }) {
  return (
    <article
      className="backju-panel border p-4"
      style={{ backgroundColor: "var(--color-surface)", borderColor: "var(--color-border)" }}
    >
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="text-xs font-bold" style={{ color: "var(--color-brand)" }}>
            추천 {result.rank}순위
          </p>
          <h2 className="mt-1 text-lg font-extrabold">{result.name}</h2>
          <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            부스 {result.booth_number}
            {result.zone_name ? ` · ${result.zone_name}` : ""}
          </p>
        </div>
        <span
          className="shrink-0 rounded-full px-3 py-1 text-xs font-bold"
          style={{
            color:
              result.operating_status === "OPEN"
                ? "var(--color-success)"
                : "var(--color-text-muted)",
            backgroundColor: "var(--color-bg)",
          }}
        >
          {statusLabel(result.operating_status)}
        </span>
      </div>

      {result.summary ? <p className="mt-3 text-sm leading-relaxed">{result.summary}</p> : null}

      {result.product_names.length > 0 ? (
        <p className="mt-2 text-sm" style={{ color: "var(--color-text-muted)" }}>
          대표 제품: {result.product_names.slice(0, 3).join(", ")}
        </p>
      ) : null}

      <div
        className="mt-3 rounded-xl border px-3 py-2 text-sm"
        style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
      >
        <span className="font-bold">찾아드린 이유</span>
        <p className="mt-1">{result.reason}</p>
      </div>

      {result.concepts.length > 0 ? (
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="일치한 관심 분야">
          {result.concepts.slice(0, 5).map((concept) => (
            <li
              key={concept}
              className="rounded-full border px-2 py-1 text-xs"
              style={{ borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}
            >
              {concept}
            </li>
          ))}
        </ul>
      ) : null}

      <Link
        href={`/booths/${encodeURIComponent(result.booth_id)}`}
        className="tap-target mt-4 w-full rounded-xl px-4 text-sm font-bold"
        style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
      >
        업체·부스 상세 보기
      </Link>
    </article>
  );
}

export default function ExplorePage() {
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [results, setResults] = useState<WebSearchResult[]>([]);
  const [clarification, setClarification] = useState<WebSearchClarification | null>(null);
  const [state, setState] = useState<SearchState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function runSearch(rawQuery: string) {
    const normalized = rawQuery.trim().replace(/\s+/g, " ");
    if (!normalized) {
      setErrorMessage("찾고 싶은 제품, 업체 또는 방문 목적을 입력해 주세요.");
      setState("error");
      return;
    }
    if (!EVENT_ID_IS_CONFIGURED) {
      setErrorMessage("행사 검색 설정이 아직 연결되지 않았습니다. 운영자에게 문의해 주세요.");
      setState("error");
      return;
    }

    setQuery(normalized);
    setSubmittedQuery(normalized);
    setErrorMessage(null);
    setClarification(null);
    setState("loading");
    try {
      const response = await searchApprovedCatalog({
        event_id: EVENT_ID,
        query: normalized,
        channel: "WEB",
        limit: 12,
      });
      setResults(response.results);
      setClarification(response.clarification);
      setState(response.results.length > 0 ? "loaded" : "empty");
    } catch (error) {
      setResults([]);
      setErrorMessage(
        error instanceof ApiClientError
          ? error.message
          : "검색 결과를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.",
      );
      setState("error");
    }
  }

  function handleSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    void runSearch(query);
  }

  return (
    <div className="mx-auto max-w-screen-content space-y-5 px-4 py-5 md:py-6">
      <header className="backju-hero">
        <div className="backju-hero-content">
          <p className="backju-eyebrow">로그인 없이 바로 검색</p>
          <h1 className="mt-2 text-3xl font-extrabold">어떤 업체를 찾고 계세요?</h1>
          <p className="mt-2 max-w-xl text-sm text-white/90 md:text-base">
            제품명, 방문 목적, 필요한 거래조건을 자연어로 입력해 보세요. 승인된 참가업체만
            검색합니다.
          </p>
        </div>
      </header>
      <p className="backju-asset-credit -mt-3 text-right">
        행사 이미지 출처: {" "}
        <a href="https://www.backju.kr/" target="_blank" rel="noreferrer">
          대한민국 백주대간 공식 홈페이지
        </a>
      </p>

      <form onSubmit={handleSubmit} role="search" className="space-y-3">
        <label htmlFor="guest-search" className="sr-only">
          참가업체와 제품 검색
        </label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            id="guest-search"
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            maxLength={300}
            autoComplete="off"
            placeholder="예: 선물용 전통주를 시음할 수 있는 곳"
            className="min-h-12 flex-1 rounded-none border px-4 text-base"
            style={{ backgroundColor: "var(--color-surface)", borderColor: "var(--color-border)" }}
          />
          <button
            type="submit"
            disabled={state === "loading"}
            className="tap-target min-h-12 rounded-full px-7 text-base font-bold disabled:opacity-60"
            style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
          >
            {state === "loading" ? "찾는 중…" : "검색"}
          </button>
        </div>
      </form>

      <section aria-labelledby="quick-search-heading">
        <h2 id="quick-search-heading" className="backju-section-title text-sm font-bold">
          빠른 검색
        </h2>
        <div className="mt-2 flex flex-wrap gap-2">
          {QUICK_SEARCHES.map((item) => (
            <button
              key={item}
              type="button"
              onClick={() => void runSearch(item)}
              disabled={state === "loading"}
              className="tap-target rounded-full border px-3 text-sm font-semibold disabled:opacity-60"
              style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
            >
              {item}
            </button>
          ))}
        </div>
      </section>

      {state === "loading" ? (
        <div role="status" aria-live="polite" className="space-y-3">
          <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            승인된 참가업체에서 관련 결과를 찾고 있어요.
          </p>
          {[0, 1, 2].map((item) => (
            <div
              key={item}
              className="h-40 animate-pulse rounded-2xl border"
              style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
            />
          ))}
        </div>
      ) : null}

      {state === "error" && errorMessage ? (
        <div
          role="alert"
          className="rounded-2xl border p-4"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
        >
          <p className="font-bold" style={{ color: "var(--color-danger)" }}>
            검색하지 못했어요
          </p>
          <p className="mt-1 text-sm">{errorMessage}</p>
        </div>
      ) : null}

      {state === "empty" ? (
        <section
          className="rounded-2xl border p-4"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
        >
          <h2 className="font-bold">“{submittedQuery}” 검색 결과가 없어요.</h2>
          <p className="mt-1 text-sm" style={{ color: "var(--color-text-muted)" }}>
            {clarification?.question ?? "다른 제품명이나 관심 분야로 다시 검색해 보세요."}
          </p>
          {clarification?.options.length ? (
            <div className="mt-3 flex flex-wrap gap-2">
              {clarification.options.map((option) => (
                <button
                  key={option}
                  type="button"
                  onClick={() => void runSearch(option)}
                  className="tap-target rounded-full border px-3 text-sm font-semibold"
                  style={{ borderColor: "var(--color-border)" }}
                >
                  {option}
                </button>
              ))}
            </div>
          ) : null}
        </section>
      ) : null}

      {state === "loaded" ? (
        <section aria-labelledby="search-results-heading" className="space-y-3">
          <div className="flex items-end justify-between gap-3">
            <div>
              <h2 id="search-results-heading" className="text-lg font-extrabold">
                검색 결과 {results.length}곳
              </h2>
              <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
                “{submittedQuery}” 기준
              </p>
            </div>
            <Link href="/start" className="text-sm font-semibold underline">
              맞춤 추천 시작
            </Link>
          </div>
          <div className="space-y-3">
            {results.map((result) => (
              <SearchResultCard key={result.result_id} result={result} />
            ))}
          </div>
        </section>
      ) : null}

      <p className="pb-2 text-center text-xs" style={{ color: "var(--color-text-muted)" }}>
        앱 설치나 전용 키오스크 없이 현재 브라우저에서 계속 이용할 수 있습니다.
      </p>
    </div>
  );
}
