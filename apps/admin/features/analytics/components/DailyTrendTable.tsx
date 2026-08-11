"use client";

/**
 * 일자별 추이 미니 테이블 (외부 차트 라이브러리 의존 없이 막대 폭으로 표현).
 * 입력은 이미 집계·정화된 DailyCount[]만 받는다.
 */

import type { DailyCount } from "../types";

export default function DailyTrendTable({
  title,
  items,
}: {
  title: string;
  items: DailyCount[];
}) {
  const max = Math.max(1, ...items.map((item) => item.count));
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4">
      <p className="mb-2 text-sm font-semibold">{title}</p>
      {items.length === 0 ? (
        <p className="text-sm text-[var(--color-text-muted)]">해당 기간 데이터가 없습니다.</p>
      ) : (
        <table className="w-full text-sm">
          <tbody>
            {items.map((item) => (
              <tr key={item.activity_date}>
                <td className="w-28 py-0.5 pr-2 text-xs text-[var(--color-text-muted)]">
                  {item.activity_date}
                </td>
                <td className="py-0.5">
                  <div className="flex items-center gap-2">
                    <div
                      className="h-2 rounded bg-[var(--color-brand)]"
                      style={{ width: `${Math.max(2, Math.round((item.count / max) * 100))}%` }}
                    />
                    <span className="text-xs">{item.count.toLocaleString("ko-KR")}</span>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
