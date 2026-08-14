import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("../api", () => ({
  resolveFloorPlanStops: vi.fn(),
}));

import { resolveFloorPlanStops } from "../api";
import RouteFloorPlan from "../RouteFloorPlan";
import type { ResolvedStop } from "../types";
import type { RouteItemView } from "@/lib/types";

const mockResolveFloorPlanStops = vi.mocked(resolveFloorPlanStops);

function routeItem(overrides: Partial<RouteItemView>): RouteItemView {
  return {
    sequence: 1,
    object_type: "BOOTH",
    object_id: "booth-1",
    expected_arrival_at: null,
    expected_stay_minutes: 15,
    actual_arrival_at: null,
    status: "PENDING",
    ...overrides,
  };
}

function resolvedStop(sequence: number, boothNumber: string, x: number, y: number): ResolvedStop {
  return {
    item: routeItem({ sequence, object_id: `booth-${sequence}` }),
    boothId: `booth-${sequence}`,
    boothNumber,
    zoneName: "A구역",
    point: { x, y },
  };
}

describe("RouteFloorPlan", () => {
  it("shows a loading state before booth positions resolve", () => {
    mockResolveFloorPlanStops.mockReturnValue(new Promise(() => {}));
    render(<RouteFloorPlan items={[routeItem({ sequence: 1 })]} />);
    expect(screen.getByRole("status")).toHaveTextContent("평면도를 준비하고 있어요");
  });

  it("renders stops in sequence order regardless of the resolution order returned", async () => {
    // 일부러 순서를 뒤섞어 반환한다 - 컴포넌트가 반드시 sequence 기준으로 재정렬해야 한다.
    mockResolveFloorPlanStops.mockResolvedValue({
      resolved: [resolvedStop(3, "C-03", 80, 20), resolvedStop(1, "A-01", 10, 10), resolvedStop(2, "B-02", 40, 15)],
      unresolved: [],
    });

    render(
      <RouteFloorPlan
        items={[routeItem({ sequence: 1 }), routeItem({ sequence: 2 }), routeItem({ sequence: 3 })]}
      />,
    );

    await waitFor(() => expect(screen.getByRole("list")).toBeInTheDocument());
    const listItems = screen.getAllByRole("listitem");
    expect(listItems.map((el) => el.textContent)).toEqual([
      "1. A-01 · A구역",
      "2. B-02 · A구역",
      "3. C-03 · A구역",
    ]);
  });

  it("states plainly that this is an approximate plan-view, not precise indoor navigation", async () => {
    mockResolveFloorPlanStops.mockResolvedValue({
      resolved: [resolvedStop(1, "A-01", 10, 10)],
      unresolved: [],
    });
    render(<RouteFloorPlan items={[routeItem({ sequence: 1 })]} />);
    await waitFor(() => expect(screen.getByRole("list")).toBeInTheDocument());
    expect(screen.getByText(/개략적인 평면도/)).toBeInTheDocument();
    expect(screen.getByText(/정밀한 실내\s*내비게이션이 아니니/)).toBeInTheDocument();
  });

  it("notes how many stops could not be plotted rather than guessing their position", async () => {
    mockResolveFloorPlanStops.mockResolvedValue({
      resolved: [resolvedStop(1, "A-01", 10, 10)],
      unresolved: [{ item: routeItem({ sequence: 2, object_type: "MEETING" }), reason: "NO_BOOTH_MAPPING" }],
    });
    render(<RouteFloorPlan items={[routeItem({ sequence: 1 }), routeItem({ sequence: 2 })]} />);
    await waitFor(() => expect(screen.getByText(/1개 방문지는 위치 정보가 없어/)).toBeInTheDocument());
  });

  it("shows an error state when position resolution fails", async () => {
    mockResolveFloorPlanStops.mockRejectedValue(new Error("network"));
    render(<RouteFloorPlan items={[routeItem({ sequence: 1 })]} />);
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("평면도를 불러오지 못했습니다"));
  });

  it("renders without crashing at a 360px mobile viewport", async () => {
    mockResolveFloorPlanStops.mockResolvedValue({
      resolved: [resolvedStop(1, "A-01", 10, 10), resolvedStop(2, "B-02", 90, 90)],
      unresolved: [],
    });
    const originalWidth = window.innerWidth;
    Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: 360 });
    render(<RouteFloorPlan items={[routeItem({ sequence: 1 }), routeItem({ sequence: 2 })]} />);
    await waitFor(() => expect(screen.getByRole("list")).toBeInTheDocument());
    expect(screen.getByRole("img")).toBeInTheDocument();
    Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: originalWidth });
  });
});
