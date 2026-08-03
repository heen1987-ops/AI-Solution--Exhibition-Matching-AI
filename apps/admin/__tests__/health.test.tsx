import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import HealthPage from "../app/health/page";

test("/health renders admin app status without contacting a real API", () => {
  render(<HealthPage />);
  expect(
    screen.getByRole("heading", { level: 1, name: "관리자 앱 상태" })
  ).toBeDefined();
  expect(screen.getByText(/어떤 요청도 보내지 않습니다/)).toBeDefined();
  expect(screen.getAllByText("미구현 (예정)").length).toBeGreaterThan(0);
});

test("/health reflects NEXT_PUBLIC_ env vars when set", () => {
  const original = process.env.NEXT_PUBLIC_ADMIN_APP_NAME;
  process.env.NEXT_PUBLIC_ADMIN_APP_NAME = "테스트 관리자";

  render(<HealthPage />);
  expect(screen.getByText("테스트 관리자")).toBeDefined();

  process.env.NEXT_PUBLIC_ADMIN_APP_NAME = original;
});
