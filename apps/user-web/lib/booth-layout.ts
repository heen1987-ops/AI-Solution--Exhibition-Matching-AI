export const BOOTH_LAYOUT_STATUS = "DRAFT_REFERENCE" as const;

export type ProvisionalBoothZone = {
  id: string;
  title: string;
  detail: string;
  status: "PROVISIONAL";
};

export const PROVISIONAL_BOOTH_ZONES: readonly ProvisionalBoothZone[] = [
  { id: "A", title: "우리술", detail: "탁주 · 약주 · 청주 · 증류주", status: "PROVISIONAL" },
  { id: "B", title: "기타주류", detail: "과실주 · 와인 · 맥주", status: "PROVISIONAL" },
  { id: "C", title: "연관제품", detail: "술잔 · 옹기 · 식품 · 서비스", status: "PROVISIONAL" },
  { id: "D", title: "양조·유통 기술", detail: "발효 · 전후공정 · 유통", status: "PROVISIONAL" },
  { id: "E", title: "가맹·비즈니스", detail: "주점 · 바틀샵 · K-PUB", status: "PROVISIONAL" },
  { id: "F", title: "지역문화", detail: "농업 · 음식 · 관광", status: "PROVISIONAL" },
] as const;
