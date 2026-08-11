"use client";

/**
 * 현재 매칭에 적용 중인 하드 필터 칩. 제거하면 해당 조건을 프로파일에서 지우고
 * 매칭을 다시 계산하도록 알린다(작업 지시: "hard-filter chips").
 */

import type { HardFilterChip } from "./api";

export interface HardFilterChipsProps {
  chips: HardFilterChip[];
  onRemove: (chip: HardFilterChip) => void;
  removingCode: string | null;
}

export default function HardFilterChips({ chips, onRemove, removingCode }: HardFilterChipsProps) {
  if (chips.length === 0) {
    return (
      <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
        적용된 조건이 없어요. 바이어 프로파일에서 조건을 추가하면 더 정확한 매칭을 받을 수 있어요.
      </p>
    );
  }

  return (
    <div className="flex flex-wrap gap-2" role="group" aria-label="적용 중인 조건">
      {chips.map((chip) => (
        <button
          key={`${chip.field}-${chip.code}`}
          type="button"
          onClick={() => onRemove(chip)}
          disabled={removingCode === chip.code}
          className="tap-target inline-flex items-center gap-1 rounded-full border px-3 text-sm font-medium disabled:opacity-60"
          style={{ borderColor: "var(--color-brand)", color: "var(--color-brand)" }}
          aria-label={`${chip.label} 조건 제거`}
        >
          {chip.label}
          <span aria-hidden="true">✕</span>
        </button>
      ))}
    </div>
  );
}
