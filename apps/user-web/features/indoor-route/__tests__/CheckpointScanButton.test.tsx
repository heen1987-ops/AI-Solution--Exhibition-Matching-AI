import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/lib/api-client", () => ({
  ApiClientError: class ApiClientError extends Error {
    code: string;
    constructor(info: { code: string; message: string }) {
      super(info.message);
      this.code = info.code;
    }
  },
  checkpointScan: vi.fn(),
  generateClientId: () => "client-id-1",
}));

import { ApiClientError, checkpointScan } from "@/lib/api-client";
import type { RouteResponse } from "@/lib/types";

import CheckpointScanButton from "../CheckpointScanButton";

const mockCheckpointScan = vi.mocked(checkpointScan);

function route(overrides: Partial<RouteResponse> = {}): RouteResponse {
  return {
    route_id: "r1",
    visit_session_id: "vs1",
    route_preference: null,
    total_minutes: 40,
    walking_minutes: 10,
    status: "ACTIVE",
    items: [],
    ...overrides,
  };
}

describe("CheckpointScanButton", () => {
  it("opens as a manual code entry, not a fake camera scanner", () => {
    render(<CheckpointScanButton onScanned={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "지금 이 부스에 도착했어요" }));
    expect(screen.getByLabelText("체크포인트 코드")).toBeInTheDocument();
    expect(screen.getByText(/카메라로 QR을 찍는 기능은 아직 없어요/)).toBeInTheDocument();
  });

  it("requires a non-empty code before submitting", () => {
    render(<CheckpointScanButton onScanned={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "지금 이 부스에 도착했어요" }));
    fireEvent.click(screen.getByRole("button", { name: "도착 확인" }));
    expect(screen.getByRole("alert")).toHaveTextContent("체크포인트 코드를 입력해 주세요");
    expect(mockCheckpointScan).not.toHaveBeenCalled();
  });

  it("submits the entered code and forwards the server-recalculated route via onScanned", async () => {
    const recalculated = route();
    mockCheckpointScan.mockResolvedValue({
      indoor_checkpoint_scan_id: "scan-1",
      booth_id: "booth-1",
      scanned_at: "2026-08-13T00:00:00Z",
      route: recalculated,
    });
    const onScanned = vi.fn();

    render(<CheckpointScanButton onScanned={onScanned} />);
    fireEvent.click(screen.getByRole("button", { name: "지금 이 부스에 도착했어요" }));
    fireEvent.change(screen.getByLabelText("체크포인트 코드"), { target: { value: "ABC123" } });
    fireEvent.click(screen.getByRole("button", { name: "도착 확인" }));

    await waitFor(() => expect(onScanned).toHaveBeenCalledWith(recalculated));
    expect(mockCheckpointScan).toHaveBeenCalledWith(
      { qr_token: "ABC123" },
      { idempotencyKey: "client-id-1" },
    );
    expect(screen.getByText(/다시 계산했어요/)).toBeInTheDocument();
  });

  it("shows a friendly message for an invalid/expired code", async () => {
    mockCheckpointScan.mockRejectedValue(
      new ApiClientError({
        code: "INVALID_QR",
        message: "invalid",
        field_errors: [],
        retryable: false,
        retry_after_seconds: null,
        http_status: 400,
        request_id: null,
      }),
    );

    render(<CheckpointScanButton onScanned={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "지금 이 부스에 도착했어요" }));
    fireEvent.change(screen.getByLabelText("체크포인트 코드"), { target: { value: "bad" } });
    fireEvent.click(screen.getByRole("button", { name: "도착 확인" }));

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("유효하지 않거나 만료된 코드입니다"),
    );
  });

  it("keeps its actions as 44px tap targets (mobile smoke)", () => {
    render(<CheckpointScanButton onScanned={() => {}} />);
    const openButton = screen.getByRole("button", { name: "지금 이 부스에 도착했어요" });
    expect(openButton.className).toContain("tap-target");
    fireEvent.click(openButton);
    expect(screen.getByRole("button", { name: "도착 확인" }).className).toContain("tap-target");
    expect(screen.getByRole("button", { name: "취소" }).className).toContain("tap-target");
  });
});
