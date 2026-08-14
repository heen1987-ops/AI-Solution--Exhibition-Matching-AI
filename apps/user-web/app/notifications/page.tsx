"use client";

/**
 * 알림함 (`/notifications`).
 *
 * 근거: 작업 지시(WAVE 2E USER-WEB-NOTIFICATION) GOAL - "unread count, type, title,
 * summary, timestamp, read state, priority, and a link that navigates to the right in-app
 * destination... Empty/error/expired/target-deleted UI states handled gracefully."
 *
 * `apps/user-web/lib/api-client.ts`/`lib/types.ts`는 편집 범위 밖이라 이 화면은
 * `features/notifications/api.ts`·`types.ts`(로컬 정본, 백엔드 계약이 아직 없어 "가정
 * 계약"임 - 근거는 `features/notifications/types.ts` docstring 참고)를 쓴다.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { ApiClientError } from "@/lib/api-client";

import { listNotifications, markAllNotificationsRead, markNotificationRead } from "@/features/notifications/api";
import NotificationListItem from "@/features/notifications/components/NotificationListItem";
import { countUnread, markAllItemsRead, markItemRead } from "@/features/notifications/logic";
import type { NotificationItem } from "@/features/notifications/types";

export default function NotificationsPage() {
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [pendingIds, setPendingIds] = useState<Set<string>>(new Set());
  const [markingAll, setMarkingAll] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await listNotifications();
      setNotifications(result.items);
    } catch (err) {
      setLoadError(err instanceof ApiClientError ? err.message : "알림을 불러오지 못했습니다.");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  const handleMarkRead = useCallback(
    async (notificationId: string) => {
      if (pendingIds.has(notificationId)) return;
      const target = notifications.find((item) => item.notification_id === notificationId);
      if (!target || target.read) return;

      setActionError(null);
      setPendingIds((prev) => new Set(prev).add(notificationId));
      setNotifications((prev) => markItemRead(prev, notificationId));

      try {
        await markNotificationRead(notificationId);
      } catch (err) {
        // 서버가 거부하면(예: 다른 사용자 소유 알림 ID 조작, 만료 등) 화면에 성공한 것처럼
        // 남겨두지 않고 원래 안읽음 상태로 되돌린다.
        setNotifications((prev) =>
          prev.map((item) => (item.notification_id === notificationId ? { ...item, read: false } : item)),
        );
        setActionError(err instanceof ApiClientError ? err.message : "읽음 처리에 실패했습니다.");
      } finally {
        setPendingIds((prev) => {
          const next = new Set(prev);
          next.delete(notificationId);
          return next;
        });
      }
    },
    [notifications, pendingIds],
  );

  const handleMarkAll = useCallback(async () => {
    if (markingAll) return;
    const previous = notifications;
    if (countUnread(previous) === 0) return;

    setActionError(null);
    setMarkingAll(true);
    setNotifications(markAllItemsRead(previous));

    try {
      await markAllNotificationsRead();
    } catch (err) {
      setNotifications(previous);
      setActionError(err instanceof ApiClientError ? err.message : "모두 읽음 처리에 실패했습니다.");
    } finally {
      setMarkingAll(false);
    }
  }, [markingAll, notifications]);

  if (loading) {
    return (
      <div className="mx-auto max-w-screen-content px-4 py-6">
        <p role="status" aria-live="polite" style={{ color: "var(--color-text-muted)" }}>
          불러오는 중...
        </p>
      </div>
    );
  }

  if (loadError) {
    return (
      <div className="mx-auto flex max-w-screen-content flex-col gap-3 px-4 py-6">
        <p role="alert" style={{ color: "var(--color-danger)" }}>
          {loadError}
        </p>
        <button
          type="button"
          onClick={() => void load()}
          className="tap-target self-start rounded-lg border px-4 py-2 text-sm"
          style={{ borderColor: "var(--color-border)" }}
        >
          다시 시도
        </button>
      </div>
    );
  }

  const unreadCount = countUnread(notifications);

  return (
    <div className="mx-auto flex max-w-screen-content flex-col gap-4 px-4 py-6">
      <header className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-bold">
            알림
            {unreadCount > 0 ? (
              <span className="ml-2 text-sm font-semibold" style={{ color: "var(--color-brand)" }}>
                안읽음 {unreadCount}
              </span>
            ) : null}
          </h1>
          <Link href="/notifications/preferences" className="text-sm underline" style={{ color: "var(--color-text-muted)" }}>
            알림 설정
          </Link>
        </div>
        {unreadCount > 0 ? (
          <button
            type="button"
            disabled={markingAll}
            onClick={() => void handleMarkAll()}
            className="tap-target self-start rounded-lg border px-3 text-sm font-semibold"
            style={{ borderColor: "var(--color-border)" }}
          >
            모두 읽음으로 표시
          </button>
        ) : null}
      </header>

      {actionError ? (
        <p role="alert" className="text-sm" style={{ color: "var(--color-danger)" }}>
          {actionError}
        </p>
      ) : null}

      {notifications.length === 0 ? (
        <p style={{ color: "var(--color-text-muted)" }}>새로운 알림이 없어요.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {notifications.map((notification) => (
            <NotificationListItem
              key={notification.notification_id}
              notification={notification}
              onMarkRead={(id) => void handleMarkRead(id)}
              pending={pendingIds.has(notification.notification_id)}
            />
          ))}
        </ul>
      )}
    </div>
  );
}
