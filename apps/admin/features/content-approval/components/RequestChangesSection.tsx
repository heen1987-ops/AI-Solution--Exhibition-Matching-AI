"use client";

/**
 * 문서(검수요청) 단위 보완요청 - 업체에게 돌려보내며 사유코드가 필수다
 * (작업 지시: "request changes (back to exhibitor) with a reason code").
 * `POST /admin/ai-review/{review_request_id}/request-changes` (`../../ai-review/api.ts`).
 */

import { useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";

import ReasonCodeForm from "./ReasonCodeForm";
import { requestChangesOnDocument } from "../../ai-review/api";

export default function RequestChangesSection({
  reviewRequestId,
  onRequested,
}: {
  reviewRequestId: string;
  onRequested?: (status: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [doneStatus, setDoneStatus] = useState<string | null>(null);

  const run = async (payload: string) => {
    setBusy(true);
    setError(null);
    try {
      const res = await requestChangesOnDocument(reviewRequestId, { comment: payload });
      setDoneStatus(res.status);
      setOpen(false);
      onRequested?.(res.status);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="flex flex-col gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <h2 className="text-sm font-semibold">업체에 보완요청</h2>
      <p className="text-xs text-[var(--color-text-muted)]">
        문서 전체를 업체에게 돌려보냅니다. 사유코드를 반드시 선택해야 합니다.
      </p>
      {doneStatus && (
        <p className="rounded-md bg-[var(--color-success-bg)] p-2 text-xs font-medium text-[var(--color-success)]">
          보완요청이 전송되었습니다. 현재 상태: {doneStatus}
        </p>
      )}
      {error != null && <ErrorBanner error={error} />}
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="tap-target self-start rounded-md border border-[var(--color-warning)] px-3 py-1.5 text-xs font-semibold text-[var(--color-warning)]"
        >
          보완요청 작성
        </button>
      ) : (
        <ReasonCodeForm submitLabel="보완요청 전송" busy={busy} onSubmit={(payload) => run(payload)} onCancel={() => setOpen(false)} />
      )}
    </section>
  );
}
