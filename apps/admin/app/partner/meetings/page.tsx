"use client";

/**
 * 참가업체 포털 - 상담 요청함 (E-02). GET /partner/meetings.
 *
 * 회사 범위(own-company-only)는 프론트 필터가 아니라 백엔드가 Secure/HttpOnly 세션
 * 쿠키의 principal → 소속 참가업체로 강제한다(features/partner-meeting/api.ts 참고) - 이
 * 목록은 그 요청을 그대로 보여줄 뿐이다. (통합 시 재작성: 브라우저에 담당자가 직접
 * staff_id를 입력하던 StaffSessionBar/use-staff-session은 삭제됐다 - SECURITY, 다른 회사
 * 상담함을 열람할 수 있는 결함이었다.)
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";

import { listPartnerMeetings } from "@/features/partner-meeting/api";
import MeetingStatusBadge from "@/features/partner-meeting/components/MeetingStatusBadge";
import type { PartnerMeetingListItem } from "@/features/partner-meeting/types";
import { useSession } from "@/lib/use-session";

const STATUS_FILTERS: { value: string; label: string }[] = [
  { value: "", label: "전체" },
  { value: "requested", label: "요청됨" },
  { value: "accepted", label: "확정" },
  { value: "counter_proposed", label: "시간 재제안" },
  { value: "completed", label: "완료" },
  { value: "rejected", label: "반려" },
  { value: "cancelled", label: "취소" },
  { value: "no_show", label: "노쇼" },
];

export default function PartnerMeetingsInboxPage() {
  const [session] = useSession();
  const [status, setStatus] = useState("");
  const [items, setItems] = useState<PartnerMeetingListItem[] | null>(null);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(
    (cursor?: string) => {
      setLoading(true);
      setError(null);
      listPartnerMeetings({ status: status || undefined, cursor })
        .then((res) => {
          setItems((prev) => (cursor ? [...(prev ?? []), ...res.items] : res.items));
          setNextCursor(res.next_cursor);
        })
        .catch((err) => setError(err))
        .finally(() => setLoading(false));
    },
    [status],
  );

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [status]);

  return (
    <div className="flex flex-col gap-4">
      <div>
        <h1 className="text-xl font-semibold">상담 요청함</h1>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          우리 회사{session.displayName ? `(${session.displayName})` : ""}로 들어온 상담 요청만
          표시됩니다. 확정(accepted) 전에는 바이어 연락처가 표시되지 않습니다.
        </p>
      </div>

      <div className="flex flex-wrap gap-2" role="group" aria-label="상태 필터">
        {STATUS_FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setStatus(f.value)}
            aria-pressed={status === f.value}
            className={`tap-target rounded-full border px-3 py-1.5 text-xs font-medium ${
              status === f.value
                ? "border-[var(--color-brand)] bg-[var(--color-brand)] text-[var(--color-brand-contrast)]"
                : "border-[var(--color-border)] text-[var(--color-text-muted)]"
            }`}
          >
            {f.label}
          </button>
        ))}
      </div>

      {loading && !items && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {error ? <ErrorBanner error={error} onRetry={() => load()} /> : null}

      {items && items.length === 0 && !loading && (
        <p className="text-sm text-[var(--color-text-muted)]">조건에 맞는 상담 요청이 없습니다.</p>
      )}

      {items && items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--color-surface-muted)] text-xs uppercase text-[var(--color-text-muted)]">
              <tr>
                <th className="px-3 py-2">상태</th>
                <th className="px-3 py-2">상담주제</th>
                <th className="px-3 py-2">희망/확정 시간</th>
                <th className="px-3 py-2">신규</th>
                <th className="px-3 py-2">요청일</th>
                <th className="px-3 py-2 text-right">동작</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.meeting_id} className="border-t border-[var(--color-border)]">
                  <td className="px-3 py-2">
                    <MeetingStatusBadge status={item.status} />
                  </td>
                  <td className="px-3 py-2">{item.topic_code ?? "-"}</td>
                  <td className="px-3 py-2 text-xs">
                    {item.confirmed_start
                      ? `${new Date(item.confirmed_start).toLocaleString("ko-KR")} (확정)`
                      : item.candidate_slots[0]
                        ? `${new Date(item.candidate_slots[0].start_at).toLocaleString("ko-KR")} (희망)`
                        : "-"}
                  </td>
                  <td className="px-3 py-2">
                    {!item.viewed_at && (
                      <span className="rounded-full bg-[var(--color-brand)] px-2 py-0.5 text-[10px] font-semibold text-[var(--color-brand-contrast)]">
                        NEW
                      </span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs">
                    {new Date(item.created_at).toLocaleDateString("ko-KR")}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Link
                      href={`/partner/meetings/${item.meeting_id}`}
                      className="tap-target text-[var(--color-brand)] underline"
                    >
                      상세보기
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {nextCursor && (
        <button
          type="button"
          onClick={() => load(nextCursor)}
          disabled={loading}
          className="tap-target self-start rounded-md border border-[var(--color-border)] px-4 py-2 text-sm disabled:opacity-50"
        >
          더 보기
        </button>
      )}
    </div>
  );
}
