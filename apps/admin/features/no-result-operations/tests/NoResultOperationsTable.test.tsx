import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import NoResultOperationsTable from "../components/NoResultOperationsTable";
import { toOperationsRow } from "../logic";
import type { NoResultOperationsRow, OperationsTask } from "../types";

afterEach(() => {
  cleanup();
});

function row(overrides: Partial<NoResultOperationsRow> = {}): NoResultOperationsRow {
  return {
    ...toOperationsRow({ query: "복분자 원액", count: 4, last_seen_at: "2026-08-01T00:00:00Z" }),
    ...overrides,
  };
}

describe("NoResultOperationsTable (integration - cause-classification + action affordances)", () => {
  it("shows 정보 없음 for backend contract gaps instead of fabricating 0/empty", () => {
    render(<NoResultOperationsTable rows={[row()]} tasks={{}} onAssignCause={vi.fn()} onApplyAction={vi.fn()} />);
    // resolved_concept_codes and channel each render as a standalone "정보 없음" cell.
    expect(screen.getAllByText("정보 없음").length).toBeGreaterThanOrEqual(2);
    // first_seen_at is also null on a freshly-mapped row, rendered inline as "최초: 정보 없음".
    expect(screen.getByText((_, element) => element?.textContent === "최초: 정보 없음")).toBeInTheDocument();
  });

  it("shows 태스크 없음 when no task exists yet for a query", () => {
    render(<NoResultOperationsTable rows={[row()]} tasks={{}} onAssignCause={vi.fn()} onApplyAction={vi.fn()} />);
    expect(screen.getByText("태스크 없음")).toBeInTheDocument();
  });

  it("lets the operator assign a cause even before a task exists (lazy task creation is the page's job)", () => {
    const onAssignCause = vi.fn();
    render(<NoResultOperationsTable rows={[row()]} tasks={{}} onAssignCause={onAssignCause} onApplyAction={vi.fn()} />);
    const select = screen.getByRole("combobox", { name: /원인 분류: 복분자 원액/ });
    fireEvent.change(select, { target: { value: "SYNONYM_MISSING" } });
    expect(onAssignCause).toHaveBeenCalledWith("복분자 원액", "SYNONYM_MISSING");
  });

  it("narrows action affordances to the task's current cause", () => {
    const task: OperationsTask = {
      task_id: "t-1",
      query_norm: "복분자 원액",
      status: "OPEN",
      cause: "NO_ELIGIBLE_EXHIBITOR",
      assignee: null,
      reason: null,
      history: [],
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
    };
    render(
      <NoResultOperationsTable
        rows={[row()]}
        tasks={{ "복분자 원액": task }}
        onAssignCause={vi.fn()}
        onApplyAction={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: /재인덱싱 요청/ })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /해결됨으로 표시/ })).toBeInTheDocument();
  });

  it("renders status history when present", () => {
    const task: OperationsTask = {
      task_id: "t-1",
      query_norm: "복분자 원액",
      status: "ACTION_REQUIRED",
      cause: "SYNONYM_MISSING",
      assignee: "operator-1",
      reason: null,
      history: [
        { from_status: "OPEN", to_status: "IN_REVIEW", actor: "operator-1", reason: null, at: "2026-08-01T00:00:00Z" },
        {
          from_status: "IN_REVIEW",
          to_status: "ACTION_REQUIRED",
          actor: "operator-1",
          reason: "동의어 추가 요청",
          at: "2026-08-01T01:00:00Z",
        },
      ],
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T01:00:00Z",
    };
    render(
      <NoResultOperationsTable
        rows={[row()]}
        tasks={{ "복분자 원액": task }}
        onAssignCause={vi.fn()}
        onApplyAction={vi.fn()}
      />,
    );
    expect(screen.getByText("이력 2건")).toBeInTheDocument();
    expect(screen.getByText("담당: operator-1")).toBeInTheDocument();
  });

  it("routes the applied action and note back through onApplyAction", () => {
    const onApplyAction = vi.fn();
    const task: OperationsTask = {
      task_id: "t-1",
      query_norm: "복분자 원액",
      status: "OPEN",
      cause: "INDEXING_DELAY",
      assignee: null,
      reason: null,
      history: [],
      created_at: "2026-08-01T00:00:00Z",
      updated_at: "2026-08-01T00:00:00Z",
    };
    render(
      <NoResultOperationsTable
        rows={[row()]}
        tasks={{ "복분자 원액": task }}
        onAssignCause={vi.fn()}
        onApplyAction={onApplyAction}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: /재인덱싱 요청/ }));
    expect(onApplyAction).toHaveBeenCalledWith("복분자 원액", "REQUEST_REINDEX", null);
  });
});
