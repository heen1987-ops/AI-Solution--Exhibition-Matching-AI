/**
 * 변경 전후 값 비교 표 (작업 지시 필수 요구사항: "변경 전후 값 비교 표시").
 * 값이 객체/배열이면 JSON으로 직렬화해 보여준다. 값이 같으면 회색, 다르면 강조한다.
 */

export interface DiffRow {
  label: string;
  before: unknown;
  after: unknown;
}

function formatValue(value: unknown): string {
  if (value === null || value === undefined || value === "") return "(없음)";
  if (typeof value === "object") return JSON.stringify(value, null, 0);
  return String(value);
}

export default function DiffTable({ rows, caption }: { rows: DiffRow[]; caption?: string }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
      <table className="w-full text-left text-sm">
        {caption && <caption className="p-2 text-left text-xs text-[var(--color-text-muted)]">{caption}</caption>}
        <thead>
          <tr className="bg-[var(--color-surface-muted)] text-xs uppercase tracking-wide text-[var(--color-text-muted)]">
            <th scope="col" className="px-3 py-2">항목</th>
            <th scope="col" className="px-3 py-2">변경 전</th>
            <th scope="col" className="px-3 py-2">변경 후</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => {
            const before = formatValue(row.before);
            const after = formatValue(row.after);
            const changed = before !== after;
            return (
              <tr key={row.label} className="border-t border-[var(--color-border)]">
                <th scope="row" className="px-3 py-2 align-top font-medium">
                  {row.label}
                </th>
                <td className="px-3 py-2 align-top text-[var(--color-text-muted)]">
                  <span className={changed ? "line-through opacity-70" : ""}>{before}</span>
                </td>
                <td className="px-3 py-2 align-top">
                  <span className={changed ? "font-semibold text-[var(--color-brand)]" : ""}>
                    {after}
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
