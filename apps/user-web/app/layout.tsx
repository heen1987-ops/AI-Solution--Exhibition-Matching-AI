/**
 * 루트 레이아웃.
 *
 * 근거: docs/user-ia-wireframes.md 4절(글로벌 내비게이션) - 4.1절 하단 탭
 * (`components/BottomNav.tsx`), 4.2절 상단 공통 영역(`components/TopBar.tsx`)을 모든
 * 화면에 공통으로 포함한다. 13.2절(접근성) - "키보드만으로 모든 기능 사용 가능"을 위한
 * 본문 바로가기 링크, `lang="ko"`, 뷰포트 안전영역(`viewport-fit=cover`, 13.1절)의 근거.
 *
 * 온보딩 화면과의 관계에 대한 메모: 7절 와이어프레임 목업(U-01~U-07)은 상단바·하단탭 없이
 * 단일 카드만 보여준다. 이 저장소에는 아직 라우트 그룹이 없어(온보딩/메인 화면 담당
 * 에이전트가 각자 `app/onboarding/...`, `app/home/...` 등을 만드는 중) 지금은 전역으로
 * 적용해 둔다. 온보딩 라우트를 만드는 에이전트가 챗 없는 경험이 필요하면 자신의 라우트
 * 그룹에 별도 레이아웃을 추가해 이 전역 크롬을 대체/숨김 처리할 수 있다.
 */

import type { Metadata, Viewport } from "next";
import type { ReactNode } from "react";

import BottomNav from "@/components/BottomNav";
import TopBar from "@/components/TopBar";

import "./globals.css";

export const metadata: Metadata = {
  title: {
    default: "백주 AI 셀파",
    template: "%s | 백주 AI 셀파",
  },
  description: "나에게 맞는 술·양조장과 상담할 업체를 찾아주는 2026 대한민국 백주대간 AI 추천 서비스",
};

// 13.1절: 고정 CTA(상단바·하단탭)가 iOS/Android 안전영역을 침범하지 않도록
// viewport-fit=cover와 함께 env(safe-area-inset-*)를 쓴다 (globals.css 참고).
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
  themeColor: "#fbfaf6",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>
        {/* 13.2절: 키보드만으로 모든 기능 사용 가능 - 본문 바로가기. */}
        <a href="#main-content" className="skip-link">
          본문으로 바로가기
        </a>

        <TopBar />

        <main
          id="main-content"
          style={{
            minHeight: "100dvh",
            paddingTop: "calc(var(--top-bar-height) + var(--safe-top))",
            paddingBottom: "calc(var(--bottom-nav-height) + var(--safe-bottom))",
          }}
        >
          {children}
        </main>

        <BottomNav />
      </body>
    </html>
  );
}
