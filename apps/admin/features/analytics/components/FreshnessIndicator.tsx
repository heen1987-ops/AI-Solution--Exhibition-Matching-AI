"use client";

/**
 * 작업 지시 필수 요소: "데이터 기준 시각 / 집계 지연 가능" 신선도 표시기.
 * 모든 통계 화면 상단에 항상 보이게 렌더링한다.
 */

import { freshnessLabel } from "../logic";

export default function FreshnessIndicator({
  dataAsOf,
  fetchedAt,
}: {
  dataAsOf?: string | null;
  fetchedAt: Date | null;
}) {
  return (
    <p
      data-testid="freshness-indicator"
      className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-3 py-1.5 text-xs text-[var(--color-text-muted)]"
    >
      {fetchedAt
        ? freshnessLabel(dataAsOf ?? null, fetchedAt)
        : "아직 조회 전 · 집계는 실제 활동보다 지연될 수 있습니다"}
    </p>
  );
}
