"use client";

/**
 * 자연어 정제 검색창. 작업 지시: "natural-language refine box".
 *
 * `POST /api/v1/search`로 자연어를 개념 코드로 해석해 보여주고, 사용자가 "이 조건으로
 * 다시 찾기"를 눌러야 실제로 매칭에 반영한다(해석 결과를 사용자 확인 없이 바로 적용하지
 * 않음 - AGENTS.md "AI 산출물은 제안이며, 하드 제약·정본 데이터는 사용자/운영자 확인을
 * 거친다"와 동일한 원칙을 검색 정제에도 적용).
 */

import { useState } from "react";

import { ApiClientError } from "@/lib/api-client";

import { refineWithNaturalLanguage } from "./api";

export interface RefineBoxProps {
  eventId: string;
  onApply: (concepts: string[]) => void;
}

export default function RefineBox({ eventId, onApply }: RefineBoxProps) {
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [concepts, setConcepts] = useState<string[]>([]);
  const [clarification, setClarification] = useState<string | null>(null);

  async function handleInterpret() {
    if (!query.trim()) return;
    setLoading(true);
    setError(null);
    try {
      const result = await refineWithNaturalLanguage(eventId, query.trim());
      setConcepts(result.concepts);
      setClarification(result.clarificationQuestion);
    } catch (err) {
      setError(err instanceof ApiClientError ? err.message : "검색어를 해석하지 못했어요.");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div
      className="flex flex-col gap-2 rounded-xl border p-3"
      style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-surface)" }}
    >
      <label className="sr-only" htmlFor="matching-refine-query">
        찾고 있는 조건을 자연어로 입력
      </label>
      <div className="flex gap-2">
        <input
          id="matching-refine-query"
          type="text"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void handleInterpret();
          }}
          placeholder="예) 수도권 편의점 유통 가능한 저도수 증류주"
          className="min-h-[44px] flex-1 rounded-lg border px-3 text-base"
          style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
        />
        <button
          type="button"
          onClick={() => void handleInterpret()}
          disabled={loading || !query.trim()}
          className="tap-target rounded-lg px-4 text-sm font-bold disabled:opacity-60"
          style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
        >
          {loading ? "분석 중..." : "조건 찾기"}
        </button>
      </div>

      {error ? (
        <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
          {error}
        </p>
      ) : null}

      {clarification ? (
        <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
          {clarification}
        </p>
      ) : null}

      {concepts.length > 0 ? (
        <div className="flex flex-col gap-2">
          <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
            이런 조건으로 이해했어요:
          </p>
          <div className="flex flex-wrap gap-2">
            {concepts.map((concept) => (
              <span
                key={concept}
                className="rounded-full border px-2 py-0.5 text-xs font-medium"
                style={{ borderColor: "var(--color-border)" }}
              >
                {concept}
              </span>
            ))}
          </div>
          <button
            type="button"
            onClick={() => onApply(concepts)}
            className="tap-target w-fit rounded-lg border px-3 text-sm font-semibold"
            style={{ borderColor: "var(--color-brand)", color: "var(--color-brand)" }}
          >
            이 조건으로 다시 찾기
          </button>
        </div>
      ) : null}
    </div>
  );
}
