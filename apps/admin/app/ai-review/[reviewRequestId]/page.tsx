"use client";

/**
 * 운영자 AI 추출 검수 화면 (ADMIN-AI-REVIEW, WAVE 2D).
 *
 * 속성마다 4-way 비교(AI 원제안 / 업체 확인·수정 / 현재 게시값 / 운영자 최종값)를 보여주고,
 * 속성 단위 승인·반려(사유코드 필수)와 선택 항목 일괄 승인, 문서 단위 보완요청(사유코드
 * 필수), 최종 공개범위 설정을 제공한다. 승인 사전조건이 실패하면 승인 버튼은 비활성화된다
 * (`features/content-approval/logic.ts`의 `evaluateApprovalPrecondition`이 정본).
 *
 * URL: /ai-review/{reviewRequestId}?document_id={documentId}
 *   - 추출 목록 조회는 document_id 기준이고(`features/ai-review/api.ts`
 *     `getDocumentExtractions`), 보완요청은 review_request_id 기준이다 - 큐 테이블이 두 id를
 *     모두 링크에 실어 보낸다. document_id가 없으면 조회 불가를 정직하게 표시한다.
 */

import { useParams, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import RoleGate from "@/components/RoleGate";

import { approveExtraction, getDocumentExtractions } from "@/features/ai-review/api";
import type { ExtractedAttributeRead } from "@/features/ai-review/types";
import AttributeComparisonCard from "@/features/content-approval/components/AttributeComparisonCard";
import RequestChangesSection from "@/features/content-approval/components/RequestChangesSection";
import { buildComparisonRows, bulkApprovePreview } from "@/features/content-approval/logic";

export default function AdminAiReviewDetailPage() {
  return (
    <RoleGate capability="EXHIBITOR_REVIEW" fallback={<NoAccessNotice />}>
      <DetailBody />
    </RoleGate>
  );
}

function NoAccessNotice() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">AI 콘텐츠 검수</h1>
      <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-text-muted)]">
        현재 역할에는 운영자 검수 권한이 없습니다.
      </p>
    </div>
  );
}

function DetailBody() {
  const params = useParams<{ reviewRequestId: string }>();
  const reviewRequestId = params.reviewRequestId;
  const searchParams = useSearchParams();
  const documentId = searchParams.get("document_id");

  const [attributes, setAttributes] = useState<ExtractedAttributeRead[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [bulkNotice, setBulkNotice] = useState<string | null>(null);
  const [bulkError, setBulkError] = useState<unknown>(null);

  const load = useCallback(() => {
    if (!documentId) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setError(null);
    getDocumentExtractions(documentId)
      .then((res) => setAttributes(res.items))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  }, [documentId]);

  useEffect(() => {
    load();
  }, [load]);

  const rows = useMemo(() => buildComparisonRows(attributes ?? []), [attributes]);

  const toggleSelect = useCallback((extractionId: string) => {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(extractionId)) next.delete(extractionId);
      else next.add(extractionId);
      return next;
    });
  }, []);

  const preview = useMemo(() => bulkApprovePreview(rows, selectedIds), [rows, selectedIds]);

  const runBulkApprove = async () => {
    if (preview.approvable.length === 0) return;
    setBulkBusy(true);
    setBulkNotice(null);
    setBulkError(null);
    let approved = 0;
    try {
      // 백엔드에 배치 엔드포인트가 없어(`features/ai-review/api.ts` docstring) 단건 승인을
      // 순차 호출한다. 사전조건 미충족 항목(preview.blocked)은 애초에 호출하지 않는다.
      for (const extractionId of preview.approvable) {
        await approveExtraction(extractionId, {});
        approved += 1;
      }
      setBulkNotice(
        `일괄 승인 ${approved}건 완료` +
          (preview.blocked.length > 0 ? ` · 사전조건 미충족 ${preview.blocked.length}건 건너뜀` : ""),
      );
      setSelectedIds(new Set());
      load();
    } catch (err) {
      setBulkError(err);
      if (approved > 0) setBulkNotice(`오류 발생 전까지 ${approved}건 승인됨 - 목록을 새로고침합니다.`);
      load();
    } finally {
      setBulkBusy(false);
    }
  };

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">AI 콘텐츠 검수</h1>
        <span className="text-xs text-[var(--color-text-muted)]">
          review_request_id: {reviewRequestId}
          {documentId ? ` · document_id: ${documentId}` : ""}
        </span>
      </div>

      {!documentId && (
        <p className="rounded-lg border border-[var(--color-warning)] bg-[var(--color-warning-bg)] p-4 text-sm text-[var(--color-warning)]">
          document_id 쿼리 파라미터가 없어 추출 목록을 조회할 수 없습니다. 검수 큐에서 다시
          진입해 주세요. (큐 응답의 document_id가 null인 검수요청은 문서가 아직 연결되지 않은
          상태입니다.)
        </p>
      )}

      {documentId && loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {documentId && !loading && error != null && <ErrorBanner error={error} onRetry={load} />}

      {documentId && !loading && error == null && attributes && (
        <>
          <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-muted)] p-3 text-xs text-[var(--color-text-muted)]">
            승인된 속성만 게시 대상이 됩니다. AI 추론(AI_INFERRED) 값은 업체 확인 없이는 승인할
            수 없고, 승인 사전조건이 하나라도 미충족이면 승인 버튼이 비활성화됩니다.
          </p>

          {/* ---- 일괄 동작 바 ---- */}
          <div className="flex flex-wrap items-center gap-2 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-3">
            <span className="text-xs text-[var(--color-text-muted)]">
              선택 {selectedIds.size}건 · 승인 가능 {preview.approvable.length}건
              {preview.blocked.length > 0 ? ` · 사전조건 미충족 ${preview.blocked.length}건(제외됨)` : ""}
            </span>
            <button
              type="button"
              onClick={runBulkApprove}
              disabled={bulkBusy || preview.approvable.length === 0}
              className="tap-target rounded-md bg-[var(--color-success)] px-3 py-1.5 text-xs font-semibold text-white disabled:opacity-50"
            >
              {bulkBusy ? "일괄 승인 중…" : "선택 항목 일괄 승인"}
            </button>
          </div>
          {bulkNotice && (
            <p className="rounded-md bg-[var(--color-success-bg)] p-2 text-xs font-medium text-[var(--color-success)]">
              {bulkNotice}
            </p>
          )}
          {bulkError != null && <ErrorBanner error={bulkError} />}

          {/* ---- 속성별 4-way 비교 카드 ---- */}
          <section className="flex flex-col gap-3">
            {rows.map((row) => (
              <AttributeComparisonCard
                key={row.extraction.extraction_id}
                row={row}
                selected={selectedIds.has(row.extraction.extraction_id)}
                onToggleSelect={toggleSelect}
                onDecided={load}
              />
            ))}
            {rows.length === 0 && (
              <p className="text-sm text-[var(--color-text-muted)]">이 문서에는 추출된 속성이 없습니다.</p>
            )}
          </section>

          <RequestChangesSection reviewRequestId={reviewRequestId} onRequested={() => load()} />
        </>
      )}
    </div>
  );
}
