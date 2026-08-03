/**
 * 공용 로딩/빈결과/오류 상태 뷰. AGENTS.md §5 "오류·로딩·빈 결과 상태 필수" 원칙을
 * 화면마다 반복 구현하지 않도록 공용 컴포넌트로 둔다.
 */

export function EmptyState({
  title,
  description,
}: {
  title: string;
  description?: string;
}) {
  return (
    <div
      role="status"
      className="flex flex-col items-center gap-2 rounded-lg border border-dashed border-zinc-300 bg-zinc-50 px-6 py-10 text-center dark:border-zinc-700 dark:bg-zinc-900"
    >
      <p className="text-sm font-medium text-zinc-600 dark:text-zinc-300">{title}</p>
      {description ? (
        <p className="text-xs text-zinc-500 dark:text-zinc-400">{description}</p>
      ) : null}
    </div>
  );
}

export function ErrorNotice({
  title,
  description,
  onRetry,
}: {
  title: string;
  description?: string;
  onRetry?: () => void;
}) {
  return (
    <div
      role="alert"
      className="flex flex-col items-start gap-2 rounded-lg border border-red-300 bg-red-50 px-6 py-5 text-left dark:border-red-900 dark:bg-red-950"
    >
      <p className="text-sm font-semibold text-red-700 dark:text-red-300">{title}</p>
      {description ? (
        <p className="text-xs text-red-600 dark:text-red-400">{description}</p>
      ) : null}
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="mt-1 rounded-md border border-red-400 px-3 py-1 text-xs font-medium text-red-700 hover:bg-red-100 dark:border-red-700 dark:text-red-300 dark:hover:bg-red-900"
        >
          다시 시도
        </button>
      ) : null}
    </div>
  );
}

export function LoadingSkeleton({ rows = 3 }: { rows?: number }) {
  return (
    <div role="status" aria-label="로딩 중" className="flex flex-col gap-3">
      {Array.from({ length: rows }, (_, index) => `skeleton-row-${index}`).map((key) => (
        <div
          key={key}
          className="h-16 w-full animate-pulse rounded-lg bg-zinc-200 dark:bg-zinc-800"
        />
      ))}
      <span className="sr-only">로딩 중</span>
    </div>
  );
}

export function StatusBadge({
  tone,
  children,
}: {
  tone: "ok" | "warn" | "error";
  children: React.ReactNode;
}) {
  const toneClass =
    tone === "ok"
      ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-900 dark:text-emerald-200"
      : tone === "warn"
        ? "bg-amber-100 text-amber-800 dark:bg-amber-900 dark:text-amber-200"
        : "bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200";
  return (
    <span
      className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-semibold ${toneClass}`}
    >
      {children}
    </span>
  );
}
