import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import IdleGuard from "@/components/IdleGuard";
import LangSync from "@/components/LangSync";
import { KioskSessionProvider } from "@/lib/kiosk-session-context";

import "./globals.css";

export const metadata: Metadata = {
  title: "백주 AI 셀파 키오스크",
  description: "회원가입 없이 자연어로 관심 업체·부스를 찾는 현장 키오스크",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
  viewportFit: "cover",
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#fdf6ec" },
    { media: "(prefers-color-scheme: dark)", color: "#17130f" },
  ],
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <KioskSessionProvider>
          <IdleGuard />
          <LangSync />
          <main
            id="main-content"
            style={{
              minHeight: "100dvh",
              paddingTop: "var(--safe-top)",
              paddingBottom: "var(--safe-bottom)",
            }}
          >
            {children}
          </main>
        </KioskSessionProvider>
      </body>
    </html>
  );
}
