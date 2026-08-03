import { afterEach, expect, test, vi } from "vitest";
import {
  loadAdminConsoleSnapshot,
  submitBoothStatus,
  submitContentApproval,
} from "../lib/admin-api";

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
});

test("content approval posts to the frozen admin endpoint with operator headers", async () => {
  vi.stubEnv("MEETAI_API_BASE_URL", "http://api.test");
  vi.stubEnv("MEETAI_ADMIN_USER_ID", "user-1");
  const fetchMock = vi.fn().mockResolvedValueOnce(
    jsonResponse({
      content_approval_id: "approval-1",
      exhibitor_id: "exhibitor-1",
      decision: "APPROVED",
      approved_at: "2026-08-03T00:00:00Z",
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await submitContentApproval({
    exhibitor_id: "exhibitor-1",
    decision: "APPROVED",
    note: "확인",
  });

  expect(fetchMock).toHaveBeenCalledWith(
    "http://api.test/api/v1/admin/content-approvals",
    expect.objectContaining({
      method: "POST",
      headers: expect.objectContaining({
        "X-MeetAI-Actor-Role": "OPERATOR",
        "X-MeetAI-User-Id": "user-1",
      }),
    }),
  );
});

test("booth status patch uses optimistic row_version when provided", async () => {
  vi.stubEnv("MEETAI_API_BASE_URL", "http://api.test");
  const fetchMock = vi.fn().mockResolvedValueOnce(
    jsonResponse({
      booth_id: "booth-1",
      exhibitor_id: "exhibitor-1",
      operating_status: "PAUSED",
      congestion_level: "HIGH",
      row_version: 4,
    }),
  );
  vi.stubGlobal("fetch", fetchMock);

  await submitBoothStatus("booth-1", {
    operating_status: "PAUSED",
    congestion_level: "HIGH",
    row_version: 3,
  });
  const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];

  expect(fetchMock.mock.calls[0]?.[0]).toBe(
    "http://api.test/api/v1/admin/booths/booth-1/status",
  );
  expect(JSON.parse(String(init.body))).toEqual(
    expect.objectContaining({ operating_status: "PAUSED", row_version: 3 }),
  );
});

test("console snapshot falls back when the API base URL is not configured", async () => {
  vi.stubEnv("MEETAI_API_BASE_URL", "");
  vi.stubEnv("NEXT_PUBLIC_API_BASE_URL", "");

  const snapshot = await loadAdminConsoleSnapshot();

  expect(snapshot.source).toBe("fallback");
  expect(snapshot.metrics.some((metric) => metric.key === "profile-completeness")).toBe(true);
});
