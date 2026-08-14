"use client";

/**
 * 이벤트 메시지 목록 (ADMIN-NOTIFICATION, WAVE 2E).
 *
 * URL: /event-messages?event_id={eventId}
 *   - event_id가 없으면 조회 자체가 불가능함을 정직하게 안내한다(가짜 빈 목록 금지).
 *
 * 역할 게이트: `EVENT_MANAGE` capability(EVENT_ADMIN 역할)만 접근 가능 - 이 화면은 회의/상담
 * 상태 알림이 아니라 운영자가 직접 작성하는 캠페인 도구이므로 참가업체·바이어 계정에는
 * 노출되지 않는다. 이 트랙의 owned path(`apps/admin/lib/auth-state.ts`는 owned path 밖)에는
 * 전용 capability를 추가할 수 없어 기존 `EVENT_MANAGE`(행사 운영자 전용)를 재사용한다 -
 * 백엔드도 동일하게 OPERATOR/ADMIN 역할만 허용한다
 * (`apps/api/app/api/v1/routers/event_message.py::_require_operator_role`).
 */

import { useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import RoleGate from "@/components/RoleGate";

import { listEventMessages } from "@/features/event-message/api";
import WorkflowStatusBadge from "@/features/event-message/components/WorkflowStatusBadge";
import {
  MESSAGE_STATUSES,
  MESSAGE_TYPE_LABEL_KO,
  type EventMessage,
  type MessageStatus,
} from "@/features/event-message/types";

export default function EventMessagesPage() {
  return (
    <RoleGate capability="EVENT_MANAGE" fallback={<NoAccessNotice />}>
      <ListBody />
    </RoleGate>
  );
}

function NoAccessNotice() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">이벤트 메시지</h1>
      <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-text-muted)]">
        현재 역할에는 이벤트 메시지 작성 권한이 없습니다.
      </p>
    </div>
  );
}

function ListBody() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const eventId = searchParams.get("event_id") ?? "";

  const [items, setItems] = useState<EventMessage[] | null>(null);
  const [statusFilter, setStatusFilter] = useState<MessageStatus | "">("");
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    if (!eventId) return;
    setLoading(true);
    setError(null);
    listEventMessages(eventId, statusFilter || undefined)
      .then((res) => setItems(res.items))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  }, [eventId, statusFilter]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">이벤트 메시지</h1>
        {eventId && (
          <button
            type="button"
            onClick={() => router.push(`/event-messages/new?event_id=${encodeURIComponent(eventId)}`)}
            className="tap-target rounded-md bg-[var(--color-brand)] px-3 py-1.5 text-xs font-semibold text-white"
          >
            새 메시지 작성
          </button>
        )}
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
          행사 ID
          <input
            aria-label="행사 ID"
            className="input"
            value={eventId}
            onChange={(e) => {
              const params = new URLSearchParams(searchParams.toString());
              if (e.target.value) params.set("event_id", e.target.value);
              else params.delete("event_id");
              router.replace(`/event-messages?${params.toString()}`);
            }}
            placeholder="event_id"
          />
        </label>
        <label className="flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
          상태 필터
          <select
            aria-label="상태 필터"
            className="input"
            value={statusFilter}
            onChange={(e) => setStatusFilter(e.target.value as MessageStatus | "")}
          >
            <option value="">전체</option>
            {MESSAGE_STATUSES.map((s) => (
              <option key={s} value={s}>
                {s}
              </option>
            ))}
          </select>
        </label>
      </div>

      {!eventId && (
        <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-text-muted)]">
          행사 ID를 입력하면 해당 행사의 이벤트 메시지 목록을 조회할 수 있습니다.
        </p>
      )}
      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {!loading && error != null && <ErrorBanner error={error} onRetry={load} />}
      {!loading && error == null && items && (
        <table className="w-full overflow-x-auto text-sm">
          <thead>
            <tr className="border-b border-[var(--color-border)] text-left text-xs text-[var(--color-text-muted)]">
              <th className="py-2">제목</th>
              <th className="py-2">유형</th>
              <th className="py-2">상태</th>
              <th className="py-2">예약 시각</th>
              <th className="py-2" />
            </tr>
          </thead>
          <tbody>
            {items.map((item) => (
              <tr key={item.event_message_id} className="border-b border-[var(--color-border)]">
                <td className="py-2">{item.title}</td>
                <td className="py-2 text-xs">{MESSAGE_TYPE_LABEL_KO[item.message_type]}</td>
                <td className="py-2">
                  <WorkflowStatusBadge status={item.status} />
                </td>
                <td className="py-2 text-xs">
                  {item.scheduled_at ? new Date(item.scheduled_at).toLocaleString("ko-KR") : "-"}
                </td>
                <td className="py-2 text-right">
                  <button
                    type="button"
                    onClick={() => router.push(`/event-messages/${item.event_message_id}`)}
                    className="tap-target text-xs font-medium text-[var(--color-brand)] hover:underline"
                  >
                    열기
                  </button>
                </td>
              </tr>
            ))}
            {items.length === 0 && (
              <tr>
                <td colSpan={5} className="py-4 text-center text-xs text-[var(--color-text-muted)]">
                  이벤트 메시지가 없습니다.
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
