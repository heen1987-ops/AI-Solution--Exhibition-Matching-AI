import type {
  BuyerMatchItem,
  Company,
  FavoriteItem,
  RecommendationItem,
  UserProfile,
} from "./types";

/**
 * 하드코딩된 Mock 데이터. 실제 백엔드(backend/)를 호출하지 않는다
 * (G1_CONTRACT_FREEZE 이전 원칙, worker-prompts.md D "구현 원칙").
 * 모든 항목은 approvalStatus: "APPROVED"만 사용한다(AGENTS.md §8).
 */

export const mockCompanies: Company[] = [
  {
    id: "c-001",
    name: "지리산 목재가공",
    boothNumber: "A-12",
    zone: "A홀",
    categoryLabel: "목재·건축자재",
    summary: "친환경 목재 가공 설비 및 원목 자재 전문 업체.",
    tags: ["목재", "친환경", "건축자재"],
    approvalStatus: "APPROVED",
  },
  {
    id: "c-002",
    name: "설악 아웃도어",
    boothNumber: "B-05",
    zone: "B홀",
    categoryLabel: "아웃도어 장비",
    summary: "등산·트레킹 장비 및 기능성 의류 제조사.",
    tags: ["아웃도어", "의류", "장비"],
    approvalStatus: "APPROVED",
  },
  {
    id: "c-003",
    name: "태백 발효식품",
    boothNumber: "A-27",
    zone: "A홀",
    categoryLabel: "식품·발효",
    summary: "전통 발효 방식으로 제조한 지역 특산 식품 브랜드.",
    tags: ["식품", "발효", "지역특산"],
    approvalStatus: "APPROVED",
  },
  {
    id: "c-004",
    name: "소백 바이오소재",
    boothNumber: "C-03",
    zone: "C홀",
    categoryLabel: "바이오·소재",
    summary: "산림 부산물 기반 바이오 신소재 연구개발 기업.",
    tags: ["바이오", "신소재", "R&D"],
    approvalStatus: "APPROVED",
  },
  {
    id: "c-005",
    name: "덕유 관광콘텐츠",
    boothNumber: "B-19",
    zone: "B홀",
    categoryLabel: "관광·콘텐츠",
    summary: "지역 트레일 연계 관광 콘텐츠 및 굿즈 기획사.",
    tags: ["관광", "콘텐츠", "굿즈"],
    approvalStatus: "APPROVED",
  },
];

export const mockRecommendations: RecommendationItem[] = [
  {
    company: mockCompanies[0],
    score: 0.92,
    reasons: ["관심영역 '친환경 소재'와 일치", "최근 조회한 부스와 동일 존(A홀)"],
  },
  {
    company: mockCompanies[2],
    score: 0.81,
    reasons: ["관심영역 '지역특산'과 일치", "관심목록에 저장한 유사 업체 존재"],
  },
  {
    company: mockCompanies[3],
    score: 0.74,
    reasons: ["바이어 프로파일의 소싱 카테고리와 일치"],
  },
];

export const mockFavorites: FavoriteItem[] = [
  {
    id: "fav-001",
    company: mockCompanies[0],
    savedAt: "2026-07-28T09:12:00Z",
    savedZone: "A홀",
  },
];

export const mockBuyerMatches: BuyerMatchItem[] = [
  {
    company: mockCompanies[3],
    matchScore: 0.88,
    meetingStatus: "CONFIRMED",
    contact: { email: "contact@sobaek-bio.example", phone: "02-000-0000" },
  },
  {
    company: mockCompanies[0],
    matchScore: 0.76,
    meetingStatus: "REQUESTED",
  },
  {
    company: mockCompanies[4],
    matchScore: 0.61,
    meetingStatus: "NONE",
  },
];

export const mockGeneralProfile: UserProfile = {
  displayName: "일반 참관객",
  userType: "GENERAL_REGISTERED",
  interestAreas: ["친환경 소재", "지역특산", "아웃도어"],
  marketingOptIn: true,
};

export const mockBuyerProfile: UserProfile = {
  displayName: "바이어 담당자",
  userType: "BUYER_REGISTERED",
  interestAreas: ["바이오 신소재", "OEM 소싱"],
  marketingOptIn: false,
};

/** 이번 Wave 화면 뼈대에서는 항상 이 프로파일을 로그인 사용자로 가정한다(실 인증 미구현). */
export const currentMockProfile: UserProfile = mockGeneralProfile;
