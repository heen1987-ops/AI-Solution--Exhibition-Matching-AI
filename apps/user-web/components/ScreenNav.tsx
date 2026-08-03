"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const SCREENS = [
  { href: "/home", label: "S-1 개인화 홈" },
  { href: "/recommendations", label: "S-2 추천 목록" },
  { href: "/search", label: "S-3 자연어 검색" },
  { href: "/favorites", label: "S-4 관심목록" },
  { href: "/companies/c-001", label: "S-5 업체·부스 상세" },
  { href: "/buyer-matching", label: "S-6 바이어 매칭" },
  { href: "/my", label: "S-7 MY 정보" },
  { href: "/signup", label: "S-8 회원 전환" },
] as const;

export function ScreenNav() {
  const pathname = usePathname();

  return (
    <nav
      aria-label="화면 이동"
      className="flex flex-wrap gap-2 border-b border-zinc-200 bg-white px-4 py-3 dark:border-zinc-800 dark:bg-black"
    >
      <Link href="/" className="mr-2 text-xs font-semibold text-zinc-400 hover:text-zinc-600">
        ← 준비 화면
      </Link>
      {SCREENS.map((screen) => {
        const isActive = pathname === screen.href || pathname.startsWith(`${screen.href}/`);
        return (
          <Link
            key={screen.href}
            href={screen.href}
            aria-current={isActive ? "page" : undefined}
            className={`rounded-full px-3 py-1 text-xs font-medium transition-colors ${
              isActive
                ? "bg-zinc-900 text-white dark:bg-zinc-100 dark:text-zinc-900"
                : "bg-zinc-100 text-zinc-600 hover:bg-zinc-200 dark:bg-zinc-800 dark:text-zinc-300 dark:hover:bg-zinc-700"
            }`}
          >
            {screen.label}
          </Link>
        );
      })}
    </nav>
  );
}
