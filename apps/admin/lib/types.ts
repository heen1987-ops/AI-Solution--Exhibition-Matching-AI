/**
 * 관리자 앱 공용 API 타입.
 *
 * 근거 문서
 * ---------
 * - docs/vibe-coding-master-spec-v1.md
 *     §28(업체정보 등록·승인 - 상태값 9종), §40(API 경로 목록, admin 4개 경로),
 *     §43(관리자 주요 화면 A00~A15), §44(검색·추천 데이터 품질), §45(개인정보 원칙).
 * - apps/api/app/schemas/partner.py, apps/api/app/schemas/search.py - 이미 구현되어 실제
 *   동작하는 백엔드 스키마. 이 타입들과 필드를 1:1로 맞췄다(아래 "실제 구현됨" 절).
 * - apps/api/app/models/exhibitor.py - MASTER_APPROVAL_STATUSES(DRAFT/APPROVED/REJECTED),
 *   PROFILE_APPROVAL_STATUSES(DRAFT/SUBMITTED/APPROVED/REJECTED), BOOTH_OPERATING_STATUSES
 *   (OPEN/PAUSED/CLOSED) - 실제 DB 컬럼이 갖는 값의 정본.
 *
 * 상태값 불일치에 대한 메모(중요)
 * --------------------------------
 * 작업 지시가 지정한 업체 상태값은 §28절의 9종
 * (DRAFT, SUBMITTED, AI_EXTRACTED, EXHIBITOR_REVIEWED, OPERATOR_REVIEW, APPROVED, PUBLISHED,
 * REJECTED, ARCHIVED)이다. 그러나 실제 구현된 DB 컬럼은 두 갈래로 더 단순하다:
 *   - exhibitor.master_approval_status: DRAFT | APPROVED | REJECTED (3종)
 *   - exhibitor_profile.approval_status: DRAFT | SUBMITTED | APPROVED | REJECTED (4종)
 * 이 화면들이 호출해야 할 관리자 승인/반려 API(POST /admin/exhibitors/{id}/approve 등)가
 * 아직 백엔드에 없어(TODO, lib/api-client.ts 참고) 어느 모델이 최종 정본이 될지 이
 * 작업 범위에서 확정할 수 없다. `ExhibitorReviewStatus`는 §28절 9종을 OpenEnum으로 받아
 * 화면이 깨지지 않게 하고, 실제 배지 표시는 알려진 값만 매핑한다(components/StatusBadge.tsx).
 */

// ---------------------------------------------------------------------------
// 보조 타입
// ---------------------------------------------------------------------------

/** 알려진 리터럴을 자동완성으로 제시하되 임의 문자열도 허용하는 개방형 코드 타입.
 * apps/user-web/lib/types.ts의 동명 타입과 동일한 규약. */
export type OpenEnum<Known extends string> = Known | (string & {});

export type IsoDateTime = string;
export type IsoDate = string;

export interface TaxonomyRef {
  taxonomy_version_id: string;
  concept_id: string;
}

// ---------------------------------------------------------------------------
// 공통 응답 봉투 - apps/api/app/schemas/profile.py Envelope[T]와 대응
// (apps/api/app/api/v1/routers/exhibitors.py, search.py, kiosk.py가 실제로 이 형태를 쓴다)
// ---------------------------------------------------------------------------

export interface ApiMeta {
  request_id: string;
  server_time?: IsoDateTime;
}

export interface FieldError {
  field: string;
  reason: string;
}

export interface ApiErrorBody {
  code: string;
  message: string;
  field_errors: FieldError[];
  retryable: boolean;
  retry_after_seconds: number | null;
}

export interface ApiSuccessEnvelope<T> {
  success: true;
  data: T;
  meta?: ApiMeta;
}

export interface ApiErrorEnvelope {
  success: false;
  error: ApiErrorBody;
  meta?: ApiMeta;
}

export type ApiErrorCode = OpenEnum<
  | "VALIDATION_FAILED"
  | "AUTH_REQUIRED"
  | "RESOURCE_FORBIDDEN"
  | "EXHIBITOR_NOT_FOUND"
  | "PRODUCT_NOT_FOUND"
  | "BOOTH_NOT_FOUND"
  | "NO_PARTICIPATION_FOR_EVENT"
  | "PROFILE_INCOMPLETE"
  | "BUYER_PREFERENCE_TAXONOMY_VERSION_MISMATCH"
  | "BUYER_PREFERENCE_EMPTY_DIMENSION"
  | "REJECT_REASON_REQUIRED"
  | "NOT_IMPLEMENTED"
  | "NETWORK_ERROR"
  | "UNKNOWN_ERROR"
>;

// ---------------------------------------------------------------------------
// §43 검증된 역할·서버 세션
// ---------------------------------------------------------------------------

/** 작업 지시가 지정한 세 역할. PROJECT_SCOPE.md/master-spec §46 RBAC 근거. */
export type AdminRole = "EVENT_ADMIN" | "DATA_REVIEWER" | "EXHIBITOR_ADMIN";

export interface AdminSession {
  role: AdminRole | null;
  /** 검증된 서버 principal의 subject_id. 권한 헤더로는 전송하지 않는다. */
  actorUserId: string | null;
  /** EXHIBITOR_ADMIN 역할일 때만 의미 있다 - 자사 업체로 화면 범위를 제한한다. */
  exhibitorId: string | null;
  displayName: string;
  state: "ANONYMOUS" | "AUTHENTICATED" | "MFA_PENDING" | "MFA_ENROLLMENT_REQUIRED";
  csrfToken: string | null;
}

// ---------------------------------------------------------------------------
// §28 업체 상태값 (9종, master-spec 정본 - 위 모듈 docstring의 불일치 메모 참고)
// ---------------------------------------------------------------------------

export type ExhibitorReviewStatus = OpenEnum<
  | "DRAFT"
  | "SUBMITTED"
  | "AI_EXTRACTED"
  | "EXHIBITOR_REVIEWED"
  | "OPERATOR_REVIEW"
  | "APPROVED"
  | "PUBLISHED"
  | "REJECTED"
  | "ARCHIVED"
>;

/** exhibitor.master_approval_status의 실제 DB 값 (3종, 구현 정본). */
export type MasterApprovalStatus = "DRAFT" | "APPROVED" | "REJECTED";

/** exhibitor_profile.approval_status의 실제 DB 값 (4종, 구현 정본). */
export type ProfileApprovalStatus = "DRAFT" | "SUBMITTED" | "APPROVED" | "REJECTED";

export type BoothOperatingStatus = "OPEN" | "PAUSED" | "CLOSED";

// ---------------------------------------------------------------------------
// 실제 구현됨 - GET /exhibitors/{id}/profile 등 (apps/api/app/schemas/partner.py 1:1)
// ---------------------------------------------------------------------------

export interface ExhibitorSupplyProfileRead {
  exhibitor_profile_id: string;
  business_type: string[] | null;
  capability_json: Record<string, unknown> | null;
  preferred_buyer_json: Record<string, unknown> | null;
  trade_readiness_score: number | null;
  consumer_completeness: number;
  buyer_completeness: number;
  current_version: number;
  approval_status: ProfileApprovalStatus | string;
  updated_at: IsoDateTime;
}

export interface ExhibitorProfileRead {
  exhibitor_id: string;
  company_name: string;
  company_summary: string | null;
  website_url: string | null;
  region: TaxonomyRef | null;
  business_types: TaxonomyRef[];
  master_approval_status: MasterApprovalStatus | string;
  data_completeness_percent: number;
  current_profile_version: number;
  supply_profile: ExhibitorSupplyProfileRead | null;
}

export interface ExhibitorProfileUpdate {
  company_summary?: string | null;
  website_url?: string | null;
  region?: TaxonomyRef | null;
  business_types?: TaxonomyRef[] | null;
  capability_json?: Record<string, unknown> | null;
}

export interface ProductSupplyProfileRead {
  taste_json: Record<string, unknown> | null;
  aroma_json: Record<string, unknown> | null;
  usage_json: unknown[] | null;
  feature_json: unknown[] | null;
  consumer_score: number;
  buyer_score: number;
  current_version: number;
  approval_status: string;
}

export interface ProductRead {
  product_id: string;
  exhibitor_id: string;
  product_name: string;
  product_summary: string | null;
  category: TaxonomyRef | null;
  alcohol_percentage: number | null;
  master_approval_status: MasterApprovalStatus | string;
  supply_profile: ProductSupplyProfileRead | null;
}

export interface ProductCreateRequest {
  exhibitor_id: string;
  event_id?: string | null;
  product_name: string;
  category?: TaxonomyRef | null;
  product_summary?: string | null;
  alcohol_percentage?: number | null;
  production_method?: string | null;
  main_ingredients?: string[];
  taste?: Record<string, number>;
  aroma?: Record<string, number>;
  usage?: string[];
  features?: string[];
}

export type TradeAvailabilityStatus = "YES" | "NO" | "CONDITIONAL" | "NEGOTIABLE" | "UNKNOWN";

export interface TradeConditionUpsert {
  event_id: string;
  min_order_quantity?: number | null;
  max_order_quantity?: number | null;
  monthly_capacity?: number | null;
  wholesale_price_min_amount?: number | null;
  wholesale_price_max_amount?: number | null;
  currency?: string;
  oem_status?: TradeAvailabilityStatus;
  private_label_status?: TradeAvailabilityStatus;
  export_status?: TradeAvailabilityStatus;
  exclusive_distribution_considered?: boolean;
  lead_time_days?: number | null;
  valid_from?: IsoDate | null;
  valid_until?: IsoDate | null;
  supply_regions?: TaxonomyRef[];
  channels?: TaxonomyRef[];
  countries?: TaxonomyRef[];
}

export interface TradeConditionRead extends TradeConditionUpsert {
  trade_condition_id: string;
  product_id: string;
  approval_status: string;
}

export interface SubmitResponse {
  exhibitor_id: string;
  approval_status: string;
  consumer_completeness: number;
  buyer_completeness: number;
  submitted_at: IsoDateTime;
  blocking_issues: string[];
}

// --- 공개 카탈로그 (apps/api/app/schemas/search.py 1:1, 승인된 업체만 노출) -----------

export interface PublicProductSummary {
  product_id: string;
  name: string;
  summary: string | null;
  alcohol_percentage: number | null;
  tasting_status: string;
  purchase_status: string;
}

export interface PublicBoothSummary {
  booth_id: string;
  booth_number: string;
  zone_name: string | null;
  operating_status: "OPEN" | "PAUSED";
  estimated_wait_minutes: number | null;
  map_x: number | null;
  map_y: number | null;
}

export interface PublicExhibitorListItem {
  exhibitor_id: string;
  name: string;
  summary: string | null;
  data_quality_score: number;
  booth: PublicBoothSummary;
  products: PublicProductSummary[];
}

export interface PublicExhibitorListResponse {
  items: PublicExhibitorListItem[];
  total: number;
}

export interface PublicExhibitorDetail extends PublicExhibitorListItem {
  website_url: string | null;
}

export interface PublicBoothDetail extends PublicBoothSummary {
  exhibitor_id: string;
  exhibitor_name: string;
  exhibitor_summary: string | null;
  products: PublicProductSummary[];
}

// ---------------------------------------------------------------------------
// TODO: 아직 백엔드에 없음 - master-spec §40.9 문서화된 경로만 있고 라우터 구현이 없다
// (.harness/backlog.yaml BACKEND-007 status: READY, .harness/decisions.md DECISION-005).
// 아래 타입들은 §28·§43·§44절 프로즈 설명 기준 잠정 계약이다. 백엔드가 실제로 구현되면
// 이 타입들과 apps/admin/lib/api-client.ts의 해당 함수를 함께 대조·수정해야 한다.
// ---------------------------------------------------------------------------

/** GET /admin/exhibitors/review 목록 항목 (잠정). §44절 "필수 업체정보"·§28절 상태값 기준. */
export interface AdminExhibitorListItem {
  exhibitor_id: string;
  company_name: string;
  event_id: string;
  review_status: ExhibitorReviewStatus;
  master_approval_status: MasterApprovalStatus | string;
  profile_approval_status: ProfileApprovalStatus | string;
  data_completeness_percent: number;
  product_count: number;
  submitted_at: IsoDateTime | null;
  updated_at: IsoDateTime;
  ai_extracted: boolean;
}

export interface AdminExhibitorListResponse {
  items: AdminExhibitorListItem[];
  total: number;
}

export interface AdminExhibitorListQuery {
  event_id?: string;
  review_status?: ExhibitorReviewStatus;
  cursor?: string;
  limit?: number;
}

/** §29절 "근거문장 필수" 원칙 - AI 추출값과 원본 근거를 함께 보여주기 위한 잠정 타입. */
export interface AiExtractionField {
  field: string;
  ai_value: unknown;
  evidence_text: string | null;
  confidence: number | null;
  accepted: boolean | null;
}

export interface AdminExhibitorDetail extends ExhibitorProfileRead {
  review_status: ExhibitorReviewStatus;
  event_id: string | null;
  previous_version: ExhibitorProfileRead | null;
  ai_extractions: AiExtractionField[];
}

export interface ApproveExhibitorRequest {
  note?: string | null;
}

export interface RejectExhibitorRequest {
  /** 작업 지시: "반려 시 사유 필수 입력" - 클라이언트에서도 빈 값이면 요청을 보내지 않는다. */
  reason: string;
}

export interface ExhibitorDecisionResponse {
  exhibitor_id: string;
  review_status: ExhibitorReviewStatus;
  decided_at: IsoDateTime;
  decided_by: string | null;
  reason: string | null;
}

/** PATCH /admin/booths/{id}/status 요청 (잠정, §40절 경로 문서화됨). */
export interface BoothStatusUpdateRequest {
  operating_status: BoothOperatingStatus;
  reason?: string | null;
}

export interface AdminBoothListItem {
  booth_id: string;
  booth_number: string;
  event_id: string;
  exhibitor_id: string;
  exhibitor_name: string;
  zone_name: string | null;
  operating_status: BoothOperatingStatus;
  congestion_level: string | null;
  row_version: number;
  updated_at: IsoDateTime;
}

export interface AdminBoothListResponse {
  items: AdminBoothListItem[];
  total: number;
}

export interface AdminBoothCreateRequest {
  event_id: string;
  exhibitor_id: string;
  participation_id: string;
  booth_number: string;
  zone_id?: string | null;
  map_x?: number | null;
  map_y?: number | null;
}

/** GET /admin/analytics/searches, /admin/analytics/no-results (§40절, §48절 KPI 기준 잠정). */
export interface SearchAnalyticsSummary {
  event_id: string;
  period_start: IsoDateTime;
  period_end: IsoDateTime;
  total_searches: number;
  zero_result_rate: number;
  top_queries: { query: string; count: number }[];
}

export interface NoResultQueryItem {
  query: string;
  count: number;
  last_seen_at: IsoDateTime;
}

export interface NoResultQueryResponse {
  items: NoResultQueryItem[];
}

/** A15 감사로그 - apps/api/app/models/consent.py AuditLog(audit.audit_log)에 대응하는
 * 조회 API가 아직 없다. db-erd 20.1절 컬럼 구성 기준 잠정 타입. */
export interface AuditLogEntry {
  audit_log_id: string;
  occurred_at: IsoDateTime;
  actor_user_id: string | null;
  actor_role: string | null;
  action_type: string;
  resource_type: string;
  resource_id: string;
  before_json: Record<string, unknown> | null;
  after_json: Record<string, unknown> | null;
  reason: string | null;
}

export interface AuditLogListResponse {
  items: AuditLogEntry[];
  next_cursor: string | null;
}

export interface AuditLogListQuery {
  event_id?: string;
  resource_type?: string;
  actor_user_id?: string;
  cursor?: string;
  limit?: number;
}

/** A01 행사 관리 - core.event 대응 CRUD API가 아직 없다. db-erd 근거의 최소 필드. */
export interface AdminEventItem {
  event_id: string;
  name: string;
  status: OpenEnum<"DRAFT" | "OPEN" | "PAUSED" | "CLOSED">;
  start_date: IsoDate;
  end_date: IsoDate;
  venue_name: string | null;
}

export interface AdminEventListResponse {
  items: AdminEventItem[];
}

export interface AdminEventCreateRequest {
  name: string;
  start_date: IsoDate;
  end_date: IsoDate;
  venue_name?: string | null;
}

// ---------------------------------------------------------------------------
// 실제 구현됨 - POST /admin/imports/{exhibitors|products}
// (apps/api/app/api/v1/routers/imports.py, apps/api/app/schemas/imports.py 1:1).
// 업체·제품 "등록" 폼이 이 배치 upsert 엔드포인트를 1행짜리 배치로 호출한다.
// ---------------------------------------------------------------------------

export interface ImportRowError {
  row_index: number;
  source_record_id: string | null;
  error_code: string;
  message: string;
}

export interface ImportBatchResult {
  import_id: string;
  status: "COMPLETED" | "COMPLETED_WITH_ERRORS" | "FAILED";
  total_rows: number;
  success_rows: number;
  failed_rows: number;
  errors: ImportRowError[];
}
