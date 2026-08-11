"use client";

/**
 * 바이어 섹션 — 검증, 매칭·비교 이용, 상담 신청/수락/거절/완료 건수.
 *
 * 작업 지시 필수 요구사항: 거래액(deal value)·계약 성과(contract-outcome) 수치는 절대 표시하지
 * 않는다. 백엔드 스키마(BuyerAnalyticsResponse)에도 그런 필드가 없다 — 이 컴포넌트는 그
 * 사실을 화면에 명시적으로 적어 "왜 없는지"가 버그로 오인되지 않게 한다.
 */

import { formatMetric } from "../logic";
import type { AggregateCsvRow, BuyerAnalyticsResponse } from "../types";
import MetricCard from "./MetricCard";

export function buyerCsvRows(data: BuyerAnalyticsResponse): AggregateCsvRow[] {
  const section = "바이어";
  const rows: AggregateCsvRow[] = [
    { section, label: "바이어 매칭", value: formatMetric(data.buyer_matches) },
    { section, label: "상담 신청", value: formatMetric(data.meeting_requests) },
    { section, label: "상담 수락", value: formatMetric(data.meeting_accepts) },
    { section, label: "상담 완료", value: formatMetric(data.meeting_completions) },
    { section, label: "유효 리드", value: formatMetric(data.valid_leads) },
    { section, label: "상담 수락률", value: formatMetric(data.meeting_accept_rate, { percent: true }) },
    { section, label: "상담 완료율", value: formatMetric(data.meeting_completion_rate, { percent: true }) },
    { section, label: "유효 리드율", value: formatMetric(data.valid_lead_rate, { percent: true }) },
  ];
  if (data.verified_buyers) {
    rows.push({ section, label: "검증된 바이어 수", value: formatMetric(data.verified_buyers) });
  }
  if (data.compare_usage) {
    rows.push({ section, label: "비교 기능 이용", value: formatMetric(data.compare_usage) });
  }
  for (const row of data.breakdown) {
    rows.push({
      section: "업체별 매칭 현황",
      label: row.exhibitor_id,
      value: `매칭 ${formatMetric(row.buyer_matches)} · 상담신청 ${formatMetric(row.meeting_requests)} · 상담수락 ${formatMetric(row.meeting_accepts)}`,
    });
  }
  return rows;
}

export default function BuyerSection({ data }: { data: BuyerAnalyticsResponse }) {
  return (
    <section data-testid="buyer-section" className="flex flex-col gap-3">
      <h2 className="text-base font-semibold">바이어</h2>
      <p className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface-muted)] px-3 py-2 text-xs text-[var(--color-text-muted)]">
        이 섹션은 매칭·상담 활동 건수만 집계합니다. 거래액이나 계약 성과 관련 수치는 표시하지
        않습니다.
      </p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricCard label="바이어 매칭" metric={data.buyer_matches} />
        <MetricCard label="상담 신청" metric={data.meeting_requests} />
        <MetricCard label="상담 수락" metric={data.meeting_accepts} />
        <MetricCard label="상담 완료" metric={data.meeting_completions} />
        <MetricCard label="유효 리드" metric={data.valid_leads} />
        <MetricCard label="상담 수락률" metric={data.meeting_accept_rate} percent />
        <MetricCard label="상담 완료율" metric={data.meeting_completion_rate} percent />
        <MetricCard label="유효 리드율" metric={data.valid_lead_rate} percent />
        <MetricCard label="검증된 바이어 수" metric={data.verified_buyers} />
        <MetricCard label="비교 기능 이용" metric={data.compare_usage} />
      </div>

      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <p className="mb-2 text-sm font-semibold">업체별 매칭 현황</p>
        {data.breakdown.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-[var(--color-text-muted)]">
                <tr>
                  <th className="py-1 pr-3">업체 ID</th>
                  <th className="py-1 pr-3">바이어 매칭</th>
                  <th className="py-1 pr-3">상담 신청</th>
                  <th className="py-1">상담 수락</th>
                </tr>
              </thead>
              <tbody>
                {data.breakdown.map((row) => (
                  <tr key={row.exhibitor_id} className="border-t border-[var(--color-border)]">
                    <td className="py-1.5 pr-3 font-mono text-xs">{row.exhibitor_id}</td>
                    <td className="py-1.5 pr-3">{formatMetric(row.buyer_matches)}</td>
                    <td className="py-1.5 pr-3">{formatMetric(row.meeting_requests)}</td>
                    <td className="py-1.5">{formatMetric(row.meeting_accepts)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-[var(--color-text-muted)]">해당 기간 데이터가 없습니다.</p>
        )}
      </div>
    </section>
  );
}
