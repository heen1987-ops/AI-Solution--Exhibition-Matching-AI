import { describe, expect, it } from "vitest";

import {
  countUnread,
  formatNotificationTimestamp,
  markAllItemsRead,
  markItemRead,
  notificationTypeLabel,
} from "../logic";
import type { NotificationItem } from "../types";

function notification(overrides: Partial<NotificationItem> = {}): NotificationItem {
  return {
    notification_id: "n1",
    type: "RECOMMENDATION_READY",
    title: "새 추천이 도착했어요",
    summary: "취향에 맞는 업체 3곳을 찾았어요.",
    priority: "NORMAL",
    read: false,
    created_at: "2026-08-02T05:00:00Z",
    target: { target_type: "RECOMMENDATION", target_id: null },
    ...overrides,
  };
}

describe("notificationTypeLabel", () => {
  it("returns the Korean label for a known type", () => {
    expect(notificationTypeLabel("MEETING_ACCEPTED")).toBe("상담 확정");
  });

  it("falls back to the raw code for an unrecognized type instead of hiding it", () => {
    expect(notificationTypeLabel("FUTURE_TYPE_NOT_YET_MAPPED")).toBe("FUTURE_TYPE_NOT_YET_MAPPED");
  });
});

describe("formatNotificationTimestamp", () => {
  it("formats a valid ISO timestamp without throwing", () => {
    expect(formatNotificationTimestamp("2026-08-02T05:00:00Z").length).toBeGreaterThan(0);
  });

  it("falls back to the raw string for an invalid date instead of crashing or showing blank", () => {
    expect(formatNotificationTimestamp("not-a-date")).toBe("not-a-date");
  });
});

describe("markItemRead", () => {
  it("marks only the matching item as read and leaves the rest untouched", () => {
    const items = [notification({ notification_id: "n1" }), notification({ notification_id: "n2" })];
    const result = markItemRead(items, "n1");
    expect(result.find((i) => i.notification_id === "n1")?.read).toBe(true);
    expect(result.find((i) => i.notification_id === "n2")?.read).toBe(false);
  });

  it("does not mutate the original array (immutable update)", () => {
    const items = [notification({ notification_id: "n1" })];
    const result = markItemRead(items, "n1");
    expect(items[0].read).toBe(false);
    expect(result).not.toBe(items);
  });
});

describe("markAllItemsRead", () => {
  it("marks every item read", () => {
    const items = [
      notification({ notification_id: "n1", read: false }),
      notification({ notification_id: "n2", read: true }),
    ];
    const result = markAllItemsRead(items);
    expect(result.every((i) => i.read)).toBe(true);
  });
});

describe("countUnread", () => {
  it("counts only unread items", () => {
    const items = [
      notification({ notification_id: "n1", read: false }),
      notification({ notification_id: "n2", read: true }),
      notification({ notification_id: "n3", read: false }),
    ];
    expect(countUnread(items)).toBe(2);
  });

  it("returns 0 for an empty list", () => {
    expect(countUnread([])).toBe(0);
  });
});
