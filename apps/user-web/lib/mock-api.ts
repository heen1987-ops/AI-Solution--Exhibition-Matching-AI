import {
  mockBuyerMatches,
  mockCompanies,
  mockFavorites,
  mockRecommendations,
} from "./mock-data";
import type {
  BuyerMatchItem,
  Company,
  FavoriteItem,
  MockScenario,
  RecommendationItem,
  SearchResultItem,
} from "./types";

/**
 * Mock API 레이어. 실제 네트워크 호출을 하지 않고, 인위적 지연만 흉내내어
 * App Router의 loading.tsx/error.tsx 동작을 시연한다.
 *
 * `scenario`로 loading(자동)/empty/error 3가지 상태를 재현한다 - 화면에는
 * `?state=empty`, `?state=error` 쿼리로 접근해 확인할 수 있다.
 */

function delay(ms = 400): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export async function fetchRecommendations(
  scenario: MockScenario = "default",
): Promise<RecommendationItem[]> {
  await delay();
  if (scenario === "error") {
    throw new Error("MOCK_RECOMMENDATION_FETCH_FAILED");
  }
  if (scenario === "empty") {
    return [];
  }
  return mockRecommendations;
}

export async function fetchFavorites(
  scenario: MockScenario = "default",
): Promise<FavoriteItem[]> {
  await delay(200);
  if (scenario === "error") {
    throw new Error("MOCK_FAVORITES_FETCH_FAILED");
  }
  if (scenario === "empty") {
    return [];
  }
  return mockFavorites;
}

export async function fetchBuyerMatches(
  scenario: MockScenario = "default",
): Promise<BuyerMatchItem[]> {
  await delay(200);
  if (scenario === "error") {
    throw new Error("MOCK_BUYER_MATCH_FETCH_FAILED");
  }
  if (scenario === "empty") {
    return [];
  }
  return mockBuyerMatches;
}

export async function fetchCompanyById(id: string): Promise<Company | undefined> {
  await delay(150);
  return mockCompanies.find((company) => company.id === id);
}

export function searchCompaniesByKeyword(keyword: string): SearchResultItem[] {
  const normalized = keyword.trim().toLowerCase();
  if (!normalized) {
    return [];
  }
  return mockCompanies
    .filter((company) =>
      [company.name, company.categoryLabel, ...company.tags].some((field) =>
        field.toLowerCase().includes(normalized),
      ),
    )
    .map((company) => ({ company, matchedKeyword: keyword }));
}
