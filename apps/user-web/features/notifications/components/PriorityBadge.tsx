import { NOTIFICATION_PRIORITY_LABEL } from "../logic";
import type { NotificationPriority } from "../types";

/** 13.2절 원칙(색상만으로 상태 구분 금지) - 색과 함께 항상 한글 라벨 텍스트를 보여준다. */
const PRIORITY_COLOR: Record<NotificationPriority, string> = {
  URGENT: "var(--color-danger)",
  HIGH: "var(--color-brand)",
  NORMAL: "var(--color-text-muted)",
  LOW: "var(--color-text-muted)",
};

export default function PriorityBadge({ priority }: { priority: NotificationPriority }) {
  return (
    <span
      className="inline-flex w-fit items-center rounded-full border px-2 py-0.5 text-xs font-semibold"
      style={{ color: PRIORITY_COLOR[priority], borderColor: PRIORITY_COLOR[priority] }}
    >
      {NOTIFICATION_PRIORITY_LABEL[priority]}
    </span>
  );
}
