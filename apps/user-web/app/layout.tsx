import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "백주대간 사용자 웹 (Wave 1 스켈레톤)",
  description: "웹 초개인화 모듈 - 라우트 뼈대 (Mock 데이터, WEB-001)",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className="h-full antialiased">
      <body className="min-h-full flex flex-col font-sans">{children}</body>
    </html>
  );
}
