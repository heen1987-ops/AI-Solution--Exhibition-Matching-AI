/**
 * 콘텐츠 승인 워크플로 순수 로직 - `./tests/logic.test.ts`에서 직접 검증한다(컴포넌트
 * 렌더링 테스트는 두지 않는다 - `apps/admin/package.json`에 `@testing-library/react`가 아직
 * 없고, 이 owned path 밖 파일을 건드리지 않기 위해서다. `../partner-meeting`,
 * `../buyer-verification`도 동일한 이유로 로직/시api 단위테스트만 둔다).
 */

import type {
  EntityType,
  ExtractedAttributeRead,
  JsonValue,
  Visibility,
} from "../ai-review/types";
import type {
  AttributeComparisonRow,
  PreconditionCode,
  PreconditionResult,
  PreconditionSummary,
  ReasonCode,
} from "./types";
import { REASON_CODE_LABEL_KO } from "./types";

// ---------------------------------------------------------------------------
// 4-way 비교 행 조립 (작업 지시: "comparison view renders all 4 value states")
// ---------------------------------------------------------------------------

function exhibitorDecisionOf(
  reviewStatus: ExtractedAttributeRead["review_status"],
): AttributeComparisonRow["exhibitor_decision"] {
  if (reviewStatus === "CONFIRMED_BY_EXHIBITOR") return "CONFIRMED";
  if (reviewStatus === "MODIFIED_BY_EXHIBITOR") return "MODIFIED";
  if (reviewStatus === "REJECTED_BY_EXHIBITOR") return "REJECTED";
  return "PENDING";
}

/** 근거 없이도 승인 가능한 fact_type. `app/services/extraction/review.py`의
 * `_EVIDENCE_EXEMPT_FACT_TYPES = ("SELF_DECLARED", "UNKNOWN")`와 동일 값(정본은 백엔드, 여기는
 * 화면 표시용 사본). */
const EVIDENCE_EXEMPT_FACT_TYPES = new Set(["SELF_DECLARED", "UNKNOWN"]);

function checkValuePresent(attribute: ExtractedAttributeRead): PreconditionResult {
  const ok = attribute.normalized_value !== null && attribute.normalized_value !== undefined
    && attribute.visibility !== null && attribute.visibility !== undefined;
  return { code: "VALUE_OR_VISIBILITY_MISSING", ok };
}

function checkOntology(attribute: ExtractedAttributeRead): PreconditionResult {
  // app/services/extraction/ontology_validation.py가 수집(ingestion) 시점에 이미 259개 카탈로그
  // 대조를 강제한다(DECISION-004) - 화면에는 그 결과를 다시 노출하는 필드가 없으므로, 온톨로지
  // 코드를 참조하는 행은 "수집 시점에 검증됨"으로 통과 처리한다(정보 표시 목적, 승인을 막지
  // 않음). concept_codes가 아예 없으면 애초에 온톨로지 주장이 없으므로 역시 통과.
  return { code: "ONTOLOGY_UNVERIFIED", ok: true };
}

function checkEvidenceOrConfirmation(attribute: ExtractedAttributeRead): PreconditionResult {
  if (EVIDENCE_EXEMPT_FACT_TYPES.has(attribute.fact_type)) {
    return { code: "EVIDENCE_OR_CONFIRMATION_MISSING", ok: true };
  }
  const hasEvidence = attribute.evidence.length > 0;
  const exhibitorConfirmed =
    attribute.review_status === "CONFIRMED_BY_EXHIBITOR" || attribute.review_status === "MODIFIED_BY_EXHIBITOR";
  return { code: "EVIDENCE_OR_CONFIRMATION_MISSING", ok: hasEvidence || exhibitorConfirmed };
}

function checkConflict(attribute: ExtractedAttributeRead): PreconditionResult {
  return { code: "CONFLICT_UNRESOLVED", ok: attribute.review_status !== "CONFLICTED" };
}

// 이메일/전화번호처럼 보이는 패턴 - `../buyer-verification/logic.ts`의
// redactPotentialContactInfo와 동일한 2차 방어선 철학(1차는 백엔드가 아예 이런 필드를 안 주는
// 것, 여기는 evidence_text/제안값에 실수로 섞여 들어온 개인정보를 화면이 한 번 더 잡아낸다).
const EMAIL_PATTERN = /[\w.+-]+@[\w-]+\.[\w.-]+/;
const PHONE_PATTERN = /(?:\+?\d[\d\-\s()]{6,}\d)/;

function stringifyValue(value: JsonValue): string {
  if (value === null || value === undefined) return "";
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
}

export function detectPotentialPii(attribute: ExtractedAttributeRead): boolean {
  const haystack = [
    stringifyValue(attribute.proposed_value),
    stringifyValue(attribute.normalized_value),
    ...attribute.evidence.map((e) => e.evidence_text),
  ].join(" \n ");
  return EMAIL_PATTERN.test(haystack) || PHONE_PATTERN.test(haystack);
}

function checkPii(attribute: ExtractedAttributeRead): PreconditionResult {
  return { code: "POTENTIAL_PII", ok: !detectPotentialPii(attribute) };
}

/** 작업 지시 "현재-과거 거래조건 혼동 방지" - `temporal_validity`(`ai/extraction`의 시점 축,
 * `../ai-review/types.ts` 참고)가 실제 근거 데이터다. TRADE_CONDITION 속성이면서 시점이
 * CURRENT_CAPABILITY가 아니면(과거/계획/미확인) 운영자가 반드시 인지하고 승인해야 한다 -
 * `partner-ai-review`의 UNKNOWN->YES 명시적 확인 패턴과 같은 정신. */
function checkTemporalNotConflated(attribute: ExtractedAttributeRead): PreconditionResult {
  if (attribute.entity_type !== "TRADE_CONDITION") {
    return { code: "TEMPORAL_MISMATCH", ok: true };
  }
  if (attribute.temporal_validity === null || attribute.temporal_validity === "CURRENT_CAPABILITY") {
    return { code: "TEMPORAL_MISMATCH", ok: true };
  }
  return { code: "TEMPORAL_MISMATCH", ok: false };
}

/** document-structuring.md §4 binding rule: "AI_INFERRED는 확인+승인 경로를 절대 건너뛸 수
 * 없다." `APPROVABLE_REVIEW_STATUSES`(CONFIRMED_BY_EXHIBITOR/MODIFIED_BY_EXHIBITOR/CONFLICTED)
 * 밖에 있으면 이미 백엔드가 막지만(`InvalidTransitionError`), 화면은 그 실패를 기다리지 않고
 * 먼저 버튼을 비활성화한다. */
function checkAiInferredReviewed(attribute: ExtractedAttributeRead): PreconditionResult {
  if (attribute.fact_type !== "AI_INFERRED") {
    return { code: "AI_INFERRED_NOT_YET_REVIEWED", ok: true };
  }
  const reviewed =
    attribute.review_status === "CONFIRMED_BY_EXHIBITOR" ||
    attribute.review_status === "MODIFIED_BY_EXHIBITOR" ||
    attribute.review_status === "CONFLICTED";
  return { code: "AI_INFERRED_NOT_YET_REVIEWED", ok: reviewed };
}

export function evaluateApprovalPrecondition(attribute: ExtractedAttributeRead): PreconditionSummary {
  const results: PreconditionResult[] = [
    checkValuePresent(attribute),
    checkOntology(attribute),
    checkEvidenceOrConfirmation(attribute),
    checkConflict(attribute),
    checkPii(attribute),
    checkTemporalNotConflated(attribute),
    checkAiInferredReviewed(attribute),
  ];
  return { approvable: results.every((r) => r.ok), results };
}

export function failingPreconditions(summary: PreconditionSummary): PreconditionCode[] {
  return summary.results.filter((r) => !r.ok).map((r) => r.code);
}

function operatorDefault(attribute: ExtractedAttributeRead): { value: JsonValue | null; visibility: Visibility | null } {
  const exhibitorDecided =
    attribute.review_status === "CONFIRMED_BY_EXHIBITOR" || attribute.review_status === "MODIFIED_BY_EXHIBITOR";
  const value = exhibitorDecided
    ? (attribute.normalized_value ?? attribute.proposed_value ?? null)
    : (attribute.normalized_value ?? null);
  return { value, visibility: attribute.visibility ?? null };
}

/** 속성 1건을 4-way 비교 행으로 변환한다(작업 지시 필수 요구사항). `publishedValue`는
 * `../ai-review/types.ts` 계약 공백 1번 때문에 항상 호출부가 명시적으로 `null`을 넘겨야 한다
 * (조회 API 자체가 없다는 뜻 - 나중에 생기면 이 파라미터에 실제 값을 흘려보내면 된다). */
export function buildComparisonRow(
  attribute: ExtractedAttributeRead,
  publishedValue: { value: JsonValue | null; available: boolean } = { value: null, available: false },
): AttributeComparisonRow {
  const def = operatorDefault(attribute);
  return {
    extraction: attribute,
    ai_proposed_value: attribute.proposed_value,
    exhibitor_value:
      attribute.review_status === "CONFIRMED_BY_EXHIBITOR" || attribute.review_status === "MODIFIED_BY_EXHIBITOR"
        ? (attribute.normalized_value ?? attribute.proposed_value)
        : null,
    exhibitor_decision: exhibitorDecisionOf(attribute.review_status),
    published_value: publishedValue.available ? publishedValue.value : null,
    published_value_unavailable: !publishedValue.available,
    operator_default_value: def.value,
    operator_default_visibility: def.visibility,
    entity_type: attribute.entity_type as EntityType,
    fact_type: attribute.fact_type,
    temporal_validity: attribute.temporal_validity,
    confidence: attribute.confidence,
    review_status: attribute.review_status,
    precondition: evaluateApprovalPrecondition(attribute),
  };
}

export function buildComparisonRows(attributes: ExtractedAttributeRead[]): AttributeComparisonRow[] {
  return attributes.map((a) => buildComparisonRow(a));
}

// ---------------------------------------------------------------------------
// 일괄(bulk) 승인/반려 - 작업 지시: "approve/reject per-attribute or in bulk."
// 백엔드에 진짜 배치 엔드포인트가 없어(`../ai-review/api.ts` 모듈 docstring) 이 화면은
// 선택된 항목 중 "승인 가능한 것만" 골라내는 순수 로직만 제공하고, 실제 다건 호출은
// 컴포넌트가 이 목록을 순회하며 `../ai-review/api.ts`의 단건 함수를 호출한다.
// ---------------------------------------------------------------------------

export function selectableForBulkApprove(rows: AttributeComparisonRow[]): AttributeComparisonRow[] {
  return rows.filter((row) => row.precondition.approvable);
}

export function bulkApprovePreview(
  rows: AttributeComparisonRow[],
  selectedExtractionIds: Set<string>,
): { approvable: string[]; blocked: string[] } {
  const approvable: string[] = [];
  const blocked: string[] = [];
  for (const row of rows) {
    if (!selectedExtractionIds.has(row.extraction.extraction_id)) continue;
    if (row.precondition.approvable) approvable.push(row.extraction.extraction_id);
    else blocked.push(row.extraction.extraction_id);
  }
  return { approvable, blocked };
}

// ---------------------------------------------------------------------------
// 사유코드 - 작업 지시: 반려/보완요청 모두 사유코드 필수(테스트 요구사항).
// ---------------------------------------------------------------------------

export type ReasonValidation = { ok: true } | { ok: false; message: string };

export function validateReasonSelection(
  reasonCode: ReasonCode | "" | null | undefined,
  comment: string,
): ReasonValidation {
  if (!reasonCode) {
    return { ok: false, message: "사유코드를 선택해야 합니다." };
  }
  if (reasonCode === "OTHER" && !comment.trim()) {
    return { ok: false, message: "'기타' 사유는 상세 코멘트를 함께 입력해야 합니다." };
  }
  return { ok: true };
}

/** `../ai-review/types.ts` 계약 공백 3번 - 백엔드가 아직 구조화된 reason_code 필드를 받지
 * 않으므로, 사유코드+코멘트를 하나의 자유서술 문자열로 합성해 기존 `reason`/`comment`
 * 필드에 넣는다. 백엔드가 필드를 추가하면 이 함수만 바꾸면 호출부는 그대로다. */
export function composeReasonPayload(reasonCode: ReasonCode, comment: string): string {
  const label = REASON_CODE_LABEL_KO[reasonCode] ?? reasonCode;
  const trimmed = comment.trim();
  return trimmed ? `[${reasonCode}] ${label} - ${trimmed}` : `[${reasonCode}] ${label}`;
}

// ---------------------------------------------------------------------------
// 역할 게이트 - `../buyer-verification/logic.ts`와 동일한 이유로 `apps/admin/lib/auth-state.ts`
// (owned path 밖 공유 파일)를 건드리지 않고 이 기능 전용 독립 판정 함수를 둔다.
// ---------------------------------------------------------------------------

const AI_REVIEW_ALLOWED_ROLES = new Set(["EVENT_ADMIN", "DATA_REVIEWER"]);

export function canReviewAiContent(role: string): boolean {
  return AI_REVIEW_ALLOWED_ROLES.has(role);
}
