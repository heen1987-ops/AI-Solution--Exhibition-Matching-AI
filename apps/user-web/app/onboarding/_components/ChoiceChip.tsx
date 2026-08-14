"use client";

/**
 * 온보딩 선택형 질문 공용 칩 버튼.
 *
 * 근거: docs/user-ia-wireframes.md 9.1절 `ChoiceChipGroup` 컴포넌트, 13.2절 접근성
 * 완료 조건(터치 영역 44x44px 이상, 색상만으로 선택 상태를 구분하지 않음 - 배경색과 함께
 * `aria-pressed`·체크 아이콘 텍스트를 병행한다).
 */

export interface ChoiceChipProps {
  label: string;
  selected: boolean;
  onClick: () => void;
  disabled?: boolean;
}

export default function ChoiceChip({ label, selected, onClick, disabled = false }: ChoiceChipProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      aria-pressed={selected}
      className="tap-target rounded-full border px-4 py-2 text-sm font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-40"
      style={{
        backgroundColor: selected ? "var(--color-brand)" : "var(--color-bg)",
        color: selected ? "var(--color-brand-contrast)" : "var(--color-text)",
        borderColor: selected ? "var(--color-brand)" : "var(--color-border)",
      }}
    >
      {selected ? <span aria-hidden="true">✓ </span> : null}
      {label}
    </button>
  );
}
