/**
 * 운영자 콘텐츠 승인 워크플로 - "4-way 비교 + 승인 사전조건 + 사유코드" 도메인 타입.
 *
 * `../ai-review/**`가 백엔드 원시 계약(무엇을 GET/POST하는가)을 다룬다면, 이 기능은 그 위에
 * 얹는 운영자 업무 규칙(작업 지시 필수 요구사항)을 다룬다:
 *   - 속성 1건당 4가지 값 상태 비교(AI 원제안 / 업체 확인·수정 / 현재 게시값 / 운영자 최종값).
 *   - 승인 버튼을 실제로 눌러도 되는지 판정하는 사전조건 체크리스트(값 부족 시 "거짓 승인
 *     가능" 표시 금지).
 *   - 반려·보완요청에 항상 붙어야 하는 사유코드 9종.
 */

import type {
  EntityType,
  ExtractedAttributeRead,
  FactType,
  JsonValue,
  ReviewStatus,
  TemporalValidity,
  Visibility,
} from "../ai-review/types";

// ---------------------------------------------------------------------------
// 사유코드 - 작업 지시가 명시한 9종. 반려/보완요청 모두에 적용된다(작업 지시 "reason code" +
// 테스트 요구사항 "reason-code required on reject/request-changes").
// ---------------------------------------------------------------------------

export type ReasonCode =
  | "EVIDENCE_MISSING"
  | "VALUE_INCORRECT"
  | "CONFLICT_UNRESOLVED"
  | "VISIBILITY_INCORRECT"
  | "PERSONAL_DATA_INCLUDED"
  | "ONTOLOGY_INVALID"
  | "CURRENT_PAST_MIXED"
  | "TRADE_CONDITION_UNCLEAR"
  | "OTHER";

export const REASON_CODES: ReasonCode[] = [
  "EVIDENCE_MISSING",
  "VALUE_INCORRECT",
  "CONFLICT_UNRESOLVED",
  "VISIBILITY_INCORRECT",
  "PERSONAL_DATA_INCLUDED",
  "ONTOLOGY_INVALID",
  "CURRENT_PAST_MIXED",
  "TRADE_CONDITION_UNCLEAR",
  "OTHER",
];

export const REASON_CODE_LABEL_KO: Record<ReasonCode, string> = {
  EVIDENCE_MISSING: "근거 누락",
  VALUE_INCORRECT: "값이 부정확함",
  CONFLICT_UNRESOLVED: "충돌 미해결",
  VISIBILITY_INCORRECT: "공개범위 오류",
  PERSONAL_DATA_INCLUDED: "개인정보 포함",
  ONTOLOGY_INVALID: "온톨로지 코드 오류",
  CURRENT_PAST_MIXED: "현재-과거 거래조건 혼동",
  TRADE_CONDITION_UNCLEAR: "거래조건 불명확",
  OTHER: "기타",
};

export function isReasonCode(value: string): value is ReasonCode {
  return (REASON_CODES as string[]).includes(value);
}

// ---------------------------------------------------------------------------
// 승인 사전조건 - 작업 지시: "필수 정보 존재, 온톨로지 코드 유효, 근거 존재(또는 업체 명시적
// 확인 존재), 충돌 해소, 개인정보 미검출, 현재-과거 거래조건 비혼동." UI는 이 조건이 실패하면
// "승인 가능한 것처럼" 보여주면 안 된다.
// ---------------------------------------------------------------------------

export type PreconditionCode =
  | "VALUE_OR_VISIBILITY_MISSING" // "필수 정보 존재"
  | "ONTOLOGY_UNVERIFIED" // "온톨로지 코드 유효"
  | "EVIDENCE_OR_CONFIRMATION_MISSING" // "근거 존재(또는 업체 명시적 확인)"
  | "CONFLICT_UNRESOLVED" // "충돌 해소"
  | "POTENTIAL_PII" // "개인정보 미검출"
  | "TEMPORAL_MISMATCH" // "현재-과거 거래조건 비혼동"
  | "AI_INFERRED_NOT_YET_REVIEWED"; // document-structuring.md §4 binding rule

export const PRECONDITION_LABEL_KO: Record<PreconditionCode, string> = {
  VALUE_OR_VISIBILITY_MISSING: "확정값 또는 공개범위가 아직 없습니다",
  ONTOLOGY_UNVERIFIED: "온톨로지 코드를 확인할 수 없습니다",
  EVIDENCE_OR_CONFIRMATION_MISSING: "근거 문서 인용도, 업체의 명시적 확인도 없습니다",
  CONFLICT_UNRESOLVED: "다른 추출과 충돌이 해소되지 않았습니다",
  POTENTIAL_PII: "개인정보로 보이는 내용이 감지되었습니다",
  TEMPORAL_MISMATCH: "현재 거래조건인지 과거/계획인지 확인이 필요합니다",
  AI_INFERRED_NOT_YET_REVIEWED: "AI 추론값은 업체 확인을 먼저 거쳐야 합니다",
};

export interface PreconditionResult {
  code: PreconditionCode;
  /** true = 이 조건은 통과(승인을 막지 않음). */
  ok: boolean;
  /** true = 이 조건은 "확인됨"이 아니라 "아직 알 수 없음"(예: 온톨로지 검증 결과를 백엔드가
   * 노출하지 않음) - 승인은 막되, 사용자에게 "실패"가 아니라 "미확인"으로 보여준다. */
  unknown?: boolean;
}

export interface PreconditionSummary {
  approvable: boolean;
  results: PreconditionResult[];
}

// ---------------------------------------------------------------------------
// 4-way 비교 행 - 작업 지시: "원본 AI 제안값, 업체 확인·수정값, 현재 게시값, [운영자 최종
// 결정]" 4가지를 한 속성마다 나란히 보여준다.
// ---------------------------------------------------------------------------

export interface AttributeComparisonRow {
  extraction: ExtractedAttributeRead;

  // 1) AI 원제안값 - proposed_value는 수정 후에도 항상 보존된다(app/models/extraction.py 참고).
  ai_proposed_value: JsonValue;

  // 2) 업체 확인·수정값 - review_status가 CONFIRMED_BY_EXHIBITOR/MODIFIED_BY_EXHIBITOR에
  // 도달했을 때만 존재한다. 아직 PROPOSED거나 업체가 거절했으면 null(값이 없다는 뜻이지 "AI
  // 값과 같다"는 뜻이 아니다 - exhibitor_decision으로 어느 쪽인지 구분한다).
  exhibitor_value: JsonValue | null;
  exhibitor_decision: "PENDING" | "CONFIRMED" | "MODIFIED" | "REJECTED";

  // 3) 현재 게시값 - `../ai-review/types.ts` 계약 공백 1번: 이걸 채울 API가 아직 없다. 항상
  // null이며, published_value_unavailable=true로 "값이 없다"와 "조회할 방법이 없다"를
  // 구분한다.
  published_value: JsonValue | null;
  published_value_unavailable: boolean;

  // 4) 운영자 최종값 - approve 시 실제로 게시될 값의 미리보기(정책: 업체 확인값이 있으면 그
  // 값, 없으면 AI 원제안값을 기본으로 제시하되 운영자가 화면에서 바꿀 수 있다는 것을
  // buildComparisonRow는 "기본값"만 계산하고 실제 override는 컴포넌트 상태가 갖는다).
  operator_default_value: JsonValue | null;
  operator_default_visibility: Visibility | null;

  entity_type: EntityType;
  fact_type: FactType;
  temporal_validity: TemporalValidity | null;
  confidence: number | null;
  review_status: ReviewStatus;

  precondition: PreconditionSummary;
}
