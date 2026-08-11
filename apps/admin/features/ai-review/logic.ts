/**
 * AI 검수 큐의 순수 로직 - 컴포넌트에서 분리해 vitest로 검증한다(`./tests/logic.test.ts`).
 *
 * document-structuring.md §4 binding rule: "운영자 검수 큐는 AI_INFERRED 행을 먼저 보여줄 수
 * 있도록 필터/정렬 가능해야 한다." `AdminReviewQueueItem`은 행 단위 fact_type이 아니라 문서당
 * `ai_inferred_count`만 주므로, 이 파일은 "AI_INFERRED 속성을 더 많이 포함한 문서를 먼저"로
 * 그 요건을 구현한다.
 */

import type { AdminReviewQueueItem, AiReviewQueueRow } from "./types";

export type RiskIndicator = "LOW" | "MEDIUM" | "HIGH";

export const RISK_INDICATOR_LABEL_KO: Record<RiskIndicator, string> = {
  LOW: "낮음",
  MEDIUM: "보통",
  HIGH: "높음",
};

/**
 * 큐 항목 하나의 위험도를 가용한 신호만으로 근사한다(`./types.ts` 계약 공백 4번 - 정확한
 * 근거누락/업체수정 건수가 없어 완벽한 위험도 산정은 불가능하다는 것을 전제로 한 보수적
 * 근사치). 규칙:
 *   - 미해결 충돌이 있으면 무조건 HIGH(충돌은 게시를 막는 하드 블로커이므로).
 *   - AI_INFERRED 비중이 대기 건수의 절반을 넘으면 MEDIUM 이상(완곡한 신뢰도 표시 철학,
 *     `../partner-ai-review/logic.ts`의 confidenceTone과 같은 정신 - 단정적으로 "위험"이라고
 *     하지 않고 "확인이 더 필요함"을 나타낸다).
 *   - 대기 건수가 아예 0이면 LOW(더 볼 것이 없다는 뜻).
 */
export function computeRiskIndicator(
  item: Pick<AdminReviewQueueItem, "has_unresolved_conflict" | "ai_inferred_count" | "pending_extraction_count">,
): RiskIndicator {
  if (item.has_unresolved_conflict) return "HIGH";
  if (item.pending_extraction_count <= 0) return "LOW";
  const aiInferredRatio = item.ai_inferred_count / item.pending_extraction_count;
  if (aiInferredRatio >= 0.5) return "MEDIUM";
  return "LOW";
}

/** `AdminReviewQueueItem`(백엔드가 실제로 주는 것)을 화면 표시용 `AiReviewQueueRow`로
 * 변환한다. 백엔드가 아직 주지 않는 컬럼은 `null`로 남긴다(값을 지어내지 않는다 -
 * `./types.ts` 모듈 docstring 계약 공백 4번). */
export function toQueueRow(item: AdminReviewQueueItem): AiReviewQueueRow {
  return {
    review_request_id: item.review_request_id,
    document_id: item.document_id,
    exhibitor_id: item.exhibitor_id,
    exhibitor_name: null,
    document_type: null,
    status: item.status,
    submitted_at: item.submitted_at,
    pending_extraction_count: item.pending_extraction_count,
    ai_inferred_count: item.ai_inferred_count,
    has_unresolved_conflict: item.has_unresolved_conflict,
    evidence_missing_count: null,
    exhibitor_modified_count: null,
    risk_indicator: computeRiskIndicator(item),
  };
}

export function toQueueRows(items: AdminReviewQueueItem[]): AiReviewQueueRow[] {
  return items.map(toQueueRow);
}

const RISK_ORDER: Record<RiskIndicator, number> = { HIGH: 0, MEDIUM: 1, LOW: 2 };

/** document-structuring.md §4 요건: AI_INFERRED가 많은(=확인이 더 필요한) 문서를 먼저 보여
 * 준다. 동률이면 위험도, 그다음 제출일이 이른 순(오래 기다린 것 먼저)으로 정렬한다. 원본
 * 배열을 변형하지 않는다(순수 함수). */
export function sortQueueAiInferredFirst(rows: AiReviewQueueRow[]): AiReviewQueueRow[] {
  return [...rows].sort((a, b) => {
    if (b.ai_inferred_count !== a.ai_inferred_count) return b.ai_inferred_count - a.ai_inferred_count;
    const riskDiff = RISK_ORDER[a.risk_indicator] - RISK_ORDER[b.risk_indicator];
    if (riskDiff !== 0) return riskDiff;
    return new Date(a.submitted_at).getTime() - new Date(b.submitted_at).getTime();
  });
}

export interface QueueFilter {
  status?: string;
  exhibitorId?: string;
}

/** 서버 쿼리 파라미터(`AdminReviewQueueQuery`)와 별개로, 이미 받아온 목록을 클라이언트에서
 * 한 번 더 좁힐 때 쓰는 순수 필터(예: 서버가 필터를 아직 지원하지 않을 때의 폴백). */
export function filterQueueRows(rows: AiReviewQueueRow[], filter: QueueFilter): AiReviewQueueRow[] {
  return rows.filter((row) => {
    if (filter.status && row.status !== filter.status) return false;
    if (filter.exhibitorId && row.exhibitor_id !== filter.exhibitorId) return false;
    return true;
  });
}
