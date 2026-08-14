"use client";

/**
 * 운영 개요 섹션 — 가입자, 프로파일 확정률, 키오스크 세션, 검색, 무결과율,
 * 추천 클릭률, 관심목록, 바이어 매칭, 상담 신청/수락, 공개(발행) 업체·제품 수.
 */

import { formatMetric } from "../logic";
import type { AggregateCsvRow, OverviewAnalyticsResponse } from "../types";
import MetricCard from "./MetricCard";

export function overviewCsvRows(data: OverviewAnalyticsResponse): AggregateCsvRow[] {
  const section = "운영 개요";
  return [
    { section, label: "가입자 수", value: formatMetric(data.registered_users) },
    { section, label: "프로파일 확정률", value: formatMetric(data.profile_confirm_rate, { percent: true }) },
    { section, label: "웹 활성 사용자", value: formatMetric(data.web_active_users) },
    { section, label: "키오스크 세션", value: formatMetric(data.kiosk_sessions) },
    { section, label: "검색 수", value: formatMetric(data.total_searches) },
    { section, label: "무결과율", value: formatMetric(data.no_result_rate, { percent: true }) },
    { section, label: "추천 클릭률", value: formatMetric(data.recommendation_click_rate, { percent: true }) },
    { section, label: "관심목록 저장", value: formatMetric(data.favorites_saved) },
    { section, label: "바이어 매칭", value: formatMetric(data.buyer_matches) },
    { section, label: "상담 신청", value: formatMetric(data.meeting_requests) },
    { section, label: "상담 수락", value: formatMetric(data.meeting_accepts) },
    { section, label: "공개 업체 수", value: formatMetric(data.published_exhibitor_count) },
    { section, label: "공개 제품 수", value: formatMetric(data.published_product_count) },
  ];
}

export default function OverviewSection({ data }: { data: OverviewAnalyticsResponse }) {
  return (
    <section data-testid="overview-section" className="flex flex-col gap-3">
      <h2 className="text-base font-semibold">운영 개요</h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricCard label="가입자 수" metric={data.registered_users} />
        <MetricCard label="프로파일 확정률" metric={data.profile_confirm_rate} percent />
        <MetricCard label="웹 활성 사용자" metric={data.web_active_users} />
        <MetricCard label="키오스크 세션" metric={data.kiosk_sessions} />
        <MetricCard label="검색 수" metric={data.total_searches} />
        <MetricCard label="무결과율" metric={data.no_result_rate} percent />
        <MetricCard label="추천 클릭률" metric={data.recommendation_click_rate} percent />
        <MetricCard label="관심목록 저장" metric={data.favorites_saved} />
        <MetricCard label="바이어 매칭" metric={data.buyer_matches} />
        <MetricCard label="상담 신청" metric={data.meeting_requests} />
        <MetricCard label="상담 수락" metric={data.meeting_accepts} />
        <MetricCard
          label="공개 업체 / 제품"
          metric={data.published_exhibitor_count}
          hint={`제품 ${formatMetric(data.published_product_count)}건`}
        />
      </div>
    </section>
  );
}
