/**
 * 승인상태·운영상태 배지. 색상만으로 상태를 구분하지 않도록(접근성) 항상 텍스트 라벨을
 * 함께 표시한다.
 */

const TONE_STYLES: Record<"neutral" | "info" | "warning" | "success" | "danger", string> = {
  neutral: "bg-[var(--color-surface-muted)] text-[var(--color-text-muted)] border-[var(--color-border)]",
  info: "bg-[#e8f0fe] text-[#1a56db] border-[#c3d9fb] dark:bg-[#132038] dark:text-[#8ab4f8] dark:border-[#274270]",
  warning: "bg-[var(--color-warning-bg)] text-[var(--color-warning)] border-transparent",
  success: "bg-[var(--color-success-bg)] text-[var(--color-success)] border-transparent",
  danger: "bg-[var(--color-danger-bg)] text-[var(--color-danger)] border-transparent",
};

const STATUS_TONE: Record<string, keyof typeof TONE_STYLES> = {
  DRAFT: "neutral",
  SUBMITTED: "info",
  AI_EXTRACTED: "info",
  EXHIBITOR_REVIEWED: "info",
  OPERATOR_REVIEW: "warning",
  APPROVED: "success",
  PUBLISHED: "success",
  REJECTED: "danger",
  ARCHIVED: "neutral",
  OPEN: "success",
  PAUSED: "warning",
  CLOSED: "neutral",
};

const STATUS_LABEL_KO: Record<string, string> = {
  DRAFT: "작성중",
  SUBMITTED: "제출됨",
  AI_EXTRACTED: "AI 추출됨",
  EXHIBITOR_REVIEWED: "업체 확인",
  OPERATOR_REVIEW: "운영자 검수중",
  APPROVED: "승인",
  PUBLISHED: "게시됨",
  REJECTED: "반려",
  ARCHIVED: "보관됨",
  OPEN: "운영중",
  PAUSED: "일시중단",
  CLOSED: "종료",
};

export default function StatusBadge({ status }: { status: string }) {
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
