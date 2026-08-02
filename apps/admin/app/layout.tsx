import type { Metadata } from "next";
import "./globals.css";
import { NavBar } from "./nav-bar";

export const metadata: Metadata = {
  title: "백주대간 관리자 (Admin) - 스켈레톤",
  description:
    "행사 운영자용 관리자 포털의 Wave 1 라우트 뼈대. 실제 인증/권한/승인 로직은 아직 구현되지 않았다.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="ko" className="h-full antialiased">
      <body className="flex min-h-full flex-col">
        <NavBar />
        <main className="mx-auto w-full max-w-4xl flex-1 px-6 py-10">
          {children}
        </main>
      </body>
    </html>
  );
}
