import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { ComparisonSelectionProvider, useComparisonSelection } from "../comparison-selection";

function Harness() {
  const { selectedIds, toggle } = useComparisonSelection();
  return (
    <div>
      <output data-testid="selected">{selectedIds.join(",")}</output>
      {["e1", "e2", "e3", "e4", "e5"].map((id) => (
        <button key={id} type="button" onClick={() => toggle(id)}>
          toggle-{id}
        </button>
      ))}
    </div>
  );
}

describe("useComparisonSelection", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("최대 4곳까지만 담기고, 5번째는 막힌다", () => {
    render(
      <ComparisonSelectionProvider>
        <Harness />
      </ComparisonSelectionProvider>,
    );

    fireEvent.click(screen.getByText("toggle-e1"));
    fireEvent.click(screen.getByText("toggle-e2"));
    fireEvent.click(screen.getByText("toggle-e3"));
    fireEvent.click(screen.getByText("toggle-e4"));
    expect(screen.getByTestId("selected")).toHaveTextContent("e1,e2,e3,e4");

    fireEvent.click(screen.getByText("toggle-e5"));
    expect(screen.getByTestId("selected")).toHaveTextContent("e1,e2,e3,e4");
    expect(screen.getByTestId("selected").textContent?.split(",").filter(Boolean)).toHaveLength(4);
  });

  it("이미 담긴 항목을 다시 누르면 빠지고, 그 자리에 새 항목을 담을 수 있다", () => {
    render(
      <ComparisonSelectionProvider>
        <Harness />
      </ComparisonSelectionProvider>,
    );

    fireEvent.click(screen.getByText("toggle-e1"));
    fireEvent.click(screen.getByText("toggle-e2"));
    fireEvent.click(screen.getByText("toggle-e3"));
    fireEvent.click(screen.getByText("toggle-e4"));
    fireEvent.click(screen.getByText("toggle-e1")); // 제거
    expect(screen.getByTestId("selected")).toHaveTextContent("e2,e3,e4");

    fireEvent.click(screen.getByText("toggle-e5"));
    expect(screen.getByTestId("selected")).toHaveTextContent("e2,e3,e4,e5");
  });
});
