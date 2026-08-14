"use client";

/**
 * 운영자 AI 추출 검수 큐 (ADMIN-AI-REVIEW, WAVE 2D).
 *
 * 큐 컬럼(업체/문서/문서유형/속성수/충돌/근거누락/업체수정/위험도/제출일)은
 * `features/ai-review/components/QueueTable.tsx`가, 백엔드 계약과 그 공백은
 * `features/ai-review/types.ts` 모듈 docstring이 정본이다. document-structuring.md §4의
 * binding rule(AI_INFERRED 우선 노출)을 기본 정렬로 적용한다.
 *
 * 역할 게이트: EXHIBITOR_REVIEW 능력(EVENT_ADMIN/DATA_REVIEWER)만 접근 가능 - 참가업체
 * 계정에는 이 큐 자체가 보이지 않는다.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import RoleGate from "@/components/RoleGate";

import { claimReviewRequests, listAiReviewQueue } from "@/features/ai-review/api";
import QueueTable from "@/features/ai-review/components/QueueTable";
import { filterQueueRows, sortQueueAiInferredFirst, toQueueRows } from "@/features/ai-review/logic";
import type { AiReviewQueueRow } from "@/features/ai-review/types";

const STATUS_OPTIONS = ["SUBMITTED", "IN_OPERATOR_REVIEW", "CHANGES_REQUESTED", "APPROVED", "REJECTED"];

export default function AiReviewQueuePage() {
  return (
    <RoleGate capability="EXHIBITOR_REVIEW" fallback={<NoAccessNotice />}>
      <QueueBody />
    </RoleGate>
  );
}

function NoAccessNotice() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">AI 콘텐츠 검수 큐</h1>
      <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-text-muted)]">
        현재 역할에는 운영자 검수 권한이 없습니다.
      </p>
    </div>
  );
}

function QueueBody() {
  const [rows, setRows] = useState<AiReviewQueueRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [statusFilter, setStatusFilter] = useState("");
  const [exhibitorFilter, setExhibitorFilter] = useState("");
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [claiming, setClaiming] = useState(false);
  const [claimNotice, setClaimNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    listAiReviewQueue(statusFilter ? { status: statusFilter } : {})
      .then((res) => setRows(toQueueRows(res.items)))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  }, [statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  const visibleRows = useMemo(() => {
    const filtered = filterQueueRows(rows ?? [], {
      status: statusFilter || undefined,
      exhibitorId: exhibitorFilter.trim() || undefined,
    });
    return sortQueueAiInferredFirst(filtered);
  }, [rows, statusFilter, exhibitorFilter]);

  const toggleSelect = useCallback((reviewRequestId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(reviewRequestId)) next.delete(reviewRequestId);
      else next.add(reviewRequestId);
      return next;
    });
  }, []);

  const runClaim = async () => {
    if (selectedIds.size === 0) return;
    setClaiming(true);
    setClaimNotice(null);
    setError(null);
    try {
      const res = await claimReviewRequests([...selectedIds]);
      setClaimNotice(
        `클레임 ${res.claimed.length}건 완료` +
          (res.already_claimed.length > 0 ? `, 이미 다른 운영자가 클레임한 ${res.already_claimed.length}건 제외` : ""),
      );
      setSelectedIds(new Set());
      load();
    } catch (err) {
      setError(err);
    } finally {
      setClaiming(false);
    }
  };

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">AI 콘텐츠 검수 큐</h1>
        <span className="text-xs text-[var(--color-text-muted)]">
          AI 추론 항목이 많은 문서가 먼저 표시됩니다 (document-structuring §4)
        </span>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
          상태 필터
          <select
            aria-label="상태 필터"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value)}
            className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
          >
            <option value="">전체</option>
            {STATUS_OPTIONS.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
          업체 ID 필터
          <input
            aria-label="업체 ID 필터"
            value={exhibitorFilter}
            onChange={(e) => setExhibitorFilter(e.target.value)}
            placeholder="exhibitor_id"
            className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
          />
        </label>
        <button
          type="button"
          onClick={runClaim}
          disabled={claiming || selectedIds.size === 0}
          className="tap-target rounded-md bg-[var(--color-brand)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
        >
          {claiming ? "클레임 중…" : `선택 ${selectedIds.size}건 내가 검수하기`}
        </button>
      </div>

      {claimNotice && (
        <p className="rounded-md bg-[var(--color-success-bg)] p-2 text-xs font-medium text-[var(--color-success)]">
          {claimNotice}
        </p>
      )}

      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {!loading && error != null && <ErrorBanner error={error} onRetry={load} />}
      {!loading && error == null && rows && (
        <QueueTable rows={visibleRows} selectedIds={selectedIds} onToggleSelect={toggleSelect} />
      )}
    </div>
  );
}
