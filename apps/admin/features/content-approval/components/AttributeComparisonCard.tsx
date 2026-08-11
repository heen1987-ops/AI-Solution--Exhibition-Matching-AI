"use client";

/**
 * 속성 1건의 4-way 비교 카드 (작업 지시 필수 요구사항).
 *
 *   1) AI 원제안값  2) 업체 확인·수정값  3) 현재 게시값  4) 운영자 최종값(공개범위 포함)
 *
 * 승인 버튼은 사전조건(`evaluateApprovalPrecondition` -> `row.precondition`)이 전부 통과했을
 * 때만 활성화된다 - 사전조건이 실패하는데 "승인 가능한 것처럼" 버튼을 보여주는 것 자체가
 * 금지다(작업 지시: "the UI must not offer a false approve affordance"). 반려는 사유코드가
 * 필수다(`ReasonCodeForm`).
 */

import { useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";

import ReasonCodeForm from "./ReasonCodeForm";
import { approveExtraction, rejectExtraction } from "../../ai-review/api";
import type { JsonValue, Visibility } from "../../ai-review/types";
import { VISIBILITY_LABEL_KO, VISIBILITY_TIERS } from "../../ai-review/types";
import { failingPreconditions } from "../logic";
import { PRECONDITION_LABEL_KO, type AttributeComparisonRow } from "../types";

export function formatJsonValue(value: JsonValue | null | undefined): string {
  if (value === null || value === undefined) return "(값 없음)";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

const EXHIBITOR_DECISION_LABEL_KO: Record<AttributeComparisonRow["exhibitor_decision"], string> = {
  PENDING: "업체 확인 대기",
  CONFIRMED: "업체 확인함",
  MODIFIED: "업체 수정함",
  REJECTED: "업체 거절함",
};

const FACT_TYPE_LABEL_KO: Record<string, string> = {
  SOURCE_FACT: "문서 근거",
  SELF_DECLARED: "업체 자기신고",
  AI_INFERRED: "AI 추론",
  CALCULATED: "계산값",
  UNKNOWN: "미확인",
};

export default function AttributeComparisonCard({
  row,
  selected,
  onToggleSelect,
  onDecided,
}: {
  row: AttributeComparisonRow;
  selected?: boolean;
  onToggleSelect?: (extractionId: string) => void;
  onDecided: () => void;
}) {
  const extraction = row.extraction;
  const [visibility, setVisibility] = useState<Visibility | "">(row.operator_default_visibility ?? "");
  const [rejecting, setRejecting] = useState(false);
  const [busy, setBusy] = useState<"approve" | "reject" | null>(null);
  const [error, setError] = useState<unknown>(null);

  const approvable = row.precondition.approvable;
  const failures = failingPreconditions(row.precondition);

  const runApprove = async () => {
    setBusy("approve");
    setError(null);
    try {
      await approveExtraction(extraction.extraction_id, {
        // 계약 공백 2번(../../ai-review/types.ts): 최종 공개범위를 확장 필드로 실어 보낸다.
        visibility: visibility || null,
      });
      onDecided();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  const runReject = async (payload: string) => {
    setBusy("reject");
    setError(null);
    try {
      await rejectExtraction(extraction.extraction_id, { reason: payload });
      setRejecting(false);
      onDecided();
    } catch (err) {
      setError(err);
    } finally {
      setBusy(null);
    }
  };

  return (
    <article className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <header className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          {onToggleSelect && (
            <input
              type="checkbox"
              aria-label={`${extraction.attribute_code} 선택`}
              checked={selected ?? false}
              onChange={() => onToggleSelect(extraction.extraction_id)}
            />
          )}
          <h3 className="font-mono text-sm font-semibold">{extraction.attribute_code}</h3>
        </div>
        <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--color-text-muted)]">
          <span>{FACT_TYPE_LABEL_KO[row.fact_type] ?? row.fact_type}</span>
          {row.confidence !== null && <span>신뢰도(참고): {Math.round(row.confidence * 100)}%</span>}
          <span>{row.review_status}</span>
        </div>
      </header>

      {/* ---- 4-way 비교 (작업 지시: 4가지 값 상태를 나란히) ---- */}
      <div className="grid grid-cols-1 gap-2 md:grid-cols-2 xl:grid-cols-4">
        <section className="rounded-md border border-[var(--color-border)] p-2">
          <h4 className="text-xs font-medium text-[var(--color-text-muted)]">1. AI 원제안값</h4>
          <p className="mt-1 break-all text-sm">{formatJsonValue(row.ai_proposed_value)}</p>
        </section>

        <section className="rounded-md border border-[var(--color-border)] p-2">
          <h4 className="text-xs font-medium text-[var(--color-text-muted)]">
            2. 업체 확인·수정값 — {EXHIBITOR_DECISION_LABEL_KO[row.exhibitor_decision]}
          </h4>
          <p className="mt-1 break-all text-sm">
            {row.exhibitor_value !== null
              ? formatJsonValue(row.exhibitor_value)
              : row.exhibitor_decision === "REJECTED"
                ? "(업체가 이 값을 거절함)"
                : "(아직 업체 확인 전)"}
          </p>
        </section>

        <section className="rounded-md border border-[var(--color-border)] p-2">
          <h4 className="text-xs font-medium text-[var(--color-text-muted)]">3. 현재 게시값</h4>
          <p className="mt-1 break-all text-sm">
            {row.published_value_unavailable ? (
              // 계약 공백 1번: 조회 API 자체가 없다 - "게시된 값 없음"으로 단정하지 않는다.
              <span className="text-[var(--color-text-muted)]">게시 이력 조회 API 없음</span>
            ) : (
              formatJsonValue(row.published_value)
            )}
          </p>
        </section>

        <section className="rounded-md border-2 border-[var(--color-brand)] p-2">
          <h4 className="text-xs font-medium text-[var(--color-brand)]">4. 운영자 최종값 (승인 시 게시)</h4>
          <p className="mt-1 break-all text-sm">{formatJsonValue(row.operator_default_value)}</p>
          <label className="mt-2 flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
            최종 공개범위
            <select
              aria-label={`${extraction.attribute_code} 최종 공개범위`}
              value={visibility}
              onChange={(e) => setVisibility(e.target.value as Visibility | "")}
              className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1 text-sm"
            >
              <option value="">공개범위 미지정</option>
              {VISIBILITY_TIERS.map((tier) => (
                <option key={tier} value={tier}>
                  {VISIBILITY_LABEL_KO[tier] ?? tier}
                </option>
              ))}
            </select>
          </label>
        </section>
      </div>

      {/* ---- 근거 ---- */}
      {extraction.evidence.length > 0 ? (
        <details className="rounded-md border border-[var(--color-border)] p-2 text-sm">
          <summary className="cursor-pointer text-xs font-medium text-[var(--color-text-muted)]">
            근거 {extraction.evidence.length}건
          </summary>
          <ul className="mt-2 flex flex-col gap-2">
            {extraction.evidence.map((ev) => (
              <li key={ev.evidence_id} className="rounded bg-[var(--color-surface-muted)] p-2">
                <p className="break-all">&ldquo;{ev.evidence_text}&rdquo;</p>
                <p className="mt-1 text-xs text-[var(--color-text-muted)]">
                  {ev.page_number !== null ? `p.${ev.page_number}` : "페이지 미상"}
                  {ev.section_title ? ` · ${ev.section_title}` : ""}
                </p>
              </li>
            ))}
          </ul>
        </details>
      ) : (
        <p className="text-xs text-[var(--color-text-muted)]">첨부된 근거 인용이 없습니다.</p>
      )}

      {/* ---- 승인 사전조건 체크리스트 ---- */}
      <section aria-label="승인 사전조건" className="rounded-md border border-[var(--color-border)] p-2">
        <h4 className="text-xs font-medium text-[var(--color-text-muted)]">승인 사전조건</h4>
        <ul className="mt-1 flex flex-col gap-0.5 text-xs">
          {row.precondition.results.map((result) => (
            <li
              key={result.code}
              className={result.ok ? "text-[var(--color-success)]" : "font-medium text-[var(--color-danger)]"}
            >
              {result.ok ? "통과" : "미충족"} — {PRECONDITION_LABEL_KO[result.code]}
            </li>
          ))}
        </ul>
      </section>

      {error != null && <ErrorBanner error={error} />}

      {/* ---- 동작 ---- */}
      <footer className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          onClick={runApprove}
          disabled={!approvable || busy !== null}
          title={approvable ? undefined : `승인 불가: ${failures.map((c) => PRECONDITION_LABEL_KO[c]).join(", ")}`}
          className="tap-target rounded-md bg-[var(--color-success)] px-3 py-1.5 text-xs font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
        >
          {busy === "approve" ? "승인 중…" : "승인"}
        </button>
        <button
          type="button"
          onClick={() => setRejecting((v) => !v)}
          disabled={busy !== null}
          className="tap-target rounded-md border border-[var(--color-danger)] px-3 py-1.5 text-xs font-semibold text-[var(--color-danger)] disabled:opacity-50"
        >
          반려
        </button>
        {!approvable && (
          <span className="text-xs text-[var(--color-text-muted)]">
            사전조건 미충족으로 승인이 비활성화되었습니다.
          </span>
        )}
      </footer>

      {rejecting && (
        <ReasonCodeForm
          submitLabel="반려 확정"
          busy={busy === "reject"}
          onSubmit={(payload) => runReject(payload)}
          onCancel={() => setRejecting(false)}
        />
      )}
    </article>
  );
}
