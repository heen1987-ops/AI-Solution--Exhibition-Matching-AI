import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import AnalyticsFilterBar from "../components/AnalyticsFilterBar";
import type { AnalyticsFilter } from "../types";

afterEach(() => {
  cleanup();
});

function baseFilter(overrides: Partial<AnalyticsFilter> = {}): AnalyticsFilter {
  return { eventId: "", preset: "LAST_7_DAYS", customStart: null, customEnd: null, channel: "ALL", ...overrides };
}

describe("AnalyticsFilterBar", () => {
  it("exposes all four required date-range presets", () => {
    render(<AnalyticsFilterBar filter={baseFilter()} onChange={vi.fn()} />);
    const select = screen.getByLabelText("기간") as HTMLSelectElement;
    const optionLabels = Array.from(select.options).map((o) => o.textContent);
    expect(optionLabels).toEqual(["오늘", "행사 기간 전체", "최근 7일", "직접 지정"]);
  });

  it("only shows the custom start/end date inputs when preset is CUSTOM", () => {
    const { rerender } = render(<AnalyticsFilterBar filter={baseFilter({ preset: "TODAY" })} onChange={vi.fn()} />);
    expect(screen.queryByLabelText("시작일")).not.toBeInTheDocument();

    rerender(<AnalyticsFilterBar filter={baseFilter({ preset: "CUSTOM" })} onChange={vi.fn()} />);
    expect(screen.getByLabelText("시작일")).toBeInTheDocument();
    expect(screen.getByLabelText("종료일")).toBeInTheDocument();
  });

  it("calls onChange with the updated preset when the user selects a different one", () => {
    const onChange = vi.fn();
    render(<AnalyticsFilterBar filter={baseFilter()} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("기간"), { target: { value: "TODAY" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ preset: "TODAY" }));
  });

  it("calls onChange with the typed event id, preserving the rest of the filter", () => {
    const onChange = vi.fn();
    render(<AnalyticsFilterBar filter={baseFilter()} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("행사 ID"), { target: { value: "evt-42" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ eventId: "evt-42", preset: "LAST_7_DAYS" }));
  });

  it("hides the channel selector when showChannel is false (buyer section has no channel dimension)", () => {
    render(<AnalyticsFilterBar filter={baseFilter()} onChange={vi.fn()} showChannel={false} />);
    expect(screen.queryByLabelText("채널")).not.toBeInTheDocument();
  });

  it("calls onChange with the selected channel", () => {
    const onChange = vi.fn();
    render(<AnalyticsFilterBar filter={baseFilter()} onChange={onChange} />);
    fireEvent.change(screen.getByLabelText("채널"), { target: { value: "KIOSK" } });
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ channel: "KIOSK" }));
  });
});
