"use client";

/** A00 관리자 홈. §43절. 역할별 요약과 다음 작업으로의 진입점을 보여준다. */

import Link from "next/link";
import { useEffect, useState } from "react";

import { getSearchAnalytics } from "@/lib/api-client";
import { ROLE_LABELS, hasCapability } from "@/lib/auth-state";
import { useSession } from "@/lib/use-session";
import type { SearchAnalyticsSummary } from "@/lib/types";
import ErrorBanner from "@/components/ErrorBanner";

const DEMO_EVENT_ID = "00000000-0000-0000-0000-000000000000";

export default function DashboardPage() {
  const [session] = useSession();
  const [analytics, setAnalytics] = useState<SearchAnalyticsSummary | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    setError(null);
    getSearchAnalytics(DEMO_EVENT_ID)
      .then((data) => {
        if (!cancelled) setAnalytics(data);
      })
      .catch((err) => {
        if (!cancelled) setError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">관리자 홈</h1>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          현재 역할: <strong>{ROLE_LABELS[session.role]}</strong>
          {session.displayName ? ` · ${session.displayName}` : ""}
        </p>
      </div>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <QuickLinkCard
          href="/exhibitors"
          title="참가업체 검수"
          description="승인상태별 목록 조회, 업체 등록·수정, 검수·승인/반려"
          visible
        />
        <QuickLinkCard
          href="/products"
          title="제품·서비스"
          description="제품 등록·수정, 승인상태 확인"
          visible
        />
        <QuickLinkCard
          href="/booths"
          title="부스·지도"
          description="부스 등록·수정, 운영상태(OPEN/PAUSED/CLOSED) 변경"
          visible={hasCapability(session.role, "BOOTH_MANAGE") || hasCapability(session.role, "BOOTH_STATUS_CHANGE")}
        />
        <QuickLinkCard
          href="/events"
          title="행사 관리"
          description="행사 기본정보 조회"
          visible={hasCapability(session.role, "EVENT_MANAGE")}
        />
        <QuickLinkCard
          href="/audit"
          title="감사로그"
          description="업체 승인/반려, 부스 상태변경 등 활동 이력"
          visible={hasCapability(session.role, "AUDIT_VIEW")}
        />
      </section>

      <section>
        <h2 className="mb-2 text-base font-semibold">검색 통계 요약 (§48 KPI)</h2>
        {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
        {!loading && error ? <ErrorBanner error={error} /> : null}
        {!loading && !error && analytics && (
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm">
            <p>총 검색 수: {analytics.total_searches}</p>
            <p>무결과율: {(analytics.zero_result_rate * 100).toFixed(1)}%</p>
          </div>
        )}
      </section>
    </div>
  );
}

function QuickLinkCard({
  href,
  title,
  description,
  visible,
}: {
  href: string;
  title: string;
  description: string;
  visible: boolean;
}) {
  if (!visible) return null;
  return (
    <Link
      href={href}
      className="block rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 hover:border-[var(--color-brand)]"
    >
      <p className="font-semibold">{title}</p>
      <p className="mt-1 text-sm text-[var(--color-text-muted)]">{description}</p>
    </Link>
  );
}
