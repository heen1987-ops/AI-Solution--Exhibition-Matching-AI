import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import NotificationListItem from "../components/NotificationListItem";
import type { NotificationItem } from "../types";

// `tests/setup.ts`(앱 공용, 이 트랙 소유 범위 밖)가 `@testing-library/react`의 자동
// after-each cleanup을 활성화하는 전역(`globals: true` 또는 동등 설정)을 아직 등록하지
// 않아, 같은 파일 안의 여러 `render()` 호출이 누적되어 "여러 요소가 매칭됨" 오류를
// 일으킨다(다른 feature의 테스트에서도 동일 패턴 확인 - 이 트랙만의 문제가 아님). 공용
// 설정 파일을 이 트랙 범위 밖에서 수정하는 대신, 이 파일이 소유한 테스트에서만 명시적으로
// cleanup을 등록해 격리한다.
afterEach(cleanup);

function notification(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    notification_id: "n1",
    type: "MEETING_ACCEPTED",
    title: "상담이 확정되었어요",
    summary: "8월 3일 14:00에 A업체와 상담이 확정되었어요.",
    priority: "HIGH",
    read: false,
    created_at: "2026-08-02T05:00:00Z",
    target: { target_type: "MEETING", target_id: "m1" },
    ...overrides,
  };
}

describe("NotificationListItem", () => {
  it("renders type, title, summary, timestamp and priority", () => {
    render(
      <ul>
        <NotificationListItem notification={notification()} onMarkRead={vi.fn()} />
      </ul>,
    );
    expect(screen.getByText("상담 확정")).toBeInTheDocument();
    expect(screen.getByText("상담이 확정되었어요")).toBeInTheDocument();
    expect(screen.getByText("8월 3일 14:00에 A업체와 상담이 확정되었어요.")).toBeInTheDocument();
    expect(screen.getByText("중요")).toBeInTheDocument();
  });

  it("marks unread state via text, not color alone, and shows a mark-read button", () => {
    render(
      <ul>
        <NotificationListItem notification={notification({ read: false })} onMarkRead={vi.fn()} />
      </ul>,
    );
    expect(screen.getByText("안읽음")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "읽음으로 표시" })).toBeInTheDocument();
  });

  it("hides the mark-read button once already read", () => {
    render(
      <ul>
        <NotificationListItem notification={notification({ read: true })} onMarkRead={vi.fn()} />
      </ul>,
    );
    expect(screen.getByText("읽음")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "읽음으로 표시" })).not.toBeInTheDocument();
  });

  it("renders an internal-route link only for an allowlisted, non-deleted target", () => {
    render(
      <ul>
        <NotificationListItem notification={notification()} onMarkRead={vi.fn()} />
      </ul>,
    );
    const link = screen.getByRole("link", { name: "자세히 보기" });
    expect(link).toHaveAttribute("href", "/meetings/m1");
  });

  it("never renders a link for a target the server did not put on the allowlist (no arbitrary URL fallback)", () => {
    render(
      <ul>
        <NotificationListItem
          notification={notification({ target: { target_type: "EXTERNAL_LINK", target_id: "https://evil.example" } })}
          onMarkRead={vi.fn()}
        />
      </ul>,
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("shows a safe explanatory message instead of a broken link when the target was deleted", () => {
    render(
      <ul>
        <NotificationListItem
          notification={notification({ target: { target_type: "MEETING", target_id: "m1", target_deleted: true } })}
          onMarkRead={vi.fn()}
        />
      </ul>,
    );
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
    expect(screen.getByRole("note").textContent).toMatch(/더 이상 찾을 수 없어요/);
  });

  it("calls onMarkRead with the notification id when the mark-read button is clicked", () => {
    const onMarkRead = vi.fn();
    render(
      <ul>
        <NotificationListItem notification={notification({ read: false })} onMarkRead={onMarkRead} />
      </ul>,
    );
    // fireEvent 사용 - `@testing-library/user-event`는 이 앱의 선언된 devDependency가 아니다
    // (다른 feature 테스트들과 동일한 패턴).
    fireEvent.click(screen.getByRole("button", { name: "읽음으로 표시" }));
    expect(onMarkRead).toHaveBeenCalledWith("n1");
  });

  it("also marks read as a side effect of following the link (best-effort read receipt)", () => {
    const onMarkRead = vi.fn();
    render(
      <ul>
        <NotificationListItem notification={notification({ read: false })} onMarkRead={onMarkRead} />
      </ul>,
    );
    fireEvent.click(screen.getByRole("link", { name: "자세히 보기" }));
    expect(onMarkRead).toHaveBeenCalledWith("n1");
  });
});
