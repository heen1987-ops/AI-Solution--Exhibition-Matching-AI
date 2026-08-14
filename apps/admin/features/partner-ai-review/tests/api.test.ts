import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "@/lib/api-client";
import { getDefaultSession, setRuntimeSession } from "@/lib/auth-state";

import {
  confirmExtraction,
  confirmProposedValue,
  listExtractions,
  patchExtraction,
  rejectProposedValue,
  saveModifiedValue,
  submitDocumentForReview,
} from "../api";
import type { ExtractedAttributeRead } from "../types";

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

function makeAttribute(overrides: Partial<ExtractedAttributeRead> = {}): ExtractedAttributeRead {
  return {
    extraction_id: "extraction-1",
    document_id: "doc-1",
    ai_run_id: "run-1",
    entity_type: "TRADE_CONDITION",
    entity_reference: "trade-1",
    temporary_entity_ref: null,
    attribute_code: "trade.export_capability",
    proposed_value: "UNKNOWN",
    normalized_value: null,
    concept_codes: ["TRADE.EXPORT"],
    fact_type: "UNKNOWN",
    temporal_validity: "UNKNOWN",
    confidence: null,
    review_status: "PROPOSED",
    visibility: null,
    edited_by_exhibitor: false,
    evidence: [],
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

describe("partner-ai-review api client", () => {
  beforeEach(() => {
    window.localStorage.clear();
    setRuntimeSession({
      role: "EXHIBITOR_ADMIN",
      actorUserId: "11111111-1111-4111-8111-111111111111",
      exhibitorId: "exhibitor-a",
      displayName: "테스트 참가업체",
      state: "AUTHENTICATED",
      csrfToken: "test-csrf-token",
    });
  });

  afterEach(() => {
    setRuntimeSession(getDefaultSession());
    vi.unstubAllGlobals();
  });

  it("lists a document's extractions via the landed extraction.py router path", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: { document_id: "doc-1", items: [] } });
    await listExtractions("doc-1");
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(new URL(url, "http://localhost").pathname).toBe(
      "/api/v1/partner/documents/doc-1/extractions",
    );
  });

  // 통합 시 재작성: main의 세션 모델은 신원을 `X-Actor-User-Id` 같은 클라이언트 통제
  // 헤더가 아니라 Secure/HttpOnly 세션 쿠키로 나른다. 상태를 바꾸는 confirm 호출에서
  // CSRF 토큰이 실제로 실리는지로 세션 연결을 검증한다.
  it("attaches the session's X-CSRF-Token on the mutating confirm call", async () => {
    const fetchMock = mockFetchOnce({
      success: true,
      data: makeAttribute({ review_status: "CONFIRMED_BY_EXHIBITOR" }),
    });
    await confirmExtraction("extraction-1", { decision: "confirm", reason: null });
    const [, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = requestInit.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("test-csrf-token");
  });

  it("PATCHes normalized_value/visibility without ever including review_status (server owns that transition)", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: makeAttribute() });
    await patchExtraction("extraction-1", { normalized_value: "SUPPORTED", reason: "메모" });
    const [url, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(requestInit.method).toBe("PATCH");
    expect(new URL(url, "http://localhost").pathname).toBe("/api/v1/partner/extractions/extraction-1");
    const body = JSON.parse(requestInit.body as string);
    expect(body).toEqual({ normalized_value: "SUPPORTED", reason: "메모" });
    expect(body).not.toHaveProperty("review_status");
  });

  it("posts decision=confirm to the confirm endpoint", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: makeAttribute({ review_status: "CONFIRMED_BY_EXHIBITOR" }) });
    await confirmExtraction("extraction-1", { decision: "confirm", reason: null });
    const [url, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url, "http://localhost").pathname).toBe(
      "/api/v1/partner/extractions/extraction-1/confirm",
    );
    expect(JSON.parse(requestInit.body as string)).toEqual({ decision: "confirm", reason: null });
  });

  it("confirmProposedValue never gates on UNKNOWN->YES: the confirm request carries no value at all, so accepting whatever is already on the row can never itself be the transition (see api.ts module docstring)", async () => {
    const fetchMock = mockFetchOnce({
      success: true,
      data: makeAttribute({ review_status: "CONFIRMED_BY_EXHIBITOR" }),
    });
    // Even a row whose own proposed_value is the literal string "UNKNOWN" confirms without
    // friction - it just acknowledges it stays UNKNOWN (backend's ACKNOWLEDGE_UNKNOWN action).
    const attribute = makeAttribute({ proposed_value: "UNKNOWN", normalized_value: null });
    await confirmProposedValue(attribute, undefined);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(requestInit.body as string)).toEqual({ decision: "confirm", reason: null });
  });

  it("confirms with an optional reason passed through unchanged (a free-text memo, not a gate)", async () => {
    const fetchMock = mockFetchOnce({
      success: true,
      data: makeAttribute({ review_status: "CONFIRMED_BY_EXHIBITOR", normalized_value: "SUPPORTED" }),
    });
    const attribute = makeAttribute({ proposed_value: "SUPPORTED", normalized_value: null, fact_type: "SOURCE_FACT" });
    await confirmProposedValue(attribute, "카탈로그에서 직접 확인함");
    const [, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(JSON.parse(requestInit.body as string)).toEqual({
      decision: "confirm",
      reason: "카탈로그에서 직접 확인함",
    });
  });

  it("saveModifiedValue sends PATCH then confirm(decision=confirm) in sequence - the two-call contract the router actually requires", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        text: async () => JSON.stringify({ success: true, data: makeAttribute({ normalized_value: "NOT_SUPPORTED" }) }),
      } as unknown as Response)
      .mockResolvedValueOnce({
        status: 200,
        ok: true,
        text: async () =>
          JSON.stringify({
            success: true,
            data: makeAttribute({ review_status: "MODIFIED_BY_EXHIBITOR", normalized_value: "NOT_SUPPORTED" }),
          }),
      } as unknown as Response);
    vi.stubGlobal("fetch", fetchMock);

    const attribute = makeAttribute();
    const updated = await saveModifiedValue(attribute, "NOT_SUPPORTED");

    expect(fetchMock).toHaveBeenCalledTimes(2);
    const [firstUrl, firstInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(firstInit.method).toBe("PATCH");
    expect(new URL(firstUrl, "http://localhost").pathname).toBe("/api/v1/partner/extractions/extraction-1");
    const [secondUrl, secondInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    expect(secondInit.method).toBe("POST");
    expect(new URL(secondUrl, "http://localhost").pathname).toBe(
      "/api/v1/partner/extractions/extraction-1/confirm",
    );
    expect(updated.review_status).toBe("MODIFIED_BY_EXHIBITOR");
  });

  it("saveModifiedValue never calls PATCH when the resulting value is an ungated UNKNOWN->YES capability transition missing justification", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: makeAttribute() });
    await expect(saveModifiedValue(makeAttribute(), "SUPPORTED")).rejects.toMatchObject({
      code: "JUSTIFICATION_REQUIRED",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("rejectProposedValue posts decision=reject with the given reason", async () => {
    const fetchMock = mockFetchOnce({
      success: true,
      data: makeAttribute({ review_status: "REJECTED_BY_EXHIBITOR" }),
    });
    await rejectProposedValue("extraction-1", "원문 근거와 불일치");
    const [url, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url, "http://localhost").pathname).toBe(
      "/api/v1/partner/extractions/extraction-1/confirm",
    );
    expect(JSON.parse(requestInit.body as string)).toEqual({
      decision: "reject",
      reason: "원문 근거와 불일치",
    });
  });

  it("submits a document for review to the document-scoped (not extraction-scoped) submit-review path", async () => {
    const fetchMock = mockFetchOnce({
      success: true,
      data: {
        review_request_id: "rr-1",
        document_id: "doc-1",
        status: "SUBMITTED",
        submitted_at: "2026-08-03T00:00:00Z",
      },
    });
    await submitDocumentForReview({ document_id: "doc-1" });
    const [url, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url, "http://localhost").pathname).toBe("/api/v1/partner/extractions/submit-review");
    expect(JSON.parse(requestInit.body as string)).toEqual({ document_id: "doc-1" });
  });

  it("surfaces a 403 (cross-company access) as a real ApiClientError instead of a fake success - this is the only own-company-only defense the AI-review screen has, since the response never includes exhibitor_id", async () => {
    mockFetchOnce({ detail: { code: "RESOURCE_FORBIDDEN", message: "다른 업체의 문서입니다." } }, { status: 403 });
    await expect(listExtractions("doc-of-another-company")).rejects.toMatchObject({
      code: "RESOURCE_FORBIDDEN",
    });
  });

  it("surfaces a 404 from the not-yet-mounted router as NOT_IMPLEMENTED instead of a fake success", async () => {
    mockFetchOnce(null, { status: 404 });
    try {
      await listExtractions("doc-1");
      expect.unreachable("expected listExtractions to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiClientError);
      expect((err as ApiClientError).code).toBe("NOT_IMPLEMENTED");
    }
  });
});
