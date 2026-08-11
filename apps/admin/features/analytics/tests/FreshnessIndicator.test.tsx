import "@testing-library/jest-dom/vitest";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import FreshnessIndicator from "../components/FreshnessIndicator";

afterEach(() => {
  cleanup();
});

describe("FreshnessIndicator (task instruction: always-visible freshness indicator)", () => {
  it("is present before any fetch has completed", () => {
    render(<FreshnessIndicator dataAsOf={null} fetchedAt={null} />);
    const el = screen.getByTestId("freshness-indicator");
    expect(el).toBeInTheDocument();
    expect(el.textContent).toContain("집계는 실제 활동보다 지연될 수 있습니다");
  });

  it("shows the backend data_as_of timestamp once available", () => {
    render(<FreshnessIndicator dataAsOf="2026-08-03T09:00:00Z" fetchedAt={new Date("2026-08-03T10:00:00Z")} />);
    const el = screen.getByTestId("freshness-indicator");
    expect(el.textContent).toContain("데이터 기준");
    expect(el.textContent).toContain("집계는 실제 활동보다 지연될 수 있습니다");
  });

  it("falls back to the fetch time when data_as_of is missing, but still flags possible lag", () => {
    render(<FreshnessIndicator dataAsOf={null} fetchedAt={new Date("2026-08-03T10:00:00Z")} />);
    const el = screen.getByTestId("freshness-indicator");
    expect(el.textContent).toContain("조회 시각 기준");
  });
});
