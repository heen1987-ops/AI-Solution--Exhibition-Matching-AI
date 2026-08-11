import { describe, expect, it } from "vitest";

import {
  confidenceLabel,
  confidenceTone,
  isTradeConditionAttribute,
  requiresExplicitUnknownToYesConfirmation,
  validateUnknownToYesJustification,
} from "../logic";
import type { ExtractedAttributeRead } from "../types";

function makeAttribute(overrides: Partial<ExtractedAttributeRead> = {}): ExtractedAttributeRead {
  return {
    extraction_id: "extraction-1",
    document_id: "doc-1",
    ai_run_id: "run-1",
    entity_type: "TRADE_CONDITION",
    entity_reference: "trade-1",
    temporary_entity_ref: null,
    attribute_code: "trade.oem_capability",
    proposed_value: "SUPPORTED",
    normalized_value: null,
    concept_codes: ["TRADE.OEM"],
    fact_type: "AI_INFERRED",
    temporal_validity: "CURRENT_CAPABILITY",
    confidence: 0.7,
    review_status: "PROPOSED",
    visibility: "VERIFIED_BUYER",
    edited_by_exhibitor: false,
    evidence: [
      {
        evidence_id: "ev-1",
        document_id: "doc-1",
        segment_ref: null,
        page_number: 3,
        section_title: null,
        text_start: null,
        text_end: null,
        evidence_text: "OEM 생산 가능",
        evidence_hash: "hash-1",
      },
    ],
    created_at: "2026-08-01T00:00:00Z",
    updated_at: "2026-08-01T00:00:00Z",
    reviewed_by_exhibitor_user_id: null,
    reviewed_by_exhibitor_at: null,
    reviewed_by_operator_user_id: null,
    reviewed_by_operator_at: null,
    rejection_reason: null,
    superseded_by_extraction_id: null,
    ...overrides,
  };
}

describe("confidenceTone / confidenceLabel", () => {
  it("buckets confidence into low/medium/high and never claims certainty", () => {
    expect(confidenceTone(0.2)).toBe("low");
    expect(confidenceTone(0.6)).toBe("medium");
    expect(confidenceTone(0.95)).toBe("high");
    expect(confidenceTone(null)).toBe("unknown");
  });

  it("never renders a bare percentage as the headline - always a hedged label first", () => {
    const label = confidenceLabel(0.42);
    expect(label.startsWith("AI 확신도")).toBe(true);
    expect(label).toContain("참고치 42%");
  });

  it("does not imply false precision when confidence is missing", () => {
    expect(confidenceLabel(null)).toBe("신뢰도 정보 없음");
  });
});

describe("isTradeConditionAttribute", () => {
  it("flags entity_type=TRADE_CONDITION regardless of the specific code", () => {
    expect(
      isTradeConditionAttribute({ attribute_code: "company.name", entity_type: "TRADE_CONDITION" }),
    ).toBe(true);
  });

  it("flags the known trade-condition attribute codes even outside entity_type=TRADE_CONDITION", () => {
    expect(isTradeConditionAttribute({ attribute_code: "trade.moq", entity_type: "EXHIBITOR" })).toBe(true);
    expect(
      isTradeConditionAttribute({ attribute_code: "trade.export_capability", entity_type: "PRODUCT" }),
    ).toBe(true);
  });

  it("does not flag unrelated product attributes", () => {
    expect(isTradeConditionAttribute({ attribute_code: "product.taste_notes", entity_type: "PRODUCT" })).toBe(
      false,
    );
  });
});

describe("requiresExplicitUnknownToYesConfirmation - the core silent-toggle guard", () => {
  it("requires confirmation when a capability field moves UNKNOWN -> SUPPORTED", () => {
    const attribute = makeAttribute({ normalized_value: null, proposed_value: "UNKNOWN" });
    expect(requiresExplicitUnknownToYesConfirmation(attribute, "SUPPORTED")).toBe(true);
  });

  it("also treats the legacy alias YES as a positive transition", () => {
    const attribute = makeAttribute({ normalized_value: null, proposed_value: "UNKNOWN" });
    expect(requiresExplicitUnknownToYesConfirmation(attribute, "YES")).toBe(true);
  });

  it("does NOT require confirmation for UNKNOWN -> NOT_SUPPORTED (only a positive result is gated)", () => {
    const attribute = makeAttribute({ normalized_value: null, proposed_value: "UNKNOWN" });
    expect(requiresExplicitUnknownToYesConfirmation(attribute, "NOT_SUPPORTED")).toBe(false);
  });

  it("does NOT require confirmation when the baseline was already SUPPORTED/NOT_SUPPORTED (no real transition)", () => {
    expect(
      requiresExplicitUnknownToYesConfirmation(
        makeAttribute({ normalized_value: "SUPPORTED" }),
        "SUPPORTED",
      ),
    ).toBe(false);
    expect(
      requiresExplicitUnknownToYesConfirmation(
        makeAttribute({ normalized_value: "NOT_SUPPORTED" }),
        "SUPPORTED",
      ),
    ).toBe(false);
  });

  it("treats a null baseline (normalized_value unset, proposed_value null) as UNKNOWN (still gated)", () => {
    const attribute = makeAttribute({ normalized_value: null, proposed_value: null });
    expect(requiresExplicitUnknownToYesConfirmation(attribute, "SUPPORTED")).toBe(true);
  });

  it("prefers normalized_value over proposed_value as the baseline once the exhibitor has edited it", () => {
    const attribute = makeAttribute({ normalized_value: "NOT_SUPPORTED", proposed_value: "UNKNOWN" });
    expect(requiresExplicitUnknownToYesConfirmation(attribute, "SUPPORTED")).toBe(false);
  });

  it("does not apply to non-capability attribute codes (numbers, text, taxonomy refs)", () => {
    const numberAttribute = makeAttribute({
      attribute_code: "trade.moq",
      normalized_value: null,
      proposed_value: "UNKNOWN",
    });
    expect(requiresExplicitUnknownToYesConfirmation(numberAttribute, "SUPPORTED")).toBe(false);
  });
});

describe("validateUnknownToYesJustification", () => {
  it("rejects empty/whitespace-only justification", () => {
    expect(validateUnknownToYesJustification(null)).not.toBeNull();
    expect(validateUnknownToYesJustification(undefined)).not.toBeNull();
    expect(validateUnknownToYesJustification("   ")).not.toBeNull();
  });

  it("accepts a real justification", () => {
    expect(validateUnknownToYesJustification("카탈로그 3페이지에서 직접 확인함")).toBeNull();
  });
});
