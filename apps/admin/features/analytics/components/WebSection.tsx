"use client";

/**
 * 웹 초개인화 섹션 — 활성 사용자, 세션, 추천 노출/클릭, 관심목록, 일별 활성 사용자 추이.
 *
 * 계약 공백 필드(profile_funnel, negative_feedback_rate, per_interest_performance,
 * personalization_opt_out_rate)는 백엔드가 아직 주지 않으면 각 섹션이 "백엔드 미제공"으로
 * 명시하고 조용히 숨기지 않는다 — types.ts 모듈 docstring의 계약 공백 목록 참고.
 */

import { formatDurationMetric, formatMetric } from "../logic";
import type { AggregateCsvRow, WebAnalyticsResponse } from "../types";
import DailyTrendTable from "./DailyTrendTable";
import MetricCard from "./MetricCard";

export function webCsvRows(data: WebAnalyticsResponse): AggregateCsvRow[] {
  const section = "웹 초개인화";
  const rows: AggregateCsvRow[] = [
    { section, label: "활성 사용자", value: formatMetric(data.active_users) },
    { section, label: "세션 수", value: formatMetric(data.sessions) },
    { section, label: "평균 세션 시간", value: formatMetric(data.avg_session_duration_seconds, { unit: "초" }) },
    { section, label: "추천 노출", value: formatMetric(data.recommendation_impressions) },
    { section, label: "추천 클릭", value: formatMetric(data.recommendation_clicks) },
    { section, label: "추천 클릭률", value: formatMetric(data.recommendation_click_rate, { percent: true }) },
    { section, label: "관심목록 저장", value: formatMetric(data.favorites_saved) },
  ];
  if (data.negative_feedback_rate) {
    rows.push({ section, label: "부정 피드백 비율", value: formatMetric(data.negative_feedback_rate, { percent: true }) });
  }
  if (data.personalization_opt_out_rate) {
    rows.push({
      section,
      label: "개인화 거부율",
      value: formatMetric(data.personalization_opt_out_rate, { percent: true }),
    });
  }
  for (const step of data.profile_funnel ?? []) {
    rows.push({ section: "프로파일 퍼널", label: step.step, value: formatMetric(step.users) });
  }
  for (const row of data.per_interest_performance ?? []) {
    rows.push({
      section: "관심사별 추천 성과",
      label: row.concept_code,
      value: `노출 ${formatMetric(row.impressions)} · 클릭 ${formatMetric(row.clicks)} · 클릭률 ${formatMetric(row.click_rate, { percent: true })}`,
    });
  }
  return rows;
}

export default function WebSection({ data }: { data: WebAnalyticsResponse }) {
  return (
    <section data-testid="web-section" className="flex flex-col gap-3">
      <h2 className="text-base font-semibold">웹 초개인화</h2>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricCard label="활성 사용자" metric={data.active_users} />
        <MetricCard label="세션 수" metric={data.sessions} />
        <MetricCard label="평균 세션 시간" metric={data.avg_session_duration_seconds} duration />
        <MetricCard label="추천 노출" metric={data.recommendation_impressions} />
        <MetricCard label="추천 클릭" metric={data.recommendation_clicks} />
        <MetricCard label="추천 클릭률" metric={data.recommendation_click_rate} percent />
        <MetricCard label="관심목록 저장" metric={data.favorites_saved} />
        <MetricCard label="부정 피드백 비율" metric={data.negative_feedback_rate} percent />
        <MetricCard label="개인화 거부율" metric={data.personalization_opt_out_rate} percent />
      </div>

      <DailyTrendTable title="일별 활성 사용자" items={data.daily_active_users} />

      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <p className="mb-2 text-sm font-semibold">프로파일 진행 퍼널</p>
        {data.profile_funnel && data.profile_funnel.length > 0 ? (
          <table className="w-full text-left text-sm">
            <thead className="text-xs uppercase text-[var(--color-text-muted)]">
              <tr>
                <th className="py-1">단계</th>
                <th className="py-1">사용자 수</th>
              </tr>
            </thead>
            <tbody>
              {data.profile_funnel.map((step) => (
                <tr key={step.step} className="border-t border-[var(--color-border)]">
                  <td className="py-1.5">{step.step}</td>
                  <td className="py-1.5">{formatMetric(step.users)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="text-sm text-[var(--color-text-muted)]">백엔드 미제공</p>
        )}
      </div>

      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <p className="mb-2 text-sm font-semibold">관심사별 추천 성과</p>
        {data.per_interest_performance && data.per_interest_performance.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-[var(--color-text-muted)]">
                <tr>
                  <th className="py-1 pr-3">관심사 코드</th>
                  <th className="py-1 pr-3">노출</th>
                  <th className="py-1 pr-3">클릭</th>
                  <th className="py-1">클릭률</th>
                </tr>
              </thead>
              <tbody>
                {data.per_interest_performance.map((row) => (
                  <tr key={row.concept_code} className="border-t border-[var(--color-border)]">
                    <td className="py-1.5 pr-3 font-mono text-xs">{row.concept_code}</td>
                    <td className="py-1.5 pr-3">{formatMetric(row.impressions)}</td>
                    <td className="py-1.5 pr-3">{formatMetric(row.clicks)}</td>
                    <td className="py-1.5">{formatMetric(row.click_rate, { percent: true })}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-sm text-[var(--color-text-muted)]">백엔드 미제공</p>
        )}
      </div>
    </section>
  );
}
