import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "@/lib/api-client";
import { getDefaultSession, setRuntimeSession } from "@/lib/auth-state";

import { decidePartnerMeeting, getPartnerBuyerSummary, listPartnerMeetings } from "../api";

const STAFF_USER_ID = "22222222-2222-4222-8222-222222222222";

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

describe("partner-meeting api client", () => {
  beforeEach(() => {
    window.localStorage.clear();
    setRuntimeSession({
      role: "EXHIBITOR_ADMIN",
      actorUserId: STAFF_USER_ID,
      exhibitorId: "exhibitor-a",
      displayName: "테스트 담당자",
      state: "AUTHENTICATED",
      csrfToken: "test-csrf-token",
    });
  });

  afterEach(() => {
    setRuntimeSession(getDefaultSession());
    vi.unstubAllGlobals();
  });

  // 통합 시 재작성(SECURITY): 이 파일은 원래 브라우저 localStorage에 담당자가 직접
  // 입력한 staffId를 `X-Staff-Id` 헤더로 실어 보내는 독립 클라이언트였다 - 그 값을 바꿔
  // 입력하면 다른 회사의 상담함을 그대로 열 수 있었다(백엔드는 그 헤더를 인가에 쓰지
  // 않는다). 지금은 다른 관리자 화면과 동일하게 `@/lib/api-client`를 그대로 재사용한다:
  // 회사 범위는 Secure/HttpOnly 세션 쿠키의 principal로 서버가 강제하고(스코핑 파라미터를
  // 클라이언트가 보낼 방법 자체가 없다), 상태를 바꾸는 요청에는 그 세션에 묶인 CSRF
  // 토큰이 실린다.
  it("never lets the client attach a company-scoping identity header - the backend enforces company scope from the session cookie alone", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: { items: [], next_cursor: null } });

    await listPartnerMeetings({ status: "requested" });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = requestInit.headers as Record<string, string>;
    expect(headers["X-Staff-Id"]).toBeUndefined();
    expect(headers["X-Actor-User-Id"]).toBeUndefined();
    expect(requestInit.credentials).toBe("include");
    expect(url).toContain("/partner/meetings");
  });

  it("never lets the client attach a company-scoping parameter of its own - only status/cursor/limit go on the wire", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: { items: [], next_cursor: null } });

    await listPartnerMeetings({ status: "accepted", cursor: "abc", limit: 10 });

    const [url] = fetchMock.mock.calls[0] as [string];
    const query = new URL(url, "http://localhost").searchParams;
    expect(new Set(query.keys())).toEqual(new Set(["status", "cursor", "limit"]));
    expect(query.get("status")).toBe("accepted");
  });

  it("unwraps the {success,data} envelope for buyer-summary and never fabricates a contact object client-side", async () => {
    mockFetchOnce({
      success: true,
      data: {
        meeting_id: "m1",
        status: "requested",
        topic_code: "BIZ_GOAL.EXPORT",
        message_preview: null,
        buyer_need: null,
        contact: null,
        contact_disclosed: false,
      },
    });

    const result = await getPartnerBuyerSummary("m1");

    expect(result.contact).toBeNull();
    expect(result.contact_disclosed).toBe(false);
  });

  it("attaches the session's X-CSRF-Token on the mutating decision call", async () => {
    const fetchMock = mockFetchOnce({
      success: true,
      data: {
        meeting_id: "m1",
        status: "rejected",
        exhibitor_id: "e1",
        participation_id: "p1",
        topic_code: null,
        message_preview: null,
        candidate_slots: [],
        confirmed_start: null,
        confirmed_end: null,
        contact_share_accepted: false,
        contact_share_fields: [],
        viewed_at: null,
        row_version: 1,
        created_at: "2026-08-02T00:00:00Z",
        updated_at: "2026-08-02T00:00:00Z",
      },
    });

    await decidePartnerMeeting(
      "m1",
      { action: "REJECT", version: 0, reason_code: "OTHER" },
      "idem-key-0",
    );

    const [, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = requestInit.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("test-csrf-token");
  });

  it("surfaces MEETING_VERSION_CONFLICT as a typed ApiClientError instead of pretending success", async () => {
    mockFetchOnce(
      {
        success: false,
        error: {
          code: "MEETING_VERSION_CONFLICT",
          message: "최신 상태를 다시 확인해 주세요.",
          field_errors: [],
          retryable: false,
          retry_after_seconds: null,
        },
      },
      { status: 409 },
    );

    await expect(
      decidePartnerMeeting("m1", { action: "REJECT", version: 0, reason_code: "OTHER" }, "idem-1"),
    ).rejects.toBeInstanceOf(ApiClientError);

    try {
      await decidePartnerMeeting(
        "m1",
        { action: "REJECT", version: 0, reason_code: "OTHER" },
        "idem-2",
      );
      expect.unreachable("expected decidePartnerMeeting to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiClientError);
      expect((err as ApiClientError).code).toBe("MEETING_VERSION_CONFLICT");
      expect((err as ApiClientError).http_status).toBe(409);
    }
  });

  it("sends the Idempotency-Key header for decide calls", async () => {
    const fetchMock = mockFetchOnce({
      success: true,
      data: {
        meeting_id: "m1",
        status: "rejected",
        exhibitor_id: "e1",
        participation_id: "p1",
        topic_code: null,
        message_preview: null,
        candidate_slots: [],
        confirmed_start: null,
        confirmed_end: null,
        contact_share_accepted: false,
        contact_share_fields: [],
        viewed_at: null,
        row_version: 1,
        created_at: "2026-08-02T00:00:00Z",
        updated_at: "2026-08-02T00:00:00Z",
      },
    });

    await decidePartnerMeeting(
      "m1",
      { action: "REJECT", version: 0, reason_code: "OTHER" },
      "idem-key-1",
    );

    const [, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = requestInit.headers as Record<string, string>;
    expect(headers["Idempotency-Key"]).toBe("idem-key-1");
  });
});
