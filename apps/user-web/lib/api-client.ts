import {
  currentMockProfile,
  mockBuyerMatches,
  mockCompanies,
  mockFavorites,
  mockRecommendations,
} from "./mock-data";
import type {
  BuyerMatchItem,
  Company,
  FavoriteItem,
  LoadedData,
  MockScenario,
  RecommendationItem,
  SearchMode,
  SearchResultItem,
  UserProfile,
  UserType,
} from "./types";

type ApiErrorBody = {
  error?: {
    code?: string;
    message?: string;
    request_id?: string;
    details?: unknown;
  };
};

type ApiPage = {
  page: number;
  page_size: number;
  total_count: number;
};

type ApiRecommendationListResponse = {
  recommendation_session_id?: string | null;
  results: Array<{
    match_result_id?: string;
    recommendable_id: string;
    rank: number;
    normalized_score: number;
    recommended_action?: string | null;
    reasons: Array<{ reason_code: string; reason_text: string }>;
  }>;
  page: ApiPage;
};

type ApiFavoriteListResponse = {
  items: Array<{
    saved_recommendable_id: string;
    recommendable_id: string;
    saved_at: string;
  }>;
  page: ApiPage;
};

type ApiSearchResponse = {
  search_query_id: string;
  result_count: number;
  results: Array<{
    recommendable_id: string;
    rank: number;
    final_score?: number | null;
    reason_codes: string[];
  }>;
  meta?: {
    code?: "SEARCH_NO_RESULT" | null;
    recovery_action?: string | null;
    clarification_question?: string | null;
    unavailable_providers?: string[];
  } | null;
};

type ApiExhibitorDetailResponse = {
  exhibitor_id: string;
  exhibitor_name: string;
  business_types?: string[];
  booths?: string[];
};

type ApiBoothDetailResponse = {
  booth_id: string;
  exhibitor_id: string;
  operating_status: string;
  congestion_level: string;
  row_version: number;
};

type ApiUserProfileResponse = {
  profile_id: string;
  user_type: UserType;
  profile_status: string;
  completeness_score: number;
  attributes?: Array<{ attribute_code: string }>;
};

type ApiGuestWebSessionResponse = {
  guest_session_id: string;
  session_status: string;
};

function apiBaseUrl(): string | null {
  const raw =
    process.env.MEETAI_API_BASE_URL ?? process.env.NEXT_PUBLIC_API_BASE_URL ?? "";
  const trimmed = raw.trim().replace(/\/+$/, "");
  return trimmed || null;
}

function headerValue(name: string, publicName = `NEXT_PUBLIC_${name}`): string | null {
  const raw = process.env[name] ?? process.env[publicName] ?? "";
  const trimmed = raw.trim();
  return trimmed || null;
}

function authHeaders(userType?: UserType): HeadersInit {
  const headers: Record<string, string> = {};
  const profileId = headerValue("MEETAI_PROFILE_ID");
  const userId = headerValue("MEETAI_USER_ID");
  const actorRole = headerValue("MEETAI_ACTOR_ROLE");
  const resolvedUserType = userType ?? (headerValue("MEETAI_USER_TYPE") as UserType | null);
  if (profileId) {
    headers["X-MeetAI-Profile-Id"] = profileId;
  }
  if (userId) {
    headers["X-MeetAI-User-Id"] = userId;
  }
  if (resolvedUserType) {
    headers["X-MeetAI-User-Type"] = resolvedUserType;
  }
  if (actorRole) {
    headers["X-MeetAI-Actor-Role"] = actorRole;
  }
  return headers;
}

function userTypeForSearchMode(mode: SearchMode): UserType {
  if (mode === "BUYER_WEB") {
    return "BUYER_REGISTERED";
  }
  if (mode === "GUEST_WEB") {
    return "GUEST_WEB";
  }
  return "GENERAL_REGISTERED";
}

function fallback<T>(data: T, notice?: string): LoadedData<T> {
  return { data, source: "fallback", notice };
}

function fromApi<T>(data: T): LoadedData<T> {
  return { data, source: "api" };
}

async function apiFetch<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const baseUrl = apiBaseUrl();
  if (!baseUrl) {
    throw new Error("API_BASE_URL_NOT_CONFIGURED");
  }
  const response = await fetch(`${baseUrl}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "Content-Type": "application/json",
      ...(init.headers ?? {}),
    },
  });
  if (!response.ok) {
    let body: ApiErrorBody | undefined;
    try {
      body = (await response.json()) as ApiErrorBody;
    } catch {
      body = undefined;
    }
    const code = body?.error?.code ?? `HTTP_${response.status}`;
    throw new Error(code);
  }
  return (await response.json()) as T;
}

function shortId(id: string): string {
  return id.split("-")[0] ?? id.slice(0, 8);
}

function isLikelyUuid(id: string): boolean {
  return /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(id);
}

function companyFromRecommendable(id: string, label = "AI 추천 대상"): Company {
  return {
    id,
    recommendableId: id,
    name: `${label} ${shortId(id)}`,
    boothNumber: "-",
    zone: "현장",
    categoryLabel: label,
    summary: "백엔드 추천 결과에 포함된 승인 대상입니다. 상세 정보 API가 제공되면 카드가 확장됩니다.",
    tags: ["API", "승인대상"],
    approvalStatus: "APPROVED",
  };
}

function companyFromExhibitor(exhibitor: ApiExhibitorDetailResponse): Company {
  return {
    id: exhibitor.exhibitor_id,
    name: exhibitor.exhibitor_name,
    boothNumber: exhibitor.booths?.[0] ? shortId(exhibitor.booths[0]) : "-",
    zone: "전시장",
    categoryLabel: exhibitor.business_types?.[0] ?? "승인 업체",
    summary: "승인된 참가업체 공개 정보입니다.",
    tags: exhibitor.business_types?.length ? exhibitor.business_types : ["APPROVED"],
    approvalStatus: "APPROVED",
  };
}

function companyFromBooth(booth: ApiBoothDetailResponse): Company {
  return {
    id: booth.exhibitor_id,
    name: `부스 ${shortId(booth.booth_id)}`,
    boothNumber: shortId(booth.booth_id),
    zone: "전시장",
    categoryLabel: `상태 ${booth.operating_status}`,
    summary: `혼잡도 ${booth.congestion_level}, row version ${booth.row_version}`,
    tags: ["BOOTH", booth.operating_status, booth.congestion_level],
    approvalStatus: "APPROVED",
  };
}

function recommendationFromApi(
  item: ApiRecommendationListResponse["results"][number],
): RecommendationItem {
  return {
    company: companyFromRecommendable(item.recommendable_id),
    score: item.normalized_score,
    reasons: item.reasons.length
      ? item.reasons.map((reason) => reason.reason_text)
      : [item.recommended_action ?? "추천 세션 결과"],
  };
}

function favoriteFromApi(item: ApiFavoriteListResponse["items"][number]): FavoriteItem {
  return {
    id: item.saved_recommendable_id,
    company: companyFromRecommendable(item.recommendable_id, "관심 대상"),
    savedAt: item.saved_at,
  };
}

function buyerMatchFromApi(
  item: ApiRecommendationListResponse["results"][number],
): BuyerMatchItem {
  return {
    company: companyFromRecommendable(item.recommendable_id, "바이어 매칭 대상"),
    matchScore: item.normalized_score,
    meetingStatus: item.recommended_action === "MEETING_REQUESTED" ? "REQUESTED" : "NONE",
  };
}

function profileFromApi(profile: ApiUserProfileResponse): UserProfile {
  return {
    displayName: profile.user_type === "BUYER_REGISTERED" ? "바이어 담당자" : "일반 참관객",
    userType: profile.user_type,
    interestAreas: profile.attributes?.map((attribute) => attribute.attribute_code) ?? [],
    marketingOptIn: false,
  };
}

export async function loadProfile(): Promise<LoadedData<UserProfile>> {
  try {
    const profile = await apiFetch<ApiUserProfileResponse>("/api/v1/profile/me", {
      headers: authHeaders(),
    });
    return fromApi(profileFromApi(profile));
  } catch (error) {
    return fallback(currentMockProfile, (error as Error).message);
  }
}

export async function loadRecommendations(
  scenario: MockScenario = "default",
): Promise<LoadedData<RecommendationItem[]>> {
  if (scenario === "error") {
    throw new Error("API_RECOMMENDATION_FETCH_FAILED");
  }
  if (scenario === "empty") {
    return fallback([]);
  }
  try {
    const response = await apiFetch<ApiRecommendationListResponse>("/api/v1/recommendations", {
      headers: authHeaders(),
    });
    return fromApi(response.results.map(recommendationFromApi));
  } catch (error) {
    return fallback(mockRecommendations, (error as Error).message);
  }
}

export async function loadFavorites(
  scenario: MockScenario = "default",
): Promise<LoadedData<FavoriteItem[]>> {
  if (scenario === "error") {
    throw new Error("API_FAVORITES_FETCH_FAILED");
  }
  if (scenario === "empty") {
    return fallback([]);
  }
  try {
    const response = await apiFetch<ApiFavoriteListResponse>("/api/v1/favorites", {
      headers: authHeaders(),
    });
    return fromApi(response.items.map(favoriteFromApi));
  } catch (error) {
    return fallback(mockFavorites, (error as Error).message);
  }
}

export async function loadBuyerMatches(
  scenario: MockScenario = "default",
): Promise<LoadedData<BuyerMatchItem[]>> {
  if (scenario === "error") {
    throw new Error("API_BUYER_MATCH_FETCH_FAILED");
  }
  if (scenario === "empty") {
    return fallback([]);
  }
  try {
    const response = await apiFetch<ApiRecommendationListResponse>("/api/v1/buyer/matches", {
      headers: authHeaders("BUYER_REGISTERED"),
    });
    return fromApi(response.results.map(buyerMatchFromApi));
  } catch (error) {
    return fallback(mockBuyerMatches, (error as Error).message);
  }
}

export async function loadCompanyById(
  id: string,
): Promise<LoadedData<Company | undefined>> {
  const fallbackCompany =
    mockCompanies.find((company) => company.id === id) ??
    (isLikelyUuid(id) ? companyFromRecommendable(id, "승인 대상") : undefined);
  try {
    const exhibitor = await apiFetch<ApiExhibitorDetailResponse>(
      `/api/v1/exhibitors/${encodeURIComponent(id)}`,
    );
    return fromApi(companyFromExhibitor(exhibitor));
  } catch (exhibitorError) {
    try {
      const booth = await apiFetch<ApiBoothDetailResponse>(
        `/api/v1/booths/${encodeURIComponent(id)}`,
      );
      return fromApi(companyFromBooth(booth));
    } catch {
      return fallback(fallbackCompany, (exhibitorError as Error).message);
    }
  }
}

async function createGuestSession(): Promise<string> {
  const eventId = headerValue("MEETAI_EVENT_ID");
  if (!eventId) {
    throw new Error("MEETAI_EVENT_ID_NOT_CONFIGURED");
  }
  const response = await apiFetch<ApiGuestWebSessionResponse>("/api/v1/guest/sessions", {
    method: "POST",
    body: JSON.stringify({
      event_id: eventId,
      entry_method: "EVENT_WEBSITE",
    }),
  });
  return response.guest_session_id;
}

export async function searchCompanies(
  query: string,
  mode: SearchMode,
): Promise<LoadedData<SearchResultItem[]>> {
  const normalized = query.trim();
  if (!normalized) {
    return fallback([]);
  }
  try {
    const guestSessionId = mode === "GUEST_WEB" ? await createGuestSession() : undefined;
    const response = await apiFetch<ApiSearchResponse>("/api/v1/search", {
      method: "POST",
      headers: authHeaders(userTypeForSearchMode(mode)),
      body: JSON.stringify({
        channel: mode,
        query_type: "FREE_TEXT",
        query_text: normalized,
        guest_session_id: guestSessionId,
      }),
    });
    return fromApi(
      response.results.map((result) => ({
        company: companyFromRecommendable(result.recommendable_id, "검색 결과"),
        matchedKeyword: normalized,
        score: result.final_score ?? undefined,
        reasons: result.reason_codes,
      })),
    );
  } catch (error) {
    const lower = normalized.toLowerCase();
    return fallback(
      mockCompanies
        .filter((company) =>
          [company.name, company.categoryLabel, ...company.tags].some((field) =>
            field.toLowerCase().includes(lower),
          ),
        )
        .map((company) => ({ company, matchedKeyword: normalized })),
      (error as Error).message,
    );
  }
}
