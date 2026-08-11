"use client";

/**
 * 참가업체 포털 - 문서함 (A-DOC). 작업 지시 필수 요구사항: 문서 목록(이름, 유형, 업로드일,
 * 처리상태, 추출진행률, 오류, 검수상태).
 *
 * own-company-only: EXHIBITOR_ADMIN 역할은 세션의 exhibitorId로 조회를 고정하고, 응답도
 * `filterOwnCompanyOnly`로 한 번 더 방어적으로 거른다(백엔드가 partner.py
 * `_require_exhibitor_access`와 동일한 검사를 해야 한다는 전제 - features/partner-document/api.ts
 * 참고). EVENT_ADMIN/DATA_REVIEWER는 검수 목적상 임의 업체를 조회할 수 있다.
 */

import { useCallback, useEffect, useMemo, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import Field from "@/components/Field";
import RoleGate from "@/components/RoleGate";
import { hasCapability } from "@/lib/auth-state";
import { useSession } from "@/lib/use-session";

import { listPartnerDocuments } from "@/features/partner-document/api";
import DocumentsTable from "@/features/partner-document/components/DocumentsTable";
import { documentStatusLabel, filterOwnCompanyOnly } from "@/features/partner-document/logic";
import type { DocumentRead, DocumentStatus } from "@/features/partner-document/types";

const STATUS_FILTERS: DocumentStatus[] = ["UPLOADED", "PROCESSING", "PROCESSED", "PROCESSING_FAILED"];

export default function PartnerDocumentsPage() {
  return (
    <RoleGate
      capability="EXHIBITOR_EDIT_OWN"
      fallback={
        <RoleGate
          capability="EXHIBITOR_REVIEW"
          fallback={<NoAccessNotice />}
        >
          <DocumentsBody />
        </RoleGate>
      }
    >
      <DocumentsBody />
    </RoleGate>
  );
}

function NoAccessNotice() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">문서함</h1>
      <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-text-muted)]">
        현재 역할에는 문서함 조회 권한이 없습니다.
      </p>
    </div>
  );
}

function DocumentsBody() {
  const [session] = useSession();
  const isExhibitorAdmin = session.role === "EXHIBITOR_ADMIN";
  const canReviewAny = hasCapability(session.role, "EXHIBITOR_REVIEW");

  const [exhibitorIdInput, setExhibitorIdInput] = useState(session.exhibitorId ?? "");
  const [statusFilter, setStatusFilter] = useState<DocumentStatus | "">("");
  const [items, setItems] = useState<DocumentRead[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (isExhibitorAdmin) setExhibitorIdInput(session.exhibitorId ?? "");
  }, [isExhibitorAdmin, session.exhibitorId]);

  const effectiveExhibitorId = isExhibitorAdmin ? session.exhibitorId : exhibitorIdInput.trim() || null;

  const search = useCallback(() => {
    if (!effectiveExhibitorId) {
      setItems(null);
      return;
    }
    setLoading(true);
    setError(null);
    listPartnerDocuments({
      exhibitor_id: effectiveExhibitorId,
      status: statusFilter || undefined,
    })
      .then((res) => setItems(res.items))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveExhibitorId, statusFilter]);

  useEffect(() => {
    search();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [effectiveExhibitorId]);

  const scopedItems = useMemo(
    () => (items ? filterOwnCompanyOnly(items, session.role, session.exhibitorId) : null),
    [items, session.role, session.exhibitorId],
  );

  return (
    <div className="flex flex-col gap-6">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h1 className="text-xl font-semibold">문서함</h1>
      </div>

      {isExhibitorAdmin && !session.exhibitorId && (
        <p className="rounded-lg border border-dashed border-[var(--color-warning)] bg-[var(--color-warning-bg)] p-3 text-sm text-[var(--color-warning)]">
          자사 업체 ID가 세션에 설정되어 있지 않습니다. 상단의 세션 전환기에서 업체 ID를
          먼저 지정해 주세요.
        </p>
      )}

      <form
        onSubmit={(event) => {
          event.preventDefault();
          search();
        }}
        className="flex flex-wrap items-end gap-3 rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4"
      >
        <div className="min-w-[240px]">
          <Field label="업체 ID" hint={isExhibitorAdmin ? "자사 업체로 고정됨" : "비워두면 조회하지 않음"}>
            <input
              value={exhibitorIdInput}
              onChange={(event) => setExhibitorIdInput(event.target.value)}
              className="input font-mono text-xs"
              placeholder="UUID"
              disabled={isExhibitorAdmin}
              readOnly={isExhibitorAdmin}
            />
          </Field>
        </div>
        <div className="min-w-[180px]">
          <Field label="처리상태 필터">
            <select
              value={statusFilter}
              onChange={(event) => setStatusFilter(event.target.value as DocumentStatus | "")}
              className="input"
            >
              <option value="">전체</option>
              {STATUS_FILTERS.map((status) => (
                <option key={status} value={status}>
                  {documentStatusLabel(status)}
                </option>
              ))}
            </select>
          </Field>
        </div>
        <button
          type="submit"
          className="tap-target rounded-md border border-[var(--color-brand)] px-4 py-2 text-sm font-medium text-[var(--color-brand)]"
        >
          검색
        </button>
      </form>

      {!effectiveExhibitorId && !isExhibitorAdmin && (
        <p className="text-sm text-[var(--color-text-muted)]">
          {canReviewAny ? "업체 ID를 입력해 문서를 조회하세요." : "조회할 업체를 지정해 주세요."}
        </p>
      )}

      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {!loading && error ? <ErrorBanner error={error} onRetry={search} /> : null}

      {!loading && !error && scopedItems && <DocumentsTable items={scopedItems} />}

      <p className="text-xs text-[var(--color-text-muted)]">
        표시 항목 근거: <code>apps/api/app/schemas/document.py</code> DocumentRead(실제 구현된
        스키마, 라우터 미구현 - <code>features/partner-document/types.ts</code> 모듈 docstring
        참고). 목록 API가 아직 없어 위 표는 <code>NOT_IMPLEMENTED</code> 오류로 대체 표시될 수
        있습니다.
      </p>
    </div>
  );
}
