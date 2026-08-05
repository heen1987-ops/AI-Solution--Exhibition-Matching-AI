export const DEMO_CATEGORIES = [
  "우리술",
  "기타주류",
  "연관제품",
  "기술",
  "가맹",
  "지역문화",
] as const;

export type DemoCategory = (typeof DEMO_CATEGORIES)[number];

export interface DemoExhibitor {
  id: string;
  name: string;
  boothNumber: string;
  category: DemoCategory;
  product: string;
  x: number;
  y: number;
  simulationOnly: true;
}

export interface RankedDemoExhibitor extends DemoExhibitor {
  score: number;
  reason: string;
}

export const DEMO_HALL = {
  name: "EXCO 서관 1층 3홀",
  areaSquareMeters: 4410,
  layoutStatus: "INFERRED_SIMULATION",
  entrance: { x: 50, y: 94 },
  zones: ["백주 사랑방", "달구벌 술곳간", "달구벌 주막", "초이스, 대구!!"],
} as const;

export const DEMO_VISITOR_PROFILE = {
  displayName: "김희섭",
  interests: ["우리술", "기술", "지역문화"] as DemoCategory[],
  goals: ["시음·이벤트 참여", "비즈니스"],
} as const;

const CATEGORY_SEQUENCE: DemoCategory[] = [
  ...Array<DemoCategory>(18).fill("우리술"),
  ...Array<DemoCategory>(8).fill("기타주류"),
  ...Array<DemoCategory>(6).fill("연관제품"),
  ...Array<DemoCategory>(7).fill("기술"),
  ...Array<DemoCategory>(5).fill("가맹"),
  ...Array<DemoCategory>(6).fill("지역문화"),
];

const NAME_PREFIXES = ["달빛", "산들", "누리", "고운", "다온", "마루", "새봄", "솔향", "한결", "온새미"];

const NAME_SUFFIX: Record<DemoCategory, string> = {
  우리술: "양조",
  기타주류: "브루잉",
  연관제품: "공방",
  기술: "테크",
  가맹: "컴퍼니",
  지역문화: "로컬랩",
};

const PRODUCTS: Record<DemoCategory, readonly string[]> = {
  우리술: ["쌀 탁주", "약주", "청주", "증류식 소주", "지역특산주"],
  기타주류: ["과실주", "로컬 와인", "수제 맥주", "허브 리큐르"],
  연관제품: ["백자 술잔", "전통 옹기", "술지게미 간식", "숙취해소 음료"],
  기술: ["스마트 발효기", "양조 미생물", "저온 살균기", "주류 물류 솔루션", "친환경 용기"],
  가맹: ["한식주점", "바틀샵", "K-PUB", "우리술 큐레이션"],
  지역문화: ["지역 안주", "양조장 관광", "우리쌀", "로컬 미식여행"],
};

function pad(value: number): string {
  return String(value).padStart(2, "0");
}

export const DEMO_EXHIBITORS: readonly DemoExhibitor[] = CATEGORY_SEQUENCE.map((category, index) => {
  const row = Math.floor(index / 10);
  const column = index % 10;
  const boothNumber = `${String.fromCharCode(65 + row)}-${pad(column + 1)}`;

  return {
    id: `demo-exhibitor-${pad(index + 1)}`,
    name: `${NAME_PREFIXES[index % NAME_PREFIXES.length]}${NAME_SUFFIX[category]} ${pad(index + 1)} (가상)`,
    boothNumber,
    category,
    product: PRODUCTS[category][index % PRODUCTS[category].length],
    x: 7.5 + column * 9.45,
    y: 25 + row * 13,
    simulationOnly: true,
  };
});

function goalBonus(category: DemoCategory, goals: readonly string[]): number {
  let bonus = 0;
  if (goals.includes("시음·이벤트 참여") && (category === "우리술" || category === "기타주류")) bonus += 14;
  if (goals.includes("비즈니스") && (category === "기술" || category === "가맹")) bonus += 13;
  if (goals.includes("비즈니스") && category === "지역문화") bonus += 7;
  return bonus;
}

function recommendationReason(category: DemoCategory, product: string, interests: readonly DemoCategory[], goals: readonly string[]): string {
  const interestMatched = interests.includes(category);
  if (interestMatched && category === "기술") return `${product} 중심의 비즈니스 관심을 반영`;
  if (interestMatched && category === "지역문화") return `${product} 중심의 지역문화 관심을 반영`;
  if (interestMatched && (category === "우리술" || category === "기타주류")) return `시음 목적과 연결되는 대표 품목: ${product}`;
  if (interestMatched) return `${category} 관심 반영 · 대표 품목 ${product}`;
  if (goals.includes("비즈니스") && (category === "기술" || category === "가맹")) return `${product} 비즈니스 가능성을 반영`;
  return `함께 둘러볼 대표 품목: ${product}`;
}

export function rankDemoExhibitors(
  interests: readonly DemoCategory[],
  goals: readonly string[] = DEMO_VISITOR_PROFILE.goals,
): RankedDemoExhibitor[] {
  return DEMO_EXHIBITORS.map((exhibitor, index) => ({
    ...exhibitor,
    score:
      25 +
      (interests.includes(exhibitor.category) ? 45 : 0) +
      goalBonus(exhibitor.category, goals) +
      ((index * 7) % 11),
    reason: recommendationReason(exhibitor.category, exhibitor.product, interests, goals),
  })).sort((left, right) => right.score - left.score || left.boothNumber.localeCompare(right.boothNumber));
}

export function selectDemoRecommendations(
  ranked: readonly RankedDemoExhibitor[],
  interests: readonly DemoCategory[],
  count = 10,
): RankedDemoExhibitor[] {
  const selected: RankedDemoExhibitor[] = [];
  const selectedIds = new Set<string>();
  const perCategory = interests.length <= 4 ? 2 : 1;

  for (const category of interests) {
    for (const candidate of ranked.filter((item) => item.category === category).slice(0, perCategory)) {
      if (selected.length >= count) break;
      selected.push(candidate);
      selectedIds.add(candidate.id);
    }
  }

  for (const candidate of ranked) {
    if (selected.length >= count) break;
    if (selectedIds.has(candidate.id)) continue;
    selected.push(candidate);
    selectedIds.add(candidate.id);
  }

  return selected;
}

function distance(
  from: { x: number; y: number },
  to: { x: number; y: number },
): number {
  return Math.hypot(from.x - to.x, from.y - to.y);
}

export function buildDemoRoute(
  recommendations: readonly RankedDemoExhibitor[],
  stopCount = 6,
): RankedDemoExhibitor[] {
  const remaining = [...recommendations.slice(0, Math.max(stopCount, 0))];
  const route: RankedDemoExhibitor[] = [];
  let current: { x: number; y: number } = DEMO_HALL.entrance;

  while (remaining.length > 0) {
    remaining.sort((left, right) => distance(current, left) - distance(current, right));
    const next = remaining.shift();
    if (!next) break;
    route.push(next);
    current = next;
  }

  return route;
}
