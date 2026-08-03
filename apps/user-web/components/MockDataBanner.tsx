import type { DataSource } from "@/lib/types";

export function DataSourceBanner({
  source,
  notice,
}: {
  source: DataSource;
  notice?: string;
}) {
  if (source === "api") {
    return (
      <p className="rounded-md bg-emerald-50 px-3 py-2 text-xs text-emerald-800 dark:bg-emerald-950 dark:text-emerald-200">
        실제 백엔드 API 응답을 표시하고 있습니다.
      </p>
    );
  }
  return (
    <p className="rounded-md bg-amber-50 px-3 py-2 text-xs text-amber-800 dark:bg-amber-950 dark:text-amber-200">
      백엔드 API를 사용할 수 없어 fallback 데이터를 표시합니다.
      {notice ? ` ${notice}` : ""}
    </p>
  );
}

export function MockDataBanner() {
  return <DataSourceBanner source="fallback" />;
}
