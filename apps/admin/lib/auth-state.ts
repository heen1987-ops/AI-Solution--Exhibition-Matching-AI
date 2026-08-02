/**
 * 관리자 세션(역할) 상태.
 *
 * TODO(ADMIN-001 범위 - 이 작업 지시에는 없음): 이 작업 지시는 "역할별 버튼 노출 제어"만
 * 요구하고 실제 로그인·MFA 화면은 요구하지 않는다(.harness/backlog.yaml ADMIN-001이 별도
 * 과제로 MFA 로그인을 다룬다). apps/api에도 아직 관리자 로그인 API가 없다. 그래서 이
 * 모듈은 "로그인된 것처럼 꾸미는 가짜 인증"이 아니라, 화면 우측 상단의 명시적 세션 전환기
 * (components/SessionSwitcher.tsx)로 관리자가 직접 역할·actor_user_id를 선택하는 개발용
 * 스텁이다. actor_user_id는 apps/api/app/api/v1/routers/partner.py의 `X-Actor-User-Id`
 * 헤더로 그대로 전달되어 백엔드가 실제 DB의 UserRole 레코드로 권한을 검사한다(관리자가
 * 잘못된 ID를 넣으면 진짜 403이 뜬다 - 가짜 성공이 아니다).
 *
 * localStorage에 저장해 새로고침 후에도 유지한다. 서버 컴포넌트에서는 접근하지 않는다
 * (모든 사용처가 "use client" 컴포넌트).
 */

import type { AdminRole, AdminSession } from "./types";

const STORAGE_KEY = "backju-admin-session/v1";

export const ROLE_LABELS: Record<AdminRole, string> = {
  EVENT_ADMIN: "행사 운영자 (전체 승인권한)",
  DATA_REVIEWER: "데이터 검수자 (검수·승인)",
  EXHIBITOR_ADMIN: "참가업체 담당자 (자사 초안·제출만)",
};

const DEFAULT_SESSION: AdminSession = {
  role: "DATA_REVIEWER",
  actorUserId: null,
  exhibitorId: null,
  displayName: "미확인 사용자",
};

function isBrowser(): boolean {
  return typeof window !== "undefined";
}

export function getStoredSession(): AdminSession | null {
  if (!isBrowser()) return null;
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as Partial<AdminSession>;
    if (!parsed || typeof parsed !== "object") return null;
    return {
      role: (parsed.role as AdminRole) ?? DEFAULT_SESSION.role,
      actorUserId: parsed.actorUserId ?? null,
      exhibitorId: parsed.exhibitorId ?? null,
      displayName: parsed.displayName ?? DEFAULT_SESSION.displayName,
    };
  } catch {
    return null;
  }
}

export function saveSession(session: AdminSession): void {
  if (!isBrowser()) return;
  window.localStorage.setItem(STORAGE_KEY, JSON.stringify(session));
  // 같은 탭 안의 다른 컴포넌트(SessionSwitcher, RoleGate 등)에게 변경을 알린다.
  window.dispatchEvent(new CustomEvent("backju-admin-session-changed"));
}

export function clearSession(): void {
  if (!isBrowser()) return;
  window.localStorage.removeItem(STORAGE_KEY);
  window.dispatchEvent(new CustomEvent("backju-admin-session-changed"));
}

export function getDefaultSession(): AdminSession {
  return { ...DEFAULT_SESSION };
}

// ---------------------------------------------------------------------------
// §46 RBAC - 역할별 허용 동작. 화면 컴포넌트는 이 헬퍼로 버튼 노출을 결정한다
// (작업 지시: "역할별 버튼 노출 제어").
// ---------------------------------------------------------------------------

export type AdminCapability =
  | "EXHIBITOR_APPROVE" // 업체 승인/반려 (전체)
  | "EXHIBITOR_REVIEW" // 검수 큐 조회·검수 코멘트
  | "EXHIBITOR_EDIT_OWN" // 자사 업체 초안 작성·수정
  | "EXHIBITOR_SUBMIT_OWN" // 자사 업체 검수 제출
  | "BOOTH_STATUS_CHANGE"
  | "BOOTH_MANAGE"
  | "PRODUCT_MANAGE_ANY"
  | "PRODUCT_MANAGE_OWN"
  | "EVENT_MANAGE"
  | "AUDIT_VIEW";

const ROLE_CAPABILITIES: Record<AdminRole, AdminCapability[]> = {
  EVENT_ADMIN: [
    "EXHIBITOR_APPROVE",
    "EXHIBITOR_REVIEW",
    "BOOTH_STATUS_CHANGE",
    "BOOTH_MANAGE",
    "PRODUCT_MANAGE_ANY",
    "EVENT_MANAGE",
    "AUDIT_VIEW",
  ],
  DATA_REVIEWER: ["EXHIBITOR_APPROVE", "EXHIBITOR_REVIEW", "PRODUCT_MANAGE_ANY", "AUDIT_VIEW"],
  EXHIBITOR_ADMIN: ["EXHIBITOR_EDIT_OWN", "EXHIBITOR_SUBMIT_OWN", "PRODUCT_MANAGE_OWN"],
};

export function hasCapability(role: AdminRole, capability: AdminCapability): boolean {
  return ROLE_CAPABILITIES[role]?.includes(capability) ?? false;
}
