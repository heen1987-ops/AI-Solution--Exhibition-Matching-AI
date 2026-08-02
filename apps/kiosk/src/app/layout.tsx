import type { Metadata, Viewport } from "next";
import { SessionTimeoutProvider } from "@/components/kiosk/SessionTimeoutProvider";
import "./globals.css";

export const metadata: Metadata = {
  title: "백주대간 전시 안내 키오스크",
  description:
    "현장 비등록 방문객을 위한 익명 키오스크 검색모듈 - 회원가입/개인정보 입력 없음",
};

export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  maximumScale: 1,
  userScalable: false,
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body>
        <SessionTimeoutProvider>{children}</SessionTimeoutProvider>
      </body>
    </html>
  );
}
