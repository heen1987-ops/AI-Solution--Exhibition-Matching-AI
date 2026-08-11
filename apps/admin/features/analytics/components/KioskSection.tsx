"use client";

/**
 * 키오스크 섹션 — 세션, QR 핸드오프, 검색, 무결과율, 일별 세션 추이, 기기별 세션.
 *
 * 작업 지시 필수 요구사항: 이 섹션의 모든 지표(특히 기기별 세션)는 "검색 품질" 지표이지
 * 직원·개인 성과 평가 지표가 아니다 — kiosk_id는 기기 코드일 뿐 사람 식별자가 아니다
 * (types.ts KioskDeviceRow 참고). 화면에도 그 문구를 명시적으로 노출한다.
 */

import { formatDurationMetric, formatMetric } from "../logic";
import type { AggregateCsvRow, KioskAnalyticsResponse } from "../types";
import DailyTrendTable from "./DailyTrendTable";
import MetricCard from "./MetricCard";

export function kioskCsvRows(data: KioskAnalyticsResponse): AggregateCsvRow[] {
  const section = "키오스크";
  const rows: AggregateCsvRow[] = [
    { section, label: "세션 수", value: formatMetric(data.sessions) },
    { section, label: "평균 세션 시간", value: formatMetric(data.avg_session_duration_seconds, { unit: "초" }) },
    { section, label: "QR 핸드오프", value: formatMetric(data.qr_handoffs) },
    { section, label: "검색 수", value: formatMetric(data.searches) },
    { section, label: "무결과율", value: formatMetric(data.zero_result_rate, { percent: true }) },
  ];
  if (data.search_completion_rate) {
    rows.push({ section, label: "검색 완료율", value: formatMetric(data.search_completion_rate, { percent: true }) });
  }
  if (data.detail_view_rate) {
    rows.push({ section, label: "상세보기 전환율", value: formatMetric(data.detail_view_rate, { percent: true }) });
  }
  if (data.map_view_rate) {
    rows.push({ section, label: "지도 이용률", value: formatMetric(data.map_view_rate, { percent: true }) });
  }
  if (data.error_rate) {
    rows.push({ section, label: "오류율", value: formatMetric(data.error_rate, { percent: true }) });
  }
  for (const device of data.per_device ?? []) {
    rows.push({
      section: "기기별 세션 (검색 품질 지표)",
      label: device.kiosk_id,
      value: `세션 ${formatMetric(device.sessions)} · 무결과율 ${formatMetric(device.zero_result_rate, { percent: true })}`,
    });
  }
  return rows;
}

export default function KioskSection({ data }: { data: KioskAnalyticsResponse }) {
  return (
    <section data-testid="kiosk-section" className="flex flex-col gap-3">
      <h2 className="text-base font-semibold">키오스크</h2>
      <p className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface-muted)] px-3 py-2 text-xs text-[var(--color-text-muted)]">
        이 섹션의 지표는 검색·서비스 품질을 보기 위한 것이며, 특정 직원이나 개인의 성과를 평가하기
        위한 지표가 아닙니다. 키오스크는 로그인·개인정보를 수집하지 않는 익명 세션입니다.
      </p>
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        <MetricCard label="세션 수" metric={data.sessions} />
        <MetricCard label="평균 세션 시간" metric={data.avg_session_duration_seconds} duration />
        <MetricCard label="QR 핸드오프" metric={data.qr_handoffs} />
        <MetricCard label="검색 수" metric={data.searches} />
        <MetricCard label="무결과율" metric={data.zero_result_rate} percent />
        <MetricCard label="검색 완료율" metric={data.search_completion_rate} percent />
        <MetricCard label="상세보기 전환율" metric={data.detail_view_rate} percent />
        <MetricCard label="지도 이용률" metric={data.map_view_rate} percent />
        <MetricCard label="오류율" metric={data.error_rate} percent />
      </div>

      <DailyTrendTable title="일별 키오스크 세션" items={data.daily_sessions} />

      <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
        <p className="mb-2 text-sm font-semibold">
          기기별 세션 <span className="font-normal text-[var(--color-text-muted)]">(검색 품질 지표 — 직원 평가 아님)</span>
        </p>
        {data.per_device && data.per_device.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase text-[var(--color-text-muted)]">
                <tr>
                  <th className="py-1 pr-3">기기 코드</th>
                  <th className="py-1 pr-3">세션</th>
                  <th className="py-1 pr-3">무결과율</th>
                  <th className="py-1">오류율</th>
                </tr>
              </thead>
              <tbody>
                {data.per_device.map((device) => (
                  <tr key={device.kiosk_id} className="border-t border-[var(--color-border)]">
                    <td className="py-1.5 pr-3 font-mono text-xs">{device.kiosk_id}</td>
                    <td className="py-1.5 pr-3">{formatMetric(device.sessions)}</td>
                    <td className="py-1.5 pr-3">{formatMetric(device.zero_result_rate, { percent: true })}</td>
                    <td className="py-1.5">{formatMetric(device.error_rate, { percent: true })}</td>
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
