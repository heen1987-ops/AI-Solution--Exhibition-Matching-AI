import "@testing-library/jest-dom/vitest";

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import MetricCard from "../components/MetricCard";
import { SUPPRESSED_LABEL } from "../logic";

afterEach(() => {
  cleanup();
});

describe("MetricCard (small-group suppression rendering)", () => {
  it("shows the exact value for a normal metric", () => {
    render(<MetricCard label="가입자 수" metric={{ value: 120, suppressed: false }} />);
    expect(screen.getByText("120")).toBeInTheDocument();
  });

  it("never shows the exact number for a suppressed metric, and explains why via a title", () => {
    render(<MetricCard label="희귀 관심사" metric={{ value: null, suppressed: true }} />);
    const value = screen.getByText(SUPPRESSED_LABEL);
    expect(value).toBeInTheDocument();
    expect(value).toHaveAttribute("title", expect.stringContaining("5명 미만"));
  });

  it("shows an explicit 'backend does not provide this yet' state instead of fabricating a number", () => {
    render(<MetricCard label="개인화 거부율" metric={undefined} />);
    expect(screen.getByText("백엔드 미제공")).toBeInTheDocument();
  });
});
