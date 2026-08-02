import { ADMIN_AREAS } from "../../lib/admin-areas";

export default function ConsolePage() {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-accent">
          /console
        </p>
        <h1 className="mt-2 text-2xl font-semibold">운영 콘솔 (예정 목록)</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">
          아래 {ADMIN_AREAS.length}개 영역은 W-9(관리자 운영 범위)와 공통 플랫폼(C-1~C-8)
          문서가 정의한 향후 관리자 기능입니다. 실제 인증/RBAC이 없는 이번 Wave에는 각
          항목을 비활성(예정) 카드로만 나열합니다 - 클릭해도 이동하지 않습니다.
        </p>
      </div>

      <ul className="grid grid-cols-1 gap-3 sm:grid-cols-2">
        {ADMIN_AREAS.map((area) => (
          <li key={area.key}>
            <div
              role="group"
              aria-disabled="true"
              data-testid={`admin-area-${area.key}`}
              className="flex h-full cursor-not-allowed flex-col gap-2 rounded-xl border border-black/10 bg-white p-5 opacity-80 dark:border-white/10 dark:bg-white/5"
            >
              <div className="flex items-center justify-between gap-3">
                <h2 className="text-sm font-semibold">{area.title}</h2>
                <span className="shrink-0 rounded-full bg-black/5 px-2.5 py-1 text-xs font-medium text-slate-500 dark:bg-white/10 dark:text-slate-400">
                  예정
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
