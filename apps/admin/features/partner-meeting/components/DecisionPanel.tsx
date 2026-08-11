"use client";

/**
 * 12.4절 업체 응답(수락/거절/시간재제안). POST /partner/meetings/{id}/decision.
 *
 * 시간 슬롯: `PartnerDecisionRequest.slot_id`는 단일 값이다(types.ts 계약 공백 3 참고 -
 * 작업 지시의 "1~3개 대안 제안"과 달리 실제 백엔드는 한 번에 하나만 받는다). 바이어가
 * 애초에 여러 후보를 제시했다면(create_meeting `requested_slot_ids`) 그중 예약되지 않은
 * 나머지가 candidate_slots에 request_status="PENDING"으로 남아 있어, 업체는 그중 하나를
 * 골라 재제안할 수 있다 - 이 화면은 그 목록을 라디오로 보여주고, 후보가 없거나 다른
 * 시간을 새로 제안하고 싶으면 슬롯 ID를 직접 입력하게 한다.
 *
 * version: types.ts 계약 공백 1 참고 - 목록/버이어요약 응답 어디에도 row_version이 없어
 * 자동으로 채울 수 없다. 기본값 0으로 두고 수동 입력을 허용하며, 409
 * MEETING_VERSION_CONFLICT가 뜨면 안내 문구로 재시도를 유도한다.
 */

import { useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";

import { decidePartnerMeeting } from "../api";
import {
  REJECT_REASON_CODES,
  decisionActionLabel,
  validateDecisionInput,
  type DecisionFieldError,
} from "../logic";
import type { MeetingDecisionResult, PartnerDecisionAction, SlotCandidate } from "../types";
import { generateClientId } from "@/lib/api-client";

const ACTIONS: PartnerDecisionAction[] = ["ACCEPT", "COUNTER_PROPOSE", "REJECT"];
const DECIDABLE_STATUSES = new Set(["requested", "counter_proposed"]);

export default function DecisionPanel({
  meetingId,
  status,
  candidateSlots,
  onDecided,
}: {
  meetingId: string;
  status: string;
  candidateSlots: SlotCandidate[];
  onDecided: (result: MeetingDecisionResult) => void;
}) {
  const [action, setAction] = useState<PartnerDecisionAction>("ACCEPT");
  const [slotId, setSlotId] = useState<string>(
    candidateSlots.find((slot) => slot.request_status === "SELECTED")?.slot_id ??
      candidateSlots[0]?.slot_id ??
      "",
  );
  const [customSlotId, setCustomSlotId] = useState("");
  const [reasonCode, setReasonCode] = useState<string>("");
  const [freeTextReason, setFreeTextReason] = useState("");
  const [version, setVersion] = useState<number>(0);
  const [fieldErrors, setFieldErrors] = useState<DecisionFieldError[]>([]);
  const [error, setError] = useState<unknown>(null);
  const [submitting, setSubmitting] = useState(false);

  if (!DECIDABLE_STATUSES.has(status)) {
    return (
      <div className="rounded-lg border border-[var(--color-border)] p-4">
        <h2 className="text-base font-semibold">상담 응답</h2>
        <p className="mt-2 text-sm text-[var(--color-text-muted)]">
          현재 상태(<code>{status}</code>)에서는 수락·거절·시간재제안을 할 수 없습니다.
        </p>
      </div>
    );
  }

  const effectiveSlotId = (customSlotId.trim() || slotId || "").trim() || null;
  const effectiveReasonCode = action === "REJECT" ? reasonCode : freeTextReason;

  async function submit() {
    const errors = validateDecisionInput({
      action,
      slotId: action === "REJECT" ? null : effectiveSlotId,
      reasonCode: effectiveReasonCode || null,
    });
    setFieldErrors(errors);
    if (errors.length > 0) return;

    setSubmitting(true);
    setError(null);
    try {
      const result = await decidePartnerMeeting(
        meetingId,
        {
          action,
          slot_id: action === "REJECT" ? undefined : (effectiveSlotId as string),
          version,
          reason_code: effectiveReasonCode || undefined,
        },
        generateClientId(),
      );
      onDecided(result);
    } catch (err) {
      setError(err);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <h2 className="text-base font-semibold">상담 응답</h2>

      <div className="flex flex-wrap gap-2" role="radiogroup" aria-label="상담 응답 종류">
        {ACTIONS.map((candidate) => (
          <button
            key={candidate}
            type="button"
            role="radio"
            aria-checked={action === candidate}
            onClick={() => {
              setAction(candidate);
              setFieldErrors([]);
            }}
            className={`tap-target rounded-md border px-3 py-2 text-sm font-medium ${
              action === candidate
                ? "border-[var(--color-brand)] bg-[var(--color-brand)] text-[var(--color-brand-contrast)]"
                : "border-[var(--color-border)]"
            }`}
          >
            {decisionActionLabel(candidate)}
          </button>
        ))}
      </div>

      {action !== "REJECT" && (
        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium">시간 슬롯 선택</p>
          {candidateSlots.length === 0 && (
            <p className="text-xs text-[var(--color-text-muted)]">
              바이어가 제시한 후보 시간이 없습니다. 아래에 슬롯 ID를 직접 입력해 주세요.
            </p>
          )}
          <div className="flex flex-col gap-1">
            {candidateSlots.map((slot) => (
              <label key={slot.slot_id} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="decision-slot"
                  checked={!customSlotId && slotId === slot.slot_id}
                  onChange={() => {
                    setSlotId(slot.slot_id);
                    setCustomSlotId("");
                  }}
                />
                {new Date(slot.start_at).toLocaleString("ko-KR")} ~{" "}
                {new Date(slot.end_at).toLocaleTimeString("ko-KR")}
                <span className="text-xs text-[var(--color-text-muted)]">
                  ({slot.request_status ?? "PENDING"})
                </span>
              </label>
            ))}
          </div>
          <label className="flex flex-col gap-1 text-xs">
            다른 슬롯 ID 직접 입력(선택)
            <input
              value={customSlotId}
              onChange={(event) => setCustomSlotId(event.target.value)}
              placeholder="availability_slot_id (UUID)"
              className="input font-mono text-xs"
            />
          </label>
          {fieldErrors.some((e) => e.field === "slotId") && (
            <p className="text-xs text-[var(--color-danger)]">시간 슬롯을 선택해 주세요.</p>
          )}
        </div>
      )}

      {action === "REJECT" && (
        <div className="flex flex-col gap-1">
          <label className="text-sm font-medium">
            반려 사유 <span className="text-[var(--color-danger)]">*</span>
          </label>
          <select
            value={reasonCode}
            onChange={(event) => setReasonCode(event.target.value)}
            className="input"
          >
            <option value="">선택</option>
            {REJECT_REASON_CODES.map((r) => (
              <option key={r.code} value={r.code}>
                {r.label}
              </option>
            ))}
          </select>
          {fieldErrors.some((e) => e.field === "reasonCode") && (
            <p className="text-xs text-[var(--color-danger)]">반려 사유를 선택해야 합니다.</p>
          )}
        </div>
      )}

      {action !== "REJECT" && (
        <label className="flex flex-col gap-1 text-xs">
          메모(선택)
          <input
            value={freeTextReason}
            onChange={(event) => setFreeTextReason(event.target.value)}
            className="input text-xs"
            placeholder="예: 요청하신 시간대는 어렵고 다음날 오전을 제안드립니다"
            maxLength={50}
          />
        </label>
      )}

      <label className="flex flex-col gap-1 text-xs">
        version (낙관적 잠금값)
        <input
          type="number"
          value={version}
          onChange={(event) => setVersion(Number(event.target.value) || 0)}
          className="input font-mono text-xs"
        />
        <span className="text-[10px] opacity-70">
          TODO(BACKEND-MEETING): GET /partner/meetings, /partner/meetings/&#123;id&#125;/
          buyer-summary 응답에 row_version이 없어 자동으로 채울 수 없습니다(types.ts 참고).
          409 MEETING_VERSION_CONFLICT가 뜨면 값을 조정해 재시도해 주세요.
        </span>
      </label>

      {error ? <ErrorBanner error={error} /> : null}

      <button
        type="button"
        onClick={submit}
        disabled={submitting}
        className="tap-target self-start rounded-md bg-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand-contrast)] disabled:opacity-50"
      >
        {submitting ? "처리 중…" : "제출"}
      </button>
    </div>
  );
}
