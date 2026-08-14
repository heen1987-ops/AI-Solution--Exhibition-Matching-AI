/**
 * 운영자(operator) AI 추출 검수 큐 + 검수 화면(ADMIN-AI-REVIEW, WAVE 2D) - 원시 데이터 계약.
 *
 * 근거 문서/코드 (우선순위 순 - 먼저 나열한 쪽이 더 정본에 가깝다)
 * ------------------------------------------------------------------
 * 1. `apps/api/app/schemas/extraction.py` - BACKEND-EXTRACTION 트랙이 이미 작성한 실제
 *    Pydantic 스키마(모델·서비스도 존재: `apps/api/app/models/extraction.py`,
 *    `apps/api/app/services/extraction/review.py`). 이 파일의 타입은 그 스키마와 필드를
 *    최대한 1:1로 맞췼다 - `EvidenceRead`, `ExtractedAttributeRead`, `ExtractionListResponse`,
 *    `AdminReviewQueueItem`, `AdminReviewQueueResponse`, `AdminReviewClaimRequest/Response`,
 *    `AdminDecisionRequest/Response`, `AdminRequestChangesRequest/Response`가 전부 그 파일의
 *    동명 클래스에 대응한다.
 * 2. `.harness/contracts/document-structuring.md` (CONTRACTS-STRUCTURING) - §1~§9 상태머신·
 *    enum·엔드포인트 경로의 원 계약. 스키마 파일 자체의 docstring이 "모양은 이 문서를 따르되
 *    실제로 다루는 두 축(fact_type + temporal_validity)을 모두 노출한다"고 밝히고 있어, 이
 *    문서와 실제 스키마가 100% 같지는 않다(아래 "알려진 계약 공백" 참고).
 * 3. `.harness/handoffs/contracts/WAVE2D-CONTRACTS.md` - 위 계약의 rationale/열린 질문.
 *
 * 라우터 자체는 아직 없음 (중요)
 * -------------------------------
 * `apps/api/app/api/v1/routers/`에 `extraction.py`도 `admin.py`도 아직 없다(확인: 컴파일된
 * `__pycache__`에 두 이름 다 없음, `app/services/extraction/review.py` 모듈 docstring이
 * "라우터(`app/api/v1/routers/extraction.py`)는 인증/404/403만 다룬다"고 미래형으로 언급함 -
 * 즉 서비스/스키마/모델은 끝났지만 HTTP 계층 자체가 아직 연결되지 않았다). 이 화면은 그
 * 라우터가 스키마 파일이 이미 확정한 모양 그대로 곧 등록될 것이라는 전제로 아래 엔드포인트
 * 경로를 `.harness/contracts/document-structuring.md` §9와 `app/services/extraction/review.py`
 * 함수 시그니처(어떤 함수가 `extraction_id`를 받고 어떤 함수가 `review_request_id`를 받는지)를
 * 대조해 확정했다 - `./api.ts` 모듈 docstring에 각 함수별로 근거를 남겼다. 라우터가 실제로
 * 등록되면 경로 문자열을 대조해야 한다(이 파일 전체가 재조정 대상).
 *
 * 알려진 계약 공백 (Blocker Score < 7, 이 트랙 범위 안에서 로컬로 채우고 여기 기록)
 * --------------------------------------------------------------------------------
 * 1. **"현재 게시된 값"이 없다.** `PublishedContentVersion` 테이블(`app/models/extraction.py`)은
 *    존재하지만 그것을 읽는 Pydantic 스키마도 엔드포인트도 없다. 이 화면이 요구하는 4-way
 *    비교("AI 원제안값 / 업체 확인·수정값 / 현재 게시값 / 운영자 최종값")의 세 번째 항목을
 *    채울 방법이 현재 전혀 없다. `AttributeComparisonRow.published_value`
 *    (`../content-approval/logic.ts`)를 항상 `null`로 채우고 화면에는 "게시 이력 조회 API
 *    없음"이라고 명시한다 - 값이 없다고 조용히 "게시된 값 없음"으로 단정하지 않는다(AGENTS.md
 *    "AI/시스템이 원문에 없는 값을 단정해서는 안 된다"는 원칙을 이 화면 자신에도 적용).
 * 2. **`AdminDecisionRequest`에 `visibility` 필드가 없다.** 실제 스키마는 `{reason?: string}`
 *    뿐이다. 공개범위 설정은 `ExtractionPatchRequest`(참가업체 전용 PATCH)에만 있다. 이
 *    화면은 작업 지시("최종 공개범위 설정")를 만족하기 위해 approve 요청 바디에
 *    `visibility`를 추가 필드로 실어 보낸다(`ApproveAttributeRequest`, 아래) - 백엔드가 아직
 *    이 필드를 모른다면 무시될 뿐 에러는 아니다(Pydantic 기본 동작, extra 필드 무시). 실제로
 *    반영되게 하려면 BACKEND-EXTRACTION이 `AdminDecisionRequest`에 `visibility`를 추가하거나
 *    승인 전 별도 PATCH 호출을 허용해야 한다 - 재조정 필요 항목으로 기록.
 * 3. **사유코드(reason_code) 자체가 없다.** 실제 스키마는 `AdminDecisionRequest.reason:
 *    str | None`(반려), `AdminRequestChangesRequest.comment: str`(보완요청, 필수)뿐이고 둘 다
 *    자유서술 문자열이지 열거형이 아니다. 작업 지시가 명시한 9개 사유코드
 *    (`../content-approval/types.ts`의 `ReasonCode`)는 이 화면이 클라이언트에서 강제하는
 *    로컬 개념이며, 실제 전송 시 `"[코드] 코멘트"` 형태로 기존 자유서술 필드에 합성해 넣는다
 *    (`../content-approval/logic.ts`의 `composeReasonPayload`). 백엔드가 구조화된 필드를
 *    받도록 확장되면 이 합성 로직을 걷어내고 별도 필드로 보내면 된다.
 * 4. **큐 항목에 문서유형·업체명·전체 속성수·근거누락수·업체수정수가 없다.**
 *    `AdminReviewQueueItem`(`app/schemas/extraction.py`)은 `pending_extraction_count`,
 *    `ai_inferred_count`, `has_unresolved_conflict`만 제공한다. 작업 지시가 요구한 큐 컬럼
 *    (업체, 문서, 문서유형, 속성수, 충돌수, 근거누락수, 업체수정수, 위험도, 제출일) 중 상당수를
 *    지금은 정확히 채울 수 없다 - `AiReviewQueueRow`(아래)는 이 필드들을 전부 nullable로 갖고,
 *    실제로 채울 수 있는 것만 채운다(`../content-approval/logic.ts`의 `computeRiskIndicator`가
 *    가용한 신호만으로 위험도를 근사한다). 화면은 값이 없는 컬럼을 빈 값으로 속이지 않고
 *    "상세보기 필요"로 명시한다.
 */

/** 개방형 코드 타입 - `../partner-document/types.ts`, `apps/admin/lib/types.ts`와 동일 규약.
 * owned path 밖 공유 파일(`lib/types.ts`)을 import하지 않고 로컬 재정의한다(그 파일들이 이미
 * 채택한 관례). */
export type OpenEnum<Known extends string> = Known | (string & {});

export type IsoDateTime = string;
export type Uuid = string;

/** JSON으로 왕복 가능한 임의 값 - `proposed_value`/`normalized_value`(JSONB 컬럼)의 실제
 * 폭을 그대로 반영한다(스칼라거나 중첩 객체/배열일 수 있음). */
export type JsonValue =
  | string
  | number
  | boolean
  | null
  | { [key: string]: JsonValue }
  | JsonValue[];

// ---------------------------------------------------------------------------
// app/schemas/extraction.py의 Literal 유니언 - OpenEnum으로 받아 미래 값 추가에도 화면이
// 깨지지 않게 한다(다른 모든 admin 기능과 동일 관례).
// ---------------------------------------------------------------------------

export type EntityType = OpenEnum<"EXHIBITOR" | "PRODUCT" | "TRADE_CONDITION" | "CERTIFICATE">;

/** document-structuring.md §4 - 출처 신뢰도 축. AI_INFERRED/CALCULATED/UNKNOWN은 확인+승인
 * 전체 경로를 건너뛸 수 없다(binding rule, `../content-approval/logic.ts`가 강제). */
export type FactType = OpenEnum<"SOURCE_FACT" | "SELF_DECLARED" | "AI_INFERRED" | "CALCULATED" | "UNKNOWN">;

/** `ai/extraction/types.py`의 시점 축 - "지금도 가능한지/예전 얘기인지/계획인지". 작업 지시의
 * "현재-과거 거래조건 혼동 방지" 사전조건이 바로 이 필드를 근거로 판정된다
 * (`../content-approval/logic.ts`의 `checkTemporalNotConflated`). */
export type TemporalValidity = OpenEnum<"CURRENT_CAPABILITY" | "PAST_EXPERIENCE" | "FUTURE_PLAN" | "UNKNOWN">;

/** document-structuring.md §3 전체 8종. */
export type ReviewStatus =
  | "PROPOSED"
  | "CONFIRMED_BY_EXHIBITOR"
  | "MODIFIED_BY_EXHIBITOR"
  | "REJECTED_BY_EXHIBITOR"
  | "APPROVED_BY_OPERATOR"
  | "REJECTED_BY_OPERATOR"
  | "CONFLICTED"
  | "SUPERSEDED";

export const REVIEW_STATUSES: ReviewStatus[] = [
  "PROPOSED",
  "CONFIRMED_BY_EXHIBITOR",
  "MODIFIED_BY_EXHIBITOR",
  "REJECTED_BY_EXHIBITOR",
  "APPROVED_BY_OPERATOR",
  "REJECTED_BY_OPERATOR",
  "CONFLICTED",
  "SUPERSEDED",
];

/** 운영자가 실제로 승인 대상으로 볼 수 있는 상태 - `app/models/extraction.py`의
 * `APPROVABLE_REVIEW_STATUSES`와 동일 값(정본은 백엔드, 여기는 화면 표시용 사본). */
export const APPROVABLE_REVIEW_STATUSES: ReviewStatus[] = [
  "CONFIRMED_BY_EXHIBITOR",
  "MODIFIED_BY_EXHIBITOR",
  "CONFLICTED",
];

export type Visibility = OpenEnum<
  "PUBLIC" | "REGISTERED_USER" | "VERIFIED_BUYER" | "MEETING_ACCEPTED" | "OPERATOR_ONLY"
>;

export const VISIBILITY_TIERS: Visibility[] = [
  "PUBLIC",
  "REGISTERED_USER",
  "VERIFIED_BUYER",
  "MEETING_ACCEPTED",
  "OPERATOR_ONLY",
];

export const VISIBILITY_LABEL_KO: Record<string, string> = {
  PUBLIC: "전체 공개",
  REGISTERED_USER: "가입 사용자",
  VERIFIED_BUYER: "검증된 바이어",
  MEETING_ACCEPTED: "상담 확정 후",
  OPERATOR_ONLY: "운영자 전용",
};

// ---------------------------------------------------------------------------
// EvidenceRead / ExtractedAttributeRead - app/schemas/extraction.py 1:1
// ---------------------------------------------------------------------------

export interface EvidenceRead {
  evidence_id: Uuid;
  document_id: Uuid | null;
  segment_ref: string | null;
  page_number: number | null;
  section_title: string | null;
  text_start: number | null;
  text_end: number | null;
  evidence_text: string;
  evidence_hash: string;
}

export interface ExtractedAttributeRead {
  extraction_id: Uuid;
  document_id: Uuid | null;
  ai_run_id: Uuid | null;
  entity_type: EntityType;
  entity_reference: Uuid | null;
  temporary_entity_ref: string | null;
  attribute_code: string;
  proposed_value: JsonValue;
  normalized_value: JsonValue;
  concept_codes: string[] | null;
  fact_type: FactType;
  temporal_validity: TemporalValidity | null;
  confidence: number | null;
  review_status: ReviewStatus;
  visibility: Visibility | null;
  edited_by_exhibitor: boolean;
  evidence: EvidenceRead[];
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
  reviewed_by_exhibitor_user_id: Uuid | null;
  reviewed_by_exhibitor_at: IsoDateTime | null;
  reviewed_by_operator_user_id: Uuid | null;
  reviewed_by_operator_at: IsoDateTime | null;
  rejection_reason: string | null;
  superseded_by_extraction_id: Uuid | null;
}

export interface ExtractionListResponse {
  document_id: Uuid;
  items: ExtractedAttributeRead[];
}

// ---------------------------------------------------------------------------
// 큐 - GET /admin/ai-review
// ---------------------------------------------------------------------------

/** `app/schemas/extraction.py::AdminReviewQueueItem` 1:1 (실제 백엔드가 제공 확정한 필드만). */
export interface AdminReviewQueueItem {
  review_request_id: Uuid;
  document_id: Uuid | null;
  exhibitor_id: Uuid;
  status: OpenEnum<"SUBMITTED" | "IN_OPERATOR_REVIEW" | "CHANGES_REQUESTED" | "APPROVED" | "REJECTED">;
  submitted_at: IsoDateTime;
  claimed_by_user_id: Uuid | null;
  pending_extraction_count: number;
  ai_inferred_count: number;
  has_unresolved_conflict: boolean;
}

export interface AdminReviewQueueResponse {
  items: AdminReviewQueueItem[];
}

export interface AdminReviewQueueQuery {
  status?: string;
  exhibitor_id?: string;
}

/** 작업 지시가 요구한 큐 화면 표시용 행. `AdminReviewQueueItem`을 감싸되, 백엔드가 아직 주지
 * 않는 컬럼(모듈 docstring 계약 공백 4번)은 명시적으로 `null`로 남겨 화면이 "값이 0/없음"과
 * "값을 아직 모름"을 혼동해 표시하지 않게 한다. `../content-approval/logic.ts`의
 * `toQueueRow`가 이 타입을 만든다. */
export interface AiReviewQueueRow {
  review_request_id: Uuid;
  document_id: Uuid | null;
  exhibitor_id: Uuid;
  /** TODO(BACKEND-EXTRACTION 재조정): 표시용 업체명 필드가 큐 응답에 없다 - exhibitor_id를
   * 대신 보여준다. */
  exhibitor_name: string | null;
  /** TODO(BACKEND-EXTRACTION 재조정): 문서유형이 큐 응답에 없다. */
  document_type: string | null;
  status: string;
  submitted_at: IsoDateTime;
  /** 정확한 "전체 속성수"가 아니라 "아직 대기 중인 속성수"다(백엔드가 제공하는 유일한 카운트) -
   * 라벨을 "대기 N건"으로 명시해 전체 속성수인 것처럼 보이지 않게 한다. */
  pending_extraction_count: number;
  ai_inferred_count: number;
  has_unresolved_conflict: boolean;
  /** TODO(BACKEND-EXTRACTION 재조정): 정확한 근거누락 건수는 상세 조회(추출 목록) 없이는 알
   * 수 없다. */
  evidence_missing_count: number | null;
  /** TODO(BACKEND-EXTRACTION 재조정): 정확한 업체수정 건수도 마찬가지. */
  exhibitor_modified_count: number | null;
  risk_indicator: "LOW" | "MEDIUM" | "HIGH";
}

// ---------------------------------------------------------------------------
// POST /admin/ai-review - 일괄 클레임(재큐잉). app/services/extraction/review.py
// claim_review_requests()와 1:1.
// ---------------------------------------------------------------------------

export interface AdminReviewClaimRequest {
  review_request_ids: Uuid[];
}

export interface AdminReviewClaimResponse {
  claimed: Uuid[];
  already_claimed: Uuid[];
}

// ---------------------------------------------------------------------------
// POST /admin/ai-review/{extraction_id}/approve|reject
// app/services/extraction/review.py approve_extraction()/reject_extraction()과 1:1 +
// 모듈 docstring 계약 공백 2·3번의 로컬 확장 필드.
// ---------------------------------------------------------------------------

export interface ApproveAttributeRequest {
  reason?: string | null;
  /** 계약 공백 2번 - 실제 스키마에 없는 확장 필드. */
  visibility?: Visibility | null;
}

export interface RejectAttributeRequest {
  reason?: string | null;
}

export interface AdminDecisionResponse {
  extraction_id: Uuid;
  review_status: ReviewStatus;
  published_version_id: Uuid | null;
}

// ---------------------------------------------------------------------------
// POST /admin/ai-review/{review_request_id}/request-changes
// app/services/extraction/review.py request_changes()와 1:1.
// ---------------------------------------------------------------------------

export interface RequestChangesRequest {
  comment: string;
}

export interface AdminRequestChangesResponse {
  review_request_id: Uuid;
  status: string;
  operator_comment: string;
}
