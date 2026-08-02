"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * 작업 지시가 지정한 6개 화면 + 홈. §43절 A00~A15 화면군 중 이 작업 범위에 해당하는
 * 것만 연결한다(나머지는 ADMIN-002/003 등 후속 과제).
 */
const NAV_ITEMS: { href: string; label: string }[] = [
  { href: "/dashboard", label: "관리자 홈" },
  { href: "/events", label: "행사 관리" },
  { href: "/exhibitors", label: "참가업체" },
  { href: "/products", label: "제품·서비스" },
  { href: "/booths", label: "부스" },
  { href: "/audit", label: "감사로그" },
];

export default function SideNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="관리자 메뉴"
      className="hidden shrink-0 border-r border-[var(--color-border)] bg-[var(--color-surface)] md:block"
      style={{ width: "var(--side-nav-width)" }}
    >
      <ul className="flex flex-col gap-1 p-3">
        {NAV_ITEMS.map((item) => {
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
