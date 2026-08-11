import { describe, expect, it } from "vitest";

import {
  IMPROVEMENT_ACTIONS,
  NO_RESULT_CAUSES,
  OPERATIONS_TASK_STATUSES,
  TaskTransitionError,
  allowedActionsForCause,
  applyImprovementAction,
  applyTransition,
  assignTask,
  canTransition,
  createTask,
  setTaskCause,
  toOperationsRow,
  transitionRequiresReason,
} from "../logic";
import type { NoResultQueryItem, OperationsTask } from "../types";

function task(overrides: Partial<OperationsTask> = {}): OperationsTask {
  return {
    task_id: "task-1",
    query_norm: "복분자 원액",
    status: "OPEN",
    cause: "UNKNOWN",
    assignee: null,
    reason: null,
    history: [],
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    ...overrides,
  };
}

// ---------------------------------------------------------------------------
// 원인 분류 카탈로그 - cause-classification UI가 의존하는 정본
// ---------------------------------------------------------------------------

describe("NO_RESULT_CAUSES", () => {
  it("declares exactly the 8 spec-mandated causes", () => {
    expect(NO_RESULT_CAUSES).toEqual([
      "ONTOLOGY_MISSING",
      "SYNONYM_MISSING",
      "EXHIBITOR_DATA_MISSING",
      "NO_ELIGIBLE_EXHIBITOR",
      "FILTER_TOO_STRICT",
      "QUERY_AMBIGUOUS",
      "INDEXING_DELAY",
      "UNKNOWN",
    ]);
  });
});

// ---------------------------------------------------------------------------
// 개선 액션 - AI/시스템이 절대 데이터를 자동 수정하지 않는다는 불변조건의 기계 검증
// ---------------------------------------------------------------------------

describe("IMPROVEMENT_ACTIONS invariant (spec: AI never auto-fixes ontology/exhibitor data)", () => {
  it("every action requires a human and never auto-fixes data", () => {
    expect(IMPROVEMENT_ACTIONS.length).toBeGreaterThan(0);
    for (const action of IMPROVEMENT_ACTIONS) {
      expect(action.requires_human).toBe(true);
      expect(action.auto_fixes_data).toBe(false);
    }
  });

  it("declares exactly the 7 spec-mandated action codes", () => {
    expect(IMPROVEMENT_ACTIONS.map((a) => a.code).sort()).toEqual(
      [
        "REQUEST_SYNONYM_ADDITION",
        "FLAG_ONTOLOGY_REVIEW",
        "REQUEST_EXHIBITOR_DATA",
        "REQUEST_REINDEX",
        "IMPROVE_EXAMPLE_QUERIES",
        "MARK_RESOLVED",
        "MARK_IGNORED",
      ].sort(),
    );
  });
});

describe("allowedActionsForCause (cause-classification -> action affordances)", () => {
  it("always includes both terminal actions regardless of cause", () => {
    for (const cause of NO_RESULT_CAUSES) {
      const actions = allowedActionsForCause(cause);
      expect(actions).toContain("MARK_RESOLVED");
      expect(actions).toContain("MARK_IGNORED");
    }
  });

  it("offers ontology-review affordances for ONTOLOGY_MISSING", () => {
    expect(allowedActionsForCause("ONTOLOGY_MISSING")).toEqual(
      expect.arrayContaining(["FLAG_ONTOLOGY_REVIEW", "IMPROVE_EXAMPLE_QUERIES"]),
    );
  });

  it("offers only terminal actions for NO_ELIGIBLE_EXHIBITOR (nothing to fix)", () => {
    expect(allowedActionsForCause("NO_ELIGIBLE_EXHIBITOR")).toEqual(["MARK_RESOLVED", "MARK_IGNORED"]);
  });

  it("offers every non-terminal action for UNKNOWN (does not narrow judgement)", () => {
    const actions = allowedActionsForCause("UNKNOWN");
    const nonTerminal = IMPROVEMENT_ACTIONS.filter((a) => !a.terminal).map((a) => a.code);
    for (const code of nonTerminal) {
      expect(actions).toContain(code);
    }
  });
});

describe("toOperationsRow (backend minimal contract -> operations row)", () => {
  it("never fabricates columns the backend does not provide yet", () => {
    const item: NoResultQueryItem = { query: "화요 21", count: 3, last_seen_at: "2026-08-01T00:00:00Z" };
    const row = toOperationsRow(item);
    expect(row.resolved_concept_codes).toBeNull();
    expect(row.channel).toBeNull();
    expect(row.first_seen_at).toBeNull();
  });

  it("carries over query/count/last_seen_at and marks server-side masking", () => {
    const item: NoResultQueryItem = { query: "안동소주 20도", count: 12, last_seen_at: "2026-08-02T00:00:00Z" };
    const row = toOperationsRow(item);
    expect(row.query_norm).toBe("안동소주 20도");
    expect(row.occurrence_count).toBe(12);
    expect(row.last_seen_at).toBe("2026-08-02T00:00:00Z");
    expect(row.pii_masking_status).toBe("SERVER_MASKED");
  });
});

// ---------------------------------------------------------------------------
// 태스크 상태머신
// ---------------------------------------------------------------------------

describe("OPERATIONS_TASK_STATUSES", () => {
  it("declares exactly the 5 spec-mandated statuses", () => {
    expect(OPERATIONS_TASK_STATUSES).toEqual(["OPEN", "IN_REVIEW", "ACTION_REQUIRED", "RESOLVED", "IGNORED"]);
  });
});

describe("canTransition", () => {
  it("allows the documented forward transitions", () => {
    expect(canTransition("OPEN", "IN_REVIEW")).toBe(true);
    expect(canTransition("IN_REVIEW", "ACTION_REQUIRED")).toBe(true);
    expect(canTransition("ACTION_REQUIRED", "RESOLVED")).toBe(true);
    expect(canTransition("ACTION_REQUIRED", "IGNORED")).toBe(true);
  });

  it("allows reopening from terminal states, and only to OPEN", () => {
    expect(canTransition("RESOLVED", "OPEN")).toBe(true);
    expect(canTransition("IGNORED", "OPEN")).toBe(true);
    expect(canTransition("RESOLVED", "IN_REVIEW")).toBe(false);
    expect(canTransition("IGNORED", "ACTION_REQUIRED")).toBe(false);
  });

  it("rejects skipping straight from OPEN to RESOLVED", () => {
    expect(canTransition("OPEN", "RESOLVED")).toBe(false);
  });

  it("rejects a no-op transition to the same state", () => {
    expect(canTransition("OPEN", "OPEN")).toBe(false);
  });
});

describe("transitionRequiresReason", () => {
  it("requires a reason for any transition into IGNORED", () => {
    expect(transitionRequiresReason("OPEN", "IGNORED")).toBe(true);
    expect(transitionRequiresReason("IN_REVIEW", "IGNORED")).toBe(true);
    expect(transitionRequiresReason("ACTION_REQUIRED", "IGNORED")).toBe(true);
  });

  it("requires a reason to reopen a terminal task", () => {
    expect(transitionRequiresReason("RESOLVED", "OPEN")).toBe(true);
    expect(transitionRequiresReason("IGNORED", "OPEN")).toBe(true);
  });

  it("does not require a reason for ordinary forward progress", () => {
    expect(transitionRequiresReason("OPEN", "IN_REVIEW")).toBe(false);
    expect(transitionRequiresReason("IN_REVIEW", "ACTION_REQUIRED")).toBe(false);
    expect(transitionRequiresReason("ACTION_REQUIRED", "RESOLVED")).toBe(false);
  });
});

describe("applyTransition", () => {
  it("throws INVALID_TRANSITION for a disallowed transition and does not mutate the task", () => {
    const t = task({ status: "OPEN" });
    let caught: unknown;
    try {
      applyTransition(t, { to: "RESOLVED", actor: "op-1", at: "2026-08-02T00:00:00Z" });
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(TaskTransitionError);
    expect((caught as TaskTransitionError).code).toBe("INVALID_TRANSITION");
    expect(t.status).toBe("OPEN");
    expect(t.history).toHaveLength(0);
  });

  it("throws REASON_REQUIRED when ignoring without a reason", () => {
    const t = task({ status: "OPEN" });
    expect(() => applyTransition(t, { to: "IGNORED", actor: "op-1", at: "2026-08-02T00:00:00Z" })).toThrow(
      TaskTransitionError,
    );
    try {
      applyTransition(t, { to: "IGNORED", actor: "op-1", at: "2026-08-02T00:00:00Z" });
    } catch (err) {
      expect((err as TaskTransitionError).code).toBe("REASON_REQUIRED");
    }
  });

  it("does not mutate the original task and appends exactly one history entry", () => {
    const t = task({ status: "OPEN", history: [] });
    const next = applyTransition(t, { to: "IN_REVIEW", actor: "op-1", at: "2026-08-02T00:00:00Z" });

    expect(t.status).toBe("OPEN"); // original untouched
    expect(t.history).toHaveLength(0);

    expect(next.status).toBe("IN_REVIEW");
    expect(next.history).toHaveLength(1);
    expect(next.history[0]).toEqual({
      from_status: "OPEN",
      to_status: "IN_REVIEW",
      actor: "op-1",
      reason: null,
      at: "2026-08-02T00:00:00Z",
    });
    expect(next.updated_at).toBe("2026-08-02T00:00:00Z");
  });

  it("trims a blank reason down to null", () => {
    const t = task({ status: "OPEN" });
    const next = applyTransition(t, { to: "IN_REVIEW", actor: "op-1", reason: "   ", at: "2026-08-02T00:00:00Z" });
    expect(next.history[0].reason).toBeNull();
  });

  it("preserves a real reason on the history entry", () => {
    const t = task({ status: "ACTION_REQUIRED" });
    const next = applyTransition(t, {
      to: "IGNORED",
      actor: "op-1",
      reason: "  운영자 판단으로 무시  ",
      at: "2026-08-02T00:00:00Z",
    });
    expect(next.reason).toBe("운영자 판단으로 무시");
    expect(next.history[0].reason).toBe("운영자 판단으로 무시");
  });
});

describe("createTask / assignTask / setTaskCause", () => {
  it("creates a fresh OPEN task with no history and UNKNOWN cause by default", () => {
    const t = createTask({ task_id: "t-1", query_norm: "화요", at: "2026-08-01T00:00:00Z" });
    expect(t.status).toBe("OPEN");
    expect(t.cause).toBe("UNKNOWN");
    expect(t.history).toEqual([]);
    expect(t.assignee).toBeNull();
  });

  it("assignTask sets the assignee without touching status/history", () => {
    const t = createTask({ task_id: "t-1", query_norm: "화요", at: "2026-08-01T00:00:00Z" });
    const next = assignTask(t, "operator-42");
    expect(next.assignee).toBe("operator-42");
    expect(next.status).toBe(t.status);
    expect(next.history).toEqual(t.history);
  });

  it("setTaskCause updates only the cause", () => {
    const t = createTask({ task_id: "t-1", query_norm: "화요", at: "2026-08-01T00:00:00Z" });
    const next = setTaskCause(t, "SYNONYM_MISSING");
    expect(next.cause).toBe("SYNONYM_MISSING");
    expect(next.status).toBe(t.status);
  });
});

// ---------------------------------------------------------------------------
// 개선 액션 적용 - 사람 요청 레코드 생성 + 상태 전이(이력 포함), 데이터 변경 없음
// ---------------------------------------------------------------------------

describe("applyImprovementAction", () => {
  it("MARK_RESOLVED from OPEN routes through IN_REVIEW and leaves 2 history entries", () => {
    const t = task({ status: "OPEN" });
    const result = applyImprovementAction(t, "MARK_RESOLVED", { actor: "op-1", at: "2026-08-02T00:00:00Z" });
    expect(result.task.status).toBe("RESOLVED");
    expect(result.task.history.map((h) => h.to_status)).toEqual(["IN_REVIEW", "RESOLVED"]);
    expect(result.request).toBeNull();
  });

  it("MARK_IGNORED requires a note and throws REASON_REQUIRED without one", () => {
    const t = task({ status: "OPEN" });
    expect(() =>
      applyImprovementAction(t, "MARK_IGNORED", { actor: "op-1", at: "2026-08-02T00:00:00Z" }),
    ).toThrow(TaskTransitionError);
  });

  it("MARK_IGNORED with a note transitions directly to IGNORED and returns no request", () => {
    const t = task({ status: "IN_REVIEW" });
    const result = applyImprovementAction(t, "MARK_IGNORED", {
      actor: "op-1",
      at: "2026-08-02T00:00:00Z",
      note: "중복 질의로 판단",
    });
    expect(result.task.status).toBe("IGNORED");
    expect(result.task.reason).toBe("중복 질의로 판단");
    expect(result.request).toBeNull();
  });

  it("a non-terminal action from OPEN moves the task to ACTION_REQUIRED and returns a human action request", () => {
    const t = task({ status: "OPEN", cause: "SYNONYM_MISSING" });
    const result = applyImprovementAction(t, "REQUEST_SYNONYM_ADDITION", {
      actor: "op-1",
      at: "2026-08-02T00:00:00Z",
      note: "왕대포 -> 막걸리 동의어 추가 요청",
    });
    expect(result.task.status).toBe("ACTION_REQUIRED");
    expect(result.task.history.map((h) => h.to_status)).toEqual(["IN_REVIEW", "ACTION_REQUIRED"]);
    expect(result.request).toEqual({
      kind: "HUMAN_ACTION_REQUEST",
      action: "REQUEST_SYNONYM_ADDITION",
      target: "ONTOLOGY_REVIEWER",
      query_norm: t.query_norm,
      requested_by: "op-1",
      requested_at: "2026-08-02T00:00:00Z",
      note: "왕대포 -> 막걸리 동의어 추가 요청",
    });
  });

  it("a non-terminal action from a terminal state throws and instructs to reopen first", () => {
    const t = task({ status: "RESOLVED" });
    let caught: unknown;
    try {
      applyImprovementAction(t, "REQUEST_REINDEX", { actor: "op-1", at: "2026-08-02T00:00:00Z" });
    } catch (err) {
      caught = err;
    }
    expect(caught).toBeInstanceOf(TaskTransitionError);
    expect((caught as TaskTransitionError).code).toBe("INVALID_TRANSITION");
  });

  it("never mutates the input task object", () => {
    const t = task({ status: "OPEN" });
    const snapshot = JSON.parse(JSON.stringify(t));
    applyImprovementAction(t, "MARK_RESOLVED", { actor: "op-1", at: "2026-08-02T00:00:00Z" });
    expect(JSON.parse(JSON.stringify(t))).toEqual(snapshot);
  });
});
