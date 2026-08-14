"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { hasCapability, type AdminCapability } from "@/lib/auth-state";
import { useSession } from "@/lib/use-session";
import type { AdminRole } from "@/lib/types";

/**
 * 작업 지시가 지정한 6개 화면 + 홈, 그리고 WAVE 2C/2D/2E가 새로 추가한 화면들
 * (바이어 검증, 상담 운영, AI 검수, 통계, 운영, 행사 메시지, 참가업체 포털). §43절 A00~A15
 * 화면군 중 이 작업 범위에 해당하는 것만 연결한다.
 *
 * `AdminCapability`(apps/admin/lib/auth-state.ts, 공유 파일 - 이 트랙 소유 밖이라 새
 * capability를 추가하지 않는다)로 표현되지 않는 새 화면은 `roles`로 직접 게이트한다 -
 * 백엔드 라우터 인가(require_roles)와 동일한 역할 집합을 그대로 미러링했다.
 */
const NAV_ITEMS: {
  href: string;
  label: string;
  capabilities?: AdminCapability[];
  roles?: AdminRole[];
}[] = [
  { href: "/dashboard", label: "관리자 홈" },
  { href: "/events", label: "행사 관리", capabilities: ["EVENT_MANAGE"] },
  {
    href: "/exhibitors",
    label: "참가업체",
    capabilities: ["EXHIBITOR_REVIEW", "EXHIBITOR_EDIT_OWN"],
  },
  {
    href: "/products",
    label: "제품·서비스",
    capabilities: ["PRODUCT_MANAGE_ANY", "PRODUCT_MANAGE_OWN"],
  },
  {
    href: "/booths",
    label: "부스",
    capabilities: ["BOOTH_MANAGE", "BOOTH_STATUS_CHANGE"],
  },
  {
    href: "/buyers",
    label: "바이어 검증",
    roles: ["EVENT_ADMIN", "DATA_REVIEWER"],
  },
  {
    href: "/meetings",
    label: "상담 운영",
    roles: ["EVENT_ADMIN", "DATA_REVIEWER"],
  },
  {
    href: "/ai-review",
    label: "AI 검수",
    roles: ["EVENT_ADMIN", "DATA_REVIEWER"],
  },
  {
    href: "/analytics",
    label: "통계",
    roles: ["EVENT_ADMIN", "DATA_REVIEWER", "EXHIBITOR_ADMIN"],
  },
  {
    href: "/operations",
    label: "운영",
    roles: ["EVENT_ADMIN"],
  },
  {
    href: "/event-messages",
    label: "행사 메시지",
    roles: ["EVENT_ADMIN"],
  },
  {
    href: "/partner/meetings",
    label: "포털 · 상담",
    roles: ["EXHIBITOR_ADMIN"],
  },
  {
    href: "/partner/documents",
    label: "포털 · 문서",
    roles: ["EXHIBITOR_ADMIN"],
  },
  {
    href: "/partner/ai-review",
    label: "포털 · AI 검수",
    roles: ["EXHIBITOR_ADMIN"],
  },
  { href: "/audit", label: "감사로그", capabilities: ["AUDIT_VIEW"] },
];

export default function SideNav() {
  const pathname = usePathname();
  const [session] = useSession();
  const visibleItems = session.role
    ? NAV_ITEMS.filter((item) => {
        if (item.capabilities) {
          return item.capabilities.some((capability) => hasCapability(session.role, capability));
        }
        if (item.roles) {
          return session.role !== null && item.roles.includes(session.role);
        }
        return true;
      })
    : [];

  return (
    <nav
      aria-label="관리자 메뉴"
      className="hidden shrink-0 border-r border-[var(--color-border)] bg-[var(--color-surface)] md:block"
      style={{ width: "var(--side-nav-width)" }}
    >
      <ul className="flex flex-col gap-1 p-3">
        {visibleItems.map((item) => {
          const active = pathname === item.href || pathname?.startsWith(`${item.href}/`);
          return (
            <li key={item.href}>
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className={`tap-target block rounded-md px-3 py-2 text-sm font-medium ${
                  active
                    ? "bg-[var(--color-brand)] text-[var(--color-brand-contrast)]"
                    : "text-[var(--color-text)] hover:bg-[var(--color-surface-muted)]"
                }`}
              >
                {item.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
