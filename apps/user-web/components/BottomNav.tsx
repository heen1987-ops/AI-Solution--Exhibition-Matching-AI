"use client";

/**
 * 모바일 하단 탭 내비게이션.
 *
 * 근거: docs/user-ia-wireframes.md 4.1절(모바일 하단 탭) - 홈/탐색/지도/일정/MY 5개 탭과
 * 각 경로, "하단 탭은 5개를 넘기지 않는다. 상담은 별도 탭을 만들지 않고 홈·일정·업체
 * 상세에서 진입한다"는 원칙의 1차 근거. 13.2절(접근성) - 터치 영역 44x44px 이상, 색상만으로
 * 상태를 구분하지 않음(아이콘+텍스트+`aria-current` 병행), 13.1절 - 고정 CTA는 안전영역을
 * 침범하지 않는다.
 */

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode, SVGProps } from "react";

interface NavItem {
  href: string;
  label: string;
  icon: (props: SVGProps<SVGSVGElement>) => ReactNode;
}

function IconHome(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <path d="M3 11.5 12 4l9 7.5" />
      <path d="M5 10v9a1 1 0 0 0 1 1h4v-6h4v6h4a1 1 0 0 0 1-1v-9" />
    </svg>
  );
}

function IconExplore(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <circle cx="11" cy="11" r="7" />
      <line x1="21" y1="21" x2="16.65" y2="16.65" />
    </svg>
  );
}

function IconMap(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <polygon points="1 6 1 22 8 18 16 22 23 18 23 2 16 6 8 2 1 6" />
      <line x1="8" y1="2" x2="8" y2="18" />
      <line x1="16" y1="6" x2="16" y2="22" />
    </svg>
  );
}

function IconSchedule(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <rect x="3" y="4" width="18" height="18" rx="2" ry="2" />
      <line x1="16" y1="2" x2="16" y2="6" />
      <line x1="8" y1="2" x2="8" y2="6" />
      <line x1="3" y1="10" x2="21" y2="10" />
    </svg>
  );
}

function IconMy(props: SVGProps<SVGSVGElement>) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth={2}
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      {...props}
    >
      <path d="M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2" />
      <circle cx="12" cy="7" r="4" />
    </svg>
  );
}

// 4.1절 표: 탭 순서와 경로 고정. 6개 이상 늘리지 않는다.
const NAV_ITEMS: NavItem[] = [
  { href: "/home", label: "홈", icon: IconHome },
  { href: "/explore", label: "탐색", icon: IconExplore },
  { href: "/map", label: "지도", icon: IconMap },
  { href: "/schedule", label: "일정", icon: IconSchedule },
  { href: "/my", label: "MY", icon: IconMy },
];

function isActive(pathname: string | null, href: string): boolean {
  if (!pathname) return false;
  return pathname === href || pathname.startsWith(`${href}/`);
}

export default function BottomNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="주요 메뉴"
      className="pb-safe-bottom fixed inset-x-0 bottom-0 z-40 border-t"
      style={{
        height: "calc(var(--bottom-nav-height) + var(--safe-bottom))",
        backgroundColor: "var(--color-surface)",
        borderColor: "var(--color-border)",
      }}
    >
      <ul className="grid h-[var(--bottom-nav-height)] grid-cols-5">
        {NAV_ITEMS.map((item) => {
          const active = isActive(pathname, item.href);
          const Icon = item.icon;
          return (
            <li key={item.href} className="flex items-center justify-center">
              <Link
                href={item.href}
                aria-current={active ? "page" : undefined}
                className="tap-target relative flex h-full w-full flex-col items-center justify-center gap-1"
                style={{
                  color: active ? "var(--color-brand)" : "var(--color-text-muted)",
                }}
              >
                {active ? (
                  <span
                    aria-hidden="true"
                    className="absolute inset-x-4 top-0 h-0.5"
                    style={{ backgroundColor: "var(--color-brand)" }}
                  />
                ) : null}
                <Icon width={24} height={24} />
                <span
                  className="text-xs leading-none"
                  style={{ fontWeight: active ? 700 : 500 }}
                >
                  {item.label}
                </span>
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}
