"use client";

/**
 * 업체별 데이터 품질 표 (ADMIN-OPERATIONS, WAVE 2E).
 *
 * 작업 지시가 요구한 컬럼: 필수필드 완성도(%), 제품/서비스 수, 관심코드 수, 거래조건
 * UNKNOWN 미해소 건수, 문서 검토상태, 검색색인 상태, 최종수정일, 완성도 점수. 완성도
 * 점수는 `../logic.ts::computeCompletenessScore`(데이터 존재 요소만) 결과를 그대로
 * 표시할 뿐 이 컴포넌트가 직접 계산하지 않는다.
 */

import {
  approvalStatusLabel,
  computeCompletenessScore,
  documentReviewStatusLabel,
  requiredFieldsPercentLabel,
  searchIndexStatusLabel,
  toCompletenessInput,
} from "../logic";
import type { ExhibitorDataQualityRow } from "../types";
import CompletenessBadge from "./CompletenessBadge";

function formatDate(iso: string | null): string {
  if (iso === null) return "정보 없음";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toISOString().slice(0, 10);
}

export default function ExhibitorDataQualityTable({ rows }: { rows: ExhibitorDataQualityRow[] }) {
  if (rows.length === 0) {
    return (
      <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-text-muted)]">
        표시할 업체 데이터 품질 정보가 없습니다.
      </p>
    );
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
      <table className="w-full min-w-[980px] text-left text-sm">
        <thead className="bg-[var(--color-surface-muted)] text-xs uppercase text-[var(--color-text-muted)]">
          <tr>
            <th className="px-3 py-2">업체</th>
            <th className="px-3 py-2">필수필드 충족률</th>
            <th className="px-3 py-2">제품/서비스</th>
            <th className="px-3 py-2">관심 코드</th>
            <th className="px-3 py-2">거래조건 UNKNOWN 미해소</th>
            <th className="px-3 py-2">문서 검토상태</th>
            <th className="px-3 py-2">검색 색인상태</th>
            <th className="px-3 py-2">승인 상태</th>
            <th className="px-3 py-2">최종수정일</th>
            <th className="px-3 py-2">완성도</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const completeness = computeCompletenessScore(toCompletenessInput(row));
            return (
              <tr key={row.exhibitor_id} className="border-t border-[var(--color-border)] align-top">
                <td className="px-3 py-2 font-medium">
                  {row.exhibitor_name ?? <span className="font-mono text-xs">{row.exhibitor_id}</span>}
                </td>
                <td className="px-3 py-2">
                  {requiredFieldsPercentLabel(row.required_fields_present, row.required_fields_total)}
                </td>
                <td className="px-3 py-2">{row.product_count.toLocaleString("ko-KR")}건</td>
                <td className="px-3 py-2">{row.interest_code_count.toLocaleString("ko-KR")}개</td>
                <td className="px-3 py-2">
                  {row.unresolved_trade_condition_unknown_count > 0 ? (
                    <span className="font-medium text-[var(--color-warning)]">
                      {row.unresolved_trade_condition_unknown_count}건 확인 필요
                    </span>
                  ) : (
                    "없음"
                  )}
                </td>
                <td className="px-3 py-2">{documentReviewStatusLabel(row.document_review_status)}</td>
                <td className="px-3 py-2">{searchIndexStatusLabel(row.search_index_status)}</td>
                <td className="px-3 py-2">{approvalStatusLabel(row.approval_status)}</td>
                <td className="px-3 py-2">{formatDate(row.last_modified_at)}</td>
                <td className="px-3 py-2">
                  <CompletenessBadge completeness={completeness} />
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
