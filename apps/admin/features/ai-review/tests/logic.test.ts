import { describe, expect, it } from "vitest";

import { computeRiskIndicator, filterQueueRows, sortQueueAiInferredFirst, toQueueRow, toQueueRows } from "../logic";
import type { AdminReviewQueueItem } from "../types";

function queueItem(overrides: Partial<AdminReviewQueueItem> = {}): AdminReviewQueueItem {
  return {
    review_request_id: "rr-1",
    document_id: "doc-1",
    exhibitor_id: "ex-1",
    status: "IN_OPERATOR_REVIEW",
    submitted_at: "2026-08-01T00:00:00Z",
    claimed_by_user_id: null,
    pending_extraction_count: 4,
    ai_inferred_count: 1,
    has_unresolved_conflict: false,
    ...overrides,
  };
}

describe("computeRiskIndicator", () => {
  it("is HIGH whenever there is an unresolved conflict, regardless of other counts", () => {
    expect(computeRiskIndicator(queueItem({ has_unresolved_conflict: true, ai_inferred_count: 0 }))).toBe("HIGH");
  });

  it("is LOW when there is nothing pending", () => {
    expect(computeRiskIndicator(queueItem({ pending_extraction_count: 0, ai_inferred_count: 0 }))).toBe("LOW");
  });

  it("is MEDIUM when AI_INFERRED is at least half of the pending items", () => {
    expect(
      computeRiskIndicator(queueItem({ pending_extraction_count: 4, ai_inferred_count: 2, has_unresolved_conflict: false })),
    ).toBe("MEDIUM");
  });

  it("is LOW when AI_INFERRED is a small minority of pending items", () => {
    expect(
      computeRiskIndicator(queueItem({ pending_extraction_count: 10, ai_inferred_count: 1, has_unresolved_conflict: false })),
    ).toBe("LOW");
  });
});

describe("toQueueRow (queue column contract gap - ../types.ts docstring gap #4)", () => {
  it("never fabricates the columns the backend does not provide yet", () => {
    const row = toQueueRow(queueItem());
    expect(row.exhibitor_name).toBeNull();
    expect(row.document_type).toBeNull();
    expect(row.evidence_missing_count).toBeNull();
    expect(row.exhibitor_modified_count).toBeNull();
  });

  it("carries over the fields the backend does provide, unchanged", () => {
    const row = toQueueRow(queueItem({ pending_extraction_count: 7, ai_inferred_count: 3 }));
    expect(row.pending_extraction_count).toBe(7);
    expect(row.ai_inferred_count).toBe(3);
    expect(row.review_request_id).toBe("rr-1");
  });
});

describe("sortQueueAiInferredFirst (document-structuring.md §4 binding rule)", () => {
  it("surfaces the row with more AI_INFERRED attributes first", () => {
    const rows = toQueueRows([
      queueItem({ review_request_id: "low-ai", ai_inferred_count: 1 }),
      queueItem({ review_request_id: "high-ai", ai_inferred_count: 5 }),
    ]);
    const sorted = sortQueueAiInferredFirst(rows);
    expect(sorted.map((r) => r.review_request_id)).toEqual(["high-ai", "low-ai"]);
  });

  it("does not mutate the input array", () => {
    const rows = toQueueRows([queueItem({ review_request_id: "a" }), queueItem({ review_request_id: "b" })]);
    const copy = [...rows];
    sortQueueAiInferredFirst(rows);
    expect(rows).toEqual(copy);
  });

  it("breaks ties by risk indicator, then by earliest submitted_at", () => {
    const rows = toQueueRows([
      queueItem({
        review_request_id: "later",
        ai_inferred_count: 2,
        pending_extraction_count: 4,
        submitted_at: "2026-08-02T00:00:00Z",
      }),
      queueItem({
        review_request_id: "earlier",
        ai_inferred_count: 2,
        pending_extraction_count: 4,
        submitted_at: "2026-08-01T00:00:00Z",
      }),
    ]);
    const sorted = sortQueueAiInferredFirst(rows);
    expect(sorted.map((r) => r.review_request_id)).toEqual(["earlier", "later"]);
  });
});

describe("filterQueueRows", () => {
  it("filters by status and exhibitor id independently", () => {
    const rows = toQueueRows([
      queueItem({ review_request_id: "a", exhibitor_id: "ex-1", status: "SUBMITTED" }),
      queueItem({ review_request_id: "b", exhibitor_id: "ex-2", status: "IN_OPERATOR_REVIEW" }),
    ]);
    expect(filterQueueRows(rows, { status: "SUBMITTED" }).map((r) => r.review_request_id)).toEqual(["a"]);
    expect(filterQueueRows(rows, { exhibitorId: "ex-2" }).map((r) => r.review_request_id)).toEqual(["b"]);
    expect(filterQueueRows(rows, {})).toHaveLength(2);
  });
});
