import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EmptyState, ErrorNotice, LoadingSkeleton } from "@/components/StateViews";

describe("공용 로딩/빈결과/오류 상태 컴포넌트", () => {
  it("EmptyState는 role=status로 안내 문구를 노출한다", () => {
    render(<EmptyState title="결과가 없습니다" description="다른 조건을 시도하세요" />);

    expect(screen.getByRole("status")).toHaveTextContent("결과가 없습니다");
    expect(screen.getByText("다른 조건을 시도하세요")).toBeInTheDocument();
  });

  it("LoadingSkeleton은 role=status로 로딩 상태를 알린다", () => {
    render(<LoadingSkeleton rows={2} />);

    expect(screen.getAllByRole("status")).toHaveLength(1);
  });

  it("ErrorNotice는 role=alert이며 재시도 버튼을 누르면 onRetry가 호출된다", async () => {
    const user = userEvent.setup();
    const onRetry = vi.fn();
    render(<ErrorNotice title="오류 발생" onRetry={onRetry} />);

    expect(screen.getByRole("alert")).toHaveTextContent("오류 발생");
    await user.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });
});
