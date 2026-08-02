import type { KioskLanguage } from "./types";

/**
 * 카테고리 버튼에 쓰는 온톨로지 코드.
 *
 * 근거: src/meet_ai/ontology/catalog.v1.json의 PRODUCT_CATEGORY 개념 (259개 카탈로그
 * 중 방문객이 바로 고를 만한 assignable 리프 노드만 선별). 하드코딩 enum이 아니라
 * 온톨로지 카탈로그에 실제로 존재하는 코드 문자열이며, 검색요청의 `category_codes`에
 * 그대로 담아 보낸다. INDUSTRY.MANUFACTURING류의 폐기된 예시 코드는 쓰지 않는다.
 */
export interface KioskCategory {
  code: string;
  labels: Record<KioskLanguage, string>;
}

export const ALL_CATEGORIES: KioskCategory[] = [
  {
    code: "ALCOHOL.TAKJU",
    labels: { ko: "탁주 · 막걸리", en: "Takju (Rice Wine)", ja: "濁酒(マッコリ)", zh: "浊酒(马格利)" },
  },
  {
    code: "ALCOHOL.YAKJU",
    labels: { ko: "약주", en: "Yakju (Refined Rice Wine)", ja: "薬酒", zh: "药酒" },
  },
  {
    code: "ALCOHOL.CHEONGJU",
    labels: { ko: "청주", en: "Cheongju (Korean Sake)", ja: "清酒", zh: "清酒" },
  },
  {
    code: "ALCOHOL.SOJU_DISTILLED",
    labels: { ko: "증류식 소주", en: "Distilled Soju", ja: "蒸留式焼酎", zh: "蒸馏式烧酒" },
  },
  {
    code: "ALCOHOL.GRAIN_DISTILLED",
    labels: { ko: "곡물 증류주", en: "Grain Spirits", ja: "穀物蒸留酒", zh: "谷物蒸馏酒" },
  },
  {
    code: "ALCOHOL.FRUIT_DISTILLED",
    labels: { ko: "과실 증류주", en: "Fruit Spirits", ja: "果実蒸留酒", zh: "果物蒸馏酒" },
  },
  {
    code: "ALCOHOL.FRUIT_WINE",
    labels: { ko: "과실주", en: "Fruit Wine", ja: "果実酒", zh: "果酒" },
  },
  {
    code: "ALCOHOL.LIQUEUR",
    labels: { ko: "리큐르 · 혼성주", en: "Liqueurs & Blends", ja: "リキュール・混成酒", zh: "利口酒·混合酒" },
  },
  {
    code: "ALCOHOL.BEER",
    labels: { ko: "맥주", en: "Beer", ja: "ビール", zh: "啤酒" },
  },
  {
    code: "ALCOHOL.WINE",
    labels: { ko: "와인", en: "Wine", ja: "ワイン", zh: "葡萄酒" },
  },
  {
    code: "ALCOHOL.OTHER",
    labels: { ko: "기타 주류", en: "Other Alcohol", ja: "その他の酒類", zh: "其他酒类" },
  },
  {
    code: "NON_ALCOHOL.DRINK",
    labels: { ko: "무알코올 · 음료", en: "Non-Alcoholic Drinks", ja: "ノンアルコール飲料", zh: "无酒精饮料" },
  },
  {
    code: "PRODUCT.FOOD_PAIRING",
    labels: { ko: "안주 · 연관 식품", en: "Food Pairings", ja: "おつまみ・関連食品", zh: "下酒菜·相关食品" },
  },
  {
    code: "PRODUCT.REGIONAL_CONTENT",
    labels: { ko: "지역문화 · 관광", en: "Regional Culture & Tours", ja: "地域文化・観光", zh: "地区文化·旅游" },
  },
  {
    code: "PRODUCT.SERVICE",
    labels: { ko: "서비스 · 콘텐츠", en: "Services & Content", ja: "サービス・コンテンツ", zh: "服务·内容" },
  },
  {
    code: "PRODUCT.EQUIPMENT",
    labels: { ko: "제조 · 유통 설비", en: "Production & Distribution Equipment", ja: "製造・流通設備", zh: "生产·流通设备" },
  },
  {
    code: "PRODUCT.PACKAGING",
    labels: { ko: "포장 · 용기", en: "Packaging & Containers", ja: "包装・容器", zh: "包装·容器" },
  },
];

/** /search 검색홈 상단에 보여줄 빠른 카테고리 6개 (전체는 /categories). */
export const QUICK_CATEGORY_CODES = [
  "ALCOHOL.TAKJU",
  "ALCOHOL.YAKJU",
  "ALCOHOL.SOJU_DISTILLED",
  "ALCOHOL.FRUIT_WINE",
  "PRODUCT.FOOD_PAIRING",
  "PRODUCT.REGIONAL_CONTENT",
];

export const QUICK_CATEGORIES: KioskCategory[] = QUICK_CATEGORY_CODES.map(
  (code) => ALL_CATEGORIES.find((category) => category.code === code)!,
);

export function categoryLabel(code: string, language: KioskLanguage): string {
  return ALL_CATEGORIES.find((category) => category.code === code)?.labels[language] ?? code;
}
