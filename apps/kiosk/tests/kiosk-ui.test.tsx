import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import ResultCard from "@/components/ResultCard";
import { IDLE_TIMEOUT_DEFAULT_SECONDS, clampIdleTimeoutSeconds } from "@/lib/config";
import { KioskSessionProvider, useKioskSession } from "@/lib/kiosk-session-context";
import type { StoredKioskState } from "@/lib/types";

vi.mock("@/lib/api-client", () => ({
  getKioskConfig: vi.fn().mockRejectedValue(new Error("offline")),
  kioskClose: vi.fn().mockResolvedValue({ closed: true }),
}));

const storedState: StoredKioskState = {
  language: "ko",
  session: {
    session_id: "11111111-1111-4111-8111-111111111111",
    event_id: "22222222-2222-4222-8222-222222222222",
    kiosk_id: "kiosk_a01",
    language: "ko",
    created_at: "2026-08-02T00:00:00Z",
    expires_at: "2026-08-02T00:01:30Z",
    session_timeout_seconds: 90,
  },
  query: "막걸리",
  categoryCodes: ["ALCOHOL.TAKJU"],
  results: [],
  interpretedConcepts: ["ALCOHOL.TAKJU"],
  handoff: {
    handoff_id: "33333333-3333-4333-8333-333333333333",
    token: "signed-token",
    handoff_url: "https://example.test/kiosk-handoff?token=signed-token",
    expires_at: "2026-08-02T00:30:00Z",
  },
  savedAt: "2026-08-02T00:00:00Z",
};

function ResetHarness() {
  const { query, results, handoff, resetAll } = useKioskSession();
  return (
    <div>
      <output data-testid="state">{`${query}|${results.length}|${handoff?.token ?? ""}`}</output>
      <button type="button" onClick={() => resetAll({ notifyServer: false })}>
        reset
      </button>
    </div>
  );
}

describe("kiosk privacy and touch flow", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  it("clears the previous visitor's query and QR token from memory and storage", async () => {
    window.sessionStorage.setItem("kiosk.session.v1", JSON.stringify(storedState));
    render(
      <KioskSessionProvider>
        <ResetHarness />
      </KioskSessionProvider>,
    );

    expect(screen.getByTestId("state")).toHaveTextContent("막걸리|0|signed-token");
    fireEvent.click(screen.getByRole("button", { name: "reset" }));

    await waitFor(() => {
      expect(screen.getByTestId("state")).toHaveTextContent("|0|");
      expect(window.sessionStorage.getItem("kiosk.session.v1")).toBeNull();
    });
  });

  it("renders a large public result action without identity fields", () => {
    render(
      <ResultCard
        language="ko"
        result={{
          result_id: "exhibitor:1:booth:2",
          rank: 1,
          object_type: "EXHIBITOR",
          exhibitor_id: "1",
          booth_id: "2",
          name: "풍년 양조장",
          booth_number: "A-01",
          zone_name: "A홀",
          summary: "승인된 공개 소개",
          product_names: ["생막걸리"],
          reason: "검색어와 관련된 승인 업체예요.",
          concepts: ["ALCOHOL.TAKJU"],
          operating_status: "OPEN",
          estimated_wait_minutes: 5,
          map_x: 40,
          map_y: 60,
        }}
      />,
    );

    const detailLink = screen.getByRole("link", { name: "업체·부스 자세히 보기" });
    expect(detailLink).toHaveAttribute("href", "/exhibitors/1");
    expect(screen.queryByLabelText(/이메일|전화번호|비밀번호/)).not.toBeInTheDocument();
  });

  it("honors the server's full 60–120 second timeout contract", () => {
    expect(clampIdleTimeoutSeconds(undefined)).toBe(IDLE_TIMEOUT_DEFAULT_SECONDS);
    expect(clampIdleTimeoutSeconds(30)).toBe(60);
    expect(clampIdleTimeoutSeconds(60)).toBe(60);
    expect(clampIdleTimeoutSeconds(120)).toBe(120);
    expect(clampIdleTimeoutSeconds(180)).toBe(120);
  });
});
