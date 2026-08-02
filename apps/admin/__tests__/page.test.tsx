import { expect, test } from "vitest";
import { render, screen } from "@testing-library/react";
import Home from "../app/page";

test("/ renders the admin ready/placeholder screen", () => {
  render(<Home />);
  expect(
    screen.getByRole("heading", { level: 1, name: "관리자 준비 화면" })
  ).toBeDefined();
  // Skeleton-only: page must not claim real auth/RBAC exists yet.
  expect(screen.getByText(/실제 로그인·권한\(RBAC\)/)).toBeDefined();
});
