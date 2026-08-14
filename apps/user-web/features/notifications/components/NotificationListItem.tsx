"use client";

/**
 * 알림함(`/notifications`) 목록 항목.
 *
 * 근거: 작업 지시 GOAL - "unread count, type, title, summary, timestamp, read state,
 * priority, and a link that navigates to the right in-app destination... never render an
 * arbitrary external URL from a notification payload (validate it is an internal route
 * before navigating; treat notification body/link fields as untrusted data)".
 *
 * 내비게이션은 `../target.ts`의 화이트리스트를 통과한 경로만 `next/link`의 `href`로 쓴다 -
 * 서버가 준 어떤 URL/문자열도 직접 렌더링하지 않는다. 대상이 삭제됐거나(`target_deleted`)
 * 화이트리스트에 없는 유형이면 링크 대신 안내 문구를 보여준다("깨진 링크" 대신).
 */

import Link from "next/link";

import { formatNotificationTimestamp, notificationTypeLabel } from "../logic";
import { resolveNotificationTarget } from "../target";
import type { NotificationItem } from "../types";
import PriorityBadge from "./PriorityBadge";

export interface NotificationListItemProps {
  notification: NotificationItem;
  /** 읽음 처리 요청(단건). 실패 시 호출자가 낙관적 업데이트를 되돌린다. */
  onMarkRead: (notificationId: string) => void;
  /** 이 항목에 대해 읽음 처리 요청이 진행 중이면 true - 중복 클릭을 막는다. */
  pending?: boolean;
}

export default function NotificationListItem({ notification, onMarkRead, pending = false }: NotificationListItemProps) {
  const href = resolveNotificationTarget(notification.target);
  const targetDeleted = notification.target?.target_deleted === true;

  function handleLinkClick() {
    if (!notification.read) onMarkRead(notification.notification_id);
  }

  return (
    <li
      data-testid="notification-item"
      data-read={notification.read}
      className="flex flex-col gap-2 rounded-lg border p-3 text-sm"
      style={{
        borderColor: "var(--color-border)",
        backgroundColor: notification.read ? "var(--color-surface)" : "var(--color-bg)",
      }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2">
          {/* 13.2절: 색상만으로 상태를 구분하지 않는다 - 점(색) + 텍스트(sr-only)를 함께 쓴다. */}
          <span
            aria-hidden="true"
            className="inline-block h-2 w-2 shrink-0 rounded-full"
            style={{ backgroundColor: notification.read ? "transparent" : "var(--color-brand)" }}
          />
          <span className="sr-only">{notification.read ? "읽음" : "안읽음"}</span>
          <span className="text-xs font-medium" style={{ color: "var(--color-text-muted)" }}>
            {notificationTypeLabel(notification.type)}
          </span>
        </div>
        <PriorityBadge priority={notification.priority} />
      </div>

      <div className="flex flex-col gap-1">
        <span className="font-semibold">{notification.title}</span>
        <p style={{ color: "var(--color-text-muted)" }}>{notification.summary}</p>
        <time dateTime={notification.created_at} className="text-xs" style={{ color: "var(--color-text-muted)" }}>
          {formatNotificationTimestamp(notification.created_at)}
        </time>
      </div>

      {targetDeleted ? (
        <p role="note" className="text-xs" style={{ color: "var(--color-text-muted)" }}>
          연결된 항목을 더 이상 찾을 수 없어요. 삭제되었거나 만료되었을 수 있어요.
        </p>
      ) : null}

      <div className="flex items-center gap-2">
        {!targetDeleted && href ? (
          <Link
            href={href}
            onClick={handleLinkClick}
            className="tap-target inline-flex items-center rounded-lg border px-4 text-sm font-semibold"
            style={{ borderColor: "var(--color-border)" }}
          >
            자세히 보기
          </Link>
        ) : null}
        {!notification.read ? (
          <button
            type="button"
            disabled={pending}
            onClick={() => onMarkRead(notification.notification_id)}
            className="tap-target inline-flex items-center rounded-lg border px-4 text-sm"
            style={{ borderColor: "var(--color-border)", color: "var(--color-text-muted)" }}
          >
            읽음으로 표시
          </button>
        ) : null}
      </div>
    </li>
  );
}
