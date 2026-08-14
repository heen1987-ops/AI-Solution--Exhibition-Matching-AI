"use client";

/**
 * 취소 흐름 - 사유를 먼저 고르게 하고, 확정 버튼을 한 번 더 눌러야 실제 취소가 실행된다
 * (돌이킬 수 없는 액션을 실수로 누르지 않도록 하는 2단계 확인).
 */

import { useState } from "react";

import { CANCEL_REASON_OPTIONS } from "../constants";

export interface CancelDialogProps {
  isActing: boolean;
  confirmLabel: string;
  onConfirmCancel: (reasonCode: string) => void;
}

export default function CancelDialog({ isActing, confirmLabel, onConfirmCancel }: CancelDialogProps) {
  const [open, setOpen] = useState(false);
  const [reasonCode, setReasonCode] = useState<string>(CANCEL_REASON_OPTIONS[0].code);

  if (!open) {
    return (
      <button
        type="button"
        onClick={() => setOpen(true)}
        className="tap-target w-fit rounded-lg border px-5 py-3 text-sm font-semibold"
        style={{ borderColor: "var(--color-border)", color: "var(--color-danger)" }}
      >
        {confirmLabel}
      </button>
    );
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border p-3" style={{ borderColor: "var(--color-border)" }}>
      <p className="text-sm font-medium">취소 사유를 선택해 주세요</p>
      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="취소 사유">
        {CANCEL_REASON_OPTIONS.map((option) => (
          <button
            key={option.code}
            type="button"
            role="radio"
            aria-checked={reasonCode === option.code}
            onClick={() => setReasonCode(option.code)}
            className="tap-target rounded-full border px-3 py-2 text-sm"
            style={{
              borderColor: reasonCode === option.code ? "var(--color-brand)" : "var(--color-border)",
              backgroundColor: reasonCode === option.code ? "var(--color-brand)" : "var(--color-surface)",
              color: reasonCode === option.code ? "var(--color-brand-contrast)" : "var(--color-text)",
            }}
          >
            {option.label}
          </button>
        ))}
      </div>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={() => setOpen(false)}
          disabled={isActing}
          className="tap-target rounded-lg border px-4 py-2 text-sm disabled:opacity-60"
          style={{ borderColor: "var(--color-border)" }}
        >
          돌아가기
        </button>
        <button
          type="button"
          onClick={() => onConfirmCancel(reasonCode)}
          disabled={isActing}
          className="tap-target rounded-lg px-4 py-2 text-sm font-semibold disabled:opacity-60"
          style={{ backgroundColor: "var(--color-danger)", color: "#ffffff" }}
        >
          {isActing ? "처리 중..." : `${confirmLabel} 확정`}
        </button>
      </div>
    </div>
  );
}
