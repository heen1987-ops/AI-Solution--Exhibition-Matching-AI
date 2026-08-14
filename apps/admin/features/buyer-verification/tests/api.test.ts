import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "@/lib/api-client";
import { getDefaultSession, setRuntimeSession } from "@/lib/auth-state";

import { decideBuyerVerification, listAdminMeetingOps, listBuyerVerificationQueue } from "../api";

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

describe("buyer-verification api client", () => {
  beforeEach(() => {
    window.localStorage.clear();
    setRuntimeSession({
      role: "EVENT_ADMIN",
      actorUserId: "11111111-1111-4111-8111-111111111111",
      exhibitorId: null,
      displayName: "테스트 운영자",
      state: "AUTHENTICATED",
      csrfToken: "test-csrf-token",
    });
  });

  afterEach(() => {
    setRuntimeSession(getDefaultSession());
    vi.unstubAllGlobals();
  });

  it("throws REASON_REQUIRED and never calls the backend when reason is blank", () => {
    // decideBuyerVerification (like the sibling rejectExhibitor) validates and throws
    // *synchronously* rather than returning a rejected Promise, so `expect(fn()).rejects`
    // never gets a Promise to unwrap - the throw happens while evaluating the argument to
    // expect(), before expect() itself runs. `expect(() => fn()).toThrow(...)` is the
    // correct matcher for a synchronously-throwing call.
    const fetchMock = mockFetchOnce({ success: true, data: {} });

    expect(() =>
      decideBuyerVerification("buyer-1", { action: "VERIFY", reason: "   " }),
    ).toThrowError(expect.objectContaining({ code: "REASON_REQUIRED" }));
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("posts action+reason to the verification-decision endpoint and unwraps the envelope", async () => {
    const fetchMock = mockFetchOnce({
      success: true,
      data: {
        buyer_profile_id: "buyer-1",
        verification_status: "VERIFIED",
        decided_at: "2026-08-02T00:00:00Z",
        decided_by: "11111111-1111-4111-8111-111111111111",
        reason: "사업자등록증 확인 완료",
        is_meeting_eligible: true,
      },
    });

    const result = await decideBuyerVerification("buyer-1", {
      action: "VERIFY",
      reason: "사업자등록증 확인 완료",
    });

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toContain("/admin/buyers/buyer-1/verification-decision");
    expect(JSON.parse(requestInit.body as string)).toEqual({
      action: "VERIFY",
      reason: "사업자등록증 확인 완료",
    });
    expect(result.verification_status).toBe("VERIFIED");
    expect(result.is_meeting_eligible).toBe(true);
  });

  // 통합 시 재작성: main의 세션 모델은 신원을 `X-Actor-User-Id` 같은 클라이언트 통제
  // 헤더가 아니라 Secure/HttpOnly 세션 쿠키로 나른다(자바스크립트가 값을 읽거나 보낼 수
  // 없다) - 그래서 이 GET 호출에는 애초에 신원 헤더가 없다. 상태 변경 요청에서만 CSRF
  // 토큰을 함께 보내 세션이 실제로 연결돼 있는지 증명한다(decideBuyerVerification).
  it("attaches the session's X-CSRF-Token on the mutating verification-decision call (same auth model as exhibitor approve/reject)", async () => {
    const fetchMock = mockFetchOnce({
      success: true,
      data: {
        buyer_profile_id: "buyer-1",
        verification_status: "VERIFIED",
        decided_at: "2026-08-02T00:00:00Z",
        decided_by: "11111111-1111-4111-8111-111111111111",
        reason: "사업자등록증 확인 완료",
        is_meeting_eligible: true,
      },
    });

    await decideBuyerVerification("buyer-1", { action: "VERIFY", reason: "사업자등록증 확인 완료" });

    const [, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const headers = requestInit.headers as Record<string, string>;
    expect(headers["X-CSRF-Token"]).toBe("test-csrf-token");
  });

  it("only sends filters that were actually provided to the verification queue", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: { items: [], next_cursor: null } });

    await listBuyerVerificationQueue({ event_id: "event-1" });

    const [url] = fetchMock.mock.calls[0] as [string];
    const query = new URL(url, "http://localhost").searchParams;
    expect(query.get("event_id")).toBe("event-1");
    expect(query.has("verification_status")).toBe(false);
  });

  it("surfaces a 404 from a not-yet-implemented backend route as NOT_IMPLEMENTED instead of a fake success", async () => {
    mockFetchOnce(null, { status: 404 });

    await expect(listBuyerVerificationQueue()).rejects.toBeInstanceOf(ApiClientError);
    try {
      await listBuyerVerificationQueue();
      expect.unreachable("expected listBuyerVerificationQueue to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiClientError);
      expect((err as ApiClientError).code).toBe("NOT_IMPLEMENTED");
    }
  });

  it("does not request contact-carrying fields for the meeting ops view - only the scoped query params go on the wire", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: { items: [], next_cursor: null } });

    await listAdminMeetingOps({ event_id: "event-1", status: "requested" });

    const [url] = fetchMock.mock.calls[0] as [string];
    const query = new URL(url, "http://localhost").searchParams;
    expect(new Set(query.keys())).toEqual(new Set(["event_id", "status"]));
  });
});
