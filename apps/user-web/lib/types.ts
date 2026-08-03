/**
 * 공유 타입 정의.
 *
 * WEB-GROUP-001 이후 화면은 실제 백엔드 API 응답을 우선 사용하되, 로컬 DB/API가
 * 없을 때는 같은 UI 타입으로 fallback 데이터를 렌더링한다.
 */

export type UserType = "GENERAL_REGISTERED" | "BUYER_REGISTERED" | "GUEST_WEB";

export type SearchMode = "REGISTERED_WEB" | "GUEST_WEB" | "BUYER_WEB";

/** 업체 승인 상태. AGENTS.md §8 - 미승인(APPROVED 아님) 업체는 검색·추천에 노출하지 않는다. */
export type ApprovalStatus = "APPROVED";

export interface Company {
  id: string;
  recommendableId?: string;
  name: string;
  boothNumber: string;
  zone: string;
  categoryLabel: string;
  summary: string;
  tags: string[];
  approvalStatus: ApprovalStatus;
}

export interface RecommendationItem {
  company: Company;
  score: number;
  /** 추천 이유 문구 (C-4 "추천·검색 이유 생성" 결과를 흉내낸 Mock 문자열) */
  reasons: string[];
}

export interface FavoriteItem {
  id: string;
  company: Company;
  savedAt: string;
  /** 저장 시점의 zone 컨텍스트 (W-3 §3-2 참고, 실제 스키마는 CTR-006에서 확정) */
  savedZone?: string;
}

export type MeetingStatus = "NONE" | "REQUESTED" | "CONFIRMED" | "DECLINED";

export interface BuyerMatchItem {
  company: Company;
  matchScore: number;
  meetingStatus: MeetingStatus;
  /**
   * 연락처는 상담 수락(CONFIRMED) 전에는 절대 노출하지 않는다
   * (AGENTS.md §8, W-7 §3). Mock 데이터에도 이 규칙을 그대로 반영한다.
   */
  contact?: { email: string; phone: string };
}

export interface UserProfile {
  displayName: string;
  userType: UserType;
  interestAreas: string[];
  marketingOptIn: boolean;
}

export interface SearchResultItem {
  company: Company;
  matchedKeyword: string;
  score?: number;
  reasons?: string[];
}

export type DataSource = "api" | "fallback";

export interface LoadedData<T> {
  data: T;
  source: DataSource;
  notice?: string;
}

/** Mock API 시나리오 전환용 (?state=empty|error 쿼리 파라미터로 데모) */
export type MockScenario = "default" | "empty" | "error";

export function parseMockScenario(value: string | string[] | undefined): MockScenario {
  const raw = Array.isArray(value) ? value[0] : value;
  if (raw === "empty" || raw === "error") {
    return raw;
  }
  return "default";
}
