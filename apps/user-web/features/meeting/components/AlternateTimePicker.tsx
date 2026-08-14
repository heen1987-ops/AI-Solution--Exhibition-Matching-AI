"use client";

/**
 * U-15 "시간 변경 제안"(counter_proposed) 상태 - 업체가 제안한 시간 중 하나를 수락하거나
 * 모두 거절한다.
 *
 * 백엔드 계약(POST /meetings/{id}/respond, schemas/meeting.py MeetingRespondRequest)은
 * "이 상담에 지금 붙어 있는 제안(SELECTED 상태의 슬롯)을 수락/거절"하는 단일 액션이라
 * slot_id 파라미터를 받지 않는다(라우터 respond_to_counter_proposal 참고 - 서버가
 * meeting_slot_request.status='SELECTED'인 행을 스스로 찾는다). 그래서 후보가 여러 개
 * 보이더라도 "이 시간 수락" 버튼은 하나만 두고, 실제로 선택된(SELECTED) 슬롯을 굵게
 * 강조한다.
 */

import type { SlotCandidate } from "../types";

function formatDateTime(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString("ko-KR", { month: "long", day: "numeric", hour: "2-digit", minute: "2-digit" });
}

export interface AlternateTimePickerProps {
  candidateSlots: SlotCandidate[];
  isActing: boolean;
  onAccept: () => void;
  onDeclineAll: () => void;
}

export default function AlternateTimePicker({
  candidateSlots,
  isActing,
  onAccept,
  onDeclineAll,
}: AlternateTimePickerProps) {
  const proposed = candidateSlots.filter((slot) => slot.request_status === "SELECTED");
  const displaySlots = proposed.length > 0 ? proposed : candidateSlots;

  return (
    <section aria-labelledby="alternate-time-heading" className="flex flex-col gap-3">
      <h2 id="alternate-time-heading" className="text-base font-semibold">
        업체가 다른 시간을 제안했어요
      </h2>
      <ul className="flex flex-col gap-2">
        {displaySlots.map((slot) => (
          <li
            key={slot.slot_id}
            className="rounded-lg border p-3 text-sm"
            style={{ borderColor: "var(--color-border)" }}
          >
            {formatDateTime(slot.start_at)} ~ {formatDateTime(slot.end_at)}
          </li>
        ))}
      </ul>
      <div className="flex flex-wrap gap-3">
        <button
          type="button"
          onClick={onAccept}
          disabled={isActing}
          className="tap-target rounded-lg px-5 py-3 text-sm font-semibold disabled:opacity-60"
          style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
        >
          이 시간 수락
        </button>
        <button
          type="button"
          onClick={onDeclineAll}
          disabled={isActing}
          className="tap-target rounded-lg border px-5 py-3 text-sm font-semibold disabled:opacity-60"
          style={{ borderColor: "var(--color-border)" }}
        >
          모두 거절
        </button>
      </div>
    </section>
  );
}
