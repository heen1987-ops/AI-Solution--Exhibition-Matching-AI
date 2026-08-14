"use client";

/**
 * 바이어 검증 큐 (WAVE 2C ADMIN-BUYER 트랙).
 *
 * 표시 항목: buyer display name, company, buyer_type, business-email-verified flag,
 * registered event, profile completeness %, verification_status, applied_at
 * (작업 지시 필수 요구사항 그대로).
 *
 * 목록 API(`GET /admin/buyers/verification-queue`)는 아직 백엔드에 없다(TODO,
 * features/buyer-verification/api.ts 참고, CONTRACTS-BUYER 문서 부재 -
 * features/buyer-verification/types.ts 모듈 docstring 참고). 그 상태를 숨기지 않고 명확한
 * 오류로 보여준다
 * (`apps/admin/app/exhibitors/page.tsx`가 §28 업체 목록에서 쓰는 것과 동일한 패턴).
 *
 * 역할 게이트: EVENT_ADMIN·DATA_REVIEWER만 이 큐를 조회·처리할 수 있다(작업 지시 "role-gated
 * access"). 다른 역할이면 목록 자체를 불러오지 않고 안내만 보여준다.
 */

import { Fragment, useCallback, useEffect, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";
import { listBuyerVerificationQueue } from "@/features/buyer-verification/api";
import VerificationActions from "@/features/buyer-verification/components/VerificationActions";
import VerificationStatusPill from "@/features/buyer-verification/components/VerificationStatusPill";
import {
  canManageBuyerVerification,
  redactPotentialContactInfo,
} from "@/features/buyer-verification/logic";
import type {
  BuyerVerificationQueueItem,
  BuyerVerificationStatus,
} from "@/features/buyer-verification/types";
import { useSession } from "@/lib/use-session";

const VERIFICATION_STATUSES: BuyerVerificationStatus[] = [
  "PENDING",
  "VERIFIED",
  "LIMITED",
  "REJECTED",
  "SUSPENDED",
  "EXPIRED",
];

export default function BuyersPage() {
  const [session] = useSession();
  const allowed = canManageBuyerVerification(session.role);

  const [eventId, setEventId] = useState("");
  const [statusFilter, setStatusFilter] = useState<BuyerVerificationStatus | "">("PENDING");
  const [items, setItems] = useState<BuyerVerificationQueueItem[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [expandedId, setExpandedId] = useState<string | null>(null);

  const search = useCallback(() => {
    if (!allowed) return;
    setLoading(true);
    setError(null);
    listBuyerVerificationQueue({
      event_id: eventId || undefined,
      verification_status: statusFilter || undefined,
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
        <h1 className="text-xl font-semibold">바이어 검증</h1>
        <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-text-muted)]">
          현재 역할({session.role})에는 바이어 검증 큐 조회 권한이 없습니다. 행사 운영자(EVENT_ADMIN)
          또는 데이터 검수자(DATA_REVIEWER)로 전환해 주세요.
        </p>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">바이어 검증</h1>
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
          <Field label="검증상태 필터">
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as BuyerVerificationStatus | "")}
              className="input"
            >
              <option value="">전체</option>
              {VERIFICATION_STATUSES.map((status) => (
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
        <p className="text-sm text-[var(--color-text-muted)]">조건에 맞는 바이어가 없습니다.</p>
      )}

      {!loading && !error && items && items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
          <table className="w-full text-left text-sm">
            <thead className="bg-[var(--color-surface-muted)] text-xs uppercase text-[var(--color-text-muted)]">
              <tr>
                <th className="px-3 py-2">바이어</th>
                <th className="px-3 py-2">회사</th>
                <th className="px-3 py-2">유형</th>
                <th className="px-3 py-2">이메일 인증</th>
                <th className="px-3 py-2">등록 행사</th>
                <th className="px-3 py-2">완성도</th>
                <th className="px-3 py-2">검증상태</th>
                <th className="px-3 py-2">신청일</th>
                <th className="px-3 py-2 text-right">동작</th>
              </tr>
            </thead>
            <tbody>
              {items.map((item) => (
                <Fragment key={item.buyer_profile_id}>
                  <tr className="border-t border-[var(--color-border)]">
                    <td className="px-3 py-2 font-medium">
                      {redactPotentialContactInfo(item.display_name)}
                    </td>
                    <td className="px-3 py-2">{item.company_name ?? "-"}</td>
                    <td className="px-3 py-2">{item.buyer_type ?? "-"}</td>
                    <td className="px-3 py-2">
                      {item.business_email_verified ? (
                        <span className="text-[var(--color-success)]">인증됨</span>
                      ) : (
                        <span className="text-[var(--color-text-muted)]">미인증</span>
                      )}
                    </td>
                    <td className="px-3 py-2">{item.event_name ?? item.event_id}</td>
                    <td className="px-3 py-2">{item.completeness_percent}%</td>
                    <td className="px-3 py-2">
                      <VerificationStatusPill status={item.verification_status} />
                    </td>
                    <td className="px-3 py-2">
                      {item.applied_at ? new Date(item.applied_at).toLocaleDateString("ko-KR") : "-"}
                    </td>
                    <td className="px-3 py-2 text-right">
                      <button
                        type="button"
                        onClick={() =>
                          setExpandedId(expandedId === item.buyer_profile_id ? null : item.buyer_profile_id)
                        }
                        className="tap-target text-[var(--color-brand)] underline"
                      >
                        {expandedId === item.buyer_profile_id ? "닫기" : "처리"}
                      </button>
                    </td>
                  </tr>
                  {expandedId === item.buyer_profile_id && (
                    <tr className="border-t border-[var(--color-border)]">
                      <td colSpan={9} className="px-3 py-3">
                        <VerificationActions item={item} onDecided={search} />
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
