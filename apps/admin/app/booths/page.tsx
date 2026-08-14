"use client";

/**
 * A07 부스·지도 관리. §43절. 작업 지시 필수 요구사항: 부스 등록/수정 + 상태 변경.
 *
 * 관리자용 부스 목록/등록 API(`GET/POST /admin/booths`)는 §40.9절에 문서화조차 되어 있지
 * 않다(경로는 REST 관례 추정치, lib/api-client.ts TODO). 개별 부스 조회(`GET /booths/{id}`)
 * 는 실제로 동작하지만 운영중(OPEN/PAUSED)인 부스만 보여준다(apps/api/app/services/
 * public_catalog.py).
 */

import Link from "next/link";
import { useCallback, useState } from "react";

import { listAdminBooths } from "@/lib/api-client";
import type { AdminBoothListItem } from "@/lib/types";
import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";
import RoleGate from "@/components/RoleGate";
import StatusBadge from "@/components/StatusBadge";

export default function BoothsPage() {
  const [eventId, setEventId] = useState("");
  const [booths, setBooths] = useState<AdminBoothListItem[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [boothIdLookup, setBoothIdLookup] = useState("");

  const search = useCallback(() => {
    if (!eventId.trim()) return;
    setLoading(true);
    setError(null);
    listAdminBooths(eventId.trim())
      .then((res) => setBooths(res.items))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  }, [eventId]);

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">부스</h1>
        <RoleGate capability="BOOTH_MANAGE">
          <Link href="/booths/new" className="tap-target rounded-md bg-[var(--color-brand)] px-3 py-2 text-sm font-medium text-[var(--color-brand-contrast)]">
            부스 등록
          </Link>
        </RoleGate>
      </div>

      <form
        onSubmit={(event) => {
          event.preventDefault();
          search();
        }}
        className="flex flex-wrap items-end gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
      >
        <div className="min-w-[260px]">
          <Field label="행사 ID" required hint="UUID">
            <input required value={eventId} onChange={(event) => setEventId(event.target.value)} className="input font-mono text-xs" />
          </Field>
        </div>
        <button type="submit" className="tap-target rounded-md border border-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand)]">
          조회
        </button>
      </form>

      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {!loading && error ? <ErrorBanner error={error} onRetry={search} /> : null}
      {!loading && !error && booths && booths.length === 0 && (
        <p className="text-sm text-[var(--color-text-muted)]">등록된 부스가 없습니다.</p>
      )}
      {!loading && !error && booths && booths.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--color-surface-muted)] text-xs uppercase text-[var(--color-text-muted)]">
              <tr>
                <th className="px-3 py-2">부스번호</th>
                <th className="px-3 py-2">업체</th>
                <th className="px-3 py-2">구역</th>
                <th className="px-3 py-2">운영상태</th>
                <th className="px-3 py-2 text-right">동작</th>
              </tr>
            </thead>
            <tbody>
              {booths.map((booth) => (
                <tr key={booth.booth_id} className="border-t border-[var(--color-border)]">
                  <td className="px-3 py-2 font-medium">{booth.booth_number}</td>
                  <td className="px-3 py-2">{booth.exhibitor_name}</td>
                  <td className="px-3 py-2">{booth.zone_name ?? "-"}</td>
                  <td className="px-3 py-2"><StatusBadge status={booth.operating_status} /></td>
                  <td className="px-3 py-2 text-right">
                    <Link href={`/booths/${booth.booth_id}/edit`} className="tap-target text-[var(--color-brand)] underline">
                      수정
                    </Link>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <div className="rounded-lg border border-dashed border-[var(--color-border)] p-4">
        <p className="mb-2 text-sm font-medium">부스 ID로 바로 수정</p>
        <p className="mb-3 text-xs text-[var(--color-text-muted)]">
          위 목록 API가 없거나 실패해도, 부스 ID를 알고 있으면 수정 화면으로 바로 이동할 수
          있습니다.
        </p>
        <form
          className="flex flex-wrap gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (boothIdLookup.trim()) {
              window.location.href = `/booths/${encodeURIComponent(boothIdLookup.trim())}/edit`;
            }
          }}
        >
          <input
            value={boothIdLookup}
            onChange={(event) => setBoothIdLookup(event.target.value)}
            placeholder="booth_id (UUID)"
            className="input max-w-xs font-mono text-xs"
          />
          <button type="submit" className="tap-target rounded-md border border-[var(--color-border)] px-3 py-2 text-sm">
            이동
          </button>
        </form>
      </div>
    </div>
  );
}
