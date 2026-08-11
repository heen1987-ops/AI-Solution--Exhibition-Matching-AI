"use client";

/**
 * 바이어 인증상태 배지 + 상태별 안내 배너 (공용 재사용 컴포넌트).
 *
 * 요구사항 (작업 지시 원문)
 * --------------------------
 * "verification-status-aware messaging (UNVERIFIED/PENDING: limited browsing, verification
 * required for meeting requests; VERIFIED: full access; LIMITED: show the specific
 * restriction; REJECTED/SUSPENDED: dispute/contact path only, no retry button that pretends
 * it will work)."
 *
 * REJECTED/SUSPENDED에서 "다시 시도" 버튼을 일부러 넣지 않은 이유: 실제로 상태를 바꿀 수
 * 없는 버튼을 넣으면 사용자가 재시도가 통할 것처럼 오해한다 - 대신 문의 경로(연락처)만
 * 안내한다. 인증·이의제기 접수 API가 아직 없어(이 화면 소유 범위 밖) `mailto:` 링크로
 * 대체한다 - TODO(통합 시 실제 이의제기 접수 화면/엔드포인트가 생기면 교체).
 */

import type { ReactNode } from "react";

import type { BuyerVerification, BuyerVerificationStatus } from "./types";

interface StatusPresentation {
  label: string;
  tone: "positive" | "info" | "warning" | "danger";
  message: (verification: BuyerVerification) => ReactNode;
}

const SUPPORT_EMAIL = "buyer-support@backjudaegan.example";

const PRESENTATIONS: Record<BuyerVerificationStatus, StatusPresentation> = {
  UNVERIFIED: {
    label: "미인증",
    tone: "warning",
    message: () => (
      <>
        아직 바이어 인증 전이에요. 업체·제품은 둘러볼 수 있지만, 상담을 요청하려면 먼저
        바이어 인증이 필요해요.
      </>
    ),
  },
  PENDING: {
    label: "인증 심사 중",
    tone: "info",
    message: () => (
      <>
        바이어 인증을 심사하고 있어요. 심사가 끝날 때까지는 열람만 가능하고, 상담 요청은
        인증 완료 후에 할 수 있어요.
      </>
    ),
  },
  VERIFIED: {
    label: "인증된 바이어",
    tone: "positive",
    message: () => <>인증된 바이어예요. 상담 요청을 포함한 모든 기능을 이용할 수 있어요.</>,
  },
  LIMITED: {
    label: "이용 제한",
    tone: "warning",
    message: (verification) => (
      <>{verification.restriction_note ?? "일부 기능이 제한돼 있어요. 자세한 내용은 고객센터로 문의해 주세요."}</>
    ),
  },
  REJECTED: {
    label: "인증 반려",
    tone: "danger",
    message: (verification) => (
      <>
        바이어 인증이 반려됐어요.
        {verification.decision_reason ? ` 사유: ${verification.decision_reason}` : ""} 이의가
        있으면 아래 문의처로 연락해 주세요.
      </>
    ),
  },
  SUSPENDED: {
    label: "이용 정지",
    tone: "danger",
    message: (verification) => (
      <>
        현재 계정 이용이 정지돼 있어요.
        {verification.decision_reason ? ` 사유: ${verification.decision_reason}` : ""} 이의가
        있으면 아래 문의처로 연락해 주세요.
      </>
    ),
  },
};

const TONE_COLORS: Record<StatusPresentation["tone"], { fg: string; bg: string }> = {
  positive: { fg: "var(--color-success)", bg: "color-mix(in srgb, var(--color-success) 14%, transparent)" },
  info: { fg: "var(--color-brand)", bg: "color-mix(in srgb, var(--color-brand) 12%, transparent)" },
  warning: { fg: "#8a5a00", bg: "color-mix(in srgb, #d99a00 22%, transparent)" },
  danger: { fg: "var(--color-danger)", bg: "color-mix(in srgb, var(--color-danger) 14%, transparent)" },
};

/** 요청-상담 CTA 등 다른 화면이 "지금 상담 요청을 걸어도 되는가"를 판단할 때 쓴다. */
export function canRequestMeeting(status: BuyerVerificationStatus): boolean {
  return status === "VERIFIED";
}

export interface VerificationStatusBadgeProps {
  status: BuyerVerificationStatus;
  className?: string;
}

/** 짧은 배지만 필요할 때(카드 헤더 등)는 이 컴포넌트만 쓴다. */
export function VerificationStatusBadge({ status, className }: VerificationStatusBadgeProps) {
  const presentation = PRESENTATIONS[status];
  const colors = TONE_COLORS[presentation.tone];
  return (
    <span
      data-testid="verification-status-badge"
      data-status={status}
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-semibold ${className ?? ""}`}
      style={{ color: colors.fg, backgroundColor: colors.bg }}
    >
      {presentation.label}
    </span>
  );
}

export interface VerificationStatusBannerProps {
  verification: BuyerVerification;
  className?: string;
}

/** 프로파일·매칭 화면 상단에 놓는 전체 안내 배너(배지 + 상태별 문구 + 필요 시 문의처). */
export default function VerificationStatusBanner({ verification, className }: VerificationStatusBannerProps) {
  const presentation = PRESENTATIONS[verification.status];
  const colors = TONE_COLORS[presentation.tone];
  const showContactPath = verification.status === "REJECTED" || verification.status === "SUSPENDED";

  return (
    <div
      role="status"
      aria-live="polite"
      data-testid="verification-status-banner"
      data-status={verification.status}
      className={`flex flex-col gap-2 rounded-xl border p-3 ${className ?? ""}`}
      style={{ borderColor: colors.fg, backgroundColor: colors.bg }}
    >
      <div className="flex items-center gap-2">
        <VerificationStatusBadge status={verification.status} />
        {!verification.is_authoritative ? (
          <span className="text-xs" style={{ color: "var(--color-text-muted)" }}>
            (임시 추정 상태)
          </span>
        ) : null}
      </div>
      <p className="text-sm" style={{ color: "var(--color-text)" }}>
        {presentation.message(verification)}
      </p>
      {showContactPath ? (
        <a
          href={`mailto:${SUPPORT_EMAIL}`}
          className="tap-target w-fit rounded-lg border px-3 text-sm font-semibold"
          style={{ borderColor: colors.fg, color: colors.fg }}
        >
          문의하기 ({SUPPORT_EMAIL})
        </a>
      ) : null}
    </div>
  );
}
