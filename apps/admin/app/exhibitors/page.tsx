"use client";

/**
 * A03 업체 목록. §43절. 승인상태 필터 지원(작업 지시 필수 요구사항).
 *
 * 목록 자체(`GET /admin/exhibitors/review`)는 아직 백엔드에 없다(lib/api-client.ts TODO,
 * BACKEND-007). 그 상태를 숨기지 않고 그대로 보여주되, 실제로 동작하는 대안 경로
 * (`GET /exhibitors/{id}/profile` - apps/api/app/api/v1/routers/partner.py, 실구현됨)로
 * 업체 ID를 알고 있을 때 개별 조회는 지금도 가능하다는 것을 함께 제공한다.
 */

import Link from "next/link";
import { useCallback, useEffect, useState } from "react";

import { listExhibitorsForReview } from "@/lib/api-client";
import { useSession } from "@/lib/use-session";
import type { AdminExhibitorListItem, ExhibitorReviewStatus } from "@/lib/types";
import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";
import RoleGate from "@/components/RoleGate";
import StatusBadge from "@/components/StatusBadge";

const REVIEW_STATUSES: ExhibitorReviewStatus[] = [
  "DRAFT",
  "SUBMITTED",
  "AI_EXTRACTED",
  "EXHIBITOR_REVIEWED",
  "OPERATOR_REVIEW",
  "APPROVED",
  "PUBLISHED",
  "REJECTED",
  "ARCHIVED",
];

export default function ExhibitorsPage() {
  const [session] = useSession();
  const [eventId, setEventId] = useState("");
  const [statusFilter, setStatusFilter] = useState<ExhibitorReviewStatus | "">("");
  const [items, setItems] = useState<AdminExhibitorListItem[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  const search = useCallback(() => {
    setLoading(true);
    setError(null);
    listExhibitorsForReview({
      event_id: eventId || undefined,
      review_status: statusFilter || undefined,
    })
      .then((res) => setItems(res.items))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  }, [eventId, statusFilter]);

  useEffect(() => {
    search();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">참가업체</h1>
        <div className="flex gap-2">
          <RoleGate capability="EXHIBITOR_EDIT_OWN">
            <Link
              href="/exhibitors/new"
              className="tap-target rounded-md bg-[var(--color-brand)] px-3 py-2 text-sm font-medium text-[var(--color-brand-contrast)]"
            >
              업체 등록
            </Link>
          </RoleGate>
        </div>
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
          <Field label="승인상태 필터">
            <select
              value={statusFilter}
              onChange={(event) =>
                setStatusFilter(event.target.value as ExhibitorReviewStatus | "")
              }
              className="input"
            >
              <option value="">전체</option>
              {REVIEW_STATUSES.map((status) => (
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
        <p className="text-sm text-[var(--color-text-muted)]">조건에 맞는 업체가 없습니다.</p>
      )}

      {!loading && !error && items && items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--color-surface-muted)] text-xs uppercase text-[var(--color-text-muted)]">
              <tr>
                <th className="px-3 py-2">업체명</th>
                <th className="px-3 py-2">검수상태</th>
                <th className="px-3 py-2">완성도</th>
                <th className="px-3 py-2">제품수</th>
                <th className="px-3 py-2">제출일</th>
                <th className="px-3 py-2 text-right">동작</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <tr key={item.exhibitor_id} className="border-t border-[var(--color-border)]">
                  <td className="px-3 py-2 font-medium">{item.company_name}</td>
                  <td className="px-3 py-2">
                    <StatusBadge status={item.review_status} />
                  </td>
                  <td className="px-3 py-2">{item.data_completeness_percent}%</td>
                  <td className="px-3 py-2">{item.product_count}</td>
                  <td className="px-3 py-2">
                    {item.submitted_at ? new Date(item.submitted_at).toLocaleDateString("ko-KR") : "-"}
                  </td>
                  <td className="px-3 py-2 text-right">
                    <Link
                      href={`/exhibitors/${item.exhibitor_id}/review`}
                      className="tap-target text-[var(--color-brand)] underline"
                    >
                      검수
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <QuickLookup />

      {session.role === "EXHIBITOR_ADMIN" && session.exhibitorId && (
        <p className="text-sm text-[var(--color-text-muted)]">
          현재 세션은 자사 업체({session.exhibitorId})로 범위가 제한됩니다. 목록 API가
          구현되면 서버가 이 필터를 강제해야 합니다(클라이언트 필터만으로는 불충분 - 백엔드
          쪽 RBAC TODO).
        </p>
      )}
    </div>
  );
}

/** 목록 API가 없어도 업체 ID를 알고 있으면 실제로 조회할 수 있는 경로
 * (GET /exhibitors/{id}/profile - 실구현됨)로 바로 이동한다. */
function QuickLookup() {
  const [exhibitorId, setExhibitorId] = useState("");

  return (
    <div className="rounded-lg border border-dashed border-[var(--color-border)] p-4">
      <p className="mb-2 text-sm font-medium">업체 ID로 바로 조회</p>
      <p className="mb-3 text-xs text-[var(--color-text-muted)]">
        위 목록 API가 아직 없거나 실패해도, 업체 ID를 알고 있으면 실제로 동작하는{" "}
        <code>GET /exhibitors/&#123;id&#125;/profile</code>로 검수 화면에 바로 진입할 수
        있습니다.
      </p>
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(event) => {
          event.preventDefault();
          if (exhibitorId.trim()) {
            window.location.href = `/exhibitors/${encodeURIComponent(exhibitorId.trim())}/review`;
          }
        }}
      >
        <input
          value={exhibitorId}
          onChange={(event) => setExhibitorId(event.target.value)}
          placeholder="exhibitor_id (UUID)"
          className="input max-w-xs font-mono text-xs"
        />
        <button
          type="submit"
          className="tap-target rounded-md border border-[var(--color-border)] px-3 py-2 text-sm"
        >
          이동
        </button>
      </form>
    </div>
  );
}
