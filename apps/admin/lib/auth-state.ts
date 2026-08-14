/** Verified server-session projection for admin UI authorization hints. */

import type { AdminRole, AdminSession } from "./types";

export const ROLE_LABELS: Record<AdminRole, string> = {
  EVENT_ADMIN: "행사 운영자 (전체 승인권한)",
  DATA_REVIEWER: "데이터 검수자 (검수·승인)",
  EXHIBITOR_ADMIN: "참가업체 담당자 (자사 초안·제출만)",
};

const ANONYMOUS_SESSION: AdminSession = {
  role: null,
  actorUserId: null,
  exhibitorId: null,
  displayName: "로그인 필요",
  state: "ANONYMOUS",
  csrfToken: null,
};

type RoleGrant = {
  role: AdminRole;
  exhibitor_id: string | null;
};

type ServerSession = {
  state: Exclude<AdminSession["state"], "ANONYMOUS">;
  csrf_token: string;
  principal: {
    subject_id: string;
    role_grants: RoleGrant[];
  };
};

let currentSession: AdminSession = { ...ANONYMOUS_SESSION };
const API_ORIGIN = (process.env.NEXT_PUBLIC_API_BASE_URL ?? "").replace(/\/+$/, "");

export function authApiUrl(path: string): string {
  return `${API_ORIGIN}/api/v1${path}`;
}

export function getDefaultSession(): AdminSession {
  return { ...ANONYMOUS_SESSION };
}

export function getRuntimeSession(): AdminSession {
  return currentSession;
}

export function setRuntimeSession(session: AdminSession): void {
  currentSession = session;
}

export async function fetchVerifiedSession(): Promise<AdminSession> {
  const response = await fetch(authApiUrl("/auth/session"), {
    credentials: "include",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) {
    currentSession = getDefaultSession();
    return currentSession;
  }
  const payload = (await response.json()) as ServerSession;
  const grant = payload.principal.role_grants[0] ?? null;
  currentSession = {
    role: grant?.role ?? null,
    actorUserId: payload.principal.subject_id,
    exhibitorId: grant?.exhibitor_id ?? null,
    displayName: payload.principal.subject_id,
    state: payload.state,
    csrfToken: payload.csrf_token,
  };
  return currentSession;
}

export async function revokeVerifiedSession(): Promise<void> {
  const csrf = currentSession.csrfToken;
  if (csrf) {
    await fetch(authApiUrl("/auth/session"), {
      method: "DELETE",
      credentials: "include",
      headers: { "X-CSRF-Token": csrf },
    });
  }
  currentSession = getDefaultSession();
}

export type AdminCapability =
  | "EXHIBITOR_APPROVE"
  | "EXHIBITOR_REVIEW"
  | "EXHIBITOR_EDIT_OWN"
  | "EXHIBITOR_SUBMIT_OWN"
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

export function hasCapability(
  role: AdminRole | null,
  capability: AdminCapability,
): boolean {
  return role ? ROLE_CAPABILITIES[role].includes(capability) : false;
}
