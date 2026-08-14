/**
 * 상담 상태 배지. apps/admin/components/StatusBadge.tsx와 같은 시각 언어(항상 텍스트
 * 라벨 동반)를 쓰지만, 상담 상태값은 소문자 스네이크케이스(meeting.py MEETING_STATUSES)라
 * 그 컴포넌트의 대문자 상태 매핑과 겹치지 않는다 - 별도로 둔다.
 */

type Tone = "neutral" | "info" | "warning" | "success" | "danger";

const TONE_STYLES: Record<Tone, string> = {
  neutral:
    "bg-[var(--color-surface-muted)] text-[var(--color-text-muted)] border-[var(--color-border)]",
  info: "bg-[#e8f0fe] text-[#1a56db] border-[#c3d9fb] dark:bg-[#132038] dark:text-[#8ab4f8] dark:border-[#274270]",
  warning: "bg-[var(--color-warning-bg)] text-[var(--color-warning)] border-transparent",
  success: "bg-[var(--color-success-bg)] text-[var(--color-success)] border-transparent",
  danger: "bg-[var(--color-danger-bg)] text-[var(--color-danger)] border-transparent",
};

/** meeting.py MEETING_STATUSES: draft/requested/accepted/counter_proposed/rejected/
 * cancelled/completed/no_show (docs/user-ia-wireframes.md 6.2절). */
const STATUS_TONE: Record<string, Tone> = {
  draft: "neutral",
  requested: "info",
  accepted: "success",
  counter_proposed: "warning",
  rejected: "danger",
  cancelled: "neutral",
  completed: "success",
  no_show: "danger",
};

const STATUS_LABEL_KO: Record<string, string> = {
  draft: "임시저장",
  requested: "요청됨",
  accepted: "확정",
  counter_proposed: "시간 재제안",
  rejected: "반려",
  cancelled: "취소",
  completed: "완료",
  no_show: "노쇼",
};

export default function MeetingStatusBadge({ status }: { status: string }) {
  const tone = STATUS_TONE[status] ?? "neutral";
  const label = STATUS_LABEL_KO[status] ?? status;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium ${TONE_STYLES[tone]}`}
    >
      {label}
      <span className="text-[10px] opacity-70">({status})</span>
    </span>
  );
}
