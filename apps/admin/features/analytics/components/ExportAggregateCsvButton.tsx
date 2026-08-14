"use client";

/**
 * 집계 수치 전용 CSV 내보내기 버튼.
 *
 * 개인정보 원칙: 개인 단위 데이터의 무제한 CSV 내보내기는 제공하지 않는다.
 * 이 버튼은 현재 화면에 표시된 집계 스칼라(AggregateCsvRow — 섹션/지표명/값)만
 * 내보내며, 억제된 지표는 CSV에서도 "5 미만"으로 유지된다. 원시(개인 단위)
 * 데이터 내보내기 경로는 이 대시보드에 존재하지 않는다.
 */

import { buildAggregateCsv } from "../logic";
import type { AggregateCsvRow } from "../types";

export default function ExportAggregateCsvButton({
  rows,
  filename,
  disabled = false,
}: {
  rows: AggregateCsvRow[];
  filename: string;
  disabled?: boolean;
}) {
  function handleExport() {
    const csv = buildAggregateCsv(rows);
    const blob = new Blob([`﻿${csv}`], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={handleExport}
        disabled={disabled || rows.length === 0}
        className="rounded-md border border-[var(--color-border)] px-3 py-1.5 text-xs font-medium hover:border-[var(--color-brand)] disabled:opacity-50"
      >
        집계 CSV 내보내기
      </button>
      <span className="text-xs text-[var(--color-text-muted)]">
        집계 수치만 포함 · 개인 단위 데이터는 내보낼 수 없습니다
      </span>
    </div>
  );
}
