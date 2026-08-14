"use client";

/**
 * 역할별 버튼·영역 노출 제어 (작업 지시 필수 요구사항).
 * EVENT_ADMIN=전체승인권한, DATA_REVIEWER=검수·승인, EXHIBITOR_ADMIN=자사 초안·제출만.
 * lib/auth-state.ts의 ROLE_CAPABILITIES가 정본 매핑이다.
 */

import type { ReactNode } from "react";

import { hasCapability, type AdminCapability } from "@/lib/auth-state";
import { useSession } from "@/lib/use-session";

export default function RoleGate({
  capability,
  children,
  fallback = null,
}: {
  capability: AdminCapability;
  children: ReactNode;
  fallback?: ReactNode;
}) {
  const [session] = useSession();
  if (!hasCapability(session.role, capability)) return <>{fallback}</>;
  return <>{children}</>;
}
