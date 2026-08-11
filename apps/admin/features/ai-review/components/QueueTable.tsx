"use client";

/**
 * 운영자 AI 검수 큐 테이블 (ADMIN-AI-REVIEW, WAVE 2D).
 *
 * 작업 지시가 요구한 컬럼: 업체, 문서, 문서유형, 속성수, 충돌수, 근거누락수, 업체수정수,
 * 위험도, 제출일. 백엔드(`AdminReviewQueueItem`)가 아직 주지 않는 컬럼(`../types.ts` 계약
 * 공백 4번)은 값을 지어내지 않고 "상세보기 필요"로 명시한다 - "0건"과 "아직 모름"을 화면이
 * 혼동시키지 않는 것이 원칙이다.
 */

import Link from "next/link";

import { RISK_INDICATOR_LABEL_KO } from "../logic";
import type { AiReviewQueueRow } from "../types";

const QUEUE_STATUS_LABEL_KO: Record<string, string> = {
  SUBMITTED: "제출됨",
  IN_OPERATOR_REVIEW: "검수중",
  CHANGES_REQUESTED: "보완요청",
  APPROVED: "승인",
  REJECTED: "반려",
};

const RISK_TONE: Record<AiReviewQueueRow["risk_indicator"], string> = {
  HIGH: "bg-[var(--color-danger-bg)] text-[var(--color-danger)]",
  MEDIUM: "bg-[var(--color-warning-bg)] text-[var(--color-warning)]",
  LOW: "bg-[var(--color-success-bg)] text-[var(--color-success)]",
};

/** null = 백엔드가 아직 제공하지 않는 컬럼 - "상세보기 필요"로 표시(계약 공백 4번). */
function unknownOrCount(value: number | null, unit = "건"): string {
  return value === null ? "상세보기 필요" : `${value}${unit}`;
}

function formatDate(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().slice(0, 10);
}

export default function QueueTable({
  rows,
  selectedIds,
  onToggleSelect,
}: {
  rows: AiReviewQueueRow[];
  selectedIds?: Set<string>;
  onToggleSelect?: (reviewRequestId: string) => void;
}) {
  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-text-muted)]">
        검수 대기 중인 문서가 없습니다.
      </p>
    );
  }

  const selectable = !!onToggleSelect;

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
      <table className="w-full min-w-[880px] text-left text-sm">
        <thead className="bg-[var(--color-surface-muted)] text-xs text-[var(--color-text-muted)]">
          <tr>
            {selectable && <th className="px-3 py-2">선택</th>}
            <th className="px-3 py-2">업체</th>
            <th className="px-3 py-2">문서</th>
            <th className="px-3 py-2">문서유형</th>
            <th className="px-3 py-2">상태</th>
            <th className="px-3 py-2">대기 속성</th>
            <th className="px-3 py-2">AI 추론</th>
            <th className="px-3 py-2">충돌</th>
            <th className="px-3 py-2">근거누락</th>
            <th className="px-3 py-2">업체수정</th>
            <th className="px-3 py-2">위험도</th>
            <th className="px-3 py-2">제출일</th>
            <th className="px-3 py-2">동작</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.review_request_id} className="border-t border-[var(--color-border)]">
              {selectable && (
                <td className="px-3 py-2">
                  <input
                    type="checkbox"
                    aria-label={`${row.review_request_id} 선택`}
                    checked={selectedIds?.has(row.review_request_id) ?? false}
                    onChange={() => onToggleSelect?.(row.review_request_id)}
                  />
                </td>
              )}
              <td className="px-3 py-2 font-mono text-xs">
                {/* TODO(BACKEND-EXTRACTION 재조정): 큐 응답에 표시용 업체명이 없어 id를 보여준다. */}
                {row.exhibitor_name ?? row.exhibitor_id}
              </td>
              <td className="px-3 py-2 font-mono text-xs">{row.document_id ?? "-"}</td>
              <td className="px-3 py-2">{row.document_type ?? "상세보기 필요"}</td>
              <td className="px-3 py-2">{QUEUE_STATUS_LABEL_KO[row.status] ?? row.status}</td>
              <td className="px-3 py-2">대기 {row.pending_extraction_count}건</td>
              <td className="px-3 py-2">{row.ai_inferred_count}건</td>
              <td className="px-3 py-2">
                {row.has_unresolved_conflict ? (
                  <span className="font-medium text-[var(--color-danger)]">미해결 충돌</span>
                ) : (
                  "없음"
                )}
              </td>
              <td className="px-3 py-2 text-[var(--color-text-muted)]">
                {unknownOrCount(row.evidence_missing_count)}
              </td>
              <td className="px-3 py-2 text-[var(--color-text-muted)]">
                {unknownOrCount(row.exhibitor_modified_count)}
              </td>
              <td className="px-3 py-2">
                <span
                  className={`inline-flex rounded-full px-2 py-0.5 text-xs font-medium ${RISK_TONE[row.risk_indicator]}`}
                >
                  {RISK_INDICATOR_LABEL_KO[row.risk_indicator]}
                </span>
              </td>
              <td className="px-3 py-2">{formatDate(row.submitted_at)}</td>
              <td className="px-3 py-2">
                {row.document_id ? (
                  <Link
                    href={`/ai-review/${encodeURIComponent(row.review_request_id)}?document_id=${encodeURIComponent(row.document_id)}`}
                    className="rounded-md border border-[var(--color-border)] px-2.5 py-1 text-xs font-medium hover:bg-[var(--color-surface-muted)]"
                  >
                    검수
                  </Link>
                ) : (
                  <span className="text-xs text-[var(--color-text-muted)]">문서 없음</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
