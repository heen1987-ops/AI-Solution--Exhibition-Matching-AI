"use client";

/**
 * 바이어 검증 행 1건의 동작 패널. 작업 지시 필수 요구사항을 모두 구현한다:
 *   - 상태전이 가드레일: `../logic.ts`의 상태머신이 허용하는 동작 버튼만 노출한다(예:
 *     VERIFIED 상태에는 검증승인/제한/반려 버튼이 아예 없다).
 *   - 사유 필수: 모든 동작에 사유 textarea가 있고, validateReason을 통과해야 버튼이
 *     활성화된다. 서버 계약이 아직 없어도(TODO, ../api.ts 참고) 이 가드레일 자체는 지금
 *     검증 가능하다.
 *   - 역할 게이트: canManageBuyerVerification(role)이 false면 버튼을 렌더링하지 않고 안내
 *     문구만 보여준다(호출부인 app/buyers/page.tsx도 큐 자체를 먼저 게이트하지만, "프론트만
 *     믿지 말 것" 원칙을 이 컴포넌트 경계에서도 한 번 더 지킨다).
 */

import { useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import { useSession } from "@/lib/use-session";

import { decideBuyerVerification } from "../api";
import {
  BUYER_VERIFICATION_ACTION_LABEL_KO,
  allowedActions,
  canManageBuyerVerification,
  validateReason,
} from "../logic";
import type { BuyerVerificationAction, BuyerVerificationQueueItem } from "../types";

const ACTION_TONE: Record<BuyerVerificationAction, string> = {
  VERIFY: "bg-[var(--color-success)] text-white",
  LIMIT: "border border-[var(--color-warning)] text-[var(--color-warning)]",
  REJECT: "bg-[var(--color-danger)] text-white",
  SUSPEND: "bg-[var(--color-danger)] text-white",
  EXPIRE: "border border-[var(--color-border)] text-[var(--color-text)]",
};

export default function VerificationActions({
  item,
  onDecided,
}: {
  item: BuyerVerificationQueueItem;
  onDecided: () => void;
}) {
  const [session] = useSession();
  const [reason, setReason] = useState("");
  const [busyAction, setBusyAction] = useState<BuyerVerificationAction | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [message, setMessage] = useState<string | null>(null);

  if (!canManageBuyerVerification(session.role)) {
    return (
      <p className="text-sm text-[var(--color-text-muted)]">
        현재 역할({session.role})에는 바이어 검증 처리 권한이 없습니다.
      </p>
    );
  }

  const actions = allowedActions(item.verification_status);
  const reasonCheck = validateReason(reason);

  if (actions.length === 0) {
    return (
      <p className="text-sm text-[var(--color-text-muted)]">
        현재 상태({item.verification_status})에서는 추가로 처리할 수 있는 동작이 없습니다.
      </p>
    );
  }

  const runAction = async (action: BuyerVerificationAction) => {
    setBusyAction(action);
    setError(null);
    setMessage(null);
    try {
      const res = await decideBuyerVerification(item.buyer_profile_id, { action, reason });
      setMessage(`${BUYER_VERIFICATION_ACTION_LABEL_KO[action]} 처리되었습니다 (${res.decided_at}).`);
      setReason("");
      onDecided();
    } catch (err) {
      setError(err);
    } finally {
      setBusyAction(null);
    }
  };

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-muted)] p-3">
      {error ? <ErrorBanner error={error} /> : null}
      {message && (
        <p className="rounded-md border border-[var(--color-success)] bg-[var(--color-success-bg)] p-2 text-sm text-[var(--color-success)]">
          {message}
        </p>
      )}

      <label className="flex flex-col gap-1 text-sm">
        <span className="font-medium">
          처리 사유 <span className="text-[var(--color-danger)]">*</span>
        </span>
        <textarea
          value={reason}
          onChange={(event) => setReason(event.target.value)}
          className="input"
          rows={2}
          placeholder="검증/제한/반려/정지/만료 처리 사유를 입력해야 버튼이 활성화됩니다 (5자 이상)."
        />
        {!reasonCheck.ok && reason.length > 0 && (
          <span className="text-xs text-[var(--color-danger)]">{reasonCheck.message}</span>
        )}
      </label>

      <div className="flex flex-wrap gap-2">
        {actions.map((action) => (
          <button
            key={action}
            type="button"
            disabled={busyAction !== null || !reasonCheck.ok}
            onClick={() => void runAction(action)}
            className={`tap-target rounded-md px-3 py-2 text-sm font-medium disabled:opacity-50 ${ACTION_TONE[action]}`}
          >
            {busyAction === action ? "처리 중…" : BUYER_VERIFICATION_ACTION_LABEL_KO[action]}
          </button>
        ))}
      </div>
    </div>
  );
}
