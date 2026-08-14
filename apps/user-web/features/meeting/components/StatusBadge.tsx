import { MEETING_STATUS_LABEL } from "../constants";
import type { MeetingStatus } from "../types";

export default function StatusBadge({ status }: { status: MeetingStatus }) {
  return (
    <span
      className="inline-flex w-fit items-center rounded-full px-3 py-1 text-xs font-semibold"
      style={{ backgroundColor: "var(--color-brand)", color: "var(--color-brand-contrast)" }}
    >
      {MEETING_STATUS_LABEL[status]}
    </span>
  );
}
