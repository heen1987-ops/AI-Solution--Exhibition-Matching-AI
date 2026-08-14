"use client";

/**
 * 문서 목록 표 - `app/partner/documents/page.tsx`에서 데이터 로딩/세션 로직을 뺀 순수 표시
 * 컴포넌트로 분리했다(세션·API 모킹 없이 `items` prop만으로 단위 테스트하기 위함,
 * `../tests/DocumentsTable.test.tsx` 참고).
 */

import Link from "next/link";

import StatusBadge from "@/components/StatusBadge";

import { computeExtractionProgress, documentTypeLabel } from "../logic";
import type { DocumentRead } from "../types";

export default function DocumentsTable({ items }: { items: DocumentRead[] }) {
  if (items.length === 0) {
    return <p className="text-sm text-[var(--color-text-muted)]">등록된 문서가 없습니다.</p>;
  }

  return (
    <div className="overflow-x-auto rounded-lg border border-[var(--color-border)]">
      <table className="w-full text-left text-sm">
        <thead className="bg-[var(--color-surface-muted)] text-xs uppercase text-[var(--color-text-muted)]">
          <tr>
            <th className="px-3 py-2">문서명</th>
            <th className="px-3 py-2">유형</th>
            <th className="px-3 py-2">업로드일</th>
            <th className="px-3 py-2">처리상태</th>
            <th className="px-3 py-2">추출 진행률</th>
            <th className="px-3 py-2">검수상태</th>
            <th className="px-3 py-2 text-right">동작</th>
          </tr>
        </thead>
        <tbody>
          {items.map((item) => {
            const progress = computeExtractionProgress(item.status, undefined);
            return (
              <tr key={item.document_id} className="border-t border-[var(--color-border)] align-top">
                <td className="px-3 py-2 font-medium">{item.filename ?? "(파일명 없음)"}</td>
                <td className="px-3 py-2">{documentTypeLabel(item.document_type)}</td>
                <td className="px-3 py-2">{new Date(item.created_at).toLocaleDateString("ko-KR")}</td>
                <td className="px-3 py-2">
                  <StatusBadge status={item.status} />
                </td>
                <td className="px-3 py-2">
                  <span className={progress.hasError ? "text-[var(--color-danger)]" : ""}>
                    {progress.label} ({progress.percent}%)
                  </span>
                </td>
                <td className="px-3 py-2">
                  {item.is_published ? (
                    <span className="text-[var(--color-success)]">게시됨</span>
                  ) : item.status === "PROCESSED" ? (
                    <span className="text-[var(--color-warning)]">AI 검수 필요</span>
                  ) : (
                    <span className="text-[var(--color-text-muted)]">-</span>
                  )}
                </td>
                <td className="px-3 py-2 text-right">
                  {item.status === "PROCESSED" ? (
                    <Link
                      href={`/partner/ai-review/${encodeURIComponent(item.document_id)}`}
                      className="tap-target text-[var(--color-brand)] underline"
                    >
                      AI 검수
                    </Link>
                  ) : (
                    <span className="text-xs text-[var(--color-text-muted)]">
                      {item.status === "PROCESSING_FAILED" ? "재처리 필요" : "처리 대기중"}
                    </span>
                  )}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
