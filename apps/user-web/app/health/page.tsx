import { StatusBadge } from "@/components/StateViews";
import packageJson from "../../package.json";

/**
 * "/health" - 프런트엔드 빌드/환경 상태 화면 (WEB-001 acceptance).
 *
 * 백엔드에 실제로 접속하지 않는 정적/로컬 상태 표시다 - 이 페이지가 렌더링됐다는
 * 사실 자체가 "빌드·기동 성공"의 증거이며, 여기서는 프런트가 기대하는 환경변수가
 * 설정돼 있는지만 확인한다. 실제 백엔드 헬스체크(GET /health/live, /health/ready)는
 * BAC-001에서 제공되며, 이 화면과 무관하다.
 */
export default function HealthPage() {
  const apiBaseUrl = process.env.NEXT_PUBLIC_API_BASE_URL;
  const appEnv = process.env.NEXT_PUBLIC_APP_ENV ?? "unset";
  const nodeEnv = process.env.NODE_ENV;
  const checkedAt = new Date().toISOString();

  const checks: Array<{ label: string; ok: boolean; value: string }> = [
    {
      label: "NEXT_PUBLIC_API_BASE_URL",
      ok: Boolean(apiBaseUrl),
      value: apiBaseUrl ?? "(설정되지 않음)",
    },
    {
      label: "NEXT_PUBLIC_APP_ENV",
      ok: appEnv !== "unset",
      value: appEnv,
    },
  ];
  const allOk = checks.every((check) => check.ok);

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-1 flex-col gap-6 px-6 py-12">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-zinc-900 dark:text-zinc-50">
          프런트엔드 빌드·환경 상태
        </h1>
        <StatusBadge tone={allOk ? "ok" : "warn"}>{allOk ? "OK" : "환경변수 확인 필요"}</StatusBadge>
      </div>

      <dl className="grid grid-cols-1 gap-3 rounded-lg border border-zinc-200 p-4 text-sm dark:border-zinc-800">
        <div className="flex justify-between">
          <dt className="text-zinc-500 dark:text-zinc-400">서비스</dt>
          <dd className="font-medium text-zinc-900 dark:text-zinc-50">
            {packageJson.name} v{packageJson.version}
          </dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-zinc-500 dark:text-zinc-400">NODE_ENV</dt>
          <dd className="font-medium text-zinc-900 dark:text-zinc-50">{nodeEnv}</dd>
        </div>
        <div className="flex justify-between">
          <dt className="text-zinc-500 dark:text-zinc-400">확인 시각(UTC)</dt>
          <dd className="font-medium text-zinc-900 dark:text-zinc-50">{checkedAt}</dd>
        </div>
      </dl>

      <div className="flex flex-col gap-2">
        <h2 className="text-sm font-semibold text-zinc-700 dark:text-zinc-300">
          환경변수 점검
        </h2>
        <ul className="flex flex-col gap-2">
          {checks.map((check) => (
            <li
              key={check.label}
              className="flex items-center justify-between rounded-md border border-zinc-200 px-3 py-2 text-sm dark:border-zinc-800"
            >
              <span className="text-zinc-600 dark:text-zinc-300">{check.label}</span>
              <span className="flex items-center gap-2">
                <span className="text-xs text-zinc-500 dark:text-zinc-400">{check.value}</span>
                <StatusBadge tone={check.ok ? "ok" : "warn"}>
                  {check.ok ? "설정됨" : "미설정"}
                </StatusBadge>
              </span>
            </li>
          ))}
        </ul>
      </div>

      <p className="text-xs text-zinc-500 dark:text-zinc-400">
        이 화면은 실제 백엔드를 호출하지 않는 정적 상태 표시입니다. 백엔드 자체 헬스체크는
        `GET /health/live`, `/health/ready`(BAC-001)를 참고하세요.
      </p>
    </div>
  );
}
