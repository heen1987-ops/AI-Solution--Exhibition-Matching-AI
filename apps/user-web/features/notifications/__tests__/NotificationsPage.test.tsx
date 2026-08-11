/**
 * `/notifications` 인박스 화면 통합 테스트 (API 모킹).
 *
 * 작업 지시(WAVE 2E) 테스트 요구 중 이 파일이 담당하는 것:
 *   - list rendering (unread count 포함)
 *   - mark-read / mark-all-read (성공 + 서버 거부 시 낙관적 갱신 롤백)
 *   - cross-user access denial: 다른 사용자 소유 notification_id 조작 시 서버가
 *     RESOURCE_FORBIDDEN으로 거부하면, 클라이언트는 읽음 상태를 되돌리고 오류를 그대로
 *     보여준다(다른 사용자의 데이터가 있는 것처럼 보이는 대체 콘텐츠를 만들지 않는다).
 *     소유권 판정 자체는 서버 책임이고(api.ts docstring), 클라이언트 계약은 "사용자 ID를
 *     요청에 싣지 않고, 거부를 성공처럼 숨기지 않는다"이다 - 그 계약을 검증한다.
 *   - empty / error 상태.
 */

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiClientError } from "@/lib/api-client";

// `tests/setup.ts`(공용, 이 트랙 소유 범위 밖)가 아직 `@testing-library/react`의 자동
// after-each cleanup을 활성화하지 않아 파일 내 여러 `render()`가 누적된다(다른 feature
// 테스트에서도 동일 패턴 - 공용 설정 이슈). 공용 파일을 건드리는 대신 이 파일 범위에서만
// 명시적으로 등록한다.
afterEach(cleanup);

import NotificationsPage from "@/app/notifications/page";
import type { NotificationItem, NotificationListResponse } from "../types";

vi.mock("@/features/notifications/api", () => ({
  listNotifications: vi.fn(),
  markNotificationRead: vi.fn(),
  markAllNotificationsRead: vi.fn(),
}));

import { listNotifications, markAllNotificationsRead, markNotificationRead } from "../api";

const listMock = vi.mocked(listNotifications);
const markReadMock = vi.mocked(markNotificationRead);
const markAllMock = vi.mocked(markAllNotificationsRead);

function notification(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    notification_id: "n1",
    type: "MEETING_ACCEPTED",
    title: "상담이 확정되었어요",
    summary: "8월 3일 14:00 상담이 확정되었어요.",
    priority: "HIGH",
    read: false,
    created_at: "2026-08-02T05:00:00Z",
    target: { target_type: "MEETING", target_id: "m1" },
    ...overrides,
  };
}

function listResponse(items: NotificationItem[]): NotificationListResponse {
  return { items, next_cursor: null, unread_count: items.filter((i) => !i.read).length };
}

function forbiddenError(): ApiClientError {
  return new ApiClientError({
    code: "RESOURCE_FORBIDDEN",
    message: "이 알림에 접근할 수 없습니다.",
    field_errors: [],
    retryable: false,
    retry_after_seconds: null,
    http_status: 403,
    request_id: "req-1",
  });
}

beforeEach(() => {
  listMock.mockReset();
  markReadMock.mockReset();
  markAllMock.mockReset();
});

describe("NotificationsPage", () => {
  it("renders the list with an unread count derived from the items", async () => {
    listMock.mockResolvedValue(
      listResponse([
        notification({ notification_id: "n1", read: false }),
        notification({ notification_id: "n2", read: true, title: "지난 알림" }),
      ]),
    );
    render(<NotificationsPage />);
    expect(await screen.findByText("상담이 확정되었어요")).toBeInTheDocument();
    expect(screen.getByText("안읽음 1")).toBeInTheDocument();
    expect(screen.getAllByTestId("notification-item")).toHaveLength(2);
  });

  it("shows the empty state when there are no notifications", async () => {
    listMock.mockResolvedValue(listResponse([]));
    render(<NotificationsPage />);
    expect(await screen.findByText("새로운 알림이 없어요.")).toBeInTheDocument();
  });

  it("shows an error state with retry when loading fails", async () => {
    listMock.mockRejectedValueOnce(forbiddenError()).mockResolvedValueOnce(listResponse([]));
    render(<NotificationsPage />);
    expect(await screen.findByRole("alert")).toHaveTextContent("이 알림에 접근할 수 없습니다.");
    fireEvent.click(screen.getByRole("button", { name: "다시 시도" }));
    expect(await screen.findByText("새로운 알림이 없어요.")).toBeInTheDocument();
  });

  it("marks a single notification read optimistically and calls the API with only the id", async () => {
    listMock.mockResolvedValue(listResponse([notification({ notification_id: "n1", read: false })]));
    markReadMock.mockResolvedValue(notification({ notification_id: "n1", read: true }));
    render(<NotificationsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "읽음으로 표시" }));
    await waitFor(() => expect(markReadMock).toHaveBeenCalledWith("n1"));
    // 요청 인자에 사용자 식별자가 실리지 않는다 - 소유권 판정은 서버 세션 몫.
    expect(markReadMock.mock.calls[0]).toHaveLength(1);
    await waitFor(() => expect(screen.queryByText("안읽음 1")).not.toBeInTheDocument());
  });

  it("rolls back and surfaces the server denial when marking another user's notification (id manipulation)", async () => {
    listMock.mockResolvedValue(listResponse([notification({ notification_id: "someone-elses-id", read: false })]));
    markReadMock.mockRejectedValue(forbiddenError());
    render(<NotificationsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "읽음으로 표시" }));
    // 서버 거부(403) -> 성공한 것처럼 남기지 않고 안읽음 상태로 롤백 + 오류 표시.
    expect(await screen.findByRole("alert")).toHaveTextContent("이 알림에 접근할 수 없습니다.");
    expect(screen.getByText("안읽음 1")).toBeInTheDocument();
    expect(screen.getByTestId("notification-item")).toHaveAttribute("data-read", "false");
  });

  it("marks all notifications read and hides the unread affordances", async () => {
    listMock.mockResolvedValue(
      listResponse([
        notification({ notification_id: "n1", read: false }),
        notification({ notification_id: "n2", read: false }),
      ]),
    );
    markAllMock.mockResolvedValue({ updated_count: 2 });
    render(<NotificationsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "모두 읽음으로 표시" }));
    await waitFor(() => expect(markAllMock).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByText(/안읽음 \d/)).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "모두 읽음으로 표시" })).not.toBeInTheDocument();
  });

  it("restores the previous list when mark-all-read is denied by the server", async () => {
    listMock.mockResolvedValue(listResponse([notification({ notification_id: "n1", read: false })]));
    markAllMock.mockRejectedValue(forbiddenError());
    render(<NotificationsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "모두 읽음으로 표시" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("이 알림에 접근할 수 없습니다.");
    expect(screen.getByText("안읽음 1")).toBeInTheDocument();
  });
});
