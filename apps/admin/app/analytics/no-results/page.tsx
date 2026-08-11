"use client";

/**
 * 무응답(0건) 검색 운영 화면 (ADMIN-OPERATIONS, WAVE 2E).
 *
 * 컬럼: 정규화 질의 / 해석된 온톨로지 코드(있으면) / 발생 건수 / 채널 / 최초·최근 발생 /
 * PII 마스킹 상태 / 개선 상태 - `features/no-result-operations/components/NoResultOperationsTable.tsx`.
 * 운영자가 원인(`NoResultCause`)을 수동 지정하고 개선 액션을 요청한다 - AI/시스템은 온톨로지·
 * 업체 데이터를 절대 자동 수정하지 않는다(요청/플래그 레코드만 생성, `features/no-result-operations/logic.ts`).
 *
 * 백엔드 상태
 * ----------
 * - 질의 목록(`GET /admin/analytics/no-results`)은 BACKEND-ANALYTICS가 스키마를 확정했지만
 *   라우터가 아직 등록되지 않았다 - 호출은 NOT_IMPLEMENTED로 떨어지고 ErrorBanner가 그대로
 *   보여준다(재시도 가능).
 * - 운영 태스크(원인·액션·상태이력)는 어느 트랙에도 백엔드가 없다. 그래서 태스크 상태머신은
 *   이 화면의 로컬 세션 상태로 동작한다(`features/no-result-operations/logic.ts`의 순수
 *   함수가 유일한 정본 - 서버 확정 전까지 이 로직이 신뢰의 원천이다). 각 조작은 best-effort로
 *   `features/no-result-operations/api.ts`의 추정 경로도 함께 호출하지만 그 결과가 화면
 *   상태를 좌우하지 않는다(실패해도 로컬 상태는 유지 - "가짜 성공"이 아니라 "이 화면은 정직하게
 *   당장 동작하되, 백엔드가 붙으면 자동으로 서버 상태와 합쳐진다"는 뜻).
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import { generateClientId } from "@/lib/api-client";
import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";
import { useSession } from "@/lib/use-session";

import { createOperationsTask, listNoResultQueries, requestImprovementAction, transitionOperationsTask } from "@/features/no-result-operations/api";
import NoResultOperationsTable from "@/features/no-result-operations/components/NoResultOperationsTable";
import {
  applyImprovementAction,
  createTask,
  setTaskCause,
  toOperationsRow,
  TaskTransitionError,
} from "@/features/no-result-operations/logic";
import type {
  ImprovementActionCode,
  NoResultCause,
  NoResultOperationsRow,
  OperationsTask,
} from "@/features/no-result-operations/types";

const DEMO_EVENT_ID = "00000000-0000-0000-0000-000000000000";

export default function NoResultOperationsPage() {
  const [session] = useSession();
  const actor = session.actorUserId ?? session.displayName ?? "unknown-operator";

  const [eventId, setEventId] = useState(DEMO_EVENT_ID);
  const [rows, setRows] = useState<NoResultOperationsRow[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [tasks, setTasks] = useState<Record<string, OperationsTask>>({});
  const [busyQuery, setBusyQuery] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    listNoResultQueries(eventId)
      .then((res) => setRows(res.items.map(toOperationsRow)))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  }, [eventId]);

  useEffect(() => {
    load();
  }, [load]);

  const ensureTask = useCallback(
    (queryNorm: string): OperationsTask => {
      const existing = tasks[queryNorm];
      if (existing) return existing;
      const created = createTask({ task_id: generateClientId(), query_norm: queryNorm, at: new Date().toISOString() });
      setTasks((prev) => ({ ...prev, [queryNorm]: created }));
      // best-effort - 태스크 백엔드가 아직 없으므로(모듈 docstring) 실패해도 로컬 상태는 유지한다.
      createOperationsTask({ event_id: eventId, query_norm: queryNorm }).catch(() => {});
      return created;
    },
    [tasks, eventId],
  );

  const handleAssignCause = useCallback(
    (queryNorm: string, cause: NoResultCause) => {
      const task = ensureTask(queryNorm);
      setTasks((prev) => ({ ...prev, [queryNorm]: setTaskCause(prev[queryNorm] ?? task, cause) }));
      // 원인 필드 자체를 갱신하는 전용 백엔드 엔드포인트가 아직 없다 - 이후 개선 액션 요청에
      // 함께 실려 서버로 전달된다.
    },
    [ensureTask],
  );

  const handleApplyAction = useCallback(
    (queryNorm: string, action: ImprovementActionCode, note: string | null) => {
      const task = tasks[queryNorm] ?? ensureTask(queryNorm);
      setError(null);
      try {
        const at = new Date().toISOString();
        const result = applyImprovementAction(task, action, { actor, at, note });
        setTasks((prev) => ({ ...prev, [queryNorm]: result.task }));
        setNotice(
          result.request
            ? `"${queryNorm}" - ${result.request.action} 요청이 ${result.request.target}에게 등록되었습니다(로컬).`
            : `"${queryNorm}" 태스크가 ${result.task.status} 상태로 전환되었습니다.`,
        );

        setBusyQuery(queryNorm);
        const settle = result.request
          ? requestImprovementAction(task.task_id, { action, note })
          : transitionOperationsTask(task.task_id, { to_status: result.task.status, reason: note });
        settle.catch(() => {}).finally(() => setBusyQuery((cur) => (cur === queryNorm ? null : cur)));
      } catch (err) {
        if (err instanceof TaskTransitionError) {
          setError(err);
        } else {
          throw err;
        }
      }
    },
    [tasks, ensureTask, actor],
  );

  const totalOccurrences = useMemo(
    () => (rows ?? []).reduce((sum, r) => sum + r.occurrence_count, 0),
    [rows],
  );

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">무응답(0건) 검색 운영</h1>
        <span className="text-xs text-[var(--color-text-muted)]">
          AI는 원인을 자동 확정하거나 온톨로지·업체 데이터를 수정하지 않습니다 - 모든 개선은 담당자 요청/플래그입니다.
        </span>
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
        {rows && (
          <span className="text-xs text-[var(--color-text-muted)]">
            질의 {rows.length}종 · 총 발생 {totalOccurrences.toLocaleString("ko-KR")}건
          </span>
        )}
      </div>

      {notice && (
        <p className="rounded-md bg-[var(--color-success-bg)] p-2 text-xs font-medium text-[var(--color-success)]">
          {notice}
        </p>
      )}

      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {!loading && error != null && <ErrorBanner error={error} onRetry={load} />}
      {!loading && rows && (
        <NoResultOperationsTable
          rows={rows}
          tasks={tasks}
          onAssignCause={handleAssignCause}
          onApplyAction={handleApplyAction}
          busyQuery={busyQuery}
        />
      )}
    </div>
  );
}
