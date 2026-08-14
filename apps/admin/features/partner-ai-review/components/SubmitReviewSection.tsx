"use client";

/** 검수 제출 버튼 - PROPOSED(미검토) 항목이 남아있으면 비활성화한다(백엔드
 * `_pending_checks`와 별개로 클라이언트가 선제 방어). `app/partner/ai-review/[documentId]/page.tsx`
 * 에서 분리했다.
 *
 * 2026-08-03 재조정: 실제 착지한 계약은 `POST /partner/extractions/submit-review`
 * (body: `{ document_id }`) -> `SubmitReviewResponse { review_request_id, document_id, status,
 * submitted_at }`이다(`../types.ts` 참고). 이전 버전은 `blocking_issues: string[]`가 성공
 * 응답에 실린다고 가정했지만, 실제로는 실패(422)만 `SubmitReviewRejected { checks: [...] }`로
 * 상세를 담고 성공 응답에는 그런 필드가 없다.
 *
 * 계약 공백(플래그): 공용 `apps/admin/lib/api-client.ts`(owned path 밖, 수정 금지)는 422
 * 본문에서 `code`/`message`만 `ApiClientError`에 싣고 `checks` 배열은 버린다. 그래서 이 화면은
 * 개별 미검토 항목을 나열하지 못하고 백엔드가 준 요약 메시지만 보여준다 - 통합 단계에서
 * `ApiClientError`에 원본 detail을 보존하도록 공용 클라이언트를 확장하는 편이 낫다(그 전까지는
 * 사용자가 위 문서 목록에서 개별 항목의 검수상태 배지를 보고 무엇이 남았는지 확인해야 한다). */

import { useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import RoleGate from "@/components/RoleGate";

import { submitDocumentForReview } from "../api";
import type { SubmitReviewResponse } from "../types";

export default function SubmitReviewSection({
  documentId,
  pendingCount,
}: {
  documentId: string;
  pendingCount: number;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [result, setResult] = useState<SubmitReviewResponse | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const res = await submitDocumentForReview({ document_id: documentId });
      setResult(res);
    } catch (err) {
      setError(err);
    } finally {
      setBusy(false);
    }
  };

  return (
    <RoleGate capability="EXHIBITOR_SUBMIT_OWN">
      <section className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <h2 className="text-base font-semibold">검수 제출</h2>
        <p className="text-xs text-[var(--color-text-muted)]">
          <code>POST /partner/extractions/submit-review</code> (BACKEND-EXTRACTION,
          착지된 계약 - <code>features/partner-ai-review/types.ts</code> 참고).
        </p>
        {pendingCount > 0 && (
          <p className="text-xs text-[var(--color-warning)]">
            아직 검토하지 않은 항목이 {pendingCount}건 있습니다. 모든 항목을 확인/수정/삭제한
            뒤 제출해 주세요.
          </p>
        )}
        {error ? <ErrorBanner error={error} /> : null}
        {result && (
          <div className="rounded-md border border-[var(--color-success)] bg-[var(--color-success-bg)] p-2 text-sm text-[var(--color-success)]">
            제출 완료: {result.status} (검수요청 ID: {result.review_request_id})
          </div>
        )}
        <button
          type="button"
          onClick={() => void submit()}
          disabled={busy || pendingCount > 0}
          className="tap-target w-fit rounded-md bg-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand-contrast)] disabled:opacity-50"
        >
          {busy ? "제출 중…" : "검수 제출"}
        </button>
      </section>
    </RoleGate>
  );
}
