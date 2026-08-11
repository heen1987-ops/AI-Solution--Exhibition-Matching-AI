"use client";

/**
 * 완성도 점수 배지. 점수(0..100)만 표시하고 산식은 절대 여기서 다시 계산하지 않는다
 * (`../logic.ts::computeCompletenessScore`가 유일한 산식 소스 - 이 컴포넌트는 결과만 렌더).
 */

import type { CompletenessScore } from "../types";

function tone(score: number): "danger" | "warning" | "success" {
  if (score < 40) return "danger";
  if (score < 75) return "warning";
  return "success";
}

const TONE_CLASS: Record<string, string> = {
  danger: "bg-[var(--color-danger-bg)] text-[var(--color-danger)]",
  warning: "bg-[var(--color-warning-bg)] text-[var(--color-warning)]",
  success: "bg-[var(--color-success-bg)] text-[var(--color-success)]",
};

export default function CompletenessBadge({
  completeness,
  showBreakdown = false,
}: {
  completeness: CompletenessScore;
  showBreakdown?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      <span
        className={`inline-flex w-fit items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-semibold ${TONE_CLASS[tone(completeness.score)]}`}
      >
        완성도 {completeness.score}점
      </span>
      {showBreakdown && (
        <ul className="text-[10px] text-[var(--color-text-muted)]">
          {completeness.factors.map((f) => (
            <li key={f.factor}>
              {f.factor}: {Math.round(f.attainment * 100)}% (가중치 {f.weight})
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
