import "@testing-library/jest-dom/vitest";

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import TargetSegmentPicker from "../components/TargetSegmentPicker";
import { TARGET_SEGMENTS } from "../logic";

describe("TargetSegmentPicker", () => {
  it("renders exactly the 6 allowed coarse segments and nothing else", () => {
    render(
      <TargetSegmentPicker segment="ALL_REGISTERED_USERS" roleCode={null} onChange={vi.fn()} />,
    );
    const select = screen.getByLabelText("대상 세그먼트") as HTMLSelectElement;
    const optionValues = Array.from(select.options).map((o) => o.value);
    expect(optionValues).toHaveLength(TARGET_SEGMENTS.length);
    expect(new Set(optionValues)).toEqual(new Set(TARGET_SEGMENTS));
  });

  it("never renders a free-text input for targeting (no attribute/behavior escape hatch)", () => {
    render(
      <TargetSegmentPicker segment="ALL_REGISTERED_USERS" roleCode={null} onChange={vi.fn()} />,
    );
    expect(screen.queryByRole("textbox")).toBeNull();
  });

  it("shows the role picker only when SPECIFIC_ROLE is selected", () => {
    const { rerender } = render(
      <TargetSegmentPicker segment="BUYERS" roleCode={null} onChange={vi.fn()} />,
    );
    expect(screen.queryByLabelText("역할")).toBeNull();

    rerender(
      <TargetSegmentPicker segment="SPECIFIC_ROLE" roleCode="OPERATOR" onChange={vi.fn()} />,
    );
    expect(screen.getByLabelText("역할")).toBeInTheDocument();
  });
});
