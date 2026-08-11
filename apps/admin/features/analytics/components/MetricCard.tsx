"use client";

/**
 * 억제 규칙을 아는 단일 지표 카드. suppressed=true면 정확한 수 대신 "5 미만"을
 * 표기하고 이유를 title로 제공한다(소수집단 보호 — 5명 미만 집계 비공개).
 */

import { formatDurationMetric, formatMetric } from "../logic";
import type { Metric } from "../types";

export default function MetricCard({
  label,
  metric,
  percent = false,
  duration = false,
  hint,
}: {
  label: string;
  metric: Metric | null | undefined;
  percent?: boolean;
  duration?: boolean;
  hint?: string;
}) {
  const display = duration ? formatDurationMetric(metric) : formatMetric(metric, { percent });
  const suppressed = Boolean(metric?.suppressed);
  const missing = !metric;
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <p className="text-xs text-[var(--color-text-muted)]">{label}</p>
      <p
        className="mt-1 text-lg font-semibold"
        title={
          suppressed
            ? "5명 미만 소수집단 보호를 위해 정확한 수치를 표시하지 않습니다."
            : undefined
        }
      >
        {missing ? (
          <span className="text-sm font-normal text-[var(--color-text-muted)]">백엔드 미제공</span>
        ) : (
          display
        )}
      </p>
      {hint ? <p className="mt-1 text-xs text-[var(--color-text-muted)]">{hint}</p> : null}
    </div>
  );
}
