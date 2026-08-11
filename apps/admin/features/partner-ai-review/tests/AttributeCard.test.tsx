import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import AttributeCard from "../components/AttributeCard";
import type { ExtractedAttributeRead } from "../types";

const confirmMock = vi.fn();
const saveModifiedMock = vi.fn();
const rejectMock = vi.fn();

vi.mock("../api", () => ({
  confirmProposedValue: (...args: unknown[]) => confirmMock(...args),
  saveModifiedValue: (...args: unknown[]) => saveModifiedMock(...args),
  rejectProposedValue: (...args: unknown[]) => rejectMock(...args),
}));

// vitest.config.ts (shared, not owned by this track) does not enable `test.globals`, so
// @testing-library/react's auto-cleanup (which relies on a global `afterEach`) never
// registers. Without this, DOM from one `it(...)` leaks into the next within this file and
// `getByRole` queries start matching duplicates. Clean up explicitly instead of touching the
// shared config.
afterEach(() => {
  cleanup();
});

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
    confidence: 0.42,
    review_status: "PROPOSED",
    visibility: "VERIFIED_BUYER",
    edited_by_exhibitor: false,
    evidence: [
      {
        evidence_id: "ev-1",
        document_id: "doc-1",
        segment_ref: null,
        page_number: 3,
        section_title: "3페이지 표 2행",
        text_start: null,
        text_end: null,
        evidence_text: "당사는 OEM 생산이 가능합니다.",
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

function makeDecisionResult(overrides: Partial<ExtractedAttributeRead> = {}): ExtractedAttributeRead {
  return makeAttribute({ review_status: "CONFIRMED_BY_EXHIBITOR", ...overrides });
}

describe("AttributeCard", () => {
  beforeEach(() => {
    confirmMock.mockReset().mockResolvedValue(makeDecisionResult({ normalized_value: "SUPPORTED" }));
    saveModifiedMock
      .mockReset()
      .mockResolvedValue(
        makeDecisionResult({ review_status: "MODIFIED_BY_EXHIBITOR", normalized_value: "NOT_SUPPORTED" }),
      );
    rejectMock
      .mockReset()
      .mockResolvedValue(makeDecisionResult({ review_status: "REJECTED_BY_EXHIBITOR" }));
  });

  it("shows the AI-proposed value, a hedged confidence indicator, evidence text+page/section, and the ontology code", () => {
    render(<AttributeCard attribute={makeAttribute()} emphasized onChange={vi.fn()} />);

    expect(screen.getByText("가능")).toBeInTheDocument(); // proposed_value=SUPPORTED formatted
    expect(screen.getByText(/AI 확신도/)).toBeInTheDocument();
    expect(screen.getByText(/당사는 OEM 생산이 가능합니다/)).toBeInTheDocument();
    expect(screen.getByText(/3페이지/)).toBeInTheDocument();
    expect(screen.getByText(/trade\.oem_capability/)).toBeInTheDocument();
  });

  it("confirms the AI's own proposed value directly, with no justification gate: the confirm endpoint never receives a value, so accepting what's already there can never itself be an UNKNOWN->YES transition (see logic.ts/api.ts module docstrings)", async () => {
    const onChange = vi.fn();
    // Even a PROPOSED row whose own proposed_value is UNKNOWN must confirm without friction -
    // accepting it just acknowledges it stays UNKNOWN (backend's own ACKNOWLEDGE_UNKNOWN path).
    const attribute = makeAttribute({ proposed_value: "UNKNOWN", normalized_value: null });
    confirmMock.mockResolvedValue(makeDecisionResult({ review_status: "CONFIRMED_BY_EXHIBITOR" }));
    render(<AttributeCard attribute={attribute} emphasized onChange={onChange} />);

    expect(screen.queryByPlaceholderText(/카탈로그 3페이지에 OEM 생산 가능/)).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "AI 제안값 확인" }));
    await vi.waitFor(() => expect(confirmMock).toHaveBeenCalledTimes(1));
    expect(confirmMock).toHaveBeenCalledWith(attribute, undefined);
    await vi.waitFor(() =>
      expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ review_status: "CONFIRMED_BY_EXHIBITOR" })),
    );
  });

  it("modify: gates saving a manually-entered UNKNOWN->YES value behind a required justification", () => {
    render(
      <AttributeCard
        attribute={makeAttribute({ proposed_value: "UNKNOWN", normalized_value: null })}
        emphasized
        onChange={vi.fn()}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "수정" }));
    const select = screen.getByRole("combobox");
    fireEvent.change(select, { target: { value: "SUPPORTED" } });

    const saveButton = screen.getByRole("button", { name: "수정값 저장" });
    expect(saveButton).toBeDisabled();

    const justificationBoxes = screen.getAllByRole("textbox");
    fireEvent.change(justificationBoxes[justificationBoxes.length - 1], {
      target: { value: "직접 전화로 확인함" },
    });
    expect(saveButton).toBeEnabled();
  });

  it("delete: requires a second explicit step before calling the API (not a one-click destructive action)", async () => {
    const onChange = vi.fn();
    render(<AttributeCard attribute={makeAttribute()} emphasized onChange={onChange} />);

    expect(rejectMock).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "삭제(채택 안함)" }));
    expect(rejectMock).not.toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: "삭제 확정" }));
    await vi.waitFor(() => expect(rejectMock).toHaveBeenCalledTimes(1));
    await vi.waitFor(() =>
      expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ review_status: "REJECTED_BY_EXHIBITOR" })),
    );
  });
});
