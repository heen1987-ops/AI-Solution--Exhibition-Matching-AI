"use client";

import Link from "next/link";

import SessionSwitcher from "./SessionSwitcher";

export default function TopBar() {
  return (
    <header
      className="sticky top-0 z-30 flex items-center justify-between border-b border-[var(--color-border)] bg-[var(--color-surface)] px-4"
      style={{ height: "var(--top-bar-height)" }}
    >
      <Link href="/dashboard" className="tap-target font-semibold">
        백주 AI 셀파 · 관리자
      </Link>
      <SessionSwitcher />
    </header>
  );
}
