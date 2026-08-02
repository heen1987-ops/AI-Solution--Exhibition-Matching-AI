import type { ReactNode } from "react";

/** 폼 라벨+입력 묶음 공용 컴포넌트. `.input` 유틸리티 클래스(app/globals.css)와 짝을 이룬다. */
export default function Field({
  label,
  hint,
  required,
  children,
}: {
  label: string;
  hint?: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="font-medium">
        {label}
        {required && <span className="text-[var(--color-danger)]"> *</span>}
      </span>
      {children}
      {hint && <span className="text-xs text-[var(--color-text-muted)]">{hint}</span>}
    </label>
  );
}
