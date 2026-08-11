/**
 * ADMIN-ANALYTICS (WAVE 2E) — 관리자 통계 대시보드 타입.
 *
 * 계약 근거 (읽고 나서 수정할 것)
 * --------------------------------
 * BACKEND-ANALYTICS 트랙이 이미 착지시킨 응답 스키마
 * `apps/api/app/schemas/analytics.py`(OverviewAnalyticsResponse /
 * WebAnalyticsResponse / KioskAnalyticsResponse / BuyerAnalyticsResponse /
 * SearchInsightsResponse / NoResultQueryResponse, Metric{value,suppressed})를
 * 1:1로 미러링했다. 그 라우터(`app/api/v1/routers/analytics.py`)는 아직 api.py에
 * 등록되지 않았다 — 등록 전까지 호출은 lib/api-client.ts의 NOT_IMPLEMENTED
 * ApiClientError로 떨어지고, 화면은 그 오류를 그대로 보여준다(가짜 성공 금지).
 *
 * 계약 공백 — 백엔드 스키마에 아직 없는 이 트랙 요구 지표 (조정 필요 플래그)
 * ------------------------------------------------------------------------
 * 이 트랙의 화면 스펙이 요구하지만 backend/schemas/analytics.py에 아직 없는
 * 필드는 전부 optional로 선언했다. 백엔드가 값을 주면 그대로 표시되고, 없으면
 * 화면이 "백엔드 미제공" 상태를 명시한다(깨지지 않음). 목록:
 *   - web: profile_funnel, negative_feedback_rate, per_interest_performance,
 *     personalization_opt_out_rate
 *   - kiosk: per_device(기기별 세션), search_completion_rate, detail_view_rate,
 *     map_view_rate, error_rate
 *   - buyer: verified_buyers, compare_usage
 *   - 공통: data_as_of (신선도 — 없으면 응답 수신 시각으로 대체 표기)
 * BACKEND-ANALYTICS가 이 필드들을 추가하면 이 파일과 화면을 함께 대조할 것.
 *
 * 개인정보 원칙 (이 대시보드의 최우선 불변조건)
 * ---------------------------------------------
 * 이 대시보드는 어떤 경우에도 개인 단위 데이터(연락처·이메일·전화번호·개인명)를
 * 렌더링하지 않는다. 백엔드 응답에 실수로 PII가 섞여 들어와도 api.ts의
 * sanitizeAnalyticsPayload(logic.ts)가 UI 도달 전에 마스킹/제거한다(이중 방어).
 * 5명 미만 소수집단 억제(suppressed=true)는 정확한 수치 대신 "5 미만"으로 표기.
 */

// ---------------------------------------------------------------------------
// 공통
// ---------------------------------------------------------------------------

export type IsoDateTime = string;
export type IsoDate = string;

/** apps/api/app/schemas/analytics.py::Metric 1:1.
 * suppressed=true면 value는 null — 화면은 "5 미만"으로 표기한다. */
export interface Metric {
  value: number | null;
  suppressed: boolean;
}

/** apps/api/app/schemas/analytics.py::DailyCount 1:1. */
export interface DailyCount {
  activity_date: IsoDate;
  count: number;
}

export type AnalyticsRole = "EVENT_ADMIN" | "ANALYST" | "DATA_REVIEWER" | "EXHIBITOR_ADMIN";

// ---------------------------------------------------------------------------
// 필터 (이 트랙 스펙: 행사 / 기간 프리셋 / 채널)
// ---------------------------------------------------------------------------

export type DateRangePreset = "TODAY" | "EVENT_PERIOD" | "LAST_7_DAYS" | "CUSTOM";

export type ChannelFilter = "ALL" | "WEB" | "KIOSK";

export interface AnalyticsFilter {
  eventId: string;
  preset: DateRangePreset;
  /** preset === "CUSTOM"일 때만 사용. */
  customStart: IsoDate | null;
  customEnd: IsoDate | null;
  channel: ChannelFilter;
}

/** resolveDateRange(logic.ts)의 결과 — 쿼리스트링으로 그대로 나간다. */
export interface ResolvedDateRange {
  periodStart: IsoDate;
  periodEnd: IsoDate;
}

// ---------------------------------------------------------------------------
// GET /admin/analytics/overview — 운영 개요
// ---------------------------------------------------------------------------

export interface OverviewAnalyticsResponse {
  event_id: string;
  period_start: IsoDate;
  period_end: IsoDate;
  role: AnalyticsRole;

  registered_users: Metric;
  profile_confirm_rate: Metric;
  web_active_users: Metric;
  kiosk_sessions: Metric;
  total_searches: Metric;
  no_result_rate: Metric;
  recommendation_click_rate: Metric;
  favorites_saved: Metric;
  buyer_matches: Metric;
  meeting_requests: Metric;
  meeting_accepts: Metric;
  published_exhibitor_count: Metric;
  published_product_count: Metric;

  /** 계약 공백: 백엔드 미제공 시 응답 수신 시각으로 대체 표기. */
  data_as_of?: IsoDateTime | null;
}

// ---------------------------------------------------------------------------
// GET /admin/analytics/web — 웹 초개인화
// ---------------------------------------------------------------------------

/** 계약 공백(백엔드 스키마에 아직 없음): 프로파일 진행 퍼널 단계. */
export interface ProfileFunnelStep {
  step: string;
  users: Metric;
}

/** 계약 공백: 관심사(온톨로지 코드)별 추천 성과. concept_code는 259개 카탈로그
 * 코드만 온다(백엔드 검증) — 이 화면은 코드를 그대로 표기만 하고 새 코드를
 * 만들지 않는다. */
export interface InterestPerformanceRow {
  concept_code: string;
  impressions: Metric;
  clicks: Metric;
  click_rate: Metric;
}

export interface WebAnalyticsResponse {
  event_id: string;
  period_start: IsoDate;
  period_end: IsoDate;
  role: AnalyticsRole;

  active_users: Metric;
  sessions: Metric;
  avg_session_duration_seconds: Metric;
  recommendation_impressions: Metric;
  recommendation_clicks: Metric;
  recommendation_click_rate: Metric;
  favorites_saved: Metric;
  daily_active_users: DailyCount[];

  // ---- 계약 공백 필드 (optional, 조정 대기) ----
  profile_funnel?: ProfileFunnelStep[];
  negative_feedback_rate?: Metric | null;
  per_interest_performance?: InterestPerformanceRow[];
  personalization_opt_out_rate?: Metric | null;
  data_as_of?: IsoDateTime | null;
}

// ---------------------------------------------------------------------------
// GET /admin/analytics/kiosk — 키오스크 (검색 품질 지표. 직원/개인 성과 평가 아님)
// ---------------------------------------------------------------------------

/** 계약 공백: 기기별 세션. kiosk_id는 기기 코드(문자열)이지 사람 식별자가 아니다. */
export interface KioskDeviceRow {
  kiosk_id: string;
  sessions: Metric;
  zero_result_rate: Metric;
  error_rate?: Metric | null;
}

export interface KioskAnalyticsResponse {
  event_id: string;
  period_start: IsoDate;
  period_end: IsoDate;
  role: AnalyticsRole;

  sessions: Metric;
  avg_session_duration_seconds: Metric;
  qr_handoffs: Metric;
  searches: Metric;
  zero_result_rate: Metric;
  daily_sessions: DailyCount[];

  // ---- 계약 공백 필드 (optional, 조정 대기) ----
  per_device?: KioskDeviceRow[];
  search_completion_rate?: Metric | null;
  detail_view_rate?: Metric | null;
  map_view_rate?: Metric | null;
  error_rate?: Metric | null;
  data_as_of?: IsoDateTime | null;
}

// ---------------------------------------------------------------------------
// GET /admin/analytics/buyer — 바이어 (거래액·계약 성과 수치는 집계하지 않음)
// ---------------------------------------------------------------------------

export interface ExhibitorBuyerMatchRow {
  exhibitor_id: string;
  buyer_matches: Metric;
  meeting_requests: Metric;
  meeting_accepts: Metric;
}

export interface BuyerAnalyticsResponse {
  event_id: string;
  period_start: IsoDate;
  period_end: IsoDate;
  role: AnalyticsRole;
  exhibitor_id: string | null;

  buyer_matches: Metric;
  meeting_requests: Metric;
  meeting_accepts: Metric;
  meeting_completions: Metric;
  valid_leads: Metric;
  meeting_accept_rate: Metric;
  meeting_completion_rate: Metric;
  valid_lead_rate: Metric;
  breakdown: ExhibitorBuyerMatchRow[];

  // ---- 계약 공백 필드 (optional, 조정 대기) ----
  verified_buyers?: Metric | null;
  compare_usage?: Metric | null;
  data_as_of?: IsoDateTime | null;
}

// ---------------------------------------------------------------------------
// GET /admin/analytics/searches?detail=full / /admin/analytics/no-results
// (검색 관련 요약은 운영 개요 화면의 보조 섹션으로만 쓴다 — 전용 검색 화면은
//  기존 dashboard/page.tsx의 SearchAnalyticsSummary 카드가 이미 담당)
// ---------------------------------------------------------------------------

export interface TopQueryItem {
  query: string;
  count: number;
}

export interface LowClickQueryItem {
  query: string;
  search_count: number;
  click_count: number;
  click_through_rate: number;
  last_seen_at: IsoDateTime;
}

export interface ChannelSearchPerformance {
  channel: "WEB" | "KIOSK";
  total_searches: Metric;
  zero_result_rate: Metric;
  recommendation_click_rate?: Metric | null;
}

export interface TopInterestCodeItem {
  concept_code: string;
  search_count: number;
}

export interface SearchInsightsResponse {
  event_id: string;
  period_start: IsoDateTime;
  period_end: IsoDateTime;
  role: AnalyticsRole;
  daily_volume: DailyCount[];
  top_interest_codes: TopInterestCodeItem[];
  low_click_queries: LowClickQueryItem[];
  channel_performance: ChannelSearchPerformance[];
  data_as_of?: IsoDateTime | null;
}

export interface NoResultQueryItem {
  query: string;
  count: number;
  last_seen_at: IsoDateTime;
}

export interface NoResultQueryResponse {
  items: NoResultQueryItem[];
}

// ---------------------------------------------------------------------------
// CSV 내보내기 — 집계 수치 전용 (개인 단위 행 내보내기 금지)
// ---------------------------------------------------------------------------

/** buildAggregateCsv는 이 행 모양만 받는다 — label/value 쌍의 집계 스칼라만
 * 존재하므로 구조적으로 개인 단위 데이터가 CSV에 실릴 수 없다. */
export interface AggregateCsvRow {
  section: string;
  label: string;
  /** 억제된 지표는 숫자 대신 "5 미만" 문자열로 이미 변환되어 들어온다. */
  value: string;
}
