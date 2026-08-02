"use client";

/**
 * A15 감사로그 (작업 지시 필수 요구사항: 감사로그 표시 화면).
 *
 * audit.audit_log 테이블(apps/api/app/models/consent.py)은 이미 존재하지만 조회 API가
 * 없다 - lib/api-client.ts `listAuditLogs`의 경로는 REST 관례 추정치(TODO). 실패하면
 * 명확한 오류를 보여준다.
 */

import { useCallback, useEffect, useState } from "react";

import { listAuditLogs } from "@/lib/api-client";
import { hasCapability } from "@/lib/auth-state";
import { useSession } from "@/lib/use-session";
import type { AuditLogEntry } from "@/lib/types";
import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";

export default function AuditLogPage() {
  const [session] = useSession();
  const [eventId, setEventId] = useState("");
  const [resourceType, setResourceType] = useState("");
  const [items, setItems] = useState<AuditLogEntry[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    listAuditLogs({ event_id: eventId || undefined, resource_type: resourceType || undefined })
      .then((res) => setItems(res.items))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  }, [eventId, resourceType]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!hasCapability(session.role, "AUDIT_VIEW")) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-xl font-semibold">감사로그</h1>
        <p className="text-sm text-[var(--color-text-muted)]">현재 역할에는 감사로그 조회 권한이 없습니다.</p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">감사로그</h1>
      <p className="text-sm text-[var(--color-text-muted)]">
        업체 승인/반려, 부스 상태변경 등 운영자 활동 이력(§47절 EXHIBITOR_APPROVED,
        EXHIBITOR_REJECTED, BOOTH_STATUS_CHANGED, KIOSK_CONFIG_CHANGED 등).
      </p>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          load();
        }}
        className="flex flex-wrap items-end gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
      >
        <div className="min-w-[220px]">
          <Field label="행사 ID" hint="비워두면 전체">
            <input value={eventId} onChange={(event) => setEventId(event.target.value)} className="input font-mono text-xs" />
          </Field>
        </div>
        <div className="min-w-[200px]">
          <Field label="대상 유형" hint="예: EXHIBITOR, BOOTH">
            <input value={resourceType} onChange={(event) => setResourceType(event.target.value)} className="input" />
          </Field>
        </div>
        <button type="submit" className="tap-target rounded-md border border-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand)]">
          조회
        </button>
      </form>

      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {!loading && error ? <ErrorBanner error={error} onRetry={load} /> : null}
      {!loading && !error && items && items.length === 0 && (
        <p className="text-sm text-[var(--color-text-muted)]">감사로그가 없습니다.</p>
      )}
      {!loading && !error && items && items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--color-surface-muted)] text-xs uppercase text-[var(--color-text-muted)]">
              <tr>
                <th className="px-3 py-2">시각</th>
                <th className="px-3 py-2">행위자</th>
                <th className="px-3 py-2">동작</th>
                <th className="px-3 py-2">대상</th>
                <th className="px-3 py-2">사유</th>
              </tr>
            </thead>
            <tbody>
              {items.map((entry) => (
                <tr key={entry.audit_log_id} className="border-t border-[var(--color-border)] align-top">
                  <td className="px-3 py-2 whitespace-nowrap">
                    {new Date(entry.occurred_at).toLocaleString("ko-KR")}
                  </td>
                  <td className="px-3 py-2">{entry.actor_role ?? "-"} {entry.actor_user_id ? `(${entry.actor_user_id.slice(0, 8)}…)` : ""}</td>
                  <td className="px-3 py-2 font-medium">{entry.action_type}</td>
                  <td className="px-3 py-2">
                    {entry.resource_type} {entry.resource_id.slice(0, 8)}…
                  </td>
                  <td className="px-3 py-2">{entry.reason ?? "-"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
