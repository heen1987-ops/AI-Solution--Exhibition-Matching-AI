"use client";

/**
 * 부스 수정 + 운영상태 변경 (작업 지시 필수 요구사항).
 *
 * 조회는 실제로 동작한다(`GET /booths/{id}` - 운영중인 부스만, apps/api/app/api/v1/routers/
 * exhibitors.py). 상태 변경은 §40.9절에 문서화된 `PATCH /admin/booths/{id}/status`를
 * 호출하지만 백엔드 라우터가 아직 없어(TODO, lib/api-client.ts) 실패 시 정직한 오류를
 * 보여준다.
 */

import { useParams } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { getPublicBooth, updateBoothStatus } from "@/lib/api-client";
import type { BoothOperatingStatus, PublicBoothDetail } from "@/lib/types";
import ErrorBanner from "@/components/ErrorBanner";
import RoleGate from "@/components/RoleGate";
import StatusBadge from "@/components/StatusBadge";

const STATUS_OPTIONS: BoothOperatingStatus[] = ["OPEN", "PAUSED", "CLOSED"];

export default function EditBoothPage() {
  const params = useParams<{ boothId: string }>();
  const boothId = params.boothId;

  const [booth, setBooth] = useState<PublicBoothDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>(null);

  const [nextStatus, setNextStatus] = useState<BoothOperatingStatus>("OPEN");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [statusError, setStatusError] = useState<unknown>(null);
  const [statusSaved, setStatusSaved] = useState(false);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    getPublicBooth(boothId)
      .then((data) => {
        setBooth(data);
        setNextStatus(data.operating_status);
      })
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  }, [boothId]);

  useEffect(() => {
    load();
  }, [load]);

  const submitStatus = async () => {
    setSubmitting(true);
    setStatusError(null);
    setStatusSaved(false);
    try {
      await updateBoothStatus(boothId, { operating_status: nextStatus, reason: reason || null });
      setStatusSaved(true);
      load();
    } catch (err) {
      setStatusError(err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="flex max-w-2xl flex-col gap-4">
      <h1 className="text-xl font-semibold">부스 수정</h1>

      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {!loading && error ? (
        <div className="flex flex-col gap-2">
          <ErrorBanner error={error} onRetry={load} />
          <p className="text-xs text-[var(--color-text-muted)]">
            <code>GET /booths/&#123;id&#125;</code>는 CLOSED 상태이거나 미승인 업체의 부스를
            찾지 못할 수 있습니다(공개 카탈로그 API 특성).
          </p>
        </div>
      ) : null}

      {!loading && !error && booth && (
        <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm">
          <p className="font-semibold">
            {booth.booth_number} · {booth.exhibitor_name}
          </p>
          <p className="mt-1 text-[var(--color-text-muted)]">
            현재 상태: <StatusBadge status={booth.operating_status} />
          </p>
        </div>
      )}

      <RoleGate
        capability="BOOTH_STATUS_CHANGE"
        fallback={
          <p className="text-sm text-[var(--color-text-muted)]">
            현재 역할에는 부스 운영상태 변경 권한이 없습니다.
          </p>
        }
      >
        <section className="flex flex-col gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
          <h2 className="text-base font-semibold">운영상태 변경</h2>
          {statusError ? <ErrorBanner error={statusError} /> : null}
          {statusSaved && (
            <p className="rounded-md border border-[var(--color-success)] bg-[var(--color-success-bg)] p-2 text-sm text-[var(--color-success)]">
              변경되었습니다.
            </p>
          )}
          <div className="flex flex-wrap items-end gap-3">
            <label className="flex flex-col gap-1 text-sm">
              <span className="font-medium">상태</span>
              <select
                value={nextStatus}
                onChange={(event) => setNextStatus(event.target.value as BoothOperatingStatus)}
                className="input"
              >
                {STATUS_OPTIONS.map((status) => (
                  <option key={status} value={status}>
                    {status}
                  </option>
                ))}
              </select>
            </label>
            <label className="flex min-w-[220px] flex-1 flex-col gap-1 text-sm">
              <span className="font-medium">사유 (선택)</span>
              <input value={reason} onChange={(event) => setReason(event.target.value)} className="input" />
            </label>
            <button
              type="button"
              onClick={() => void submitStatus()}
              disabled={submitting}
              className="tap-target rounded-md bg-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand-contrast)] disabled:opacity-50"
            >
              {submitting ? "변경 중…" : "상태 변경"}
            </button>
          </div>
        </section>
      </RoleGate>
    </div>
  );
}
