"use client";

/**
 * 참가업체 포털 - AI 추출 검수 화면 (A-AIREVIEW).
 *
 * 작업 지시 필수 요구사항:
 *   - 속성별로 AI 제안값·신뢰도(완곡 지표)·근거텍스트+페이지/섹션·온톨로지 코드·공개범위·
 *     confirm/modify/delete 동작을 보여준다(`features/partner-ai-review/components/AttributeCard.tsx`).
 *   - 거래조건 필드(MOQ/OEM/PB/수출/지역/리드타임)는 시각적으로 강조한다("신규거래가능"은
 *     `ai/schemas/extraction/attribute_schema.json`에 대응 코드가 없어 커버하지 못한다 -
 *     `features/partner-ai-review/types.ts` 모듈 docstring에 플래그됨).
 *   - UNKNOWN -> YES 전이는 침묵 토글이 아니라 명시적 확인 단계(+ 사유)를 요구한다.
 *   - Submit-for-review 버튼이 BACKEND-EXTRACTION의 submit-review 엔드포인트를 호출한다
 *     (`features/partner-ai-review/components/SubmitReviewSection.tsx`).
 *
 * 2026-08-03 재조정: BACKEND-EXTRACTION 라우터가 착지한 실제 계약(`ExtractionListResponse`)에
 * 맞춰 다시 썼다. own-company-only에 대한 중요한 차이: 이전 버전은 (당시 잠정 계약의)
 * 응답에 `exhibitor_id`가 있다고 가정해 세션의 exhibitorId와 클라이언트에서 직접 비교했다.
 * 실제 착지한 `ExtractionListResponse`/`ExtractedAttributeRead`에는 exhibitor_id 필드가 없다
 * (`features/partner-ai-review/types.ts` 참고) - own-company 격리는 백엔드
 * `_require_exhibitor_access`가 유일한 방어선이고, 위반 시 403 RESOURCE_FORBIDDEN을 던진다.
 * 이 화면은 그 오류를 `ErrorBanner`로 있는 그대로 보여주는 것으로 방어를 대신한다(데이터를
 * 성공으로 위장해 노출하지 않는다는 원칙은 동일하게 지킨다).
 */

import { useParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useState } from "react";

import ErrorBanner from "@/components/ErrorBanner";
import RoleGate from "@/components/RoleGate";

import { listExtractions } from "@/features/partner-ai-review/api";
import AttributeCard from "@/features/partner-ai-review/components/AttributeCard";
import SubmitReviewSection from "@/features/partner-ai-review/components/SubmitReviewSection";
import { isTradeConditionAttribute } from "@/features/partner-ai-review/logic";
import type { ExtractedAttributeRead } from "@/features/partner-ai-review/types";

export default function PartnerAiReviewPage() {
  return (
    <RoleGate
      capability="EXHIBITOR_EDIT_OWN"
      fallback={
        <RoleGate capability="EXHIBITOR_REVIEW" fallback={<NoAccessNotice />}>
          <ReviewBody />
        </RoleGate>
      }
    >
      <ReviewBody />
    </RoleGate>
  );
}

function NoAccessNotice() {
  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-xl font-semibold">AI 추출 검수</h1>
      <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface)] p-4 text-sm text-[var(--color-text-muted)]">
        현재 역할에는 AI 검수 권한이 없습니다.
      </p>
    </div>
  );
}

function ReviewBody() {
  const params = useParams<{ documentId: string }>();
  const documentId = params.documentId;

  const [attributes, setAttributes] = useState<ExtractedAttributeRead[] | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [loading, setLoading] = useState(true);

  const load = useCallback(() => {
    setLoading(true);
    setError(null);
    listExtractions(documentId)
      .then((res) => setAttributes(res.items))
      .catch((err) => setError(err))
      .finally(() => setLoading(false));
  }, [documentId]);

  useEffect(() => {
    load();
  }, [load]);

  const updateAttribute = useCallback((updated: ExtractedAttributeRead) => {
    setAttributes((prev) =>
      prev ? prev.map((a) => (a.extraction_id === updated.extraction_id ? updated : a)) : prev,
    );
  }, []);

  const { tradeConditionAttrs, otherAttrs } = useMemo(() => {
    const list = attributes ?? [];
    return {
      tradeConditionAttrs: list.filter((a) => isTradeConditionAttribute(a)),
      otherAttrs: list.filter((a) => !isTradeConditionAttribute(a)),
    };
  }, [attributes]);

  const pendingCount = (attributes ?? []).filter((a) => a.review_status === "PROPOSED").length;

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">AI 추출 검수</h1>
        <span className="text-xs text-[var(--color-text-muted)]">document_id: {documentId}</span>
      </div>

      {loading && <p className="text-sm text-[var(--color-text-muted)]">불러오는 중…</p>}
      {!loading && error ? <ErrorBanner error={error} onRetry={load} /> : null}

      {!loading && !error && attributes && (
        <>
          <p className="rounded-lg border border-[var(--color-border)] bg-[var(--color-surface-muted)] p-3 text-xs text-[var(--color-text-muted)]">
            아래 신뢰도는 AI의 참고 지표일 뿐 확정된 사실이 아닙니다. 모든 항목은 사람이 직접
            확인(confirm)하거나 수정(modify)해야 최종 반영됩니다.
          </p>

          {tradeConditionAttrs.length > 0 && (
            <section className="flex flex-col gap-3 rounded-lg border-2 border-[var(--color-brand)] bg-[var(--color-surface)] p-4">
              <h2 className="text-base font-semibold text-[var(--color-brand)]">
                거래조건 항목 (중요 - 매칭·상담에 직접 사용됩니다)
              </h2>
              <div className="flex flex-col gap-3">
                {tradeConditionAttrs.map((attribute) => (
                  <AttributeCard
                    key={attribute.extraction_id}
                    attribute={attribute}
                    emphasized
                    onChange={updateAttribute}
                  />
                ))}
              </div>
            </section>
          )}

          {otherAttrs.length > 0 && (
            <section className="flex flex-col gap-3">
              <h2 className="text-base font-semibold">일반 항목</h2>
              <div className="flex flex-col gap-3">
                {otherAttrs.map((attribute) => (
                  <AttributeCard
                    key={attribute.extraction_id}
                    attribute={attribute}
                    emphasized={false}
                    onChange={updateAttribute}
                  />
                ))}
              </div>
            </section>
          )}

          {attributes.length === 0 && (
            <p className="text-sm text-[var(--color-text-muted)]">AI가 추출한 속성이 없습니다.</p>
          )}

          <SubmitReviewSection documentId={documentId} pendingCount={pendingCount} />
        </>
      )}
    </div>
  );
}
