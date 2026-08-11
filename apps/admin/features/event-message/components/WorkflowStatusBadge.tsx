import { STATUS_LABEL_KO } from "../logic";
import type { MessageStatus } from "../types";

const TONE_STYLES: Record<"neutral" | "info" | "warning" | "success" | "danger", string> = {
  neutral:
    "bg-[var(--color-surface-muted)] text-[var(--color-text-muted)] border-[var(--color-border)]",
  info: "bg-[#e8f0fe] text-[#1a56db] border-[#c3d9fb] dark:bg-[#132038] dark:text-[#8ab4f8] dark:border-[#274270]",
  warning: "bg-[var(--color-warning-bg)] text-[var(--color-warning)] border-transparent",
  success: "bg-[var(--color-success-bg)] text-[var(--color-success)] border-transparent",
  danger: "bg-[var(--color-danger-bg)] text-[var(--color-danger)] border-transparent",
};

const STATUS_TONE: Record<MessageStatus, keyof typeof TONE_STYLES> = {
  DRAFT: "neutral",
  PREVIEWED: "info",
  APPROVED: "info",
  SCHEDULED: "warning",
  PUBLISHED: "success",
  COMPLETED: "neutral",
  CANCELLED: "danger",
};

/** `components/StatusBadge.tsx`와 같은 톤 팔레트를 쓰지만 이 트랙의 owned path
 * (`features/event-message/**`) 안에 로컬로 둔다 - 공용 컴포넌트 파일은 소유 경로 밖이라
 * 상태 맵을 추가하지 않는다(같은 관례가 이미 다른 트랙 features에도 여럿 있다). */
export default function WorkflowStatusBadge({ status }: { status: MessageStatus }) {
  const tone = STATUS_TONE[status];
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full border px-2.5 py-0.5 text-xs font-medium ${TONE_STYLES[tone]}`}
    >
      {STATUS_LABEL_KO[status]}
      <span className="text-[10px] opacity-70">({status})</span>
    </span>
  );
}
