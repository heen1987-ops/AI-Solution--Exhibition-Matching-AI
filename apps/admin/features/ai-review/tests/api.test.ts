import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "@/lib/api-client";
import { getDefaultSession, setRuntimeSession } from "@/lib/auth-state";

import {
  approveExtraction,
  claimReviewRequests,
  getDocumentExtractions,
  listAiReviewQueue,
  rejectExtraction,
  requestChangesOnDocument,
} from "../api";

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

describe("ai-review api client", () => {
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

  afterEach(() => {
    setRuntimeSession(getDefaultSession());
    vi.unstubAllGlobals();
  });

  it("lists the queue and unwraps the success envelope", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: { items: [] } });
    const result = await listAiReviewQueue({ status: "IN_OPERATOR_REVIEW" });
    expect(result.items).toEqual([]);
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(new URL(url, "http://localhost").pathname).toContain("/admin/ai-review");
    expect(new URL(url, "http://localhost").searchParams.get("status")).toBe("IN_OPERATOR_REVIEW");
  });

  // 통합 시 재작성: main의 세션 모델은 신원을 `X-Actor-User-Id` 같은 클라이언트 통제
  // 헤더가 아니라 Secure/HttpOnly 세션 쿠키로 나른다. 상태를 바꾸는 bulk-claim 호출에서
  // CSRF 토큰이 실제로 실리는지로 세션 연결을 검증한다.
  it("attaches the session's X-CSRF-Token on the mutating bulk-claim call", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: { claimed: ["rr-1"], already_claimed: [] } });
    await claimReviewRequests(["rr-1"]);
    const [, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = requestInit.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("test-csrf-token");
  });

  it("posts review_request_ids for bulk claim", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: { claimed: ["rr-1"], already_claimed: [] } });
    const result = await claimReviewRequests(["rr-1"]);
    expect(result.claimed).toEqual(["rr-1"]);
    const [url, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url, "http://localhost").pathname).toBe("/api/v1/admin/ai-review");
    expect(JSON.parse(requestInit.body as string)).toEqual({ review_request_ids: ["rr-1"] });
  });

  it("fetches a document's extraction list via the reused partner endpoint", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: { document_id: "doc-1", items: [] } });
    await getDocumentExtractions("doc-1");
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(new URL(url, "http://localhost").pathname).toBe("/api/v1/partner/documents/doc-1/extractions");
  });

  it("posts to the per-extraction approve endpoint", async () => {
    const fetchMock = mockFetchOnce({
      success: true,
      data: { extraction_id: "ext-1", review_status: "APPROVED_BY_OPERATOR", published_version_id: null },
    });
    await approveExtraction("ext-1", { visibility: "PUBLIC" });
    const [url, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(url, "http://localhost").pathname).toBe("/api/v1/admin/ai-review/ext-1/approve");
    expect(JSON.parse(requestInit.body as string)).toEqual({ visibility: "PUBLIC" });
  });

  it("throws REASON_REQUIRED and never calls the backend when reject has a blank reason", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: {} });
    await expect(rejectExtraction("ext-1", { reason: "   " })).rejects.toMatchObject({ code: "REASON_REQUIRED" });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("posts a non-blank reason to the per-extraction reject endpoint", async () => {
    const fetchMock = mockFetchOnce({
      success: true,
      data: { extraction_id: "ext-1", review_status: "REJECTED_BY_OPERATOR", published_version_id: null },
    });
    await rejectExtraction("ext-1", { reason: "[VALUE_INCORRECT] 값이 부정확함 - 원문과 다름" });
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(new URL(url, "http://localhost").pathname).toBe("/api/v1/admin/ai-review/ext-1/reject");
  });

  it("throws REASON_REQUIRED and never calls the backend when request-changes has a blank comment", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: {} });
    await expect(requestChangesOnDocument("rr-1", { comment: "" })).rejects.toMatchObject({
      code: "REASON_REQUIRED",
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("posts to the review-request-scoped request-changes endpoint", async () => {
    const fetchMock = mockFetchOnce({
      success: true,
      data: { review_request_id: "rr-1", status: "CHANGES_REQUESTED", operator_comment: "x" },
    });
    await requestChangesOnDocument("rr-1", { comment: "[EVIDENCE_MISSING] 근거 누락 - 페이지 확인 필요" });
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(new URL(url, "http://localhost").pathname).toBe("/api/v1/admin/ai-review/rr-1/request-changes");
  });

  it("surfaces a 404 from the not-yet-registered router as NOT_IMPLEMENTED instead of a fake success", async () => {
    mockFetchOnce(null, { status: 404 });
    try {
      await listAiReviewQueue();
      expect.unreachable("expected listAiReviewQueue to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiClientError);
      expect((err as ApiClientError).code).toBe("NOT_IMPLEMENTED");
    }
  });
});
