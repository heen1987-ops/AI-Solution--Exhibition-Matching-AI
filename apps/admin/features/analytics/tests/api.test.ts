import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "@/lib/api-client";
import { getDefaultSession, setRuntimeSession } from "@/lib/auth-state";

import { getBuyerAnalytics, getKioskAnalytics, getOverviewAnalytics, getWebAnalytics } from "../api";
import type { AnalyticsFilter, ResolvedDateRange } from "../types";

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

const FILTER: AnalyticsFilter = {
  eventId: "evt-1",
  preset: "LAST_7_DAYS",
  customStart: null,
  customEnd: null,
  channel: "ALL",
};
const RANGE: ResolvedDateRange = { periodStart: "2026-07-28", periodEnd: "2026-08-03" };

describe("analytics api client", () => {
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

  it("calls GET /admin/analytics/overview with event_id + period_start/end", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: { event_id: "evt-1" } });
    await getOverviewAnalytics(FILTER, RANGE);
    const [url] = fetchMock.mock.calls[0] as [string];
    const parsed = new URL(url, "http://localhost");
    expect(parsed.pathname).toBe("/api/v1/admin/analytics/overview");
    expect(parsed.searchParams.get("event_id")).toBe("evt-1");
    expect(parsed.searchParams.get("period_start")).toBe("2026-07-28");
    expect(parsed.searchParams.get("period_end")).toBe("2026-08-03");
  });

  it("omits the channel query param when channel filter is ALL", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: {} });
    await getWebAnalytics(FILTER, RANGE);
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(new URL(url, "http://localhost").searchParams.has("channel")).toBe(false);
  });

  it("sends the channel query param when a specific channel is selected", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: {} });
    await getKioskAnalytics({ ...FILTER, channel: "KIOSK" }, RANGE);
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(new URL(url, "http://localhost").searchParams.get("channel")).toBe("KIOSK");
  });

  // 통합 시 재작성: main의 세션 모델은 신원을 `X-Actor-User-Id` 헤더가 아니라
  // Secure/HttpOnly 세션 쿠키로 나른다. `/admin/analytics/*`는 이 파일 전체가 읽기
  // 전용(GET)이라 CSRF 토큰도 붙지 않는다(apiRequest는 GET이 아닐 때만 첨부한다) - 그래서
  // 이 read 경로에서 세션이 실제로 연결됐음을 증명하는 유일한 신호는 자격증명 쿠키
  // 전송 여부(`credentials: "include"`)뿐이다.
  it("sends the session cookie via credentials: include (no client-controlled identity header on this read-only endpoint)", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: {} });
    await getOverviewAnalytics(FILTER, RANGE);
    const [, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(requestInit.credentials).toBe("include");
  });

  it("passes exhibitor_id for the buyer endpoint only when explicitly given", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: { breakdown: [] } });
    await getBuyerAnalytics(FILTER, RANGE, "ex-1");
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(new URL(url, "http://localhost").searchParams.get("exhibitor_id")).toBe("ex-1");
  });

  it("omits exhibitor_id for the buyer endpoint when not given (server scopes EXHIBITOR_ADMIN itself)", async () => {
    const fetchMock = mockFetchOnce({ success: true, data: { breakdown: [] } });
    await getBuyerAnalytics(FILTER, RANGE);
    const [url] = fetchMock.mock.calls[0] as [string];
    expect(new URL(url, "http://localhost").searchParams.has("exhibitor_id")).toBe(false);
  });

  it("surfaces a 404 from the not-yet-registered analytics router as NOT_IMPLEMENTED, never a fake success", async () => {
    mockFetchOnce(null, { status: 404 });
    try {
      await getOverviewAnalytics(FILTER, RANGE);
      expect.unreachable("expected getOverviewAnalytics to throw");
    } catch (err) {
      expect(err).toBeInstanceOf(ApiClientError);
      expect((err as ApiClientError).code).toBe("NOT_IMPLEMENTED");
    }
  });

  it("sanitizes the response before returning it, even if the backend leaked a contact field", async () => {
    mockFetchOnce({
      success: true,
      data: {
        event_id: "evt-1",
        breakdown: [{ exhibitor_id: "ex-1", buyer_name: "홍길동", buyer_matches: { value: 5, suppressed: false } }],
      },
    });
    const result = await getBuyerAnalytics(FILTER, RANGE);
    expect(JSON.stringify(result)).not.toContain("홍길동");
    expect(JSON.stringify(result)).not.toContain("buyer_name");
  });
});
