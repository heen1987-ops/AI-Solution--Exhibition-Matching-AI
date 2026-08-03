import { getAdminEnvInfo } from "../../lib/env";

const IMPLEMENTATION_CHECKLIST = [
  { label: "라우트 뼈대(/, /health, /console)", state: "완료" },
  { label: "Tailwind CSS 빌드", state: "완료" },
  { label: "실제 로그인/인증", state: "미구현 (예정)" },
  { label: "RBAC/권한 분기", state: "미구현 (예정)" },
  { label: "승인·바이어 검증·통계 실 API 연동", state: "미구현 (Wave 2, ADM-GROUP-001)" },
] as const;

export default function HealthPage() {
  const env = getAdminEnvInfo();

  return (
    <div className="flex flex-col gap-8">
      <div>
        <p className="text-xs font-medium uppercase tracking-wide text-accent">
          /health
        </p>
        <h1 className="mt-2 text-2xl font-semibold">관리자 앱 상태</h1>
        <p className="mt-3 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">
          이 화면은 백엔드에 어떤 요청도 보내지 않습니다 - 아래 값은 빌드 시점에 주입된
          공개 환경변수(<code>NEXT_PUBLIC_*</code>)와 정적 상수입니다.
        </p>
      </div>

      <section className="rounded-xl border border-black/10 bg-white p-6 dark:border-white/10 dark:bg-white/5">
        <h2 className="text-sm font-semibold text-slate-500 dark:text-slate-400">
          환경 정보
        </h2>
        <dl className="mt-4 grid grid-cols-1 gap-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-slate-500 dark:text-slate-400">앱 이름</dt>
            <dd className="font-medium">{env.appName}</dd>
          </div>
          <div>
            <dt className="text-slate-500 dark:text-slate-400">환경</dt>
            <dd className="font-medium">{env.environment}</dd>
          </div>
          <div>
            <dt className="text-slate-500 dark:text-slate-400">API Base URL (미사용)</dt>
            <dd className="font-medium">{env.apiBaseUrl}</dd>
          </div>
          <div>
            <dt className="text-slate-500 dark:text-slate-400">계약 버전</dt>
            <dd className="font-medium">{env.contractVersion}</dd>
          </div>
        </dl>
      </section>

      <section className="rounded-xl border border-black/10 bg-white p-6 dark:border-white/10 dark:bg-white/5">
        <h2 className="text-sm font-semibold text-slate-500 dark:text-slate-400">
          이번 Wave 구현 범위 점검
        </h2>
        <ul className="mt-4 flex flex-col gap-2 text-sm">
          {IMPLEMENTATION_CHECKLIST.map((item) => (
            <li key={item.label} className="flex items-center justify-between gap-4">
              <span>{item.label}</span>
              <span className="rounded-full bg-black/5 px-3 py-1 text-xs font-medium text-slate-600 dark:bg-white/10 dark:text-slate-300">
                {item.state}
              </span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
}
