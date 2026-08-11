/**
 * 바이어 검증/상담 운영 뷰의 순수 로직. 컴포넌트에서 분리해 vitest로 직접 검증한다
 * (tests/logic.test.ts) - `../partner-meeting/logic.ts`와 같은 이유·같은 패턴이다.
 */

import type { BuyerVerificationAction, BuyerVerificationStatus } from "./types";

// ---------------------------------------------------------------------------
// 상태 머신 (작업 지시 필수 요구사항: PENDING->VERIFIED/LIMITED/REJECTED,
// VERIFIED->SUSPENDED/EXPIRED. 그 외 전이는 모두 금지.)
// ---------------------------------------------------------------------------

type Transitions = Partial<Record<BuyerVerificationAction, BuyerVerificationStatus>>;

export const BUYER_VERIFICATION_STATE_MACHINE: Record<BuyerVerificationStatus, Transitions> = {
  PENDING: { VERIFY: "VERIFIED", LIMIT: "LIMITED", REJECT: "REJECTED" },
  VERIFIED: { SUSPEND: "SUSPENDED", EXPIRE: "EXPIRED" },
  LIMITED: {},
  REJECTED: {},
  SUSPENDED: {},
  EXPIRED: {},
};

export const BUYER_VERIFICATION_ACTION_LABEL_KO: Record<BuyerVerificationAction, string> = {
  VERIFY: "검증 승인",
  LIMIT: "제한 승인",
  REJECT: "반려",
  SUSPEND: "정지",
  EXPIRE: "만료 처리",
};

/** 현재 상태에서 실제로 허용되는 동작 목록. 알 수 없는 상태 문자열(open enum)이면 빈
 * 배열을 반환해 안전하게 아무 버튼도 노출하지 않는다. */
export function allowedActions(
  status: BuyerVerificationStatus | string,
): BuyerVerificationAction[] {
  const transitions = BUYER_VERIFICATION_STATE_MACHINE[status as BuyerVerificationStatus];
  return transitions ? (Object.keys(transitions) as BuyerVerificationAction[]) : [];
}

export function isTransitionAllowed(
  status: BuyerVerificationStatus | string,
  action: BuyerVerificationAction,
): boolean {
  return allowedActions(status).includes(action);
}

export function targetStatusFor(
  status: BuyerVerificationStatus | string,
  action: BuyerVerificationAction,
): BuyerVerificationStatus | null {
  const transitions = BUYER_VERIFICATION_STATE_MACHINE[status as BuyerVerificationStatus];
  return transitions?.[action] ?? null;
}

// ---------------------------------------------------------------------------
// 사유 필수 검증 (작업 지시 필수 요구사항: "every verify/limit/reject/suspend action
// REQUIRES a reason field" - expire도 동일한 상태전이 그룹이므로 같은 규칙을 적용한다.
// 네트워크 호출 전에 막아 서버 계약이 아직 없어도 가드레일 자체는 지금 검증할 수 있게 한다
// - apps/admin/lib/api-client.ts의 rejectExhibitor가 이미 쓰는 것과 같은 패턴).
// ---------------------------------------------------------------------------

const MIN_REASON_LENGTH = 5;

export type ReasonValidation = { ok: true } | { ok: false; message: string };

export function validateReason(reason: string): ReasonValidation {
  const trimmed = reason.trim();
  if (!trimmed) {
    return { ok: false, message: "사유를 입력해야 합니다." };
  }
  if (trimmed.length < MIN_REASON_LENGTH) {
    return { ok: false, message: `사유를 ${MIN_REASON_LENGTH}자 이상 입력해 주세요.` };
  }
  return { ok: true };
}

export function isReasonValid(reason: string): boolean {
  return validateReason(reason).ok;
}

// ---------------------------------------------------------------------------
// 역할 게이트 (작업 지시 필수 요구사항: "role-gated access (only appropriate admin
// roles)"). `apps/admin/lib/auth-state.ts`의 ROLE_CAPABILITIES는 다른 트랙(ADMIN-001+002)이
// 동시에 편집 중인 공유 파일이라(WAVE 2C 작업 지시: "공유 aggregator/layout 파일은 소유
// 경로 밖이면 건드리지 말 것") 여기서 새 capability를 추가하지 않고, 이 트랙 전용의 독립
// 역할표를 둔다(`../partner-meeting/`가 자체 staff-session을 두는 것과 같은 이유).
// EVENT_ADMIN(전체승인권한)·DATA_REVIEWER(검수·승인)는 업체 승인과 대칭되는 권한을 바이어
// 검증에도 갖는다고 본다. EXHIBITOR_ADMIN(자사 초안·제출만)은 바이어 검증·상담 운영 뷰 둘
// 다 접근 권한이 없다 - 자사 업체 범위를 벗어나는 운영 데이터이기 때문이다.
// ---------------------------------------------------------------------------

const BUYER_OPS_ALLOWED_ROLES = new Set(["EVENT_ADMIN", "DATA_REVIEWER"]);

// 통합 시 재작성: `role`을 `AdminRole | null`(세션 하이드레이션 전 상태 포함)까지
// 받도록 넓혔다. Set.has(null)은 그 자체로 항상 false라 이 둘은 원래도 동작상
// fail-closed였지만, 시그니처가 `string`이라 `useSession()`의 `AdminRole | null`을 그대로
// 넘기면 타입에러가 났다(app/buyers/page.tsx, app/meetings/page.tsx).
export function canManageBuyerVerification(role: string | null): boolean {
  return role !== null && BUYER_OPS_ALLOWED_ROLES.has(role);
}

export function canViewMeetingOps(role: string | null): boolean {
  return role !== null && BUYER_OPS_ALLOWED_ROLES.has(role);
}

// ---------------------------------------------------------------------------
// 상담 운영 뷰 PII 방어 (작업 지시 필수 요구사항: "no raw contact-info leak in the
// operations list view" - "implement this restriction, do not just trust the frontend to
// hide it, the backend call you make must already be scoped"). 1차 방어선은 계약 자체가
// 연락처 필드를 아예 갖지 않는 것(types.ts AdminMeetingOpsItem 참고)이고, 이 함수는 그
// 계약이 실수로라도 이메일/전화번호처럼 보이는 문자열을 표시용 필드에 흘려보냈을 때 화면이
// 그대로 렌더링하지 않도록 하는 2차 방어선이다.
// ---------------------------------------------------------------------------

const EMAIL_PATTERN = /[\w.+-]+@[\w-]+\.[\w.-]+/g;
// 국내외 전화번호로 보이는 8자리 이상 숫자열(하이픈/공백/괄호 허용).
const PHONE_PATTERN = /(?:\+?\d[\d\-\s()]{6,}\d)/g;

export function redactPotentialContactInfo(value: string): string {
  return value.replace(EMAIL_PATTERN, "[REDACTED]").replace(PHONE_PATTERN, "[REDACTED]");
}
