/**
 * 바이어 프로파일 화면 전용 타입.
 *
 * 스코프 메모
 * -----------
 * WAVE 2C(USER-WEB-BUYER) 트랙 소유. `apps/user-web/lib/types.ts`(공용, 수정 금지)와
 * 겹치는 부분(`ProfileView`, `BuyerNeedView`, `BuyerNeedsRequest` 등)은 그대로 import해
 * 재사용하고, 이 파일은 그 공용 타입이 아직 표현하지 못하는 바이어 인증상태·화면 전용
 * 폼 상태만 추가로 정의한다.
 *
 * 알려진 백엔드 공백 (통합 시 `apps/api` 담당 트랙과 조율 필요 - 최종 보고서 참고)
 * -------------------------------------------------------------------------------
 * 1. `verification_status` — `apps/api/app/schemas/profile.py`의 `BuyerNeedView`에는
 *    `business_email_verified`/`company_verified` 두 불리언만 있고, 이 화면이 요구하는
 *    UNVERIFIED/PENDING/VERIFIED/LIMITED/REJECTED/SUSPENDED 상태 머신이 없다.
 *    `fetchBuyerVerification`(./api.ts)이 전용 엔드포인트가 없을 때 이 두 불리언에서
 *    보수적으로 유추한다(LIMITED/REJECTED/SUSPENDED는 서버 신호 없이는 유추하지 않음 -
 *    잘못된 긍정/부정 상태를 지어내지 않기 위해서다).
 * 2. "업종(industry)" — 259개 온톨로지 카탈로그(`src/meet_ai/ontology/catalog.v1.json`)에
 *    별도 INDUSTRY concept_type이 없다. 가장 근접한 기존 개념인 `PROFILE_TYPE`
 *    (PROFILE.BUSINESS_BUYER/PROFILE.INDUSTRY/PROFILE.MEDIA/PROFILE.PUBLIC_AGENCY 등)를
 *    재사용한다 - 새 코드를 만들지 않는다(AGENTS.md 절대금지: "온톨로지 코드를 새로 만들지
 *    않는다").
 * 3. "협력 형태(cooperation types)" — `BuyerNeedsRequest`에 전용 필드가 없다. `TRADE_TYPE`
 *    온톨로지(TRADE.OEM/TRADE.PRIVATE_LABEL/TRADE.WHOLESALE 등)를 범용 프로파일 속성
 *    upsert/remove API(`patchProfileAttributes`, 이미 `lib/api-client.ts`에 존재)로
 *    저장한다 - `ProfileView.attributes`가 이미 이런 "온톨로지 코드 + 선택 여부" 패턴을
 *    쓰고 있어(방문 목적과 동일한 방식) 새 백엔드 작업 없이 바로 쓸 수 있다.
 */

import type {
  AttributeView,
  BuyerNeedView,
  ExpectedOrderVolume,
  ProfileView,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// 인증 상태
// ---------------------------------------------------------------------------

export type BuyerVerificationStatus =
  | "UNVERIFIED"
  | "PENDING"
  | "VERIFIED"
  | "LIMITED"
  | "REJECTED"
  | "SUSPENDED";

export interface BuyerVerification {
  status: BuyerVerificationStatus;
  /** LIMITED일 때 구체적 제한 사유. 서버가 안 주면 화면은 일반 문구로 대체한다. */
  restriction_note: string | null;
  /** REJECTED/SUSPENDED일 때 사용자가 참고할 수 있는 사유(선택). */
  decision_reason: string | null;
  reviewed_at: string | null;
  /** 이 값이 true면 실제 서버 상태이고, false면 아래 "유추 근거"에서 임시로 계산한
   * 값이라는 뜻이다 - 화면이 안내 문구 신뢰도를 조절하는 데 쓴다. */
  is_authoritative: boolean;
}

// ---------------------------------------------------------------------------
// 화면 폼 상태
// ---------------------------------------------------------------------------

export interface BuyerProfileFormState {
  /** BUYER_TYPE 온톨로지 코드 1개 (예: `BUYER.RESTAURANT`). `organization_type`에 저장한다. */
  buyerTypeCode: string | null;
  /** PROFILE_TYPE 온톨로지 코드 1개. 범용 속성으로 저장한다(위 공백 메모 2번). */
  industryCode: string | null;
  /** BUSINESS_GOAL 코드 목록. `business_interests`에 저장한다. */
  interestCodes: string[];
  /** CHANNEL 코드 목록. `distribution_channels`에 저장한다. */
  channelCodes: string[];
  /** REGION 코드 목록. `supply_regions`에 저장한다. */
  regionCodes: string[];
  /** TRADE_TYPE 코드 목록. 범용 속성으로 저장한다(위 공백 메모 3번). */
  cooperationTypeCodes: string[];
  orderScale: ExpectedOrderVolume;
  /** 개방형 문자열(온톨로지 아님, `BuyerNeedsRequest.decision_timeline`과 동일 계약). */
  decisionTimeline: string | null;
}

export function emptyBuyerProfileFormState(): BuyerProfileFormState {
  return {
    buyerTypeCode: null,
    industryCode: null,
    interestCodes: [],
    channelCodes: [],
    regionCodes: [],
    cooperationTypeCodes: [],
    orderScale: { type: null, monthly_units_min: null, monthly_units_max: null },
    decisionTimeline: null,
  };
}

/** `ProfileView` + 부가 조회 결과를 화면 폼 상태로 변환한다. */
export function toFormState(
  profile: ProfileView,
  cooperationTypeCodes: string[],
  industryCode: string | null,
): BuyerProfileFormState {
  const need: BuyerNeedView | null = profile.buyer_need;
  return {
    buyerTypeCode: need?.organization_type ?? null,
    industryCode,
    interestCodes: extractAddRemoveSource(profile, "business_interests"),
    channelCodes: extractAddRemoveSource(profile, "distribution_channels"),
    regionCodes: extractAddRemoveSource(profile, "supply_regions"),
    cooperationTypeCodes,
    orderScale: {
      type: null,
      monthly_units_min: need?.monthly_units_min ?? null,
      monthly_units_max: need?.monthly_units_max ?? null,
    },
    decisionTimeline: need?.decision_timeline ?? null,
  };
}

/**
 * `ProfileView`는 `consumer_preferences`/`attributes`처럼 여러 곳에 나눠 최신 스냅샷을
 * 담는다(07 26.1절). `business_interests`/`distribution_channels`/`supply_regions`는
 * `BuyerNeedsRequest`가 정의한 필드지만 `ProfileView` 응답 자체에는 전용 필드가 없어(현재
 * `consumer_preferences` dict 안에 병합돼 있다고 가정) 방어적으로 읽는다. 필드가 없으면
 * 빈 배열로 취급한다(값을 지어내지 않는다).
 */
function extractAddRemoveSource(profile: ProfileView, key: string): string[] {
  const source = profile.consumer_preferences?.[key];
  return Array.isArray(source) && source.every((item) => typeof item === "string")
    ? source
    : [];
}

/** `ProfileView.attributes`에서 특정 코드 프리픽스(예: `TRADE.`)로 시작하는, 현재
 * 활성 상태인 코드만 추려낸다. 협력 형태·업종처럼 범용 속성 API로 저장하는 필드에 쓴다. */
export function activeAttributeCodesByPrefix(
  attributes: AttributeView[],
  prefix: string,
): string[] {
  return attributes
    .filter((attr) => attr.active && attr.attribute_code.startsWith(prefix))
    .map((attr) => attr.attribute_code);
}

export const DECISION_TIMELINE_PRESETS: Array<{ value: string; label: string }> = [
  { value: "IMMEDIATE", label: "즉시" },
  { value: "WITHIN_1_MONTH", label: "1개월 이내" },
  { value: "WITHIN_3_MONTHS", label: "1~3개월" },
  { value: "WITHIN_6_MONTHS", label: "3~6개월" },
  { value: "UNDECIDED", label: "미정" },
];
