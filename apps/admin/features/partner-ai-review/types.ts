/**
 * 참가업체 포털 - AI 추출 검수 화면(A-AIREVIEW) 타입.
 *
 * 정본 (실제 구현된 백엔드와 1:1)
 * --------------------------------
 * BACKEND-EXTRACTION 트랙이 실제로 착지했다:
 * - apps/api/app/api/v1/routers/extraction.py `build_extraction_router()`:
 *     GET   /partner/documents/{document_id}/extractions
 *     PATCH /partner/extractions/{extraction_id}
 *     POST  /partner/extractions/{extraction_id}/confirm   (decision: confirm | reject)
 *     POST  /partner/extractions/submit-review             (body: { document_id })
 * - apps/api/app/schemas/extraction.py: EvidenceRead, ExtractedAttributeRead,
 *   ExtractionListResponse, ExtractionPatchRequest, ExtractionConfirmRequest,
 *   SubmitReviewRequest/Response/Rejected/Check - 아래 타입은 그 파일과 필드를 1:1로 맞췄다.
 * - ai/schemas/extraction/attribute_schema.json: 허용 attribute_code 목록(trade.* 접두사가
 *   거래조건, critical 플래그) - 아래 라벨 맵의 근거.
 *
 * 이 파일의 초기 버전은 라우터가 없던 시점의 잠정 계약이었다(AiReviewAttribute /
 * /partner/documents/{id}/ai-review 경로 등). 라우터 착지 후 실제 계약으로 전면 재조정했다.
 *
 * 통합 노트
 * ----------
 * - extraction 라우터는 아직 apps/api/app/api/v1/api.py에 include되지 않았다(integrator
 *   단계). 마운트 전 호출은 FastAPI 전역 404 -> ApiClientError(code: "NOT_IMPLEMENTED")로
 *   화면에 그대로 표시된다(가짜 성공 금지).
 * - 응답 목록(ExtractionListResponse)에는 exhibitor_id가 없다. own-company 격리는 백엔드
 *   `_require_exhibitor_access`(라우터에 실제 구현됨, 403 RESOURCE_FORBIDDEN)가 강제한다.
 * - 작업 지시의 "new-trade-available" 필드는 실제 attribute_schema.json에 대응 코드가 없다
 *   (스키마에 없는 코드는 검증기가 거부하므로 화면도 임의로 만들지 않는다 - 보고서에 플래그).
 */

import type { IsoDateTime, OpenEnum } from "../partner-document/types";

export type { IsoDateTime, OpenEnum };

/** JSON 값 - proposed_value/normalized_value는 백엔드에서 Any(JSONB)다. */
export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

// ---------------------------------------------------------------------------
// apps/api/app/schemas/extraction.py의 Literal들과 1:1
// ---------------------------------------------------------------------------

export type EntityType = OpenEnum<"EXHIBITOR" | "PRODUCT" | "TRADE_CONDITION" | "CERTIFICATE">;

export type FactType = OpenEnum<
  "SOURCE_FACT" | "SELF_DECLARED" | "AI_INFERRED" | "CALCULATED" | "UNKNOWN"
>;

export const FACT_TYPE_LABEL_KO: Record<string, string> = {
  SOURCE_FACT: "원문 근거 있음",
  SELF_DECLARED: "업체 자가신고",
  AI_INFERRED: "AI 추론값 (원문에 명시 없음)",
  CALCULATED: "계산값",
  UNKNOWN: "미확인",
};

export type TemporalValidity = OpenEnum<
  "CURRENT_CAPABILITY" | "PAST_EXPERIENCE" | "FUTURE_PLAN" | "UNKNOWN"
>;

export type ReviewStatus = OpenEnum<
  | "PROPOSED"
  | "CONFIRMED_BY_EXHIBITOR"
  | "MODIFIED_BY_EXHIBITOR"
  | "REJECTED_BY_EXHIBITOR"
  | "APPROVED_BY_OPERATOR"
  | "REJECTED_BY_OPERATOR"
  | "CONFLICTED"
  | "SUPERSEDED"
>;

export const REVIEW_STATUS_LABEL_KO: Record<string, string> = {
  PROPOSED: "검토 대기",
  CONFIRMED_BY_EXHIBITOR: "업체 확인함",
  MODIFIED_BY_EXHIBITOR: "업체 수정함",
  REJECTED_BY_EXHIBITOR: "업체 거절함",
  APPROVED_BY_OPERATOR: "운영자 승인",
  REJECTED_BY_OPERATOR: "운영자 반려",
  CONFLICTED: "충돌 (해소 필요)",
  SUPERSEDED: "대체됨",
};

export type Visibility = OpenEnum<
  "PUBLIC" | "REGISTERED_USER" | "VERIFIED_BUYER" | "MEETING_ACCEPTED" | "OPERATOR_ONLY"
>;

export const VISIBILITY_LEVELS: Visibility[] = [
  "PUBLIC",
  "REGISTERED_USER",
  "VERIFIED_BUYER",
  "MEETING_ACCEPTED",
  "OPERATOR_ONLY",
];

export const VISIBILITY_LABEL_KO: Record<string, string> = {
  PUBLIC: "전체 공개",
  REGISTERED_USER: "등록 사용자",
  VERIFIED_BUYER: "인증 바이어",
  MEETING_ACCEPTED: "상담 확정 후",
  OPERATOR_ONLY: "운영자 전용",
};

// ---------------------------------------------------------------------------
// 거래조건 속성 - ai/schemas/extraction/attribute_schema.json에서 trade_condition=true인
// 실제 attribute_code 목록. 작업 지시의 MOQ/OEM/PB/export/region/lead-time 요구를 이
// 코드들이 커버한다(region은 company.region으로 존재하되 trade_condition 플래그는 아님,
// new-trade-available은 스키마에 없음 - 모듈 docstring 참고).
// ---------------------------------------------------------------------------

export const TRADE_CONDITION_ATTRIBUTE_CODES = [
  "trade.oem_capability",
  "trade.private_label_capability",
  "trade.export_capability",
  "trade.supply_capacity",
  "trade.preferred_trade_types",
  "trade.moq",
  "trade.moq_unit",
  "trade.lead_time_days",
  "trade.payment_terms",
] as const;

export type TradeConditionAttributeCode = (typeof TRADE_CONDITION_ATTRIBUTE_CODES)[number];

/** attribute_code 문자열 하나가 위 목록에 속하는지 판정하는 헬퍼 - `../logic.ts`가
 * entity_type과 함께 이 값을 참조해 화면 강조 여부를 결정한다. */
export function isTradeConditionAttributeCode(code: string): boolean {
  return (TRADE_CONDITION_ATTRIBUTE_CODES as readonly string[]).includes(code);
}

/** ENUM(SUPPORTED/NOT_SUPPORTED) 능력치 속성 - UNKNOWN->긍정값 전이 방어의 주 대상. */
export const CAPABILITY_ENUM_ATTRIBUTE_CODES = [
  "trade.oem_capability",
  "trade.private_label_capability",
  "trade.export_capability",
] as const;

export const CAPABILITY_VALUES = ["SUPPORTED", "NOT_SUPPORTED"] as const;

export const CAPABILITY_VALUE_LABEL_KO: Record<string, string> = {
  SUPPORTED: "가능",
  NOT_SUPPORTED: "불가",
  YES: "가능",
  NO: "불가",
  UNKNOWN: "미확인",
};

/** attribute_schema.json description_ko 기반 표시 라벨 (알 수 없는 코드는 코드 그대로). */
export const ATTRIBUTE_LABEL_KO: Record<string, string> = {
  "company.name": "업체명",
  "company.description": "업체 소개",
  "company.established_year": "설립연도",
  "company.region": "소재 지역",
  "company.certifications": "보유 인증",
  "trade.oem_capability": "OEM 가능여부",
  "trade.private_label_capability": "PB(자체브랜드) 가능여부",
  "trade.export_capability": "수출 가능여부",
  "trade.supply_capacity": "공급 역량",
  "trade.preferred_trade_types": "선호 거래 형태",
  "trade.moq": "최소주문수량(MOQ)",
  "trade.moq_unit": "MOQ 단위",
  "trade.lead_time_days": "리드타임(일)",
  "trade.payment_terms": "결제 조건",
  "product.name": "제품명",
  "product.category": "제품 카테고리",
  "product.ingredients": "원재료",
  "product.abv_percent": "도수(%)",
  "product.taste_notes": "맛 특징",
  "product.aroma_notes": "향 특징",
  "product.price_krw": "가격(원)",
  "product.package_size_ml": "용량(ml)",
  "product.use_cases": "용도",
  "product.features": "특징",
};

// ---------------------------------------------------------------------------
// 응답/요청 모양 - apps/api/app/schemas/extraction.py와 1:1
// ---------------------------------------------------------------------------

export interface EvidenceRead {
  evidence_id: string;
  document_id: string | null;
  segment_ref: string | null;
  page_number: number | null;
  section_title: string | null;
  text_start: number | null;
  text_end: number | null;
  evidence_text: string;
  evidence_hash: string;
}

export interface ExtractedAttributeRead {
  extraction_id: string;
  document_id: string | null;
  ai_run_id: string | null;
  entity_type: EntityType;
  entity_reference: string | null;
  temporary_entity_ref: string | null;
  attribute_code: string;
  /** AI가 문서에서 추출한 원 제안값 (JSONB Any). */
  proposed_value: JsonValue;
  /** 업체가 PATCH로 수정한 값 - 수정 전이라면 백엔드 초기값(보통 제안값과 동일하거나 null). */
  normalized_value: JsonValue;
  /** 온톨로지 개념 코드 목록 - src/meet_ai/ontology/catalog.v1.json(259개)에 대해 검증됨. */
  concept_codes: string[] | null;
  fact_type: FactType;
  temporal_validity: TemporalValidity | null;
  /** 0~1. null이면 신뢰도 정보 없음. */
  confidence: number | null;
  review_status: ReviewStatus;
  visibility: Visibility | null;
  edited_by_exhibitor: boolean;
  evidence: EvidenceRead[];
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  reviewed_by_exhibitor_user_id: string | null;
  reviewed_by_exhibitor_at: IsoDateTime | null;
  reviewed_by_operator_user_id: string | null;
  reviewed_by_operator_at: IsoDateTime | null;
  rejection_reason: string | null;
  superseded_by_extraction_id: string | null;
}

export interface ExtractionListResponse {
  document_id: string;
  items: ExtractedAttributeRead[];
}

/** PATCH는 review_status를 절대 바꾸지 않는다(계약 §9 - 별도 confirm 호출이 필요).
 * reason은 content_review_action 감사로그에 기록된다 - UNKNOWN->긍정 전이 사유를 여기 싣는다. */
export interface ExtractionPatchRequest {
  normalized_value?: JsonValue;
  visibility?: Visibility;
  reason?: string | null;
}

export interface ExtractionConfirmRequest {
  decision: "confirm" | "reject";
  reason?: string | null;
}

export interface SubmitReviewRequest {
  document_id: string;
}

export interface SubmitReviewCheck {
  code: string;
  message: string;
  extraction_id: string | null;
  attribute_code: string | null;
}

export interface SubmitReviewResponse {
  review_request_id: string;
  document_id: string;
  status: string;
  submitted_at: IsoDateTime;
}

/** 422 본문 - 공용 api-client(ApiClientError)는 detail.code/message만 살리고 checks 배열은
 * 떨어뜨린다(공유 파일이라 수정 금지 - 통합 시 checks 노출 여부 검토, 보고서에 플래그).
 * 화면은 항목별 review_status를 이미 보여주므로 치명적이지는 않다. */
export interface SubmitReviewRejected {
  code: string;
  message: string;
  checks: SubmitReviewCheck[];
}
