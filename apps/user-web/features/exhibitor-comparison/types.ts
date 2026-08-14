/**
 * 업체 비교(최대 4곳) 화면 전용 타입.
 *
 * 요구사항 (작업 지시 원문)
 * --------------------------
 * "side-by-side up to 4 exhibitors across product/tech, channel, MOQ, region, OEM/PB,
 * export, meeting-availability; UNKNOWN rendered as '확인 필요', never as blank or '불가'."
 *
 * 알려진 백엔드 공백 (통합 시 조율 필요 - 최종 보고서 참고)
 * -----------------------------------------------------------
 * `apps/api/app/schemas/exhibition_public.py`는 "공개정보"(로그인 없이 볼 수 있는 정보)
 * 단계만 정의한다고 문서 상단에 명시한다. 이 화면이 요구하는 유통채널·공급지역·MOQ·
 * OEM/PB·수출가능 여부는 그 문서가 "인증 바이어 공개정보"로 분류해 의도적으로 제외한
 * 필드다. 즉 지금은 어떤 API를 불러도 이 필드들을 얻을 수 없다 - 화면이 값을 지어내는 게
 * 아니라 실제로 아직 노출되지 않은 것이다. 아래 `UNKNOWN` 값을 그대로 두고
 * `MISSING_BUYER_TIER_FIELDS`에 기록해 둔다.
 */

export const UNKNOWN = null;
export type Maybe<T> = T | typeof UNKNOWN;

export interface ComparisonProductSummary {
  product_name: string;
  category_code: string | null;
}

export interface ComparisonExhibitor {
  exhibitor_id: string;
  company_name: string;
  company_summary: string | null;
  products: ComparisonProductSummary[];
  /** "인증 바이어 공개정보" 단계 필드 - 현재 공개 API 응답 범위 밖이라 항상 UNKNOWN.
   * 백엔드가 해당 필드를 노출하면 `api.ts`의 파싱만 바꾸면 되고 이 타입/화면은 그대로
   * 동작한다(옵셔널 체이닝으로 이미 대비돼 있음). */
  channels: Maybe<string[]>;
  moq: Maybe<{ min: number | null; max: number | null }>;
  regions: Maybe<string[]>;
  oemAvailable: Maybe<boolean>;
  privateLabelAvailable: Maybe<boolean>;
  exportAvailable: Maybe<boolean>;
  /** 오늘 날짜 상담 가능 슬롯 존재 여부. 조회에 성공했으면 true/false(실제로 아는 값),
   * 조회 자체가 실패했을 때만 UNKNOWN. */
  meetingAvailableToday: Maybe<boolean>;
}

/** 08 문서가 "인증 바이어 공개정보"로 분류해 아직 공개 API에 없는 필드 - 화면·보고서가
 * 함께 참조하는 단일 소스. */
export const MISSING_BUYER_TIER_FIELDS = [
  "channels",
  "moq",
  "regions",
  "oemAvailable",
  "privateLabelAvailable",
  "exportAvailable",
] as const;

export const MAX_COMPARISON_ITEMS = 4;

export interface ComparisonRowDef {
  key: string;
  label: string;
}

export const COMPARISON_ROWS: ComparisonRowDef[] = [
  { key: "products", label: "제품·기술" },
  { key: "channels", label: "유통채널" },
  { key: "moq", label: "최소주문수량(MOQ)" },
  { key: "regions", label: "공급 가능 지역" },
  { key: "oemAvailable", label: "OEM 가능" },
  { key: "privateLabelAvailable", label: "PB(자체브랜드) 가능" },
  { key: "exportAvailable", label: "수출 가능" },
  { key: "meetingAvailableToday", label: "오늘 상담 가능" },
];
