import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import CancelDialog from "../components/CancelDialog";

describe("CancelDialog", () => {
  it("does not cancel immediately - shows a reason picker first (two-step confirmation)", () => {
    const onConfirmCancel = vi.fn();
    render(<CancelDialog isActing={false} confirmLabel="요청 취소" onConfirmCancel={onConfirmCancel} />);
    fireEvent.click(screen.getByRole("button", { name: "요청 취소" }));
    expect(screen.getByText("취소 사유를 선택해 주세요")).toBeInTheDocument();
    expect(onConfirmCancel).not.toHaveBeenCalled();
  });

  it("submits the selected reason code only after the final confirm click", () => {
    const onConfirmCancel = vi.fn();
    render(<CancelDialog isActing={false} confirmLabel="요청 취소" onConfirmCancel={onConfirmCancel} />);
    fireEvent.click(screen.getByRole("button", { name: "요청 취소" }));
    fireEvent.click(screen.getByRole("radio", { name: "다른 업체와 진행하기로 했어요" }));
    fireEvent.click(screen.getByRole("button", { name: "요청 취소 확정" }));
    expect(onConfirmCancel).toHaveBeenCalledWith("DECIDED_ELSEWHERE");
  });

  it("returns to the button state via 돌아가기 without cancelling", () => {
    const onConfirmCancel = vi.fn();
    render(<CancelDialog isActing={false} confirmLabel="요청 취소" onConfirmCancel={onConfirmCancel} />);
    fireEvent.click(screen.getByRole("button", { name: "요청 취소" }));
    fireEvent.click(screen.getByRole("button", { name: "돌아가기" }));
    expect(screen.getByRole("button", { name: "요청 취소" })).toBeInTheDocument();
    expect(onConfirmCancel).not.toHaveBeenCalled();
  });

  it("locks the confirm and back buttons while a cancel request is in flight", () => {
    const onConfirmCancel = vi.fn();
    const { rerender } = render(
      <CancelDialog isActing={false} confirmLabel="상담 취소" onConfirmCancel={onConfirmCancel} />,
    );
    fireEvent.click(screen.getByRole("button", { name: "상담 취소" }));
    rerender(<CancelDialog isActing={true} confirmLabel="상담 취소" onConfirmCancel={onConfirmCancel} />);
    expect(screen.getByRole("button", { name: "처리 중..." })).toBeDisabled();
    expect(screen.getByRole("button", { name: "돌아가기" })).toBeDisabled();
  });
});
