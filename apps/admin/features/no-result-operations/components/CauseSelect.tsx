"use client";

/**
 * 원인 분류 UI (ADMIN-OPERATIONS, WAVE 2E).
 *
 * 운영자가 무응답 질의 1건에 원인(`NoResultCause`)을 수동 지정한다. AI가 원인을 자동
 * 추론·확정하지 않는다는 스펙 불변조건에 따라 이 컴포넌트는 항상 사람의 명시적 선택만
 * 받는다 - 기본값(`UNKNOWN`)을 자동으로 다른 값으로 승격시키는 로직은 없다.
 */

import { CAUSE_LABEL_KO, NO_RESULT_CAUSES } from "../logic";
import type { NoResultCause } from "../types";

export default function CauseSelect({
  value,
  onChange,
  disabled = false,
  label = "원인 분류",
  /** false면 시각적 라벨 텍스트는 생략하고 aria-label만 남긴다 - 표 안에서 열 제목이 이미
   * "원인 분류"를 보여줄 때 행마다 중복 표시하지 않기 위함(접근성 이름은 유지). */
  showLabel = true,
}: {
  value: NoResultCause;
  onChange: (cause: NoResultCause) => void;
  disabled?: boolean;
  label?: string;
  showLabel?: boolean;
}) {
  return (
    <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
      {showLabel && label}
      <select
        aria-label={label}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as NoResultCause)}
        className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm disabled:opacity-50"
      >
        {NO_RESULT_CAUSES.map((cause) => (
          <option key={cause} value={cause}>
            {CAUSE_LABEL_KO[cause]} ({cause})
          </option>
        ))}
      </select>
    </label>
  );
}
