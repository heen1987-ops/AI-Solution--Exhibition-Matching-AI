"use client";

/**
 * 상담(미팅) 운영 뷰 (WAVE 2C ADMIN-BUYER 트랙).
 *
 * 작업 지시: "operations view only, not a rebuild of the meeting flow itself" - 상담 상태
 * 전이(수락/거절/변경제안/취소)는 이미 `apps/api/app/api/v1/routers/meetings.py`의
 * 바이어/참가업체 전용 API가 처리하며, 이 화면은 그 흐름을 다시 구현하지 않고 운영자
 * 조회 전용으로만 동작한다(쓰기 동작 없음).
 *
 * 표시 항목: request status, exhibitor, buyer(업무상 식별자만), topic, preferred/confirmed
 * time, dispute/error state (작업 지시 그대로).
 *
 * PII 방어 (작업 지시 필수 요구사항 "no raw contact-info leak", "the backend call you make
 * must already be scoped"):
 *   1차 방어선 - 이 화면이 호출하는 `GET /admin/meetings/ops` 계약 자체에 연락처 필드가
 *   없다(features/buyer-verification/types.ts의 AdminMeetingOpsItem 참고). 이 화면은
 *   `/partner/meetings/{id}/buyer-summary`처럼 연락처를 조건부로 공개하는 실제 구현된
 *   엔드포인트를 절대 호출하지 않는다(그 엔드포인트는 참가업체 담당자 전용이지 운영자
 *   전용이 아니다).
 *   2차 방어선 - redactPotentialContactInfo로 표시 직전에 한 번 더 이메일/전화번호로 보이는
 *   문자열을 걸러낸다.
 *
 * 역할 게이트: EVENT_ADMIN·DATA_REVIEWER만 조회할 수 있다(바이어 검증 큐와 동일한 정책 -
 * features/buyer-verification/logic.ts의 canViewMeetingOps).
 */

import { useCallback, useEffect, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";
import { listAdminMeetingOps } from "@/features/buyer-verification/api";
import { canViewMeetingOps, redactPotentialContactInfo } from "@/features/buyer-verification/logic";
import type { AdminMeetingOpsItem } from "@/features/buyer-verification/types";
import { useSession } from "@/lib/use-session";

const MEETING_STATUSES = [
  "draft",
  "requested",
  "accepted",
  "counter_proposed",
  "rejected",
  "cancelled",
  "completed",
  "no_show",
] as const;

function formatDateTime(value: string | null): string {
  if (!value) return "-";
  return new Date(value).toLocaleString("ko-KR", { dateStyle: "short", timeStyle: "short" });
}

export default function MeetingsOpsPage() {
  const [session] = useSession();
  const allowed = canViewMeetingOps(session.role);

  const [eventId, setEventId] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [items, setItems] = useState<AdminMeetingOpsItem[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  const search = useCallback(() => {
    if (!allowed) return;
    setLoading(true);
    setError(null);
    listAdminMeetingOps({
      event_id: eventId || undefined,
      status: statusFilter || undefined,
    })
      .then((res) => setItems(res.items))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [eventId, statusFilter, allowed]);

  useEffect(() => {
    search();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (!allowed) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-xl font-semibold">상담 운영 현황</h1>
        <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-text-muted)]">
          현재 역할({session.role})에는 상담 운영 현황 조회 권한이 없습니다. 행사 운영자
          (EVENT_ADMIN) 또는 데이터 검수자(DATA_REVIEWER)로 전환해 주세요.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">상담 운영 현황</h1>
        <p className="text-xs text-[var(--color-text-muted)]">
          조회 전용입니다. 상담 수락·거절·취소는 바이어/참가업체 화면에서 처리됩니다.
        </p>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          search();
        }}
        className="flex flex-wrap items-end gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
      >
        <div className="min-w-[220px]">
          <Field label="행사 ID" hint="비워두면 전체 행사">
            <input
              value={eventId}
              onChange={(event) => setEventId(event.target.value)}
              className="input font-mono text-xs"
              placeholder="UUID"
            />
          </Field>
        </div>
        <div className="min-w-[200px]">
          <Field label="상담상태 필터">
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value)}
              className="input"
            >
              <option value="">전체</option>
              {MEETING_STATUSES.map((status) => (
                <option key={status} value={status}>
                  {status}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <button
          type="submit"
          className="tap-target rounded-md border border-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand)]"
        >
          검색
        </button>
      </form>

      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {!loading && error ? <ErrorBanner error={error} onRetry={search} /> : null}

      {!loading && !error && items && items.length === 0 && (
        <p className="text-sm text-[var(--color-text-muted)]">조건에 맞는 상담이 없습니다.</p>
      )}

      {!loading && !error && items && items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--color-surface-muted)] text-xs uppercase text-[var(--color-text-muted)]">
              <tr>
                <th className="px-3 py-2">상태</th>
                <th className="px-3 py-2">참가업체</th>
                <th className="px-3 py-2">바이어</th>
                <th className="px-3 py-2">주제</th>
                <th className="px-3 py-2">희망 시간</th>
                <th className="px-3 py-2">확정 시간</th>
                <th className="px-3 py-2">주의 필요</th>
                <th className="px-3 py-2">최근 갱신</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.meeting_id} className="border-t border-[var(--color-border)]">
                  <td className="px-3 py-2 font-mono text-xs">{item.status}</td>
                  <td className="px-3 py-2">
                    {redactPotentialContactInfo(item.exhibitor_name ?? item.exhibitor_id)}
                  </td>
                  <td className="px-3 py-2">{redactPotentialContactInfo(item.buyer_display_ref)}</td>
                  <td className="px-3 py-2">{item.topic_code ?? "-"}</td>
                  <td className="px-3 py-2">{item.preferred_time_summary ?? "-"}</td>
                  <td className="px-3 py-2">
                    {item.confirmed_start
                      ? `${formatDateTime(item.confirmed_start)} ~ ${formatDateTime(item.confirmed_end)}`
                      : "-"}
                  </td>
                  <td className="px-3 py-2">
                    {item.attention === "NEEDS_ATTENTION" ? (
                      <span className="rounded-full bg-[var(--color-danger-bg)] px-2 py-0.5 text-xs font-medium text-[var(--color-danger)]">
                        확인 필요
                      </span>
                    ) : (
                      <span className="text-xs text-[var(--color-text-muted)]">-</span>
                    )}
                  </td>
                  <td className="px-3 py-2">{formatDateTime(item.updated_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
