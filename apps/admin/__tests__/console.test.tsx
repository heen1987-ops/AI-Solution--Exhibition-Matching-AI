import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import ConsolePage from "../app/console/page";
import { ADMIN_AREAS } from "../lib/admin-areas";

test("/console lists every planned admin area as a disabled placeholder card", () => {
  render(<ConsolePage />);

  expect(
    screen.getByRole("heading", { level: 1, name: "운영 콘솔 (예정 목록)" })
  ).toBeDefined();

  for (const area of ADMIN_AREAS) {
    const card = screen.getByTestId(`admin-area-${area.key}`);
    expect(card.getAttribute("aria-disabled")).toBe("true");
    expect(card.textContent).toContain(area.title);
  }

  // No real approval/RBAC/audit workflow should exist yet - these are cards, not links/forms.
  expect(screen.queryAllByRole("link").length).toBe(0);
  expect(screen.queryAllByRole("button").length).toBe(0);
  expect(screen.getAllByText("예정").length).toBe(ADMIN_AREAS.length);
});
