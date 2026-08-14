/**
 * 알림 화면 모바일 반응형 스모크 테스트.
 *
 * `features/meeting/__tests__/mobile-smoke.test.tsx`와 같은 접근: jsdom에는 레이아웃
 * 엔진이 없어 픽셀 검증은 불가능하므로, 최소한 "좁은 뷰포트(360px)에서도 알림 화면의
 * 핵심 조각이 예외 없이 렌더링되고, 탭 가능한 액션이 44px 터치 영역 유틸리티(`tap-target`,
 * `globals.css`)를 쓰며, 고정 픽셀 폭을 인라인으로 강제하지 않는지"를 확인한다.
 */

import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// `tests/setup.ts`(공용, 이 트랙 소유 범위 밖)가 아직 `@testing-library/react`의 자동
// after-each cleanup을 활성화하지 않아 파일 내 여러 `render()`가 누적된다(다른 feature
// 테스트에서도 동일 패턴 - 공용 설정 이슈). 공용 파일을 건드리는 대신 이 파일 범위에서만
// 명시적으로 등록한다.
afterEach(cleanup);

import PreferenceToggle from "@/features/notification-preferences/components/PreferenceToggle";
import NotificationListItem from "../components/NotificationListItem";
import PriorityBadge from "../components/PriorityBadge";
import type { NotificationItem } from "../types";

function notification(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    notification_id: "n1",
    type: "EVENT_DAY_REMINDER",
    title: "행사 당일 안내",
    summary: "오늘 14:00에 예정된 상담이 있어요.",
    priority: "NORMAL",
    read: false,
    created_at: "2026-08-02T05:00:00Z",
    target: { target_type: "MEETING", target_id: "m1" },
    ...overrides,
  };
}

describe("mobile-responsive smoke test (360px viewport)", () => {
  const originalWidth = window.innerWidth;

  beforeEach(() => {
    Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: 360 });
    window.dispatchEvent(new Event("resize"));
  });

  afterEach(() => {
    Object.defineProperty(window, "innerWidth", { writable: true, configurable: true, value: originalWidth });
  });

  it("renders a notification list item without crashing and keeps its actions tappable", () => {
    render(
      <ul>
        <NotificationListItem notification={notification()} onMarkRead={vi.fn()} />
      </ul>,
    );
    expect(screen.getByRole("link", { name: "자세히 보기" }).className).toContain("tap-target");
    expect(screen.getByRole("button", { name: "읽음으로 표시" }).className).toContain("tap-target");
  });

  it("renders the list item without inline fixed pixel widths that would overflow a narrow screen", () => {
    render(
      <ul>
        <NotificationListItem notification={notification()} onMarkRead={vi.fn()} />
      </ul>,
    );
    const item = screen.getByTestId("notification-item");
    expect(item.getAttribute("style") ?? "").not.toMatch(/width:\s*\d/);
  });

  it("renders the priority badge without layout-only assumptions", () => {
    render(<PriorityBadge priority="URGENT" />);
    const badge = screen.getByText("긴급");
    expect(badge.getAttribute("style") ?? "").not.toMatch(/width:\s*\d/);
  });

  it("renders a preference toggle as a tap target on a narrow viewport", () => {
    render(<PreferenceToggle label="추천 도착 - 앱 내 알림" checked onChange={() => {}} />);
    expect(screen.getByRole("switch", { name: "추천 도착 - 앱 내 알림" }).className).toContain("tap-target");
  });
});
