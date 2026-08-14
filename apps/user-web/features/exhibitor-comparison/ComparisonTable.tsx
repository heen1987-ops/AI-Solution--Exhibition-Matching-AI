"use client";

/**
 * 업체 비교 테이블 (최대 4곳, 가로 스크롤). UNKNOWN은 항상 "확인 필요"로만 표시하고
 * 빈 칸이나 "불가"로 그리지 않는다(작업 지시 원문, `types.ts` 상단 주석 참고).
 */

import type { ReactNode } from "react";

import type { ComparisonExhibitor } from "./types";
import { COMPARISON_ROWS } from "./types";

const UNKNOWN_LABEL = "확인 필요";

function CellValue({ children }: { children: ReactNode }) {
  return <span>{children}</span>;
}

function UnknownCell() {
  return (
    <span
      data-testid="comparison-unknown-cell"
      className="italic"
      style={{ color: "var(--color-text-muted)" }}
    >
      {UNKNOWN_LABEL}
    </span>
  );
}

function renderCell(exhibitor: ComparisonExhibitor, key: (typeof COMPARISON_ROWS)[number]["key"]) {
  switch (key) {
    case "products": {
      if (exhibitor.products.length === 0) return <UnknownCell />;
      return (
        <CellValue>
          {exhibitor.products
            .slice(0, 3)
            .map((product) => product.product_name)
            .join(", ")}
          {exhibitor.products.length > 3 ? ` 외 ${exhibitor.products.length - 3}건` : ""}
        </CellValue>
      );
    }
    case "channels": {
      if (exhibitor.channels === null) return <UnknownCell />;
      return <CellValue>{exhibitor.channels.length > 0 ? exhibitor.channels.join(", ") : UNKNOWN_LABEL}</CellValue>;
    }
    case "regions": {
      if (exhibitor.regions === null) return <UnknownCell />;
      return <CellValue>{exhibitor.regions.length > 0 ? exhibitor.regions.join(", ") : UNKNOWN_LABEL}</CellValue>;
    }
    case "moq": {
      if (exhibitor.moq === null) return <UnknownCell />;
      const { min, max } = exhibitor.moq;
      if (min == null && max == null) return <UnknownCell />;
      return (
        <CellValue>
          {min != null ? min.toLocaleString("ko-KR") : "?"} ~ {max != null ? max.toLocaleString("ko-KR") : "제한 없음"}
        </CellValue>
      );
    }
    case "oemAvailable":
    case "privateLabelAvailable":
    case "exportAvailable":
    case "meetingAvailableToday": {
      const value = exhibitor[key];
      if (value === null) return <UnknownCell />;
      return <CellValue>{value ? "가능" : "불가"}</CellValue>;
    }
    default:
      return <UnknownCell />;
  }
}

export interface ComparisonTableProps {
  exhibitors: ComparisonExhibitor[];
  onRemove?: (exhibitorId: string) => void;
}

export default function ComparisonTable({ exhibitors, onRemove }: ComparisonTableProps) {
  if (exhibitors.length === 0) {
    return (
      <p className="text-sm" style={{ color: "var(--color-text-muted)" }}>
        비교할 업체를 먼저 담아 주세요.
      </p>
    );
  }

  return (
    <div className="w-full overflow-x-auto" role="region" aria-label="업체 비교표">
      <table className="w-full min-w-[560px] border-collapse text-sm">
        <thead>
          <tr>
            <th
              className="sticky left-0 z-10 border-b p-2 text-left align-bottom"
              style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
            >
              항목
            </th>
            {exhibitors.map((exhibitor) => (
              <th
                key={exhibitor.exhibitor_id}
                className="border-b p-2 text-left align-bottom"
                style={{ borderColor: "var(--color-border)", minWidth: "160px" }}
              >
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <p className="font-bold">{exhibitor.company_name}</p>
                    {exhibitor.company_summary ? (
                      <p className="mt-0.5 text-xs font-normal" style={{ color: "var(--color-text-muted)" }}>
                        {exhibitor.company_summary}
                      </p>
                    ) : null}
                  </div>
                  {onRemove ? (
                    <button
                      type="button"
                      onClick={() => onRemove(exhibitor.exhibitor_id)}
                      aria-label={`${exhibitor.company_name} 비교에서 빼기`}
                      className="tap-target rounded-full border text-xs"
                      style={{ borderColor: "var(--color-border)" }}
                    >
                      ✕
                    </button>
                  ) : null}
                </div>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {COMPARISON_ROWS.map((row) => (
            <tr key={row.key}>
              <th
                scope="row"
                className="sticky left-0 z-10 border-b p-2 text-left font-semibold"
                style={{ borderColor: "var(--color-border)", backgroundColor: "var(--color-bg)" }}
              >
                {row.label}
              </th>
              {exhibitors.map((exhibitor) => (
                <td
                  key={`${exhibitor.exhibitor_id}-${row.key}`}
                  className="border-b p-2 align-top"
                  style={{ borderColor: "var(--color-border)" }}
                >
                  {renderCell(exhibitor, row.key)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
