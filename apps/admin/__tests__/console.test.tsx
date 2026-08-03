import { expect, test, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import ConsolePage from "../app/console/page";
import { ADMIN_AREAS } from "../lib/admin-areas";

test("/console renders live admin operations and contract-pending areas", async () => {
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");
  const element = await ConsolePage();
  render(element);

  expect(
    screen.getByRole("heading", { level: 1, name: "운영 콘솔" })
  ).toBeDefined();

  expect(screen.getByRole("button", { name: "승인 처리" })).toBeDefined();
  expect(screen.getByRole("button", { name: "상태 저장" })).toBeDefined();
  expect(screen.getAllByText("바이어 검증").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText("계약 대기").length).toBeGreaterThanOrEqual(2);
  expect(screen.getByText("사전등록 연계")).toBeDefined();

  for (const area of ADMIN_AREAS) {
    const card = screen.getByTestId(`admin-area-${area.key}`);
    expect(card.textContent).toContain(area.title);
  }
});
