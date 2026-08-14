"use client";

/**
 * 운영·재고·상담·방문 상태 배지 (공용 재사용 컴포넌트).
 *
 * 근거 문서
 * ---------
 * - docs/user-ia-wireframes.md 9.2절(상태 배지) - 그룹별 표준 상태 문구(현장/재고/부스/
 *   상담/방문)의 1차 근거. "색상만으로 상태를 전달하지 않고 텍스트·아이콘을 함께 사용한다"
 *   가 이 컴포넌트가 항상 텍스트 라벨 + 아이콘을 함께 렌더링하는 이유다.
 * - docs/user-ia-wireframes.md 10절(추천 설명 지양 표현) - 내부 점수 노출 금지. 이 배지는
 *   상태 코드→고정 문구 매핑만 하고 숫자 점수를 표시하지 않는다.
 * - docs/user-ia-wireframes.md 7절 U-10 - "운영정보가 없거나 오래된 경우
 *   `현재 상태 미확인`으로 표시한다. 추정값을 사실처럼 보여주지 않는다." - `observedAt`이
 *   `staleAfterMinutes`보다 오래됐거나 없으면 강제로 미확인 상태로 대체하는 로직의 근거.
 * - docs/frontend-backend-ai-interface-spec.md, frontend/lib/types.ts의
 *   `BoothOperatingStatus`(OpenEnum: OPEN/PAUSED/CLOSED 외 값 가능), `AvailabilityView`,
 *   `PriceDisplayStatus` - 이 컴포넌트가 매핑하는 코드값의 출처.
 *
 * 이 컴포넌트는 상태 "코드"를 받아 9.2절 고정 문구로 표시만 한다. 실제 데이터 조회는
 * 호출부(부스·제품 상세, 추천 카드 등)가 담당한다.
 */

import { useEffect, useState } from "react";

export type OperatingStatusGroup = "field" | "stock" | "booth" | "meeting" | "visit";
export type OperatingStatusTone = "positive" | "info" | "warning" | "danger" | "neutral";

/**
 * 9.2절 표에 나온 상태 + db-erd/타입 스펙의 OpenEnum 실제 값(OPEN/PAUSED/CLOSED 등)을
 * 함께 다루기 위한 매핑 키. 문서에 없는 코드가 서버에서 올 수 있어(OpenEnum) 알 수 없는
 * 코드는 `UNKNOWN`으로 폴백한다.
 */
export type OperatingStatusCode =
  // 현장
  | "TASTING_AVAILABLE"
  | "PURCHASE_AVAILABLE"
  | "MEETING_AVAILABLE"
  | "CROWDED"
  // 재고
  | "STOCK_AVAILABLE"
  | "STOCK_LOW"
  | "STOCK_SOLD_OUT"
  | "STOCK_UNKNOWN"
  // 부스 (db-erd BoothOperatingStatus: OPEN/PAUSED/CLOSED를 아래 코드로 정규화해 사용)
  | "BOOTH_OPEN"
  | "BOOTH_TASTING_CLOSED"
  | "BOOTH_MEETING_CLOSED"
  | "BOOTH_CLOSED"
  | "BOOTH_PAUSED"
  // 상담
  | "MEETING_PENDING"
  | "MEETING_COUNTER_PROPOSED"
  | "MEETING_CONFIRMED"
  | "MEETING_COMPLETED"
  | "MEETING_CANCELLED"
  // 방문
  | "VISIT_ROUTE_ADDED"
  | "VISIT_COMPLETED"
  | "VISIT_FEEDBACK_DONE"
  // 정보 없음/오래됨 (U-10)
  | "UNKNOWN";

interface StatusDef {
  label: string;
  tone: OperatingStatusTone;
  group: OperatingStatusGroup;
}

// 9.2절 표를 그대로 옮긴 고정 문구. 새 문구를 추가할 때도 표의 표현을 그대로 쓴다.
const STATUS_DEFS: Record<OperatingStatusCode, StatusDef> = {
  TASTING_AVAILABLE: { label: "시음 가능", tone: "positive", group: "field" },
  PURCHASE_AVAILABLE: { label: "구매 가능", tone: "positive", group: "field" },
  MEETING_AVAILABLE: { label: "상담 가능", tone: "positive", group: "field" },
  CROWDED: { label: "혼잡", tone: "warning", group: "field" },

  STOCK_AVAILABLE: { label: "재고 있음", tone: "positive", group: "stock" },
  STOCK_LOW: { label: "품절 임박", tone: "warning", group: "stock" },
  STOCK_SOLD_OUT: { label: "품절", tone: "danger", group: "stock" },
  STOCK_UNKNOWN: { label: "미확인", tone: "neutral", group: "stock" },

  BOOTH_OPEN: { label: "운영 중", tone: "positive", group: "booth" },
  BOOTH_TASTING_CLOSED: { label: "시음 마감", tone: "warning", group: "booth" },
  BOOTH_MEETING_CLOSED: { label: "상담 마감", tone: "warning", group: "booth" },
  BOOTH_CLOSED: { label: "운영 종료", tone: "neutral", group: "booth" },
  // 9.2절 표에는 없으나 db-erd `BoothOperatingStatus`의 PAUSED 값을 위해 근접한 표현을 둔다.
  BOOTH_PAUSED: { label: "일시 중단", tone: "warning", group: "booth" },

  MEETING_PENDING: { label: "응답 대기", tone: "info", group: "meeting" },
  MEETING_COUNTER_PROPOSED: { label: "변경 제안", tone: "warning", group: "meeting" },
  MEETING_CONFIRMED: { label: "확정", tone: "positive", group: "meeting" },
  MEETING_COMPLETED: { label: "완료", tone: "neutral", group: "meeting" },
  MEETING_CANCELLED: { label: "취소", tone: "danger", group: "meeting" },

  VISIT_ROUTE_ADDED: { label: "경로 추가", tone: "info", group: "visit" },
  VISIT_COMPLETED: { label: "방문 완료", tone: "positive", group: "visit" },
  VISIT_FEEDBACK_DONE: { label: "피드백 완료", tone: "neutral", group: "visit" },

  UNKNOWN: { label: "현재 상태 미확인", tone: "neutral", group: "booth" },
};

/** db-erd `BoothOperatingStatus`(OPEN/PAUSED/CLOSED, OpenEnum) → 이 배지 코드 정규화.
 * `tastingClosed`/`meetingClosed`는 booth의 `services` 필드로 보강해 호출부가 결정한다. */
export function boothOperatingStatusToCode(
  status: string | null | undefined,
): OperatingStatusCode {
  switch (status) {
    case "OPEN":
      return "BOOTH_OPEN";
    case "PAUSED":
      return "BOOTH_PAUSED";
    case "CLOSED":
      return "BOOTH_CLOSED";
    default:
      // OpenEnum이라 서버가 문서에 없는 값(예: TASTING_CLOSED, SOLD_OUT)을 보낼 수 있다.
      if (status === "TASTING_CLOSED") return "BOOTH_TASTING_CLOSED";
      if (status === "MEETING_CLOSED") return "BOOTH_MEETING_CLOSED";
      return "UNKNOWN";
  }
}

/** 12.2절(운영정보 신선도) 기본 임계값. 정확한 값은 아직 설계되지 않아 합리적 기본값을
 * 사용한다. TODO(운영 정책 확정 후 대조): 부스·구역별로 다른 임계값이 필요할 수 있다. */
export const DEFAULT_STALE_AFTER_MINUTES = 30;

function minutesSince(isoDateTime: string, now: number): number {
  const observed = new Date(isoDateTime).getTime();
  if (Number.isNaN(observed)) return Number.POSITIVE_INFINITY;
  return (now - observed) / 60000;
}

function formatObservedTime(isoDateTime: string): string {
  const date = new Date(isoDateTime);
  if (Number.isNaN(date.getTime())) return "";
  return date.toLocaleTimeString("ko-KR", { hour: "2-digit", minute: "2-digit" });
}

function ToneIcon({ tone }: { tone: OperatingStatusTone }) {
  // 13.2절: 색상만으로 상태를 구분하지 않도록 톤별로 모양이 다른 아이콘을 함께 쓴다.
  switch (tone) {
    case "positive":
      return (
        <svg viewBox="0 0 16 16" width={12} height={12} aria-hidden="true" fill="currentColor">
          <path d="M6.5 11.5 3 8l1.1-1.1 2.4 2.4 5.4-5.4L13 5z" />
        </svg>
      );
    case "warning":
      return (
        <svg viewBox="0 0 16 16" width={12} height={12} aria-hidden="true" fill="currentColor">
          <path d="M8 1.5 15 14H1L8 1.5Zm0 4.5v3.2M8 11.2h.01" stroke="currentColor" strokeWidth={1.4} fill="none" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      );
    case "danger":
      return (
        <svg viewBox="0 0 16 16" width={12} height={12} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth={1.6} strokeLinecap="round">
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      );
    case "info":
      return (
        <svg viewBox="0 0 16 16" width={12} height={12} aria-hidden="true" fill="none" stroke="currentColor" strokeWidth={1.6}>
          <circle cx="8" cy="8" r="6.2" />
          <path d="M8 7.2v4M8 5.2h.01" strokeLinecap="round" />
        </svg>
      );
    default:
      return (
        <svg viewBox="0 0 16 16" width={12} height={12} aria-hidden="true" fill="currentColor">
          <circle cx="8" cy="8" r="3" />
        </svg>
      );
  }
}

const TONE_COLORS: Record<OperatingStatusTone, { fg: string; bg: string }> = {
  positive: { fg: "var(--color-success)", bg: "color-mix(in srgb, var(--color-success) 14%, transparent)" },
  info: { fg: "var(--color-brand)", bg: "color-mix(in srgb, var(--color-brand) 12%, transparent)" },
  warning: { fg: "#8a5a00", bg: "color-mix(in srgb, #d99a00 22%, transparent)" },
  danger: { fg: "var(--color-danger)", bg: "color-mix(in srgb, var(--color-danger) 14%, transparent)" },
  neutral: { fg: "var(--color-text-muted)", bg: "color-mix(in srgb, var(--color-text-muted) 14%, transparent)" },
};

export interface OperatingStatusBadgeProps {
  /** 9.2절 상태 코드. 알 수 없는 값은 `UNKNOWN`("현재 상태 미확인")으로 대체된다. */
  code: OperatingStatusCode | (string & {});
  /** 상태 문구를 특정 상황에 맞게 덮어써야 할 때만 사용한다(가능하면 표준 코드를 쓴다). */
  labelOverride?: string;
  /** 상태 관측 시각. U-10: 오래되면 강제로 "현재 상태 미확인"으로 표시한다. */
  observedAt?: string | null;
  /** `observedAt` 이후 이 분(分)이 지나면 오래된 정보로 간주한다. */
  staleAfterMinutes?: number;
  /** 관측 시각을 배지 옆에 작게 함께 보여줄지 여부(U-10 "갱신시각" 요구). */
  showObservedTime?: boolean;
  size?: "sm" | "md";
  className?: string;
}

export default function OperatingStatusBadge({
  code,
  labelOverride,
  observedAt,
  staleAfterMinutes = DEFAULT_STALE_AFTER_MINUTES,
  showObservedTime = false,
  size = "md",
  className,
}: OperatingStatusBadgeProps) {
  // 서버-클라이언트 렌더 시각 불일치(hydration mismatch)를 피하려고, 마운트 전에는
  // 신선도를 판단하지 않고 일단 주어진 코드 그대로 보여준 뒤 마운트 후 보정한다.
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);

  const isStale =
    mounted &&
    (!observedAt || minutesSince(observedAt, Date.now()) > staleAfterMinutes);

  const effectiveCode: OperatingStatusCode = isStale
    ? "UNKNOWN"
    : (STATUS_DEFS as Record<string, StatusDef>)[code]
      ? (code as OperatingStatusCode)
      : "UNKNOWN";

  const def = STATUS_DEFS[effectiveCode] ?? STATUS_DEFS.UNKNOWN;
  const label = isStale ? "현재 상태 미확인" : (labelOverride ?? def.label);
  const colors = TONE_COLORS[def.tone];
  const fontSize = size === "sm" ? "0.6875rem" : "0.75rem";
  const padding = size === "sm" ? "0.125rem 0.5rem" : "0.25rem 0.625rem";

  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full font-semibold ${className ?? ""}`}
      style={{
        color: colors.fg,
        backgroundColor: colors.bg,
        fontSize,
        padding,
        lineHeight: 1.4,
      }}
    >
      <ToneIcon tone={isStale ? "neutral" : def.tone} />
      <span>{label}</span>
      {showObservedTime && observedAt && !isStale ? (
        <span style={{ fontWeight: 500, opacity: 0.8 }}>
          · {formatObservedTime(observedAt)} 확인
        </span>
      ) : null}
    </span>
  );
}
