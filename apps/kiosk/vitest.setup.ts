import "@testing-library/jest-dom/vitest";
import React from "react";
import { vi } from "vitest";

// Next.js App Router 컴포넌트(next/link, next/navigation)는 실제 RouterContext
// Provider 없이 렌더링하면 invariant 오류를 던진다. 이 스캐폴드 웨이브의 목적은
// 화면 골격 검증(특히 "개인정보 입력 필드 없음" 검증)이므로, 라우팅 동작 자체는
// 목(mock)으로 대체하고 실제 네비게이션/서버 API 연동 테스트는 이후 웨이브로 미룬다.

vi.mock("next/navigation", () => ({
  useRouter: () => ({
    push: vi.fn(),
    replace: vi.fn(),
    back: vi.fn(),
    forward: vi.fn(),
    refresh: vi.fn(),
    prefetch: vi.fn(),
  }),
  useParams: () => ({}),
  usePathname: () => "/",
  useSearchParams: () => new URLSearchParams(),
}));

vi.mock("next/link", () => ({
  default: React.forwardRef<
    HTMLAnchorElement,
    React.AnchorHTMLAttributes<HTMLAnchorElement> & { href: string }
  >(function MockLink({ href, children, ...rest }, ref) {
    return React.createElement("a", { href, ref, ...rest }, children);
  }),
}));
