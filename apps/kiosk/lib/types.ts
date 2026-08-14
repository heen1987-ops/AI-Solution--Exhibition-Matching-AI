/**
 * 키오스크 도메인 타입.
 *
 * 근거: apps/api/app/schemas/kiosk.py, apps/api/app/schemas/search.py (SearchResult /
 * SearchInterpretedQuery). 이름/전화번호/이메일/회원가입/비밀번호/장기 프로파일 필드는
 * 의도적으로 존재하지 않는다.
 */

export type KioskLanguage = "ko" | "en" | "ja" | "zh";

export interface KioskTheme {
  logo_url: string;
  primary_color: string;
}

export interface KioskFeatureFlags {
  voice_input: boolean;
  map: boolean;
  qr_handoff: boolean;
}

export interface KioskConfig {
  kiosk_id: string;
  event_id: string;
  event_name: string;
  default_language: KioskLanguage;
  supported_languages: KioskLanguage[];
  zone_id: string | null;
  session_timeout_seconds: number;
  qr_expiration_minutes: number;
  theme: KioskTheme;
  feature_flags: KioskFeatureFlags;
}

export interface KioskSession {
  session_id: string;
  event_id: string;
  kiosk_id: string;
  language: KioskLanguage;
  created_at: string;
  expires_at: string;
  session_timeout_seconds: number;
}

export interface SearchInterpretedQuery {
  intent: "SEARCH_EXHIBITOR";
  concepts: string[];
  fallback_mode: "KEYWORD";
}

export interface SearchResult {
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

export interface KioskSearchResponse {
  search_session_id: string;
  interpreted_query: SearchInterpretedQuery;
  results: SearchResult[];
  expires_at: string;
}

export interface KioskHandoffResponse {
  handoff_id: string;
  token: string;
  handoff_url: string;
  expires_at: string;
}

export interface KioskCloseResponse {
  session_id: string;
  closed: true;
}

export interface ApiSuccessEnvelope<T> {
  success: true;
  data: T;
  meta: { request_id: string; server_time?: string };
}

export interface ApiErrorBody {
  code: string;
  message: string;
  field_errors: { field: string; reason: string }[];
  retryable: boolean;
  retry_after_seconds: number | null;
}

/** 이 세션이 sessionStorage에 저장하는 형태. 개인 식별 정보를 포함하지 않는다. */
export interface StoredKioskState {
  language: KioskLanguage;
  session: KioskSession | null;
  query: string;
  categoryCodes: string[];
  results: SearchResult[];
  interpretedConcepts: string[];
  handoff: KioskHandoffResponse | null;
  savedAt: string;
}
