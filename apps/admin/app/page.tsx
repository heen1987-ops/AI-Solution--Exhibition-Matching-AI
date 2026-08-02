import Link from "next/link";

export default function Home() {
  return (
    <div className="flex flex-col gap-8">
      <div className="rounded-2xl border border-black/10 bg-white p-8 shadow-sm dark:border-white/10 dark:bg-white/5">
        <p className="text-xs font-medium uppercase tracking-wide text-accent">
          Wave 1 - ADM-001
        </p>
        <h1 className="mt-2 text-2xl font-semibold">관리자 준비 화면</h1>
        <p className="mt-4 max-w-2xl text-sm leading-6 text-slate-600 dark:text-slate-300">
          이 화면은 관리자 포털(<code className="rounded bg-black/5 px-1 py-0.5 dark:bg-white/10">apps/admin</code>)의
          라우트 뼈대입니다. 아직 실제 로그인·권한(RBAC)·승인 워크플로우는 구현되어 있지
          않습니다 - 계약(OpenAPI/오류코드)이 확정되고 백엔드 API가 노출된 뒤(Wave 2,
          <code className="rounded bg-black/5 px-1 py-0.5 dark:bg-white/10">ADM-GROUP-001</code>)
          단계적으로 채워집니다.
        </p>
        <ul className="mt-6 flex flex-col gap-2 text-sm text-slate-600 dark:text-slate-300">
          <li>- 실제 인증 없음: 이 화면은 누구나 접근 가능한 정적 placeholder입니다.</li>
          <li>- 실제 API 호출 없음: 표시되는 모든 값은 정적 상수 또는 빌드 시점 환경변수입니다.</li>
          <li>- 승인/통계/검수 등은 아직 데이터를 저장하거나 조회하지 않습니다.</li>
        </ul>
      </div>

      <div className="grid gap-4 sm:grid-cols-2">
        <Link
          href="/console"
          className="rounded-xl border border-black/10 bg-white p-5 transition-colors hover:border-accent dark:border-white/10 dark:bg-white/5"
        >
          <h2 className="text-base font-semibold">운영 콘솔 (예정 목록)</h2>
          <p className="mt-1 text-sm text-slate-600 dark:text-slate-300">
            향후 구현될 14개 관리 영역을 한눈에 보는 안내 목록입니다.
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
