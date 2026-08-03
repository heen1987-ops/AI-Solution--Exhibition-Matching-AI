import Link from "next/link";

/**
 * "/" - 사용자 웹 준비 화면 (WEB-001 acceptance).
 *
 * 실제 개인화 홈(S-1, `/home`)이 아니다 - 로그인·개인화 로직 없이, 이 앱이
 * 정상 기동했음을 보여주고 화면 뼈대(S-1~S-8) 및 상태 점검(/health)으로 이동하는
 * 진입점 역할만 한다.
 */
export default function ReadyPage() {
  return (
    <div className="flex flex-1 flex-col items-center justify-center gap-6 px-6 py-16 text-center">
      <span className="rounded-full bg-emerald-100 px-3 py-1 text-xs font-semibold text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200">
        Wave 1 · WEB-001
      </span>
      <h1 className="text-2xl font-semibold text-zinc-900 dark:text-zinc-50">
        사용자 웹 준비 화면
      </h1>
      <p className="max-w-md text-sm text-zinc-600 dark:text-zinc-400">
        백주대간 AI 매칭·탐색 서비스의 웹 초개인화 모듈이 이 서버에서 정상적으로 빌드·기동되었습니다.
        이 화면은 실제 개인화 홈이 아니며, 이번 Wave에서는 라우트 뼈대와 Mock 데이터만 제공합니다.
      </p>
      <div className="flex flex-wrap items-center justify-center gap-3 text-sm">
        <Link
          href="/health"
          className="rounded-full bg-zinc-900 px-4 py-2 font-medium text-white hover:bg-zinc-700 dark:bg-zinc-100 dark:text-zinc-900"
        >
          빌드·환경 상태 보기 (/health)
        </Link>
        <Link
          href="/home"
          className="rounded-full border border-zinc-300 px-4 py-2 font-medium text-zinc-700 hover:bg-zinc-100 dark:border-zinc-700 dark:text-zinc-200 dark:hover:bg-zinc-900"
        >
          화면 뼈대 둘러보기 (S-1~S-8)
        </Link>
      </div>
    </div>
  );
}
