import type { Metadata } from "next";
import "./globals.css";
import { NavBar } from "./nav-bar";

export const metadata: Metadata = {
  title: "백주대간 관리자 (Admin)",
  description:
    "행사 운영자용 관리자 포털. 업체 승인, 부스 운영상태, 운영 통계 계약 상태를 관리한다.",
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
