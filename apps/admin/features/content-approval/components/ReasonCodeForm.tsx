"use client";

/**
 * 반려/보완요청 공용 사유코드 폼 (작업 지시: "reason-code required on reject/request-changes").
 *
 * 사유코드 9종(`../types.ts` REASON_CODES)을 select로 강제하고, 검증(`validateReasonSelection`)을
 * 통과하기 전에는 onSubmit을 절대 호출하지 않는다. 백엔드가 아직 구조화된 reason_code 필드를
 * 받지 않으므로(`../../ai-review/types.ts` 계약 공백 3번) 제출 시 `composeReasonPayload`로
 * 합성한 자유서술 문자열을 함께 넘긴다.
 */

import { useState } from "react";

import { composeReasonPayload, validateReasonSelection } from "../logic";
import { REASON_CODES, REASON_CODE_LABEL_KO, isReasonCode, type ReasonCode } from "../types";

export default function ReasonCodeForm({
  submitLabel,
  busy = false,
  onSubmit,
  onCancel,
}: {
  submitLabel: string;
  busy?: boolean;
  /** payload = `[CODE] 라벨 - 코멘트` 합성 문자열(백엔드 자유서술 필드에 그대로 들어간다). */
  onSubmit: (payload: string, reasonCode: ReasonCode, comment: string) => void;
  onCancel?: () => void;
}) {
  const [reasonCode, setReasonCode] = useState<ReasonCode | "">("");
  const [comment, setComment] = useState("");
  const [validationMessage, setValidationMessage] = useState<string | null>(null);

  const handleSubmit = () => {
    const validation = validateReasonSelection(reasonCode, comment);
    if (!validation.ok) {
      setValidationMessage(validation.message);
      return;
    }
    setValidationMessage(null);
    // validateReasonSelection이 통과했으므로 reasonCode는 반드시 ReasonCode다.
    onSubmit(composeReasonPayload(reasonCode as ReasonCode, comment), reasonCode as ReasonCode, comment);
  };

  return (
    <div className="flex flex-col gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-muted)] p-3">
      <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
        사유코드 (필수)
        <select
          aria-label="사유코드"
          value={reasonCode}
          onChange={(e) => {
            const next = e.target.value;
            setReasonCode(isReasonCode(next) ? next : "");
          }}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
        >
          <option value="">사유코드를 선택하세요</option>
          {REASON_CODES.map((code) => (
            <option key={code} value={code}>
              {REASON_CODE_LABEL_KO[code]} ({code})
            </option>
          ))}
        </select>
      </label>
      <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
        상세 코멘트{reasonCode === "OTHER" ? " (기타 사유는 필수)" : " (선택)"}
        <textarea
          aria-label="사유 코멘트"
          value={comment}
          onChange={(e) => setComment(e.target.value)}
          rows={2}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
        />
      </label>
      {validationMessage && (
        <p role="alert" className="text-xs font-medium text-[var(--color-danger)]">
          {validationMessage}
        </p>
      )}
      <div className="flex gap-2">
        <button
          type="button"
          onClick={handleSubmit}
          disabled={busy}
          className="tap-target rounded-md bg-[var(--color-danger)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
        >
          {busy ? "처리 중…" : submitLabel}
        </button>
        {onCancel && (
          <button
            type="button"
            onClick={onCancel}
            disabled={busy}
            className="tap-target rounded-md border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium"
          >
            취소
          </button>
        )}
      </div>
    </div>
  );
}
