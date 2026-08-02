import { afterEach, describe, expect, it, vi } from "vitest";

import { apiPost } from "./api-client";
import { setRuntimeCsrfToken } from "./auth-state";

describe("user API browser-session security", () => {
  afterEach(() => {
    setRuntimeCsrfToken(null);
    vi.unstubAllGlobals();
  });

  it("attaches the runtime CSRF token to unsafe requests", async () => {
    const fetchMock = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ success: true, data: { ok: true } }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    setRuntimeCsrfToken("session-bound-csrf-token");

    await apiPost<{ ok: boolean }>("/test", { value: 1 });

    const request = fetchMock.mock.calls[0]?.[1] as RequestInit;
    expect((request.headers as Record<string, string>)["X-CSRF-Token"]).toBe(
      "session-bound-csrf-token",
    );
    expect(request.credentials).toBe("include");
  });

  it("accepts direct frozen Pydantic responses from auth routes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ session_id: "session-1" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    await expect(apiPost<{ session_id: string }>("/auth/test", {})).resolves.toEqual({
      session_id: "session-1",
    });
  });
});
