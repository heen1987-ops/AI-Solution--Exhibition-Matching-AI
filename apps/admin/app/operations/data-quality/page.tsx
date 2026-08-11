"use client";

/**
 * 업체별 데이터 품질 화면 (ADMIN-OPERATIONS, WAVE 2E).
 *
 * 완성도 점수는 오직 데이터 존재 요소(필수필드·제품·관심코드·부스·공개소개문·승인상태)로만
 * 계산한다 - CTR/조회수/인기도는 절대 섞지 않는다(`features/data-quality/logic.ts`
 * computeCompletenessScore가 유일한 정본, `features/data-quality/tests/logic.test.ts`가
 * 기계 검증). 이 화면은 그 결과를 표시만 한다.
 *
 * 백엔드 상태: 파이프라인 헬스체크 롤업(`GET /admin/analytics/data-quality`)은 스키마가
 * 확정되었으나(2026-08-03 재조정 - 체크 코드별 OK/WARN/FAIL, `features/data-quality/types.ts`
 * 참고) 라우터 미등록. 업체별 상세 행(`GET /admin/analytics/data-quality/exhibitors`)은
 * 백엔드 자체가 아직 없다(REST 관례 추정 경로, `features/data-quality/api.ts` 참고) - 두 호출
 * 모두 NOT_IMPLEMENTED로 떨어질 수 있으며 화면은 그 상태를 그대로 보여준다.
 */

import { useCallback, useEffect, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";

import { getDataQualityAnalytics, listExhibitorDataQuality } from "@/features/data-quality/api";
import ExhibitorDataQualityTable from "@/features/data-quality/components/ExhibitorDataQualityTable";
import {
  dataQualityCheckStatusLabel,
  sortChecksByStatusSeverity,
  thresholdRatio,
} from "@/features/data-quality/logic";
import type { DataQualityAnalyticsResponse, ExhibitorDataQualityRow } from "@/features/data-quality/types";

const DEMO_EVENT_ID = "00000000-0000-0000-0000-000000000000";

export default function DataQualityPage() {
  const [eventId, setEventId] = useState(DEMO_EVENT_ID);
  const [summary, setSummary] = useState<DataQualityAnalyticsResponse | null>(null);
  const [rows, setRows] = useState<ExhibitorDataQualityRow[] | null>(null);
  const [summaryError, setSummaryError] = useState<unknown>(null);
  const [rowsError, setRowsError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setSummaryError(null);
    setRowsError(null);
    Promise.allSettled([getDataQualityAnalytics(eventId), listExhibitorDataQuality(eventId)]).then(
      ([summaryResult, rowsResult]) => {
        if (summaryResult.status === "fulfilled") setSummary(summaryResult.value);
        else setSummaryError(summaryResult.reason);

        if (rowsResult.status === "fulfilled") setRows(rowsResult.value.items);
        else setRowsError(rowsResult.reason);

        setLoading(false);
      },
    );
  }, [eventId]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-xl font-semibold">업체별 데이터 품질</h1>
        <p className="mt-1 text-xs text-[var(--color-text-muted)]">
          완성도 점수는 데이터 존재 여부만 반영합니다(클릭률·조회수·인기도 미포함).
        </p>
      </div>

      <div className="flex flex-wrap items-end gap-3">
        <Field label="행사 ID" hint="개발용 - 추후 행사 선택 UI로 대체 예정">
          <input
            className="rounded-md border border-[var(--color-border)] bg-[var(--color-surface)] px-2 py-1.5 text-sm"
            value={eventId}
            onChange={(e) => setEventId(e.target.value)}
          />
        </Field>
        <button
          type="button"
          onClick={load}
          className="tap-target rounded-md border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium hover:bg-[var(--color-surface-muted)]"
        >
          새로고침
        </button>
      </div>

      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}

      {!loading && (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold">파이프라인 헬스체크 롤업</h2>
          {summaryError != null && <ErrorBanner error={summaryError} onRetry={load} />}
          {summary && (
            <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3 text-sm">
              <p>
                전체 상태:{" "}
                <span
                  className={
                    summary.overall_status === "FAIL"
                      ? "font-semibold text-[var(--color-danger)]"
                      : summary.overall_status === "WARN"
                        ? "font-semibold text-[var(--color-warning)]"
                        : "font-semibold text-[var(--color-success)]"
                  }
                >
                  {dataQualityCheckStatusLabel(summary.overall_status)}
                </span>
              </p>
              <ul className="mt-2 flex flex-col gap-1 text-xs text-[var(--color-text-muted)]">
                {sortChecksByStatusSeverity(summary.checks).map((check) => {
                  const ratio = thresholdRatio(check);
                  return (
                    <li key={check.check_code}>
                      [{dataQualityCheckStatusLabel(check.status)}] {check.check_code} - 관측값{" "}
                      {check.metric_value ?? "정보 없음"} / 임계값 {check.threshold_value ?? "정보 없음"}
                      {ratio !== null ? ` (임계값 대비 ${Math.round(ratio * 100)}%)` : ""}
                      {check.affected_count !== null ? ` · 영향 ${check.affected_count}건` : ""}
                    </li>
                  );
                })}
              </ul>
            </div>
          )}
        </section>
      )}

      {!loading && (
        <section className="flex flex-col gap-2">
          <h2 className="text-sm font-semibold">업체별 완성도</h2>
          {rowsError != null && <ErrorBanner error={rowsError} onRetry={load} />}
          {rows && <ExhibitorDataQualityTable rows={rows} />}
        </section>
      )}
    </div>
  );
}
