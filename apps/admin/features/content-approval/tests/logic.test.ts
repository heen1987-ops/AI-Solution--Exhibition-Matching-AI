import { describe, expect, it } from "vitest";

import type { ExtractedAttributeRead, EvidenceRead } from "../../ai-review/types";
import {
  bulkApprovePreview,
  buildComparisonRow,
  canReviewAiContent,
  composeReasonPayload,
  detectPotentialPii,
  evaluateApprovalPrecondition,
  failingPreconditions,
  selectableForBulkApprove,
  validateReasonSelection,
} from "../logic";

function evidence(overrides: Partial<EvidenceRead> = {}): EvidenceRead {
  return {
    evidence_id: "ev-1",
    document_id: "doc-1",
    segment_ref: "doc-1:1",
    page_number: 3,
    section_title: "제품 특징",
    text_start: 0,
    text_end: 10,
    evidence_text: "단맛이 적고 깔끔한 맛",
    evidence_hash: "sha256:abc",
    ...overrides,
  };
}

function attribute(overrides: Partial<ExtractedAttributeRead> = {}): ExtractedAttributeRead {
  return {
    extraction_id: "ext-1",
    document_id: "doc-1",
    ai_run_id: "run-1",
    entity_type: "PRODUCT",
    entity_reference: "prod-1",
    temporary_entity_ref: null,
    attribute_code: "PRODUCT.TASTE.SWEETNESS",
    proposed_value: "단맛이 적음",
    normalized_value: { concept_id: "c-1" },
    concept_codes: ["ALCOHOL.TASTE.LOW_SWEETNESS"],
    fact_type: "AI_INFERRED",
    temporal_validity: null,
    confidence: 0.62,
    review_status: "CONFIRMED_BY_EXHIBITOR",
    visibility: "PUBLIC",
    edited_by_exhibitor: false,
    evidence: [evidence()],
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    reviewed_by_exhibitor_user_id: "user-1",
    reviewed_by_exhibitor_at: "2026-08-01T01:00:00Z",
    reviewed_by_operator_user_id: null,
    reviewed_by_operator_at: null,
    rejection_reason: null,
    superseded_by_extraction_id: null,
    ...overrides,
  };
}

describe("buildComparisonRow (작업 지시 필수 요구사항: 4-way 비교)", () => {
  it("renders all 4 value states for a confirmed AI_INFERRED attribute", () => {
    const row = buildComparisonRow(attribute());

    // 1) AI 원제안값 - 수정 여부와 무관하게 항상 보존된 원본.
    expect(row.ai_proposed_value).toBe("단맛이 적음");

    // 2) 업체 확인·수정값 - CONFIRMED_BY_EXHIBITOR이므로 normalized_value가 채워진다.
    expect(row.exhibitor_value).toEqual({ concept_id: "c-1" });
    expect(row.exhibitor_decision).toBe("CONFIRMED");

    // 3) 현재 게시값 - 조회 API가 없다는 계약 공백을 명시적으로 드러낸다(값을 지어내지 않음).
    expect(row.published_value).toBeNull();
    expect(row.published_value_unavailable).toBe(true);

    // 4) 운영자 최종값(기본 미리보기) - 업체 확인값을 기본으로 제시한다.
    expect(row.operator_default_value).toEqual({ concept_id: "c-1" });
    expect(row.operator_default_visibility).toBe("PUBLIC");
  });

  it("leaves the exhibitor value null (not equal to the AI value) while still PROPOSED", () => {
    const row = buildComparisonRow(attribute({ review_status: "PROPOSED", normalized_value: null }));
    expect(row.exhibitor_value).toBeNull();
    expect(row.exhibitor_decision).toBe("PENDING");
  });

  it("marks the exhibitor decision as REJECTED distinctly from PENDING", () => {
    const row = buildComparisonRow(attribute({ review_status: "REJECTED_BY_EXHIBITOR", normalized_value: null }));
    expect(row.exhibitor_value).toBeNull();
    expect(row.exhibitor_decision).toBe("REJECTED");
  });

  it("uses an explicitly supplied published value when the caller has one", () => {
    const row = buildComparisonRow(attribute(), { value: "이전 게시값", available: true });
    expect(row.published_value).toBe("이전 게시값");
    expect(row.published_value_unavailable).toBe(false);
  });
});

describe("evaluateApprovalPrecondition (작업 지시 필수 요구사항: 승인 사전조건)", () => {
  it("approves a well-formed, confirmed, evidenced attribute with no conflicts or PII", () => {
    const summary = evaluateApprovalPrecondition(attribute());
    expect(summary.approvable).toBe(true);
    expect(failingPreconditions(summary)).toEqual([]);
  });

  it("blocks when normalized_value or visibility is missing (필수 정보 존재)", () => {
    const summary = evaluateApprovalPrecondition(attribute({ normalized_value: null }));
    expect(summary.approvable).toBe(false);
    expect(failingPreconditions(summary)).toContain("VALUE_OR_VISIBILITY_MISSING");
  });

  it("blocks on an unresolved conflict (충돌 해소)", () => {
    const summary = evaluateApprovalPrecondition(attribute({ review_status: "CONFLICTED" }));
    expect(failingPreconditions(summary)).toContain("CONFLICT_UNRESOLVED");
  });

  it("blocks when there is neither evidence nor an exhibitor confirmation, for a non-exempt fact_type", () => {
    const summary = evaluateApprovalPrecondition(
      attribute({ fact_type: "SOURCE_FACT", review_status: "MODIFIED_BY_EXHIBITOR", evidence: [] }),
    );
    // MODIFIED_BY_EXHIBITOR itself counts as an explicit confirmation, so this should pass -
    // verifies the "OR exhibitor confirmation" half of the rule, not just the evidence half.
    expect(failingPreconditions(summary)).not.toContain("EVIDENCE_OR_CONFIRMATION_MISSING");
  });

  it("blocks when there is no evidence and the attribute is still only PROPOSED", () => {
    const summary = evaluateApprovalPrecondition(
      attribute({ fact_type: "SOURCE_FACT", review_status: "PROPOSED", evidence: [] }),
    );
    expect(failingPreconditions(summary)).toContain("EVIDENCE_OR_CONFIRMATION_MISSING");
  });

  it("exempts SELF_DECLARED and UNKNOWN fact types from the evidence requirement", () => {
    const selfDeclared = evaluateApprovalPrecondition(
      attribute({ fact_type: "SELF_DECLARED", review_status: "PROPOSED", evidence: [] }),
    );
    expect(failingPreconditions(selfDeclared)).not.toContain("EVIDENCE_OR_CONFIRMATION_MISSING");
  });

  it("blocks an AI_INFERRED attribute that has not yet passed exhibitor review (document-structuring.md §4)", () => {
    const summary = evaluateApprovalPrecondition(attribute({ fact_type: "AI_INFERRED", review_status: "PROPOSED" }));
    expect(failingPreconditions(summary)).toContain("AI_INFERRED_NOT_YET_REVIEWED");
  });

  it("does not block a SOURCE_FACT attribute just for being PROPOSED (only AI_INFERRED needs the extra gate)", () => {
    const summary = evaluateApprovalPrecondition(
      attribute({ fact_type: "SOURCE_FACT", review_status: "PROPOSED", evidence: [evidence()] }),
    );
    expect(failingPreconditions(summary)).not.toContain("AI_INFERRED_NOT_YET_REVIEWED");
  });

  it("blocks a TRADE_CONDITION attribute whose temporal_validity is not CURRENT_CAPABILITY (현재-과거 혼동 방지)", () => {
    const summary = evaluateApprovalPrecondition(
      attribute({ entity_type: "TRADE_CONDITION", temporal_validity: "PAST_EXPERIENCE" }),
    );
    expect(failingPreconditions(summary)).toContain("TEMPORAL_MISMATCH");
  });

  it("does not apply the temporal check to non-TRADE_CONDITION attributes", () => {
    const summary = evaluateApprovalPrecondition(
      attribute({ entity_type: "PRODUCT", temporal_validity: "PAST_EXPERIENCE" }),
    );
    expect(failingPreconditions(summary)).not.toContain("TEMPORAL_MISMATCH");
  });

  it("blocks when the evidence text contains something that looks like an email address (개인정보 미검출)", () => {
    const summary = evaluateApprovalPrecondition(
      attribute({ evidence: [evidence({ evidence_text: "담당자 연락처 hong@example.com" })] }),
    );
    expect(failingPreconditions(summary)).toContain("POTENTIAL_PII");
  });

  it("blocks when a phone-number-like digit sequence appears in the proposed value", () => {
    const summary = evaluateApprovalPrecondition(attribute({ proposed_value: "010-1234-5678" }));
    expect(failingPreconditions(summary)).toContain("POTENTIAL_PII");
  });
});

describe("detectPotentialPii", () => {
  it("does not flag an ordinary taste description", () => {
    expect(detectPotentialPii(attribute())).toBe(false);
  });
});

describe("bulk selection (작업 지시 필수 요구사항: approve/reject in bulk)", () => {
  it("selectableForBulkApprove only returns approvable rows", () => {
    const approvableRow = buildComparisonRow(attribute({ extraction_id: "ok" }));
    const blockedRow = buildComparisonRow(attribute({ extraction_id: "blocked", review_status: "CONFLICTED" }));
    const selected = selectableForBulkApprove([approvableRow, blockedRow]);
    expect(selected.map((r) => r.extraction.extraction_id)).toEqual(["ok"]);
  });

  it("bulkApprovePreview splits a selection into approvable and blocked ids", () => {
    const approvableRow = buildComparisonRow(attribute({ extraction_id: "ok" }));
    const blockedRow = buildComparisonRow(attribute({ extraction_id: "blocked", review_status: "CONFLICTED" }));
    const preview = bulkApprovePreview([approvableRow, blockedRow], new Set(["ok", "blocked"]));
    expect(preview.approvable).toEqual(["ok"]);
    expect(preview.blocked).toEqual(["blocked"]);
  });

  it("ignores rows that were not selected at all", () => {
    const rowA = buildComparisonRow(attribute({ extraction_id: "a" }));
    const rowB = buildComparisonRow(attribute({ extraction_id: "b" }));
    const preview = bulkApprovePreview([rowA, rowB], new Set(["a"]));
    expect(preview.approvable).toEqual(["a"]);
    expect(preview.blocked).toEqual([]);
  });
});

describe("validateReasonSelection (테스트 요구사항: reason-code required on reject/request-changes)", () => {
  it("rejects when no reason code is selected", () => {
    expect(validateReasonSelection("", "아무 코멘트").ok).toBe(false);
    expect(validateReasonSelection(null, "아무 코멘트").ok).toBe(false);
    expect(validateReasonSelection(undefined, "아무 코멘트").ok).toBe(false);
  });

  it("accepts a non-OTHER reason code even with an empty comment", () => {
    expect(validateReasonSelection("EVIDENCE_MISSING", "").ok).toBe(true);
  });

  it("requires a comment when the reason code is OTHER", () => {
    expect(validateReasonSelection("OTHER", "").ok).toBe(false);
    expect(validateReasonSelection("OTHER", "   ").ok).toBe(false);
    expect(validateReasonSelection("OTHER", "상세 사유").ok).toBe(true);
  });
});

describe("composeReasonPayload", () => {
  it("embeds the reason code and label into the free-text payload the real backend accepts", () => {
    const payload = composeReasonPayload("CONFLICT_UNRESOLVED", "다른 문서와 값이 다름");
    expect(payload).toContain("CONFLICT_UNRESOLVED");
    expect(payload).toContain("충돌 미해결");
    expect(payload).toContain("다른 문서와 값이 다름");
  });

  it("still produces a valid non-empty string when the comment is blank", () => {
    const payload = composeReasonPayload("EVIDENCE_MISSING", "");
    expect(payload.trim().length).toBeGreaterThan(0);
  });
});

describe("canReviewAiContent (role gate)", () => {
  it("allows EVENT_ADMIN and DATA_REVIEWER", () => {
    expect(canReviewAiContent("EVENT_ADMIN")).toBe(true);
    expect(canReviewAiContent("DATA_REVIEWER")).toBe(true);
  });

  it("denies EXHIBITOR_ADMIN and unknown roles", () => {
    expect(canReviewAiContent("EXHIBITOR_ADMIN")).toBe(false);
    expect(canReviewAiContent("SOMETHING_ELSE")).toBe(false);
  });
});
