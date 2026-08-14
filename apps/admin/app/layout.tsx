import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import SideNav from "@/components/SideNav";
import TopBar from "@/components/TopBar";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "백주 AI 셀파 관리자",
    template: "%s | 백주 AI 셀파 관리자",
  },
  description: "행사 운영자·참가업체 관리자를 위한 업체·제품·부스 검수 및 승인 도구",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#f7f5f1" },
    { media: "(prefers-color-scheme: dark)", color: "#15130f" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <a href="#main-content" className="skip-link">
          본문으로 바로가기
        </a>

        <TopBar />

        <div className="flex" style={{ minHeight: "calc(100dvh - var(--top-bar-height))" }}>
          <SideNav />
          <main id="main-content" className="min-w-0 flex-1 p-4 md:p-6">
            <div className="mx-auto max-w-screen-content">{children}</div>
          </main>
        </div>
      </body>
    </html>
  );
}
