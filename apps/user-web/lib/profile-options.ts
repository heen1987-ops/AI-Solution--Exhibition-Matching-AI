/**
 * 사용자 프로파일 입력에 사용하는 공개 온톨로지 코드.
 *
 * 임시 화면 코드가 아니라 `src/meet_ai/ontology/catalog.v1.json`의 PUBLISHED/assignable
 * 코드만 사용한다. 이 파일의 선택지는 화면용 부분집합이며, 저장된 다른 공개 코드는
 * `profileCodeLabel`의 안전한 fallback으로 계속 표시할 수 있다.
 */

export interface ProfileOption {
  code: string;
  label: string;
}

export const VISITOR_GOAL_OPTIONS: readonly ProfileOption[] = [
  { code: "GOAL.TASTING", label: "시음" },
  { code: "GOAL.ON_SITE_PURCHASE", label: "현장구매" },
  { code: "GOAL.GIFT_SEARCH", label: "선물 찾기" },
  { code: "GOAL.REGIONAL_DISCOVERY", label: "지역술 탐색" },
  { code: "GOAL.CULTURAL_EXPERIENCE", label: "지역문화 체험" },
  { code: "GOAL.PROGRAM_PARTICIPATION", label: "프로그램 참여" },
  { code: "GOAL.INFORMATION_SEARCH", label: "정보 수집" },
  { code: "GOAL.CASUAL_VISIT", label: "일반 관람" },
] as const;

export const BUYER_GOAL_OPTIONS: readonly ProfileOption[] = [
  { code: "BIZ_GOAL.NEW_SUPPLIER", label: "신규 공급업체 발굴" },
  { code: "BIZ_GOAL.NEW_PRODUCT", label: "신규 제품 발굴" },
  { code: "BIZ_GOAL.DISTRIBUTION", label: "유통·입점 상담" },
  { code: "BIZ_GOAL.TECHNOLOGY", label: "양조기술·설비 상담" },
  { code: "BIZ_GOAL.INVESTMENT", label: "투자·사업제휴" },
  { code: "BIZ_GOAL.MARKET_RESEARCH", label: "시장조사" },
  { code: "BIZ_GOAL.EXPORT", label: "수출 상담" },
  { code: "BIZ_GOAL.PUBLIC_COOPERATION", label: "지역·공공사업 협력" },
] as const;

export const PRODUCT_CATEGORY_OPTIONS: readonly ProfileOption[] = [
  { code: "ALCOHOL.TAKJU", label: "탁주" },
  { code: "ALCOHOL.YAKJU", label: "약주" },
  { code: "ALCOHOL.CHEONGJU", label: "청주" },
  { code: "ALCOHOL.DISTILLED", label: "증류주" },
  { code: "ALCOHOL.FRUIT_WINE", label: "과실주" },
  { code: "ALCOHOL.WINE", label: "와인" },
  { code: "ALCOHOL.BEER", label: "맥주" },
  { code: "ALCOHOL.OTHER", label: "기타주류" },
] as const;

export const TASTE_OPTIONS: readonly ProfileOption[] = [
  { code: "TASTE.SWEET", label: "달콤" },
  { code: "TASTE.DRY", label: "드라이" },
  { code: "TASTE.FRESH", label: "산뜻" },
  { code: "TASTE.RICH", label: "진하고 묵직함" },
  { code: "AROMA.FRUIT", label: "과일향" },
  { code: "TASTE.SMOOTH", label: "부드러움" },
] as const;

export const BUYER_CHANNEL_OPTIONS: readonly ProfileOption[] = [
  { code: "CHANNEL.DEPARTMENT_STORE", label: "백화점" },
  { code: "CHANNEL.LARGE_MART", label: "대형마트" },
  { code: "CHANNEL.BOTTLE_SHOP", label: "바틀샵" },
  { code: "CHANNEL.SPECIALIZED_MALL", label: "온라인 전문몰" },
  { code: "CHANNEL.RESTAURANT", label: "음식점" },
  { code: "CHANNEL.EXPORT", label: "수출" },
  { code: "CHANNEL.FRANCHISE", label: "프랜차이즈" },
  { code: "CHANNEL.CORPORATE_GIFT", label: "기업 선물" },
] as const;

export const SUPPLY_REGION_OPTIONS: readonly ProfileOption[] = [
  { code: "REGION.KR.SEOUL", label: "서울" },
  { code: "REGION.KR.BUSAN", label: "부산" },
  { code: "REGION.KR.DAEGU", label: "대구" },
  { code: "REGION.KR.INCHEON", label: "인천" },
  { code: "REGION.KR.GWANGJU", label: "광주" },
  { code: "REGION.KR.DAEJEON", label: "대전" },
  { code: "REGION.KR.ULSAN", label: "울산" },
  { code: "REGION.KR.SEJONG", label: "세종" },
  { code: "REGION.KR.GYEONGGI", label: "경기" },
  { code: "REGION.KR.GANGWON", label: "강원" },
  { code: "REGION.KR.CHUNGBUK", label: "충북" },
  { code: "REGION.KR.CHUNGNAM", label: "충남" },
  { code: "REGION.KR.JEONBUK", label: "전북" },
  { code: "REGION.KR.JEONNAM", label: "전남" },
  { code: "REGION.KR.GYEONGBUK", label: "경북" },
  { code: "REGION.KR.GYEONGNAM", label: "경남" },
  { code: "REGION.KR.JEJU", label: "제주" },
] as const;

const PROFILE_LABELS = new Map<string, string>(
  [
    ...VISITOR_GOAL_OPTIONS,
    ...BUYER_GOAL_OPTIONS,
    ...PRODUCT_CATEGORY_OPTIONS,
    ...TASTE_OPTIONS,
    ...BUYER_CHANNEL_OPTIONS,
    ...SUPPLY_REGION_OPTIONS,
    { code: "PRODUCT.FOOD_PAIRING", label: "안주·연관 식품" },
    { code: "PRODUCT.EQUIPMENT", label: "제조·유통 설비" },
    { code: "PRODUCT.PACKAGING", label: "포장·용기" },
    { code: "PRODUCT.REGIONAL_CONTENT", label: "지역문화·관광" },
    { code: "CHANNEL.BOTTLE_SHOP", label: "주류 전문점·바틀샵" },
    { code: "CHANNEL.RESTAURANT", label: "음식점" },
    { code: "USE.FOOD_PAIRING", label: "음식 페어링" },
    { code: "SERVICE.TASTING", label: "시음" },
    { code: "SERVICE.PURCHASE", label: "현장구매" },
  ].map((item) => [item.code, item.label]),
);

const LEGACY_PROFILE_CODES: Readonly<Record<string, string>> = {
  TASTING: "GOAL.TASTING",
  PURCHASE: "GOAL.ON_SITE_PURCHASE",
  GIFT_SEARCH: "GOAL.GIFT_SEARCH",
  LOCAL_LIQUOR_EXPLORATION: "GOAL.REGIONAL_DISCOVERY",
  EVENT_EXPERIENCE: "GOAL.PROGRAM_PARTICIPATION",
  BREWING_TECHNOLOGY: "GOAL.INFORMATION_SEARCH",
  TRADE_CONSULTATION: "BIZ_GOAL.DISTRIBUTION",
  MARKET_RESEARCH: "BIZ_GOAL.MARKET_RESEARCH",
};

export function canonicalizeLegacyProfileCode(code: string): string {
  return LEGACY_PROFILE_CODES[code] ?? code;
}

export function profileCodeLabel(code: string): string {
  const known = PROFILE_LABELS.get(code);
  if (known) return known;
  const leaf = code.split(".").pop() ?? code;
  return leaf.replaceAll("_", " ").toLocaleLowerCase("ko-KR");
}
