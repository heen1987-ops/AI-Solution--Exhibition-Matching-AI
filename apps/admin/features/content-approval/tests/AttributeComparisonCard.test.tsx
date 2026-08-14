import "@testing-library/jest-dom/vitest";

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { getDefaultSession, setRuntimeSession } from "@/lib/auth-state";

import type { EvidenceRead, ExtractedAttributeRead } from "../../ai-review/types";
import AttributeComparisonCard from "../components/AttributeComparisonCard";
import { buildComparisonRow } from "../logic";

// vitest.config.ts가 test.globals를 켜지 않아 RTL auto-cleanup이 등록되지 않는다 -
// features/partner-document/tests/DocumentsTable.test.tsx와 동일하게 명시적으로 정리한다.
afterEach(() => {
  cleanup();
  setRuntimeSession(getDefaultSession());
  vi.unstubAllGlobals();
});

beforeEach(() => {
  window.localStorage.clear();
  setRuntimeSession({
    role: "DATA_REVIEWER",
    actorUserId: "22222222-2222-4222-8222-222222222222",
    exhibitorId: null,
    displayName: "테스트 검수자",
    state: "AUTHENTICATED",
    csrfToken: "test-csrf-token",
  });
});

function mockFetchOnce(body: unknown, init: { status?: number } = {}) {
  const status = init.status ?? 200;
  const fetchMock = vi.fn().mockResolvedValue({
    status,
    ok: status >= 200 && status < 300,
    text: async () => JSON.stringify(body),
  } as unknown as Response);
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

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
    normalized_value: "단맛 낮음(수정)",
    concept_codes: ["ALCOHOL.TASTE.LOW_SWEETNESS"],
    fact_type: "AI_INFERRED",
    temporal_validity: null,
    confidence: 0.62,
    review_status: "MODIFIED_BY_EXHIBITOR",
    visibility: "PUBLIC",
    edited_by_exhibitor: true,
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

describe("AttributeComparisonCard - 4-way 비교 렌더링 (작업 지시: renders all 4 value states)", () => {
  it("shows AI-proposed, exhibitor-modified, published, and operator-final value states together", () => {
    render(<AttributeComparisonCard row={buildComparisonRow(attribute())} onDecided={() => {}} />);

    // 1) AI 원제안값
    expect(screen.getByText("1. AI 원제안값")).toBeInTheDocument();
    expect(screen.getByText("단맛이 적음")).toBeInTheDocument();

    // 2) 업체 확인·수정값 (수정됨 상태 라벨 포함)
    expect(screen.getByText(/2\. 업체 확인·수정값/)).toBeInTheDocument();
    expect(screen.getByText(/업체 수정함/)).toBeInTheDocument();
    // 업체 수정값과 운영자 최종값 미리보기가 같은 문자열이므로 두 곳에 나타난다.
    expect(screen.getAllByText("단맛 낮음(수정)").length).toBeGreaterThanOrEqual(2);

    // 3) 현재 게시값 - 조회 API 공백을 정직하게 표시(값을 지어내지 않음)
    expect(screen.getByText("3. 현재 게시값")).toBeInTheDocument();
    expect(screen.getByText("게시 이력 조회 API 없음")).toBeInTheDocument();

    // 4) 운영자 최종값 + 최종 공개범위 설정
    expect(screen.getByText("4. 운영자 최종값 (승인 시 게시)")).toBeInTheDocument();
    expect(screen.getByLabelText("PRODUCT.TASTE.SWEETNESS 최종 공개범위")).toBeInTheDocument();
  });

  it("distinguishes a pending exhibitor review from an equal-to-AI value", () => {
    render(
      <AttributeComparisonCard
        row={buildComparisonRow(attribute({ review_status: "PROPOSED", normalized_value: null }))}
        onDecided={() => {}}
      />,
    );
    expect(screen.getByText("(아직 업체 확인 전)")).toBeInTheDocument();
  });
});

describe("AttributeComparisonCard - 사전조건 기반 승인 비활성화 (작업 지시: precondition-based disabling)", () => {
  it("enables approve when every precondition passes", () => {
    render(<AttributeComparisonCard row={buildComparisonRow(attribute())} onDecided={() => {}} />);
    expect(screen.getByRole("button", { name: "승인" })).toBeEnabled();
  });

  it("disables approve for a conflicted attribute and says why", () => {
    render(
      <AttributeComparisonCard
        row={buildComparisonRow(attribute({ review_status: "CONFLICTED" }))}
        onDecided={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "승인" })).toBeDisabled();
    expect(screen.getByText("사전조건 미충족으로 승인이 비활성화되었습니다.")).toBeInTheDocument();
    expect(screen.getByText(/충돌이 해소되지 않았습니다/)).toBeInTheDocument();
  });

  it("disables approve for an AI_INFERRED attribute the exhibitor has not reviewed", () => {
    render(
      <AttributeComparisonCard
        row={buildComparisonRow(attribute({ fact_type: "AI_INFERRED", review_status: "PROPOSED" }))}
        onDecided={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "승인" })).toBeDisabled();
  });

  it("disables approve when potential PII is detected in the evidence", () => {
    render(
      <AttributeComparisonCard
        row={buildComparisonRow(
          attribute({ evidence: [evidence({ evidence_text: "담당자 hong@example.com" })] }),
        )}
        onDecided={() => {}}
      />,
    );
    expect(screen.getByRole("button", { name: "승인" })).toBeDisabled();
  });
});

describe("AttributeComparisonCard - 승인/반려 동작 (작업 지시: approve/reject actions)", () => {
  it("posts the approve action with the chosen final visibility", async () => {
    const fetchMock = mockFetchOnce({
      success: true,
      data: { extraction_id: "ext-1", review_status: "APPROVED_BY_OPERATOR", published_version_id: null },
    });
    const onDecided = vi.fn();
    render(<AttributeComparisonCard row={buildComparisonRow(attribute())} onDecided={onDecided} />);

    fireEvent.change(screen.getByLabelText("PRODUCT.TASTE.SWEETNESS 최종 공개범위"), {
      target: { value: "VERIFIED_BUYER" },
    });
    fireEvent.click(screen.getByRole("button", { name: "승인" }));

    await waitFor(() => expect(onDecided).toHaveBeenCalled());
    const [url, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url, "http://localhost").pathname).toBe("/api/v1/admin/ai-review/ext-1/approve");
    expect(JSON.parse(requestInit.body as string)).toEqual({ visibility: "VERIFIED_BUYER" });
  });

  it("requires a reason code before the reject request is ever sent (reason-code required on reject)", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: {} });
    render(<AttributeComparisonCard row={buildComparisonRow(attribute())} onDecided={() => {}} />);

    fireEvent.click(screen.getByRole("button", { name: "반려" }));
    // 사유코드를 고르지 않고 바로 확정 시도 -> 검증 메시지, 네트워크 호출 없음.
    fireEvent.click(screen.getByRole("button", { name: "반려 확정" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("사유코드를 선택해야 합니다.");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends the composed reason-code payload once a code is selected", async () => {
    const fetchMock = mockFetchOnce({
      success: true,
      data: { extraction_id: "ext-1", review_status: "REJECTED_BY_OPERATOR", published_version_id: null },
    });
    const onDecided = vi.fn();
    render(<AttributeComparisonCard row={buildComparisonRow(attribute())} onDecided={onDecided} />);

    fireEvent.click(screen.getByRole("button", { name: "반려" }));
    fireEvent.change(screen.getByLabelText("사유코드"), { target: { value: "VALUE_INCORRECT" } });
    fireEvent.change(screen.getByLabelText("사유 코멘트"), { target: { value: "원문과 다름" } });
    fireEvent.click(screen.getByRole("button", { name: "반려 확정" }));

    await waitFor(() => expect(onDecided).toHaveBeenCalled());
    const [url, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url, "http://localhost").pathname).toBe("/api/v1/admin/ai-review/ext-1/reject");
    const body = JSON.parse(requestInit.body as string) as { reason: string };
    expect(body.reason).toContain("[VALUE_INCORRECT]");
    expect(body.reason).toContain("원문과 다름");
  });
});
