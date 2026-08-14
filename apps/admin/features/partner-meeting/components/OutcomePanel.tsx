"use client";

/**
 * E-04 상담결과·후속조치. POST /partner/meetings/{id}/outcome.
 *
 * "완료 처리(mark complete)"는 별도 액션이 아니라 meetings.py `record_meeting_outcome`이
 * status가 accepted일 때 자동으로 completed로 전이시키는 부수효과다(작업 지시 "mark
 * complete"에 대응) - 그래서 이 패널은 결과 기록 폼 하나만 제공한다.
 */

import { useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";

import { recordMeetingOutcome } from "../api";
import { FOLLOW_UP_CODES, OUTCOME_CODES } from "../logic";
import type { MeetingOutcomeResponse } from "../types";

const OUTCOME_ELIGIBLE_STATUSES = new Set(["accepted", "completed"]);

export default function OutcomePanel({
  meetingId,
  status,
  onRecorded,
}: {
  meetingId: string;
  status: string;
  onRecorded: (result: MeetingOutcomeResponse) => void;
}) {
  const [outcomeCode, setOutcomeCode] = useState(OUTCOME_CODES[0]?.code ?? "");
  const [isQualifiedLead, setIsQualifiedLead] = useState(false);
  const [memo, setMemo] = useState("");
  const [followUpCode, setFollowUpCode] = useState("");
  const [followUpDueDate, setFollowUpDueDate] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<MeetingOutcomeResponse | null>(null);

  if (!OUTCOME_ELIGIBLE_STATUSES.has(status)) {
    return (
      <div className="rounded-lg border border-[var(--color-border)] p-4">
        <h2 className="text-base font-semibold">상담 결과 · 후속조치</h2>
        <p className="mt-2 text-sm text-[var(--color-text-muted)]">
          확정(accepted) 또는 완료(completed) 상태에서만 상담 결과를 기록할 수 있습니다.
        </p>
      </div>
    );
  }

  async function submit() {
    setSubmitting(true);
    setError(null);
    try {
      const res = await recordMeetingOutcome(meetingId, {
        outcome_code: outcomeCode,
        is_qualified_lead: isQualifiedLead,
        memo: memo || undefined,
        follow_up: followUpCode
          ? { action_code: followUpCode, due_date: followUpDueDate || undefined }
          : undefined,
      });
      setResult(res);
      onRecorded(res);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <h2 className="text-base font-semibold">상담 결과 · 후속조치</h2>
      {status === "completed" && (
        <p className="text-xs text-[var(--color-text-muted)]">
          이미 완료 처리된 상담입니다. 다시 제출하면 결과가 덮어써집니다(1건당 결과는 하나,
          meeting_outcome unique).
        </p>
      )}

      <label className="flex flex-col gap-1 text-sm">
        결과
        <select
          value={outcomeCode}
          onChange={(event) => setOutcomeCode(event.target.value)}
          className="input"
        >
          {OUTCOME_CODES.map((o) => (
            <option key={o.code} value={o.code}>
              {o.label}
            </option>
          ))}
        </select>
      </label>

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={isQualifiedLead}
          onChange={(event) => setIsQualifiedLead(event.target.checked)}
        />
        유효 리드로 표시
      </label>

      <label className="flex flex-col gap-1 text-sm">
        메모(선택)
        <textarea
          value={memo}
          onChange={(event) => setMemo(event.target.value)}
          className="input"
          maxLength={2000}
          rows={3}
        />
      </label>

      <fieldset className="flex flex-col gap-2 rounded-md border border-dashed border-[var(--color-border)] p-3">
        <legend className="px-1 text-sm font-medium">후속조치(선택)</legend>
        <label className="flex flex-col gap-1 text-sm">
          조치
          <select
            value={followUpCode}
            onChange={(event) => setFollowUpCode(event.target.value)}
            className="input"
          >
            <option value="">없음</option>
            {FOLLOW_UP_CODES.map((f) => (
              <option key={f.code} value={f.code}>
                {f.label}
              </option>
            ))}
          </select>
        </label>
        {followUpCode && (
          <label className="flex flex-col gap-1 text-sm">
            다음 연락일(선택)
            <input
              type="date"
              value={followUpDueDate}
              onChange={(event) => setFollowUpDueDate(event.target.value)}
              className="input"
            />
          </label>
        )}
      </fieldset>

      {error ? <ErrorBanner error={error} /> : null}

      {result && (
        <p className="text-sm text-[var(--color-success)]">
          기록되었습니다. 상담 상태: <code>{result.meeting_status}</code>
        </p>
      )}

      <button
        type="button"
        onClick={submit}
        disabled={submitting}
        className="tap-target self-start rounded-md bg-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand-contrast)] disabled:opacity-50"
      >
        {submitting ? "저장 중…" : "결과 저장"}
      </button>
    </div>
  );
}
