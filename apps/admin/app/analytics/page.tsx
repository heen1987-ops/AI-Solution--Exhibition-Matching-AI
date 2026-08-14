"use client";

/**
 * A?? 관리자 통계 대시보드 (ADMIN-ANALYTICS, WAVE 2E).
 *
 * IA: 운영 개요 / 웹 초개인화 / 키오스크 / 바이어 4개 섹션을 탭으로 전환한다. 공통 필터
 * (행사·기간·채널)는 상단에 고정하고, "데이터 기준 시각 / 집계 지연 가능" 신선도 표시기를
 * 항상 렌더링한다(작업 지시 필수 요구사항).
 *
 * 역할 접근: EXHIBITOR_ADMIN은 바이어 섹션만 볼 수 있다(features/analytics/logic.ts
 * canViewAnalyticsSection, 백엔드 app/services/analytics/access.py와 정합 — 서버가 최종
 * 강제하고 이 화면은 링크·탭 노출만 제어한다).
 *
 * 백엔드 라우터가 아직 api.py에 등록되지 않아(features/analytics/api.ts 모듈 docstring
 * 참고) 모든 호출은 NOT_IMPLEMENTED ApiClientError로 떨어진다 — 화면은 그 상태를 있는
 * 그대로 ErrorBanner로 보여주고 가짜 성공을 표시하지 않는다.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";
import { useSession } from "@/lib/use-session";

import { getBuyerAnalytics, getKioskAnalytics, getOverviewAnalytics, getWebAnalytics } from "@/features/analytics/api";
import BuyerSection, { buyerCsvRows } from "@/features/analytics/components/BuyerSection";
import AnalyticsFilterBar from "@/features/analytics/components/AnalyticsFilterBar";
import ExportAggregateCsvButton from "@/features/analytics/components/ExportAggregateCsvButton";
import FreshnessIndicator from "@/features/analytics/components/FreshnessIndicator";
import KioskSection, { kioskCsvRows } from "@/features/analytics/components/KioskSection";
import OverviewSection, { overviewCsvRows } from "@/features/analytics/components/OverviewSection";
import WebSection, { webCsvRows } from "@/features/analytics/components/WebSection";
import { canViewAnalyticsSection, resolveDateRange } from "@/features/analytics/logic";
import type { AnalyticsSection } from "@/features/analytics/logic";
import type {
  AnalyticsFilter,
  BuyerAnalyticsResponse,
  KioskAnalyticsResponse,
  OverviewAnalyticsResponse,
  WebAnalyticsResponse,
} from "@/features/analytics/types";

const TABS: { id: AnalyticsSection; label: string }[] = [
  { id: "overview", label: "운영 개요" },
  { id: "web", label: "웹 초개인화" },
  { id: "kiosk", label: "키오스크" },
  { id: "buyer", label: "바이어" },
];

const DEFAULT_FILTER: AnalyticsFilter = {
  eventId: "",
  preset: "LAST_7_DAYS",
  customStart: null,
  customEnd: null,
  channel: "ALL",
};

export default function AnalyticsPage() {
  const [session] = useSession();
  const role = session.role;

  const visibleTabs = useMemo(() => TABS.filter((tab) => canViewAnalyticsSection(role, tab.id)), [role]);
  const [activeTab, setActiveTab] = useState<AnalyticsSection>(
    canViewAnalyticsSection(role, "overview") ? "overview" : "buyer",
  );
  useEffect(() => {
    if (!canViewAnalyticsSection(role, activeTab)) {
      setActiveTab(visibleTabs[0]?.id ?? "buyer");
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [role]);

  const [filter, setFilter] = useState<AnalyticsFilter>(DEFAULT_FILTER);
  const [exhibitorFilter, setExhibitorFilter] = useState("");

  const [overview, setOverview] = useState<OverviewAnalyticsResponse | null>(null);
  const [web, setWeb] = useState<WebAnalyticsResponse | null>(null);
  const [kiosk, setKiosk] = useState<KioskAnalyticsResponse | null>(null);
  const [buyer, setBuyer] = useState<BuyerAnalyticsResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);
  const [fetchedAt, setFetchedAt] = useState<Date | null>(null);

  const range = useMemo(() => resolveDateRange(filter, null), [filter]);
  const eventPeriodFallback = filter.preset === "EVENT_PERIOD";

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    const resolvedRange = resolveDateRange(filter, null);
    const exhibitorIdForBuyer = role === "EXHIBITOR_ADMIN" ? undefined : exhibitorFilter || undefined;

    const request =
      activeTab === "overview"
        ? getOverviewAnalytics(filter, resolvedRange).then(setOverview)
        : activeTab === "web"
          ? getWebAnalytics(filter, resolvedRange).then(setWeb)
          : activeTab === "kiosk"
            ? getKioskAnalytics(filter, resolvedRange).then(setKiosk)
            : getBuyerAnalytics(filter, resolvedRange, exhibitorIdForBuyer).then(setBuyer);

    request
      .then(() => setFetchedAt(new Date()))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  }, [activeTab, filter, exhibitorFilter, role]);

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, filter, exhibitorFilter]);

  const dataAsOf =
    activeTab === "overview"
      ? overview?.data_as_of
      : activeTab === "web"
        ? web?.data_as_of
        : activeTab === "kiosk"
          ? kiosk?.data_as_of
          : buyer?.data_as_of;

  const csvRows =
    activeTab === "overview" && overview
      ? overviewCsvRows(overview)
      : activeTab === "web" && web
        ? webCsvRows(web)
        : activeTab === "kiosk" && kiosk
          ? kioskCsvRows(kiosk)
          : activeTab === "buyer" && buyer
            ? buyerCsvRows(buyer)
            : [];

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">통계</h1>
        <FreshnessIndicator dataAsOf={dataAsOf} fetchedAt={fetchedAt} />
      </div>

      <nav aria-label="통계 섹션" className="flex flex-wrap gap-1 border-b border-[var(--color-border)]">
        {visibleTabs.map((tab) => (
          <button
            key={tab.id}
            type="button"
            onClick={() => setActiveTab(tab.id)}
            aria-current={activeTab === tab.id ? "page" : undefined}
            className={`tap-target rounded-t-md px-3 py-2 text-sm font-medium ${
              activeTab === tab.id
                ? "border-b-2 border-[var(--color-brand)] text-[var(--color-brand)]"
                : "text-[var(--color-text-muted)] hover:text-[var(--color-text)]"
            }`}
          >
            {tab.label}
          </button>
        ))}
      </nav>

      <AnalyticsFilterBar filter={filter} onChange={setFilter} showChannel={activeTab !== "buyer"} />

      {eventPeriodFallback ? (
        <p className="text-xs text-[var(--color-text-muted)]">
          행사 기간 조회는 행사 목록 API 연동 전까지 최근 7일로 대체 표시됩니다.
        </p>
      ) : null}

      {activeTab === "buyer" && role !== "EXHIBITOR_ADMIN" ? (
        <div className="max-w-xs">
          <Field label="업체 ID 필터" hint="비워두면 전체 업체 합산">
            <input
              value={exhibitorFilter}
              onChange={(event) => setExhibitorFilter(event.target.value)}
              className="input font-mono text-xs"
              placeholder="UUID"
            />
          </Field>
        </div>
      ) : null}

      <div className="flex items-center justify-between gap-2">
        <p className="text-xs text-[var(--color-text-muted)]">
          기간 {range.periodStart} ~ {range.periodEnd}
        </p>
        <ExportAggregateCsvButton
          rows={csvRows}
          filename={`analytics-${activeTab}-${range.periodStart}_${range.periodEnd}.csv`}
          disabled={loading || csvRows.length === 0}
        />
      </div>

      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {!loading && error ? <ErrorBanner error={error} onRetry={load} /> : null}

      {!loading && !error && activeTab === "overview" && overview ? <OverviewSection data={overview} /> : null}
      {!loading && !error && activeTab === "web" && web ? <WebSection data={web} /> : null}
      {!loading && !error && activeTab === "kiosk" && kiosk ? <KioskSection data={kiosk} /> : null}
      {!loading && !error && activeTab === "buyer" && buyer ? <BuyerSection data={buyer} /> : null}
    </div>
  );
}
