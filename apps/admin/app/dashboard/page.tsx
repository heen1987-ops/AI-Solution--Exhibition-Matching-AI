"use client";

/** A00 관리자 홈. §43절. 역할별 요약과 다음 작업으로의 진입점을 보여준다. */

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { getSearchInsights } from "@/features/analytics/api";
import { formatMetric, resolveDateRange } from "@/features/analytics/logic";
import type { SearchInsightsResponse } from "@/features/analytics/types";
import { ROLE_LABELS, hasCapability } from "@/lib/auth-state";
import { useSession } from "@/lib/use-session";
import ErrorBanner from "@/components/ErrorBanner";

const DEMO_EVENT_ID = "00000000-0000-0000-0000-000000000000";

export default function DashboardPage() {
  const [session] = useSession();
  const [analytics, setAnalytics] = useState<SearchInsightsResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    if (!hasCapability(session.role, "AUDIT_VIEW")) {
      setAnalytics(null);
      setError(null);
      setLoading(false);
      return () => {
        cancelled = true;
      };
    }
    setLoading(true);
    setError(null);
    const range = resolveDateRange({ preset: "LAST_7_DAYS", customStart: null, customEnd: null }, null);
    getSearchInsights(
      { eventId: DEMO_EVENT_ID, preset: "LAST_7_DAYS", customStart: null, customEnd: null, channel: "ALL" },
      range,
    )
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
  }, [session.role]);

  // 채널별 지표를 그대로 보여준다 - WEB/KIOSK Metric을 합산하면 한쪽만 억제(k<5)여도
  // 합계에 실제 소수집단 값이 섞여 나갈 수 있어(억제 우회) 채널별로만 표시한다.
  const channelSummaries = useMemo(() => analytics?.channel_performance ?? [], [analytics]);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">관리자 홈</h1>
        <p className="mt-1 text-sm text-[var(--color-text-muted)]">
          현재 역할: <strong>{session.role ? ROLE_LABELS[session.role] : "인증 필요"}</strong>
          {session.displayName ? ` · ${session.displayName}` : ""}
        </p>
      </div>

      <section className="grid grid-cols-1 gap-4 md:grid-cols-3">
        <QuickLinkCard
          href="/exhibitors"
          title="참가업체 검수"
          description="승인상태별 목록 조회, 업체 등록·수정, 검수·승인/반려"
          visible={
            hasCapability(session.role, "EXHIBITOR_REVIEW") ||
            hasCapability(session.role, "EXHIBITOR_EDIT_OWN")
          }
        />
        <QuickLinkCard
          href="/products"
          title="제품·서비스"
          description="제품 등록·수정, 승인상태 확인"
          visible={
            hasCapability(session.role, "PRODUCT_MANAGE_ANY") ||
            hasCapability(session.role, "PRODUCT_MANAGE_OWN")
          }
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
        {hasCapability(session.role, "AUDIT_VIEW") && loading && (
          <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>
        )}
        {!loading && error ? <ErrorBanner error={error} /> : null}
        {!loading && !error && analytics && (
          <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm">
            {channelSummaries.length === 0 ? (
              <p>최근 7일간 검색 데이터가 없습니다.</p>
            ) : (
              channelSummaries.map((channel) => (
                <p key={channel.channel}>
                  {channel.channel === "WEB" ? "웹" : "키오스크"} 검색 수:{" "}
                  {formatMetric(channel.total_searches)} · 무결과율:{" "}
                  {formatMetric(channel.zero_result_rate, { percent: true })}
                </p>
              ))
            )}
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
