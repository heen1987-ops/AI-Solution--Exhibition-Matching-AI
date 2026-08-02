/**
 * 백주 AI 셀파 프론트엔드 공용 API 타입.
 *
 * 근거 문서
 * ---------
 * - docs/frontend-backend-ai-interface-spec.md
 *     2.4절(시간·문자열·금액 규칙 - UTC 저장/ISO 8601/snake_case), 4절(API 공통 계약 -
 *     성공/오류 응답 봉투, 헤더), 6절(화면·API 매핑), 7~17절(세션·동의·프로파일·추천·전시·
 *     저장·경로·상담·체크인·피드백·행동이벤트 각 엔드포인트의 요청/응답 예시 JSON) - 이
 *     파일에 정의된 거의 모든 타입의 1차 근거.
 * - docs/db-erd-table-spec.md 8.3절(guest_session), 13.1절(booth), 13.3절(recommendable),
 *   16.1~16.4절(favorite/check_in/feedback/route) - 인터페이스 명세에 JSON 예시가 없는
 *   필드의 보강 근거.
 * - docs/user-ia-wireframes.md 5.1절(라우트·화면 계약), 6절(상태모델), 12절(행동 이벤트
 *   이름 규칙) - 화면 흐름과 상태값 후보의 보강 근거.
 * - backend/app/schemas/profile.py, meeting.py, recommendation.py - 이미 구현된 백엔드
 *   Pydantic 스키마. 겹치는 도메인(프로파일 온보딩, 추천/인터랙션, 상담)은 필드명을 이
 *   파일들과 1:1로 맞췄다. 백엔드 스키마가 아직 없는 도메인(세션 생성, 휴대전화 인증, 저장,
 *   경로, QR 체크인, 피드백, 부스·제품 공개 상세)은 인터페이스 명세의 예시 JSON과 db-erd
 *   컬럼 설명을 근거로 이 파일에서 처음 정의했다 - 각 섹션 주석에 "TODO(백엔드 스키마 확정
 *   후 대조)"로 표시했다.
 *
 * 코드값 표기 원칙
 * ----------------
 * 작업 지시: "6단계 매칭 온톨로지 문서가 아직 없다. 태그/속성 코드값은 하드코딩 enum을
 * 피한다." 이 문서 전반에서 실제로 개방형(온톨로지·운영 코드, DB에 CHECK 제약이 없거나
 * "등"으로 예시만 든 값)인 필드는 아래 OpenEnum<T>로 표기한다 - 알려진 값은 자동완성으로
 * 제시하되 임의 문자열도 허용해 코드 목록이 나중에 시드 데이터로 늘어나도 타입이 깨지지
 * 않는다. 반대로 DB CHECK 제약 등으로 이미 고정된 구조적 상태값(예: 상담 상태, entry_channel)은
 * 일반 Union 리터럴로 좁혀 오타를 방지한다.
 */

// ---------------------------------------------------------------------------
// 보조 타입
// ---------------------------------------------------------------------------

/** 알려진 리터럴을 자동완성으로 제시하되 임의 문자열도 허용하는 개방형 코드 타입. */
export type OpenEnum<Known extends string> = Known | (string & {});

/** URL query DTOs share this index contract so the common API client can
 * serialize them without weakening request-body types. */
export type QueryValue = string | number | boolean | undefined | null;
export interface QueryParams {
  [key: string]: QueryValue;
}

/** ISO 8601 문자열(UTC 오프셋 포함). 서버는 UTC로 저장·응답한다 (2.4절). */
export type IsoDateTime = string;

/** `YYYY-MM-DD` 형식의 날짜 전용 문자열 (2.4절: 행사일·후속연락일 등). */
export type IsoDate = string;

/** ISO 4217 통화 코드 (예: `KRW`). */
export type CurrencyCode = string;

// ---------------------------------------------------------------------------
// 4.3~4.4절 공통 응답 봉투
// ---------------------------------------------------------------------------

export interface ApiMeta {
  request_id: string;
  server_time: IsoDateTime;
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
  meta: ApiMeta;
}

// ---------------------------------------------------------------------------
// Anonymous guest web search — POST /api/v1/search
// ---------------------------------------------------------------------------

export interface WebSearchRequest {
  event_id: string;
  query: string;
  category_codes?: string[];
  channel?: "WEB";
  limit?: number;
}

export interface WebSearchInterpretedQuery {
  intent: "SEARCH_EXHIBITOR";
  concepts: string[];
  fallback_mode: "KEYWORD";
}

export interface WebSearchResult {
  result_id: string;
  rank: number;
  object_type: "EXHIBITOR";
  exhibitor_id: string;
  booth_id: string;
  name: string;
  booth_number: string;
  zone_name: string | null;
  summary: string | null;
  product_names: string[];
  reason: string;
  concepts: string[];
  operating_status: "OPEN" | "PAUSED";
  estimated_wait_minutes: number | null;
  map_x: number | null;
  map_y: number | null;
}

export interface WebSearchClarification {
  question: string;
  options: string[];
}

export interface WebSearchResponse {
  search_session_id: string;
  channel: "WEB";
  interpreted_query: WebSearchInterpretedQuery;
  results: WebSearchResult[];
  clarification: WebSearchClarification | null;
  created_at: IsoDateTime;
  expires_at: IsoDateTime;
}

export interface ApiErrorEnvelope {
  success: false;
  error: ApiErrorBody;
  meta: ApiMeta;
}

export type ApiEnvelope<T> = ApiSuccessEnvelope<T> | ApiErrorEnvelope;

/** 4.3절 목록 응답의 공통 형태 (`items` + 불투명 커서). */
export interface CursorPage<T> {
  items: T[];
  next_cursor: string | null;
}

/** 19절 오류 코드 표. 서버가 문서에 없는 새 코드를 보낼 수 있어 OpenEnum으로 둔다. */
export type ApiErrorCode = OpenEnum<
  | "VALIDATION_FAILED"
  | "AUTH_REQUIRED"
  | "SESSION_EXPIRED"
  | "PRINCIPAL_CONFLICT"
  | "AGE_CONFIRMATION_REQUIRED"
  | "PERSONALIZATION_DISABLED"
  | "RESOURCE_FORBIDDEN"
  | "PROFILE_VERSION_CONFLICT"
  | "MEETING_CONFLICT"
  | "MEETING_VERSION_CONFLICT"
  | "DUPLICATE_CHECKIN"
  | "IDEMPOTENCY_KEY_REUSED"
  | "PROFILE_INCOMPLETE"
  | "NO_CANDIDATE"
  | "INVALID_QR"
  | "BOOTH_CLOSED"
  | "PRODUCT_SOLD_OUT"
  | "RATE_LIMITED"
  | "SERVICE_TEMPORARILY_UNAVAILABLE"
  | "NETWORK_ERROR"
  | "UNKNOWN_ERROR"
>;

// ---------------------------------------------------------------------------
// 공용 값 조각 (backend/app/schemas/profile.py 1:1 대응)
// ---------------------------------------------------------------------------

export interface AddRemove {
  add: string[];
  remove: string[];
}

export interface PriceRange {
  min_amount: number | null;
  max_amount: number | null;
  currency: CurrencyCode;
}

export interface AlcoholPercentageRange {
  min: number | null;
  max: number | null;
}

/** db-erd 11절: 아직 6단계 온톨로지가 없어 (taxonomy_version_id, concept_id) 복합 참조로만
 * 표현한다. 화면은 `GET /api/v1/ontology/concepts`로 선택지를 채운 뒤 이 값을 채워야 한다. */
export interface TaxonomyRef {
  taxonomy_version_id: string;
  concept_id: string;
}

// ---------------------------------------------------------------------------
// 7.1절 익명 세션 생성 (U-01)
// ---------------------------------------------------------------------------

/** db-erd 8.3절 CHECK 제약: entry_channel은 QR/WEB/KIOSK로 고정된 구조적 값이다. */
export type EntryChannel = "QR" | "WEB";

export interface CreateSessionRequest {
  event_id: string;
  entry_channel: EntryChannel;
  entry_code?: string | null;
  /** 예: `MOBILE_WEB`. db-erd 8.3절이 "등"으로만 예시를 들어 개방형 코드다. */
  device_type?: OpenEnum<"MOBILE_WEB" | "DESKTOP_WEB"> | null;
  language?: string;
}

export interface CreateSessionResponse {
  guest_session_id: string;
  visit_session_id: string;
  profile_id: string;
  event_status: OpenEnum<"OPEN" | "PAUSED" | "CLOSED">;
  service_available: boolean;
  minimum_age: number;
  expires_at: IsoDateTime;
}

// ---------------------------------------------------------------------------
// 7.2절 휴대전화 인증 - 예시 JSON이 없어 프로즈 설명 기준 잠정 계약이다.
// TODO(인증 도메인 상세설계 확정 후 대조): 정확한 필드명은 인증 담당 에이전트의 백엔드
// 스키마가 나오면 다시 맞춘다. 지금은 표준적인 OTP 플로우 형태로 최선 추정한다.
// ---------------------------------------------------------------------------

export interface PhoneChallengeRequest {
  phone_number: string;
}

export interface PhoneChallengeResponse {
  challenge_id: string;
  expires_at: IsoDateTime;
  retry_after_seconds: number | null;
}

export interface PhoneChallengeVerifyRequest {
  code: string;
}

export interface PhoneChallengeVerifyResponse {
  verified: boolean;
  authentication_state: OpenEnum<"GUEST" | "PHONE_VERIFIED" | "ACCOUNT_AUTHENTICATED">;
}

export interface SessionMergeRequest {
  /** 7.2절: "이미 다른 계정에 연결된 데이터를 자동 병합하지 않는다" - 명시적 확인이 필요하다. */
  confirm_merge: boolean;
}

export interface SessionMergeResponse {
  user_id: string;
  merged_profile_id: string;
  merged_favorites_count: number;
  merged_schedule_items_count: number;
}

// ---------------------------------------------------------------------------
// 7.4절 자격·동의 (U-03, U-22) - backend/app/api/v1/routers/consent.py 1:1 대응
// ---------------------------------------------------------------------------

export type ConsentPurpose = OpenEnum<
  | "AGE_CONFIRMATION"
  | "PERSONALIZED_RECOMMENDATION"
  | "BEHAVIOR_PERSONALIZATION"
  | "MARKETING_MESSAGES"
>;

export type ConsentSourceChannel = "WEB" | "QR" | "KIOSK";

export interface ConsentItemInput {
  purpose: ConsentPurpose;
  document_version: string;
  accepted: boolean;
  source_channel?: ConsentSourceChannel | null;
}

export interface ConsentsPutRequest {
  consents: ConsentItemInput[];
}

export interface ConsentStateItem {
  purpose: ConsentPurpose;
  document_version: string;
  accepted: boolean;
  occurred_at: IsoDateTime;
  required_for: string | null;
}

export interface ConsentsPutResponse {
  consents: ConsentStateItem[];
}

export type ConsentsGetResponse = ConsentsPutResponse;

export type PrivacyRequestType = "ACCESS" | "EXPORT" | "CORRECT" | "DELETE" | "WITHDRAW";

export interface PrivacyRequestCreate {
  request_type: PrivacyRequestType;
  scope?: Record<string, unknown> | null;
}

export interface PrivacyRequestView {
  privacy_request_id: string;
  request_type: string;
  status: string;
  requested_at: IsoDateTime;
  due_at: IsoDateTime | null;
  completed_at: IsoDateTime | null;
}

export type PrivacyRequestListResponse = CursorPage<PrivacyRequestView>;

// ---------------------------------------------------------------------------
// 7.3절 사용자 유형 (U-02) - backend/app/schemas/profile.py 1:1 대응
// ---------------------------------------------------------------------------

export type UserType = "GENERAL_VISITOR" | "BUYER";

export interface UserTypeUpdateRequest {
  user_type: UserType;
}

export interface UserTypeUpdateResponse {
  profile_version: number;
  user_type: string;
  recommendation_refresh_required: boolean;
  invalidated_recommendation_session_ids: string[];
}

// ---------------------------------------------------------------------------
// 8.1절 방문 목적 (U-04)
// ---------------------------------------------------------------------------

export interface GoalItem {
  code: string;
  priority: number;
}

export interface GoalsUpdateRequest {
  visit_goals: GoalItem[];
  free_text_goal?: string | null;
}

export interface SuggestedAttribute {
  attribute: string;
  value: string;
  confidence: number;
  evidence_text: string;
}

export interface SelectedGoalView {
  attribute_code: string;
  priority: number;
  requirement_level: string;
}

export interface GoalsUpdateResponse {
  profile_version: number;
  selected_goals: SelectedGoalView[];
  suggested_attributes: SuggestedAttribute[];
  confirmation_required: boolean;
}

// ---------------------------------------------------------------------------
// 8.2절 관람객 취향 (U-05)
// ---------------------------------------------------------------------------

export type PurchaseIntent = "LIKELY" | "UNLIKELY" | "UNDECIDED";
export type PreferenceCertainty = "KNOWN" | "UNKNOWN";

export interface ConsumerPreferencesRequest {
  product_categories: string[];
  taste_preferences: string[];
  alcohol_percentage?: AlcoholPercentageRange | null;
  price?: PriceRange | null;
  purchase_intent?: PurchaseIntent | null;
  preferred_activities: string[];
  /** "잘 모르겠음"은 빈 배열과 다르다 (8.2절). */
  preference_certainty: PreferenceCertainty;
}

export interface ConsumerPreferencesResponse {
  profile_version: number;
  completeness_score: number;
}

// ---------------------------------------------------------------------------
// 8.3절 바이어 거래조건 (U-06)
// ---------------------------------------------------------------------------

export type PriceBasis = "RETAIL_PRICE" | "WHOLESALE_PRICE";

export interface TargetPrice {
  min_amount: number | null;
  max_amount: number | null;
  basis: PriceBasis;
  currency: CurrencyCode;
}

export interface ExpectedOrderVolume {
  /** 예: `REGULAR_SMALL`. 개방형 코드 (8.3절, 07 문서 모두 예시만 제공). */
  type?: OpenEnum<"SAMPLE" | "SMALL_LOT" | "REGULAR_SMALL" | "REGULAR_LARGE"> | null;
  monthly_units_min?: number | null;
  monthly_units_max?: number | null;
}

export interface BuyerNeedsRequest {
  organization_type?: string | null;
  distribution_channels: string[];
  desired_categories: string[];
  target_price?: TargetPrice | null;
  expected_order_volume?: ExpectedOrderVolume | null;
  supply_regions: string[];
  business_interests: string[];
  decision_timeline?: string | null;
}

export interface BuyerNeedsResponse {
  profile_version: number;
  completeness_score: number;
}

// ---------------------------------------------------------------------------
// 8.4절 방문 계획 (U-07)
// ---------------------------------------------------------------------------

export interface WalkingConstraints {
  minimize_distance: boolean;
  accessible_route: boolean;
}

export interface MeetingSlotWindow {
  start: IsoDateTime;
  end: IsoDateTime;
}

export interface VisitPlanRequest {
  visit_date: IsoDate;
  entry_time?: IsoDateTime | null;
  available_minutes?: number | null;
  /** 예: `LOW_CONGESTION`, `SHORTEST` 등 개방형 코드. */
  route_preference?: OpenEnum<"LOW_CONGESTION" | "SHORTEST" | "RECOMMENDED_FIRST"> | null;
  walking_constraints?: WalkingConstraints | null;
  meeting_available_slots: MeetingSlotWindow[];
}

export interface VisitPlanResponse {
  visit_session_id: string;
  visit_date: IsoDate;
  available_minutes: number | null;
  route_preference: string | null;
  context_profile_id: string;
}

// ---------------------------------------------------------------------------
// 14절 프로파일 일반 갱신 (U-20)
// ---------------------------------------------------------------------------

export interface ProfileGeneralPatchRequest {
  taste_preferences?: AddRemove | null;
  product_categories?: AddRemove | null;
  preferred_activities?: AddRemove | null;
  distribution_channels?: AddRemove | null;
  desired_categories?: AddRemove | null;
  business_interests?: AddRemove | null;
  supply_regions?: AddRemove | null;
  price?: PriceRange | null;
  alcohol_percentage?: AlcoholPercentageRange | null;
}

export interface ProfileGeneralPatchResponse {
  profile_version: number;
  recommendation_refresh_required: boolean;
  invalidated_recommendation_session_ids: string[];
}

// ---------------------------------------------------------------------------
// 07 26.2절 프로파일 속성 upsert/remove (범용 온톨로지 속성)
// ---------------------------------------------------------------------------

export type AttributeRequirementLevel = "REQUIRED" | "PREFERRED" | "ACCEPTABLE" | "EXCLUDED";

export interface AttributePatchItem {
  attribute_code: string;
  action: "UPSERT" | "REMOVE";
  value?: unknown;
  requirement_level?: AttributeRequirementLevel;
  priority?: number | null;
}

export interface AttributesPatchRequest {
  attributes: AttributePatchItem[];
}

export interface AttributeView {
  profile_attribute_id: string;
  attribute_code: string;
  value_json: unknown;
  requirement_level: string;
  priority: number | null;
  source_type: string;
  confidence: number;
  active: boolean;
}

export interface AttributesPatchResponse {
  profile_version: number;
  attributes: AttributeView[];
}

// ---------------------------------------------------------------------------
// 07 26.1/26.3/26.4절 프로파일 조회·완성도·버전 (U-22)
// ---------------------------------------------------------------------------

export interface GoalView {
  attribute_code: string;
  priority: number | null;
  requirement_level: string;
  confidence: number;
}

export interface BuyerNeedView {
  organization_type: string | null;
  target_price_min_amount: number | null;
  target_price_max_amount: number | null;
  currency: string;
  price_basis: string | null;
  monthly_units_min: number | null;
  monthly_units_max: number | null;
  decision_timeline: string | null;
  business_email_verified: boolean;
  company_verified: boolean;
}

export interface ProfileView {
  profile_id: string;
  user_type: string;
  profile_status: string;
  completeness_score: number;
  current_version: number;
  goals: GoalView[];
  attributes: AttributeView[];
  consumer_preferences: Record<string, unknown>;
  buyer_need: BuyerNeedView | null;
  updated_at: IsoDateTime;
}

export type CompletenessBand = "PRECISE" | "GENERAL" | "EXPLORATORY" | "NEEDS_MORE_INFO";

export interface CompletenessResponse {
  profile_id: string;
  completeness_score: number;
  band: CompletenessBand;
  breakdown: Record<string, number>;
}

export interface ProfileVersionItem {
  profile_version_id: string;
  version_number: number;
  change_reason: string;
  created_at: IsoDateTime;
}

export type ProfileVersionsResponse = CursorPage<ProfileVersionItem>;

// ---------------------------------------------------------------------------
// 9절 추천 - backend/app/schemas/recommendation.py 1:1 대응
// ---------------------------------------------------------------------------

export type RecommendationType = "BOOTH" | "PRODUCT" | "EXHIBITOR" | "PROGRAM" | "MIXED";

/** 개별 추천 항목의 대상 유형 (MIXED 제외 - 9.1절 recommendation_type의 부분집합). */
export type RecommendableObjectType = "BOOTH" | "PRODUCT" | "EXHIBITOR" | "PROGRAM";

export interface RecommendationContextRequest {
  current_zone?: string | null;
  remaining_minutes?: number | null;
  exclude_visited?: boolean;
  include_meetings?: boolean;
}

export interface RecommendationRequest {
  recommendation_type: RecommendationType;
  context?: RecommendationContextRequest;
  limit?: number | null;
}

export interface ReasonView {
  /** 허용된 근거 코드만 사용한다 (17.3절 allowed_reason_codes) - 목록은 정책에 따라
   * 늘어날 수 있어 개방형으로 둔다. */
  code: OpenEnum<"TASTE_MATCH" | "PRICE_MATCH" | "LOW_WAIT" | "GOAL_MATCH" | "PROXIMITY_MATCH">;
  text: string;
  evidence_refs: string[];
}

export interface AvailabilityView {
  open?: boolean | null;
  tasting?: boolean | null;
  purchase?: boolean | null;
  meeting?: boolean | null;
}

export type MatchLevel = "VERY_HIGH" | "HIGH" | "MEDIUM" | "LOW";

/** db-erd 15.3절: recommended_action은 VARCHAR(30)으로 "VISIT_NOW 등" 개방형 값이다. */
export type RecommendedAction = OpenEnum<"VISIT_NOW" | "REQUEST_MEETING" | "ADD_TO_ROUTE" | "VIEW_DETAILS">;

export interface RecommendationItem {
  match_result_id: string | null;
  rank: number;
  object_type: RecommendableObjectType;
  object_id: string;
  exhibitor_id?: string | null;
  match_level: MatchLevel;
  reasons: ReasonView[];
  distance_meters?: number | null;
  estimated_walk_minutes?: number | null;
  estimated_wait_minutes?: number | null;
  status_observed_at?: IsoDateTime | null;
  availability: AvailabilityView;
  recommended_action: RecommendedAction;
}

export interface RecommendationResponse {
  recommendation_session_id: string;
  generated_at: IsoDateTime;
  expires_at: IsoDateTime;
  profile_version: number;
  ranking_version: string;
  explanation_version: string;
  policy_version: string;
  items: RecommendationItem[];
  stale: boolean;
}

export type RecommendationSort = "RECOMMENDED" | "DISTANCE" | "WAIT";

export interface RecommendationListQuery extends QueryParams {
  type?: RecommendableObjectType;
  sort?: RecommendationSort;
  cursor?: string;
  limit?: number;
}

export interface RecommendationSessionItemsResponse {
  items: RecommendationItem[];
  next_cursor: string | null;
  stale: boolean;
}

// ---------------------------------------------------------------------------
// 16.1~16.2절 행동 이벤트 - backend/app/schemas/recommendation.py 1:1 대응
// ---------------------------------------------------------------------------

/** 16.2절 표준 이름. 서버가 meet_ai.ontology 카탈로그(ACTION.*)로 대조하므로 새 이벤트명이
 * 추가될 수 있어 개방형으로 둔다. */
export type InteractionEventType = OpenEnum<
  | "SERVICE_STARTED"
  | "USER_TYPE_SELECTED"
  | "CONSENT_CHOICE_RECORDED"
  | "PROFILE_QUESTION_VIEWED"
  | "PROFILE_ANSWER_SELECTED"
  | "PROFILE_QUESTION_SKIPPED"
  | "MINIMUM_PROFILE_COMPLETED"
  | "RECOMMENDATION_IMPRESSION"
  | "RECOMMENDATION_OPENED"
  | "RECOMMENDATION_SAVED"
  | "RECOMMENDATION_DISMISSED"
  | "ROUTE_ITEM_ADDED"
  | "ROUTE_STARTED"
  | "BOOTH_CHECKED_IN"
  | "VISIT_OUTCOME_SELECTED"
  | "FEEDBACK_SUBMITTED"
  | "MEETING_REQUEST_STARTED"
  | "MEETING_REQUEST_SUBMITTED"
  | "MEETING_REQUEST_DECIDED"
  | "MEETING_COMPLETED"
>;

export interface InteractionEventIn {
  client_event_id?: string | null;
  event_type: InteractionEventType;
  object_type?: RecommendableObjectType | null;
  object_id?: string | null;
  recommendation_session_id?: string | null;
  match_result_id?: string | null;
  rank_at_event?: number | null;
  /** 화면 코드. 예: `HOME`, `EXPLORE`, `MAP`, `SCHEDULE`, `MY`. */
  screen?: OpenEnum<"HOME" | "EXPLORE" | "MAP" | "SCHEDULE" | "MY"> | null;
  zone?: string | null;
  occurred_at: IsoDateTime;
  consent_snapshot_id?: string | null;
  /** 16.2절: 직접 식별정보·자유메모 원문·OTP·토큰·전체 쿼리스트링을 넣지 않는다. */
  context?: Record<string, unknown> | null;
}

export interface InteractionBatchRequest {
  events: InteractionEventIn[];
}

export interface InteractionEventResult {
  client_event_id: string | null;
  interaction_event_id: string | null;
  accepted: boolean;
  reason: string | null;
}

export interface InteractionBatchResponse {
  accepted: number;
  rejected: number;
  results: InteractionEventResult[];
}

// ---------------------------------------------------------------------------
// 10절 전시정보 - 10.1은 인터페이스 명세 JSON 예시가 있어 그대로 대응한다.
// 10.2(제품 상세)는 예시 JSON이 없어 문서 프로즈 설명 기준 잠정 스키마다.
// TODO(공개 GET /products/{id} 백엔드 스키마 확정 후 대조).
// ---------------------------------------------------------------------------

export type BoothOperatingStatus = OpenEnum<"OPEN" | "PAUSED" | "CLOSED">;

export interface BoothLocation {
  zone: string;
  x: number;
  y: number;
}

export interface BoothServices {
  tasting: boolean;
  purchase: boolean;
  meeting: boolean;
}

export interface BoothExhibitorSummary {
  exhibitor_id: string;
  name: string;
  summary: string | null;
}

/** 10.1절 예시는 `products: []`만 보여줄 뿐 항목 필드를 정의하지 않는다.
 * TODO(백엔드 확정 후 대조): 현재는 U-10 화면이 필요로 하는 최소 필드만 잠정 정의한다. */
export interface BoothProductSummary {
  product_id: string;
  product_name: string;
  category?: string | null;
  price?: PriceRange | null;
}

export interface BoothRecommendationContext {
  match_result_id: string | null;
  reasons: ReasonView[];
}

export interface BoothDetailResponse {
  booth_id: string;
  booth_number: string;
  exhibitor: BoothExhibitorSummary;
  location: BoothLocation;
  operating_status: BoothOperatingStatus;
  status_observed_at: IsoDateTime;
  estimated_wait_minutes: number | null;
  services: BoothServices;
  products: BoothProductSummary[];
  recommendation_context: BoothRecommendationContext;
}

export interface BoothDetailQuery {
  /** 소유권이 확인될 때만 개인화 이유를 포함한다 (10.1절). */
  matchResultId?: string;
}

/** 10.2절 프로즈 기준 잠정 스키마. "가격·재고 미제공 시 문의/정보없음으로 명시"를
 * price_display_status로 표현한다. */
export type PriceDisplayStatus = "AVAILABLE" | "INQUIRY" | "UNKNOWN";

export interface ProductAvailability {
  tasting: boolean;
  purchase: boolean;
  delivery: boolean;
}

export interface ProductDetailResponse {
  product_id: string;
  product_name: string;
  exhibitor: BoothExhibitorSummary;
  category: string | null;
  alcohol_percentage: number | null;
  main_ingredients: string[];
  /** 08 5.2절과 동일한 `{개념코드: 0~5 강도}` 패턴. */
  taste: Record<string, number> | null;
  aroma: Record<string, number> | null;
  volume_ml: number | null;
  price: PriceRange | null;
  price_display_status: PriceDisplayStatus;
  availability: ProductAvailability;
  data_observed_at: IsoDateTime;
  verified_by_exhibitor: boolean;
  booth_id: string | null;
  similar_product_ids: string[];
}

// ---------------------------------------------------------------------------
// 11.1절 관심 저장 (U-19) - db-erd 16.1절 컬럼 기준.
// TODO(백엔드 favorites 라우터 확정 후 대조).
// ---------------------------------------------------------------------------

export type FavoriteSource = OpenEnum<"SEARCH" | "RECOMMENDATION">;

export interface FavoriteCreateRequest {
  object_type: RecommendableObjectType;
  object_id: string;
  source: FavoriteSource;
  match_result_id?: string | null;
}

export interface FavoriteView {
  favorite_id: string;
  object_type: RecommendableObjectType;
  object_id: string;
  source: FavoriteSource;
  match_result_id: string | null;
  created_at: IsoDateTime;
}

export interface FavoriteListQuery extends QueryParams {
  object_type?: RecommendableObjectType;
  cursor?: string;
}

export type FavoriteListResponse = CursorPage<FavoriteView>;

// ---------------------------------------------------------------------------
// 11.2절 경로 생성 (U-13) - db-erd 16.4절 컬럼 기준.
// TODO(백엔드 routes 라우터 확정 후 대조).
// ---------------------------------------------------------------------------

export interface RouteStartLocation {
  type: OpenEnum<"ZONE" | "BOOTH" | "GPS">;
  id: string;
}

export interface RouteTargetInput {
  object_type: RecommendableObjectType | "MEETING";
  object_id: string;
  priority?: number | null;
  expected_duration_minutes?: number | null;
}

export interface RouteConstraints {
  available_minutes?: number | null;
  avoid_congestion?: boolean;
  minimize_walking?: boolean;
  accessible_route?: boolean;
}

export interface RouteCreateRequest {
  start_location: RouteStartLocation;
  targets: RouteTargetInput[];
  constraints?: RouteConstraints;
}

export interface RouteItemView {
  sequence: number;
  object_type: RecommendableObjectType | "MEETING" | null;
  object_id: string | null;
  expected_arrival_at: IsoDateTime | null;
  expected_stay_minutes: number | null;
  actual_arrival_at: IsoDateTime | null;
  status: OpenEnum<"PENDING" | "ARRIVED" | "SKIPPED" | "COMPLETED">;
}

export interface RouteResponse {
  route_id: string;
  visit_session_id: string;
  route_preference: string | null;
  total_minutes: number | null;
  walking_minutes: number | null;
  status: OpenEnum<"ACTIVE" | "COMPLETED" | "CANCELLED">;
  items: RouteItemView[];
}

// ---------------------------------------------------------------------------
// 12절 상담 - backend/app/schemas/meeting.py 1:1 대응
// ---------------------------------------------------------------------------

export type MeetingStatus =
  | "DRAFT"
  | "REQUESTED"
  | "CONFIRMED"
  | "COMPLETED"
  | "COUNTER_PROPOSED"
  | "REJECTED"
  | "CANCELLED_BY_BUYER"
  | "CANCELLED_BY_EXHIBITOR"
  | "NO_SHOW";

export const ALLOWED_CONTACT_SHARE_FIELDS = ["NAME", "PHONE", "BUSINESS_EMAIL", "EMAIL"] as const;
export type ContactShareField = (typeof ALLOWED_CONTACT_SHARE_FIELDS)[number];

export interface ContactShareRequest {
  accepted: boolean;
  document_version?: string | null;
  fields: ContactShareField[];
}

export interface MeetingCreateRequest {
  exhibitor_id: string;
  /** 온톨로지 concept_code (예: `DISTRIBUTION`). `GET /api/v1/ontology/concepts?concept_type=BUSINESS_GOAL`로 채운다. */
  topic: string;
  requested_slot_ids: string[];
  message?: string | null;
  contact_share?: ContactShareRequest | null;
  match_result_id?: string | null;
}

export interface SlotCandidate {
  slot_id: string;
  start_at: IsoDateTime;
  end_at: IsoDateTime;
  preference_order: number | null;
  request_status: string | null;
}

export interface MeetingResponse {
  meeting_id: string;
  status: MeetingStatus;
  exhibitor_id: string;
  participation_id: string;
  topic_code: string | null;
  message_preview: string | null;
  candidate_slots: SlotCandidate[];
  confirmed_start: IsoDateTime | null;
  confirmed_end: IsoDateTime | null;
  contact_share_accepted: boolean;
  contact_share_fields: string[];
  viewed_at: IsoDateTime | null;
  row_version: number;
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}

export type MeetingListResponse = CursorPage<MeetingResponse>;

export interface MeetingListQuery extends QueryParams {
  status?: MeetingStatus;
  cursor?: string;
  limit?: number;
}

export interface MeetingCancelRequest {
  version: number;
  reason_code?: string | null;
}

export interface MeetingRespondRequest {
  action: "ACCEPT_COUNTER" | "DECLINE";
  version: number;
  reason_code?: string | null;
}

/** U-15/12.1절: 바이어가 상담 요청 상태를 바꾸는 두 실제 엔드포인트를 하나의 함수로
 * 묶기 위한 판별 유니언. `frontend/lib/api-client.ts`의 `patchMeetingRequest` 참고. */
export type MeetingRequestPatch =
  | { kind: "CANCEL"; data: MeetingCancelRequest }
  | { kind: "RESPOND"; data: MeetingRespondRequest };

export interface PartnerDecisionRequest {
  action: "ACCEPT" | "REJECT" | "COUNTER_PROPOSE";
  slot_id?: string | null;
  version: number;
  reason_code?: string | null;
}

export interface BuyerNeedSummary {
  organization_type: string | null;
  target_price_min_amount: number | null;
  target_price_max_amount: number | null;
  currency: string | null;
  monthly_units_min: number | null;
  monthly_units_max: number | null;
  decision_timeline: string | null;
}

export interface PartnerBuyerSummaryResponse {
  meeting_id: string;
  status: string;
  topic_code: string | null;
  message_preview: string | null;
  buyer_need: BuyerNeedSummary | null;
  contact: Record<string, string> | null;
  contact_disclosed: boolean;
}

export interface PartnerMeetingListItem {
  meeting_id: string;
  status: string;
  topic_code: string | null;
  candidate_slots: SlotCandidate[];
  confirmed_start: IsoDateTime | null;
  confirmed_end: IsoDateTime | null;
  viewed_at: IsoDateTime | null;
  created_at: IsoDateTime;
}

export type PartnerMeetingListResponse = CursorPage<PartnerMeetingListItem>;

export interface PartnerMeetingListQuery extends QueryParams {
  status?: MeetingStatus;
  cursor?: string;
}

export interface FollowUpRequest {
  action_code: string;
  due_date?: IsoDate | null;
  note?: string | null;
}

export interface MeetingOutcomeRequest {
  outcome_code: string;
  is_qualified_lead: boolean;
  expected_amount?: number | null;
  currency?: CurrencyCode;
  expected_probability_percent?: number | null;
  memo?: string | null;
  follow_up?: FollowUpRequest | null;
}

export interface MeetingOutcomeResponse {
  meeting_id: string;
  meeting_outcome_id: string;
  meeting_status: string;
  is_qualified_lead: boolean;
  follow_up_action_id: string | null;
}

export interface AvailabilitySlotItem {
  slot_id: string;
  start_at: IsoDateTime;
  end_at: IsoDateTime;
  capacity: number;
  reserved_count: number;
  topic_code: string | null;
  version: number;
}

export interface AvailabilityListResponse {
  items: AvailabilitySlotItem[];
}

export interface AvailabilityQuery extends QueryParams {
  date: IsoDate;
  topic?: string;
}

// ---------------------------------------------------------------------------
// 13절 QR 체크인·피드백 - 예시 요청 JSON은 있으나 응답 JSON은 프로즈 설명뿐이다.
// TODO(백엔드 check-ins/feedback 라우터 확정 후 대조).
// ---------------------------------------------------------------------------

export type CheckInMethod = "QR" | "MANUAL" | "STAFF";
/** U-16 화면의 행동 선택지. */
export type CheckInActivity = OpenEnum<"TASTING" | "PURCHASE" | "MEETING" | "INFO_CHECK" | "LEFT_WAITING">;

export interface CheckInRequest {
  qr_token: string;
  activities: CheckInActivity[];
  match_result_id?: string | null;
  client_event_id?: string | null;
  occurred_at: IsoDateTime;
}

export interface CheckInResponse {
  check_in_id: string;
  booth_id: string | null;
  checked_in_at: IsoDateTime;
  activities: CheckInActivity[];
  /** 13.1절: 중복이면 오류 대신 기존 체크인 정보를 반환한다. */
  duplicate: boolean;
}

export type FeedbackRating = OpenEnum<"VERY_RELEVANT" | "RELEVANT" | "NOT_RELEVANT">;
/** 13.2절 처리표에서 유추한 후보 코드. */
export type FeedbackReasonCode = OpenEnum<
  "TASTE" | "PRICE" | "CONGESTION" | "SOLD_OUT_OR_CLOSED" | "EXPLANATION_ERROR"
>;

export interface FeedbackRequest {
  object_type: RecommendableObjectType;
  object_id: string;
  match_result_id?: string | null;
  rating: FeedbackRating;
  positive_reasons: FeedbackReasonCode[];
  negative_reasons: FeedbackReasonCode[];
  comment?: string | null;
  client_event_id?: string | null;
}

export interface FeedbackResponse {
  feedback_id: string;
  recorded_at: IsoDateTime;
}

// ---------------------------------------------------------------------------
// 19단계 대화형 프로파일링
// backend/app/schemas/conversation.py와 1:1로 대응한다. AI가 추출한 값은 항상
// PROPOSED 상태로 먼저 보여주고, 사용자가 확인한 뒤에만 프로파일에 반영한다.
// ---------------------------------------------------------------------------

export interface ConversationStartRequest {
  language?: string;
}

export interface ConversationStartResponse {
  conversation_id: string;
  profile_id: string;
  user_type: "GENERAL_VISITOR" | "BUYER";
  dialog_state: string;
  status: string;
  policy_version: string;
}

export interface ConversationMessageRequest {
  message: string;
}

export interface ConversationExtraction {
  extraction_id: string;
  attribute_code: string;
  operator: string;
  value: Record<string, unknown>;
  unit: string | null;
  requirement_level: AttributeRequirementLevel;
  source_text: string;
  confidence: number;
  status: string;
}

export interface ConversationClarification {
  code: string;
  text: string;
  options: string[];
}

export interface ConversationMessageResponse {
  conversation_id: string;
  message_id: string;
  assistant_message: string;
  intent_code: string;
  intent_confidence: number;
  extractions: ConversationExtraction[];
  ambiguities: string[];
  next_action: string;
  next_question: ConversationClarification | null;
  recommendation_ready: boolean;
  policy_version: string;
  input_fingerprint: string;
}

export interface ExtractionDecisionRequest {
  action: "CONFIRM" | "REJECT";
  expected_profile_version: number;
}

export interface ExtractionDecisionResponse {
  extraction_id: string;
  status: "CONFIRMED" | "REJECTED" | string;
  application_status: "APPLIED" | "NOT_APPLIED" | "STRUCTURED_FIELD_REQUIRED" | string;
  profile_version: number;
  recommendation_refresh_required: boolean;
}
