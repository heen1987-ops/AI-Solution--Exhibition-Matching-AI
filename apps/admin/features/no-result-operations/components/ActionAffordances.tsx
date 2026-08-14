"use client";

/**
 * 개선 액션 어포던스 (ADMIN-OPERATIONS, WAVE 2E).
 *
 * `allowedActionsForCause(cause)`가 돌려주는 액션만 버튼으로 노출한다 - 원인과 무관한
 * 액션은 애초에 렌더링되지 않는다. 모든 액션은 "사람에게 가는 요청/플래그"만 만들 뿐
 * 온톨로지·업체 데이터를 직접 수정하지 않는다(`../logic.ts`의 IMPROVEMENT_ACTIONS
 * requires_human/auto_fixes_data 불변조건). 무시 처리(MARK_IGNORED)는 사유 입력 전까지
 * 버튼이 비활성 상태로 남는다(상태머신의 REASON_REQUIRED와 동일 규칙을 클라이언트에서
 * 선제 적용 - 네트워크 호출 이전 이중 방어).
 */

import { useState } from "react";

import { ACTION_LABEL_KO, allowedActionsForCause } from "../logic";
import type { ImprovementActionCode, NoResultCause } from "../types";

const TERMINAL_ACTIONS: ImprovementActionCode[] = ["MARK_RESOLVED", "MARK_IGNORED"];

export default function ActionAffordances({
  cause,
  onAction,
  busy = false,
}: {
  cause: NoResultCause;
  onAction: (action: ImprovementActionCode, note: string | null) => void;
  busy?: boolean;
}) {
  const [note, setNote] = useState("");
  const actions = allowedActionsForCause(cause);
  const trimmedNote = note.trim();

  const handleClick = (action: ImprovementActionCode) => {
    onAction(action, trimmedNote ? trimmedNote : null);
    if (TERMINAL_ACTIONS.includes(action)) {
      setNote("");
    }
  };

  return (
    <div className="flex flex-col gap-2">
      <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
        메모 (무시 처리는 필수, 그 외 액션은 선택)
        <textarea
          aria-label="개선 액션 메모"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          rows={2}
          className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
        />
      </label>
      <div className="flex flex-wrap gap-2">
        {actions.map((action) => {
          const requiresNote = action === "MARK_IGNORED";
          const disabled = busy || (requiresNote && !trimmedNote);
          const isTerminal = TERMINAL_ACTIONS.includes(action);
          return (
            <button
              key={action}
              type="button"
              onClick={() => handleClick(action)}
              disabled={disabled}
              className={`tap-target rounded-md px-2.5 py-1.5 text-xs font-medium disabled:opacity-50 ${
                action === "MARK_IGNORED"
                  ? "border border-[var(--color-danger)] text-[var(--color-danger)]"
                  : action === "MARK_RESOLVED"
                    ? "bg-[var(--color-brand)] text-white"
                    : "border border-[var(--color-border)] hover:bg-[var(--color-surface-muted)]"
              }`}
            >
              {ACTION_LABEL_KO[action]}
              {isTerminal ? "" : " 요청"}
            </button>
          );
        })}
      </div>
    </div>
  );
}
