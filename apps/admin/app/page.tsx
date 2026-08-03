import Link from "next/link";

export default function Home() {
  return (
    <div className="flex flex-col gap-8">
      <div className="rounded-2xl border border-black/10 bg-white p-8 shadow-sm dark:border-white/10 dark:bg-white/5">
        <p className="text-xs font-medium uppercase tracking-wide text-accent">
          Wave 2 - ADM-GROUP-001
        </p>
        <h1 className="mt-2 text-2xl font-semibold">관리자 운영 화면</h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">
          이 화면은 관리자 포털(<code className="rounded bg-black/5 px-1 py-0.5 dark:bg-white/10">apps/admin</code>)의
          운영 진입점입니다. 업체 승인과 부스 상태 변경은 백엔드 API를 호출하고, 바이어
          검증·집계 통계는 아직 계약 대기 상태로 표시합니다.
        </p>
        <ul className="mt-6 flex flex-col gap-2 text-sm text-slate-600 dark:text-slate-300">
          <li>- 운영자 헤더는 로컬 환경변수로 주입합니다.</li>
          <li>- 백엔드가 없으면 콘솔은 fallback 상태를 표시합니다.</li>
          <li>- 미승인 업체는 공개 검색·추천에 노출하지 않는 운영 흐름을 유지합니다.</li>
        </ul>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Link
          href="/console"
          className="rounded-xl border border-black/10 bg-white p-5 transition-colors hover:border-accent dark:border-white/10 dark:bg-white/5"
        >
          <h2 className="text-base font-semibold">운영 콘솔</h2>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            승인, 부스 상태, 바이어 검증, 기본 통계 상태를 확인합니다.
          </p>
        </Link>
        <Link
          href="/health"
          className="rounded-xl border border-black/10 bg-white p-5 transition-colors hover:border-accent dark:border-white/10 dark:bg-white/5"
        >
          <h2 className="text-base font-semibold">관리자 앱 상태</h2>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            빌드/환경 정보와 이번 Wave의 구현 범위 점검표를 확인합니다.
          </p>
        </Link>
      </div>
    </div>
  );
}
