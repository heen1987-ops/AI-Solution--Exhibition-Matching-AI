/**
 * 바이어 검증상태 배지. `apps/admin/components/StatusBadge.tsx`와 같은 접근성 원칙(색상만으로
 * 구분하지 않고 항상 텍스트 라벨 병기)을 따르지만, 그 컴포넌트는 §28절 업체 상태값
 * (STATUS_TONE/STATUS_LABEL_KO)만 알고 있는 공유 컴포넌트라 새 상태값을 추가하려면 그 파일을
 * 수정해야 한다 - 소유 경로 밖 공유 컴포넌트 수정을 피하기 위해 이 트랙 전용의 작은 배지를
 * 별도로 둔다(`../partner-meeting/components/MeetingStatusBadge.tsx`와 같은 이유).
 */

const TONE_STYLES: Record<"neutral" | "info" | "warning" | "success" | "danger", string> = {
  neutral:
    "bg-[var(--color-surface-muted)] text-[var(--color-text-muted)] border-[var(--color-border)]",
  info: "bg-[#e8f0fe] text-[#1a56db] border-[#c3d9fb] dark:bg-[#132038] dark:text-[#8ab4f8] dark:border-[#274270]",
  warning: "bg-[var(--color-warning-bg)] text-[var(--color-warning)] border-transparent",
  success: "bg-[var(--color-success-bg)] text-[var(--color-success)] border-transparent",
  danger: "bg-[var(--color-danger-bg)] text-[var(--color-danger)] border-transparent",
};

const STATUS_TONE: Record<string, keyof typeof TONE_STYLES> = {
  PENDING: "warning",
  VERIFIED: "success",
  LIMITED: "info",
  REJECTED: "danger",
  SUSPENDED: "danger",
  EXPIRED: "neutral",
};

const STATUS_LABEL_KO: Record<string, string> = {
  PENDING: "검증대기",
  VERIFIED: "검증완료",
  LIMITED: "제한승인",
  REJECTED: "반려",
  SUSPENDED: "정지",
  EXPIRED: "만료",
};

export default function VerificationStatusPill({ status }: { status: string }) {
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
