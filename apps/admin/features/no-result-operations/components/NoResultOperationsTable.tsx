"use client";

/**
 * 무응답 검색 운영 표 - 데이터 로딩/세션 로직 없는 순수 표시 컴포넌트
 * (`../../partner-document/components/DocumentsTable.tsx`와 동일 분리 원칙: 네트워크 호출은
 * 화면(`apps/admin/app/analytics/no-results/page.tsx`)이 맡고, 이 컴포넌트는 props만 받는다).
 *
 * 표시 원칙: 백엔드가 아직 주지 않는 축(온톨로지 코드/채널/최초발생 - `../types.ts` 계약
 * 공백 1번)은 "정보 없음"으로 명시한다. 빈 값·0으로 속이지 않는다.
 *
 * 원인 분류(`CauseSelect`)와 개선 액션(`ActionAffordances`)은 별도 컴포넌트로 추출해
 * 독립적으로 단위 테스트한다(`../tests/CauseSelect.test.tsx`, `../tests/ActionAffordances.test.tsx`) -
 * "cause-classification UI"와 "action affordances" 각각을 기계 검증하라는 작업 지시를
 * 그대로 반영한다. 태스크가 아직 없는 행(query_norm 키가 `tasks`에 없음)도 원인 지정·액션
 * 실행이 가능하다 - 화면(page.tsx)이 최초 호출 시 `createTask`로 태스크를 지연 생성한다.
 */

import { TASK_STATUS_LABEL_KO } from "../logic";
import type {
  ImprovementActionCode,
  NoResultCause,
  NoResultOperationsRow,
  OperationsTask,
} from "../types";
import ActionAffordances from "./ActionAffordances";
import CauseSelect from "./CauseSelect";

const UNKNOWN_LABEL = "정보 없음";

export interface NoResultOperationsTableProps {
  rows: NoResultOperationsRow[];
  /** query_norm -> 운영 태스크 (없으면 아직 태스크 미생성 - UNKNOWN/OPEN으로 취급). */
  tasks: Record<string, OperationsTask | undefined>;
  onAssignCause: (queryNorm: string, cause: NoResultCause) => void;
  onApplyAction: (queryNorm: string, action: ImprovementActionCode, note: string | null) => void;
  disabled?: boolean;
  /** 현재 네트워크 호출 중인 질의(있으면 해당 행만 비활성화). disabled보다 좁은 범위. */
  busyQuery?: string | null;
}

export default function NoResultOperationsTable({
  rows,
  tasks,
  onAssignCause,
  onApplyAction,
  disabled = false,
  busyQuery = null,
}: NoResultOperationsTableProps) {
  if (rows.length === 0) {
    return <p className="text-sm text-[var(--color-text-muted)]">무응답 검색 질의가 없습니다.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
      <table className="w-full min-w-[1080px] text-left text-sm">
        <thead className="bg-[var(--color-surface-muted)] text-xs uppercase text-[var(--color-text-muted)]">
          <tr>
            <th className="px-3 py-2">정규화 질의</th>
            <th className="px-3 py-2">온톨로지 코드</th>
            <th className="px-3 py-2">발생 수</th>
            <th className="px-3 py-2">채널</th>
            <th className="px-3 py-2">최초/최근 발생</th>
            <th className="px-3 py-2">PII 마스킹</th>
            <th className="px-3 py-2">개선 상태</th>
            <th className="px-3 py-2">원인 분류</th>
            <th className="px-3 py-2">개선 액션</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const task = tasks[row.query_norm];
            const cause: NoResultCause = task?.cause ?? "UNKNOWN";
            const rowDisabled = disabled || busyQuery === row.query_norm;
            return (
              <tr key={row.query_norm} className="border-t border-[var(--color-border)] align-top">
                <td className="px-3 py-2 font-medium">{row.query_norm}</td>
                <td className="px-3 py-2">
                  {row.resolved_concept_codes === null ? (
                    <span className="text-[var(--color-text-muted)]">{UNKNOWN_LABEL}</span>
                  ) : row.resolved_concept_codes.length === 0 ? (
                    "해석된 코드 없음"
                  ) : (
                    row.resolved_concept_codes.join(", ")
                  )}
                </td>
                <td className="px-3 py-2">{row.occurrence_count.toLocaleString("ko-KR")}</td>
                <td className="px-3 py-2">
                  {row.channel ?? <span className="text-[var(--color-text-muted)]">{UNKNOWN_LABEL}</span>}
                </td>
                <td className="px-3 py-2 text-xs">
                  <div>최초: {row.first_seen_at ? new Date(row.first_seen_at).toLocaleString("ko-KR") : UNKNOWN_LABEL}</div>
                  <div>최근: {row.last_seen_at ? new Date(row.last_seen_at).toLocaleString("ko-KR") : UNKNOWN_LABEL}</div>
                </td>
                <td className="px-3 py-2">
                  {row.pii_masking_status === "SERVER_MASKED" ? (
                    <span className="text-[var(--color-success)]">서버 마스킹됨</span>
                  ) : (
                    <span className="text-[var(--color-warning)]">확인 필요</span>
                  )}
                </td>
                <td className="px-3 py-2">
                  <p>{task ? TASK_STATUS_LABEL_KO[task.status] : "태스크 없음"}</p>
                  {task?.assignee && (
                    <p className="text-xs text-[var(--color-text-muted)]">담당: {task.assignee}</p>
                  )}
                  {task && task.history.length > 0 && (
                    <details className="mt-1 text-xs text-[var(--color-text-muted)]">
                      <summary className="cursor-pointer select-none">이력 {task.history.length}건</summary>
                      <ul className="mt-1 flex flex-col gap-0.5">
                        {task.history.map((entry, idx) => (
                          <li key={idx}>
                            {new Date(entry.at).toLocaleString("ko-KR")} · {entry.actor} ·{" "}
                            {TASK_STATUS_LABEL_KO[entry.from_status]} → {TASK_STATUS_LABEL_KO[entry.to_status]}
                            {entry.reason ? ` (${entry.reason})` : ""}
                          </li>
                        ))}
                      </ul>
                    </details>
                  )}
                </td>
                <td className="px-3 py-2">
                  <CauseSelect
                    label={`원인 분류: ${row.query_norm}`}
                    showLabel={false}
                    value={cause}
                    disabled={rowDisabled}
                    onChange={(nextCause) => onAssignCause(row.query_norm, nextCause)}
                  />
                </td>
                <td className="px-3 py-2">
                  <ActionAffordances
                    cause={cause}
                    busy={rowDisabled}
                    onAction={(action, note) => onApplyAction(row.query_norm, action, note)}
                  />
                  <p className="mt-1 text-[10px] text-[var(--color-text-muted)]">
                    모든 액션은 담당자에게 요청/플래그만 남깁니다 (자동 수정 없음).
                  </p>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
