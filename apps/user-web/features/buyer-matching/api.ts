/**
 * 바이어 매칭 결과 화면 전용 API 계층.
 *
 * 재사용 vs 신규
 * ---------------
 * - 매칭 슬레이트 자체는 `lib/api-client.ts`의 기존 추천 엔드포인트
 *   (`createRecommendationSession`/`getRecommendationSessionItems`,
 *   `recommendation_type: "EXHIBITOR"`)를 그대로 재사용한다 - 바이어용 "업체 매칭"과
 *   일반 방문객용 "추천"은 같은 백엔드 슬레이트 파이프라인을 쓴다(9절).
 * - "자연어 정제 검색창"은 공용 클라이언트에 없는 `POST /api/v1/search`
 *   (`apps/api/app/api/v1/routers/search.py`, 키오스크가 이미 쓰는 자연어 해석 엔드포인트)를
 *   저수준 `apiPost`로 직접 호출한다. 반환된 개념 코드(`interpreted_query.concepts`)를
 *   하드 필터 칩으로 보여주고, 사용자가 확정하면 `updateProfilePreferences`
 *   (add/remove, 이미 공용 클라이언트에 있음)로 프로파일에 반영해 다음 매칭에 실제로
 *   영향을 준다.
 * - 업체 카드에 필요한 이름 등 "공개정보"는 `GET /exhibitors/{id}`
 *   (`exhibition_public` 라우터가 `exhibitors.py`로 재노출, 이미 등록됨)를 `apiGet`으로
 *   직접 호출한다 - 공용 클라이언트가 아직 업체 상세 함수를 노출하지 않아서다
 *   (booths/products만 있음, `RecommendationCard.tsx` 상단 주석과 동일한 공백).
 */

import { apiGet, apiPost, createRecommendationSession, getRecommendationSessionItems } from "@/lib/api-client";
import type { ProfileGeneralPatchRequest, ProfileView, RecommendationItem } from "@/lib/types";

import { buildInfoNeededFields, gradeFromMatchLevel, type ExhibitorPublicSummary, type MatchingCardData } from "./types";

// ---------------------------------------------------------------------------
// 매칭 슬레이트
// ---------------------------------------------------------------------------

export interface MatchingSlate {
  recommendationSessionId: string;
  items: RecommendationItem[];
  stale: boolean;
  nextCursor: string | null;
}

export async function fetchMatchingSlate(): Promise<MatchingSlate> {
  const created = await createRecommendationSession({ recommendation_type: "EXHIBITOR" });
  return {
    recommendationSessionId: created.recommendation_session_id,
    items: created.items,
    stale: created.stale,
    nextCursor: null,
  };
}

export async function fetchMoreMatchingSlate(
  recommendationSessionId: string,
  cursor: string | null,
): Promise<MatchingSlate> {
  const page = await getRecommendationSessionItems(recommendationSessionId, {
    type: "EXHIBITOR",
    cursor: cursor ?? undefined,
    limit: 20,
  });
  return { recommendationSessionId, items: page.items, stale: page.stale, nextCursor: page.next_cursor };
}

// ---------------------------------------------------------------------------
// 업체 공개정보 보강
// ---------------------------------------------------------------------------

interface RawPublicExhibitorDetail {
  exhibitor_id: string;
  company_name: string;
  company_summary: string | null;
  product_count: number;
  booth: { booth_id: string; booth_number: string } | null;
}

export async function fetchExhibitorSummary(exhibitorId: string): Promise<ExhibitorPublicSummary> {
  const detail = await apiGet<RawPublicExhibitorDetail>(`/exhibitors/${encodeURIComponent(exhibitorId)}`);
  return {
    exhibitor_id: detail.exhibitor_id,
    company_name: detail.company_name,
    company_summary: detail.company_summary,
    product_count: detail.product_count,
    booth_id: detail.booth?.booth_id ?? null,
    booth_number: detail.booth?.booth_number ?? null,
  };
}

export async function buildMatchingCardData(item: RecommendationItem): Promise<MatchingCardData> {
  const grade = gradeFromMatchLevel(item.match_level);
  if (!item.exhibitor_id) {
    return { item, grade, exhibitor: null, exhibitorLoadFailed: false, infoNeededFields: buildInfoNeededFields(null) };
  }
  try {
    const exhibitor = await fetchExhibitorSummary(item.exhibitor_id);
    return { item, grade, exhibitor, exhibitorLoadFailed: false, infoNeededFields: buildInfoNeededFields(exhibitor) };
  } catch {
    return { item, grade, exhibitor: null, exhibitorLoadFailed: true, infoNeededFields: buildInfoNeededFields(null) };
  }
}

// ---------------------------------------------------------------------------
// 자연어 정제 검색
// ---------------------------------------------------------------------------

export interface RefineSearchResult {
  concepts: string[];
  clarificationQuestion: string | null;
}

interface RawSearchResponse {
  interpreted_query: { concepts: string[] };
  clarification: { question: string; options: string[] } | null;
}

/**
 * `POST /api/v1/search`를 호출해 자연어를 개념 코드로 해석한다. `eventId`는 방문 세션에서
 * 이미 알고 있어야 하는 값이라 호출부가 넘긴다(이 계층은 세션 상태를 갖지 않는다).
 */
export async function refineWithNaturalLanguage(
  eventId: string,
  query: string,
): Promise<RefineSearchResult> {
  const response = await apiPost<RawSearchResponse>("/search", {
    event_id: eventId,
    query,
    category_codes: [],
    channel: "WEB",
    limit: 12,
  });
  return {
    concepts: response.interpreted_query.concepts,
    clarificationQuestion: response.clarification?.question ?? null,
  };
}

// ---------------------------------------------------------------------------
// 하드 필터 칩 (현재 프로파일이 매칭에 실제로 적용 중인 조건)
// ---------------------------------------------------------------------------

export interface HardFilterChip {
  /** `ProfileGeneralPatchRequest`의 어느 add/remove 필드에서 왔는지 - 제거 시 그대로 쓴다. */
  field: "distribution_channels" | "supply_regions" | "business_interests";
  code: string;
  label: string;
}

export function buildHardFilterChips(profile: ProfileView): HardFilterChip[] {
  const prefs = profile.consumer_preferences ?? {};
  const chips: HardFilterChip[] = [];
  const push = (field: HardFilterChip["field"]) => {
    const values = prefs[field];
    if (Array.isArray(values)) {
      for (const value of values) {
        if (typeof value === "string") chips.push({ field, code: value, label: value });
      }
    }
  };
  push("distribution_channels");
  push("supply_regions");
  push("business_interests");
  return chips;
}

export function removeHardFilterPatch(chip: HardFilterChip): ProfileGeneralPatchRequest {
  return { [chip.field]: { add: [], remove: [chip.code] } } as ProfileGeneralPatchRequest;
}
