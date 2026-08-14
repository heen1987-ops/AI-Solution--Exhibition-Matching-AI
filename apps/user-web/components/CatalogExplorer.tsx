"use client";

import Link from "next/link";
import { type FormEvent, useState } from "react";

import { ApiClientError, searchApprovedCatalog } from "@/lib/api-client";
import { EVENT_ID, EVENT_ID_IS_CONFIGURED } from "@/lib/onboarding-state";
import type { WebSearchClarification, WebSearchResult } from "@/lib/types";

const QUICK_SEARCHES = [
  "우리술 시음",
  "막걸리",
  "증류주 선물",
  "발효·유통 기술",
  "지역 음식·관광",
];

type SearchState = "idle" | "loading" | "loaded" | "empty" | "error";

interface CatalogExplorerProps {
  embedded?: boolean;
}

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
            검색 {result.rank}순위
          </p>
          <h3 className="mt-1 text-lg font-extrabold">{result.name}</h3>
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
        <ul className="mt-3 flex flex-wrap gap-2" aria-label="일치한 탐색 조건">
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

export default function CatalogExplorer({ embedded = false }: CatalogExplorerProps) {
  const [query, setQuery] = useState("");
  const [submittedQuery, setSubmittedQuery] = useState("");
  const [results, setResults] = useState<WebSearchResult[]>([]);
  const [clarification, setClarification] = useState<WebSearchClarification | null>(null);
  const [state, setState] = useState<SearchState>("idle");
  const [errorMessage, setErrorMessage] = useState<string | null>(null);

  async function runSearch(rawQuery: string) {
    const normalized = rawQuery.trim().replace(/\s+/g, " ");
    if (!normalized) {
      setErrorMessage("찾고 싶은 제품, 맛, 업체 또는 방문 목적을 입력해 주세요.");
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
        limit: embedded ? 6 : 12,
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
    <section
      id="catalog-explorer"
      aria-labelledby="catalog-explorer-heading"
      className={embedded ? "backju-panel border p-5 md:p-7" : "space-y-5"}
      style={
        embedded
          ? { borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }
          : undefined
      }
    >
      {embedded ? (
        <div>
          <p className="backju-eyebrow" style={{ color: "var(--color-brand)" }}>
            EXPLORE NOW
          </p>
          <h2 id="catalog-explorer-heading" className="backju-section-title mt-1 text-xl font-extrabold">
            원하는 업체 바로 찾기
          </h2>
          <p className="mt-2 text-sm leading-6" style={{ color: "var(--color-text-muted)" }}>
            제품, 맛, 시음 여부나 방문 목적을 입력하면 현재 탐색 결과를 바로 좁혀드립니다.
          </p>
        </div>
      ) : (
        <header className="backju-hero">
          <div className="backju-hero-content">
            <p className="backju-eyebrow">로그인 없이 바로 검색</p>
            <h1 id="catalog-explorer-heading" className="mt-2 text-3xl font-extrabold">
              어떤 업체를 찾고 계세요?
            </h1>
            <p className="mt-2 max-w-xl text-sm text-white/90 md:text-base">
              제품명, 맛, 방문 목적이나 필요한 거래조건을 입력해 보세요. 승인된 참가업체만
              검색합니다.
            </p>
          </div>
        </header>
      )}

      <form onSubmit={handleSubmit} role="search" className="mt-4 space-y-3">
        <label htmlFor={embedded ? "home-catalog-search" : "catalog-search"} className="sr-only">
          참가업체와 제품 검색
        </label>
        <div className="flex flex-col gap-2 sm:flex-row">
          <input
            id={embedded ? "home-catalog-search" : "catalog-search"}
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
            {state === "loading" ? "찾는 중…" : "업체 찾기"}
          </button>
        </div>
      </form>

      <div className="mt-3 flex flex-wrap gap-2" aria-label="빠른 탐색 조건">
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

      <p className="mt-3 text-xs leading-5" style={{ color: "var(--color-text-muted)" }}>
        입력한 내용은 이번 탐색에만 사용됩니다. 기존 사전등록 관심정보나 장기 추천 기준은
        자동으로 바뀌지 않습니다.
      </p>

      {state === "loading" ? (
        <div role="status" aria-live="polite" className="mt-5 space-y-3">
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
          className="mt-5 rounded-2xl border p-4"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
        >
          <p className="font-bold" style={{ color: "var(--color-danger)" }}>
            검색하지 못했어요
          </p>
          <p className="mt-1 text-sm">{errorMessage}</p>
        </div>
      ) : null}

      {state === "empty" ? (
        <div
          className="mt-5 rounded-2xl border p-4"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
        >
          <h3 className="font-bold">“{submittedQuery}” 검색 결과가 없어요.</h3>
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
        </div>
      ) : null}

      {state === "loaded" ? (
        <div className="mt-5 space-y-3" aria-live="polite">
          <div className="flex items-end justify-between gap-3">
            <div>
              <h3 className="text-lg font-extrabold">검색 결과 {results.length}곳</h3>
              <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
                “{submittedQuery}” 기준
              </p>
            </div>
            {embedded ? (
              <Link href="/explore" className="text-sm font-semibold underline">
                탐색 화면 열기
              </Link>
            ) : null}
          </div>
          <div className="space-y-3">
            {results.map((result) => (
              <SearchResultCard key={result.result_id} result={result} />
            ))}
          </div>
        </div>
      ) : null}
    </section>
  );
}
