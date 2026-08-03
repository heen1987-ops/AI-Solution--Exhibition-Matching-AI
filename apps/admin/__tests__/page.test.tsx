import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import Home from "../app/page";

test("/ renders the admin operations entry screen", () => {
  render(<Home />);
  expect(
    screen.getByRole("heading", { level: 1, name: "관리자 운영 화면" })
  ).toBeDefined();
  expect(screen.getByText(/업체 승인과 부스 상태 변경/)).toBeDefined();
});
