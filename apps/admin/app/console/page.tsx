import { ADMIN_AREAS } from "../../lib/admin-areas";
import { loadAdminConsoleSnapshot } from "../../lib/admin-api";
import { AdminOperationsPanel, ContractPendingPanel } from "./AdminOperationsPanel";

export const dynamic = "force-dynamic";

const STATUS_LABELS = {
  LIVE: "운영",
  CONTRACT_PENDING: "계약 대기",
  PLANNED: "예정",
} as const;

export default async function ConsolePage() {
  const snapshot = await loadAdminConsoleSnapshot();

  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-accent">
          /console
        </p>
        <h1 className="mt-2 text-2xl font-semibold">운영 콘솔</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">
          W-9 MVP 운영 범위를 실제 API 연결 상태와 함께 표시합니다.
        </p>
      </div>

      <p
        className={`rounded-md px-3 py-2 text-xs ${
          snapshot.source === "api"
            ? "bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200"
            : "bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-200"
        }`}
      >
        {snapshot.source === "api"
          ? "백엔드 API 연결 확인됨"
          : `백엔드 API fallback 표시 중${snapshot.notice ? `: ${snapshot.notice}` : ""}`}
      </p>

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="기본 통계">
        {snapshot.metrics.map((metric) => (
          <div
            key={metric.key}
            className="rounded-lg border border-black/10 bg-white p-4 dark:border-white/10 dark:bg-white/5"
          >
            <p className="text-xs text-slate-500 dark:text-slate-400">{metric.label}</p>
            <p className="mt-2 text-lg font-semibold">{metric.value}</p>
          </div>
        ))}
      </section>

      <AdminOperationsPanel />
      <ContractPendingPanel />

      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {ADMIN_AREAS.map((area) => (
          <li key={area.key}>
            <div
              role="group"
              aria-disabled={area.status === "PLANNED" ? "true" : undefined}
              data-testid={`admin-area-${area.key}`}
              className="flex h-full flex-col gap-2 rounded-lg border border-black/10 bg-white p-4 dark:border-white/10 dark:bg-white/5"
            >
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold">{area.title}</h2>
                <span className="shrink-0 rounded-full bg-black/5 px-2.5 py-1 text-xs font-medium text-slate-500 dark:bg-white/10 dark:text-slate-400">
                  {STATUS_LABELS[area.status]}
                </span>
              </div>
              <p className="text-sm text-slate-600 dark:text-slate-300">
                {area.description}
              </p>
              {area.docRef ? (
                <p className="text-xs text-slate-400 dark:text-slate-500">
                  근거: {area.docRef}
                </p>
              ) : null}
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}
