import { afterEach, describe, expect, it, vi } from "vitest";
import { loadCompanyById, loadRecommendations, searchCompanies } from "../lib/api-client";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

describe("user-web API client", () => {
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
  });

  it("추천 API 응답을 화면 카드 데이터로 매핑한다", async () => {
    vi.stubEnv("MEETAI_API_BASE_URL", "http://api.test");
    vi.stubEnv("MEETAI_PROFILE_ID", "profile-1");
    const fetchMock = vi.fn().mockResolvedValueOnce(
      jsonResponse({
        results: [
          {
            recommendable_id: "rec-12345678",
            rank: 1,
            normalized_score: 0.87,
            recommended_action: null,
            reasons: [{ reason_code: "INTEREST", reason_text: "관심 분야 일치" }],
          },
        ],
        page: { page: 1, page_size: 20, total_count: 1 },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);

    const result = await loadRecommendations();

    expect(result.source).toBe("api");
    expect(result.data[0]?.company.recommendableId).toBe("rec-12345678");
    expect(result.data[0]?.score).toBe(0.87);
    expect(fetchMock).toHaveBeenCalledWith(
      "http://api.test/api/v1/recommendations",
      expect.objectContaining({
        headers: expect.objectContaining({
          "X-MeetAI-Profile-Id": "profile-1",
        }),
      }),
    );
  });

  it("게스트 검색은 세션을 만든 뒤 GUEST_WEB 채널로 검색한다", async () => {
    vi.stubEnv("MEETAI_API_BASE_URL", "http://api.test");
    vi.stubEnv("MEETAI_EVENT_ID", "event-1");
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(
        jsonResponse({
          guest_session_id: "guest-session-1",
          session_status: "ACTIVE",
        }),
      )
      .mockResolvedValueOnce(
        jsonResponse({
          search_query_id: "query-1",
          result_count: 1,
          results: [
            {
              recommendable_id: "rec-search",
              rank: 1,
              final_score: 0.73,
              reason_codes: ["KEYWORD_MATCH"],
            },
          ],
          meta: null,
        }),
      );
    vi.stubGlobal("fetch", fetchMock);

    const result = await searchCompanies("목재", "GUEST_WEB");
    const [, searchInit] = fetchMock.mock.calls[1] as [string, RequestInit];
    const searchBody = JSON.parse(String(searchInit.body));

    expect(result.source).toBe("api");
    expect(result.data[0]?.company.recommendableId).toBe("rec-search");
    expect(fetchMock.mock.calls[0]?.[0]).toBe("http://api.test/api/v1/guest/sessions");
    expect(fetchMock.mock.calls[1]?.[0]).toBe("http://api.test/api/v1/search");
    expect(searchInit.headers).toEqual(
      expect.objectContaining({ "X-MeetAI-User-Type": "GUEST_WEB" }),
    );
    expect(searchBody).toEqual(
      expect.objectContaining({
        channel: "GUEST_WEB",
        guest_session_id: "guest-session-1",
        query_text: "목재",
        query_type: "FREE_TEXT",
      }),
    );
  });

  it("추천 결과 UUID 상세는 저장 가능한 승인 대상 fallback으로 연다", async () => {
    vi.stubEnv("MEETAI_API_BASE_URL", "");

    const result = await loadCompanyById("11111111-1111-4111-8111-111111111111");

    expect(result.source).toBe("fallback");
    expect(result.data?.recommendableId).toBe("11111111-1111-4111-8111-111111111111");
    expect(result.data?.approvalStatus).toBe("APPROVED");
  });
});
