/**
 * 바이어 프로파일 화면 전용 API 계층.
 *
 * 스코프 메모
 * -----------
 * `apps/user-web/lib/api-client.ts`/`lib/types.ts`는 통합 담당자만 고치는 공용 파일이라
 * (작업 지시) 여기서는 직접 수정하지 않는다. 대신:
 *   - 이미 계약된 엔드포인트(`getProfile`, `postAnswers`(BUYER_NEEDS 스텝),
 *     `patchProfileAttributes`)는 공용 클라이언트 함수를 그대로 재사용한다.
 *   - 아직 계약되지 않은 것(바이어 인증상태 전용 조회)은 공용 클라이언트가 이미 내보낸
 *     저수준 헬퍼(`apiGet`)로 얇게 호출한다("화면 에이전트가 이 파일에 없는 엔드포인트를
 *     임시로 호출해야 할 때 쓰는 저수준 헬퍼" - api-client.ts 337행 주석).
 *
 * 통합 시 필요한 작업(최종 보고서에도 동일하게 남김)
 * ----------------------------------------------------
 * `GET /api/v1/profiles/me/verification` 엔드포인트가 아직 백엔드에 없다. 이 파일은 그
 * 엔드포인트를 낙관적으로 호출하고, 404/UNKNOWN 계열 오류면 `deriveVerificationStatus`로
 * 안전하게 대체한다. 백엔드 트랙이 실제 엔드포인트를 추가하면 이 파일의 폴백 분기만
 * 제거하면 된다(화면 컴포넌트는 수정할 필요 없음 - `BuyerVerification.is_authoritative`로
 * 이미 구분하고 있다).
 */

import {
  ApiClientError,
  apiGet,
  getProfile,
  patchProfileAttributes,
  postAnswers,
  type RequestOptions,
} from "@/lib/api-client";
import type { BuyerNeedsRequest, ProfileView } from "@/lib/types";
import { fetchOntologyConcepts, type OntologyConcept } from "@/lib/ontology";

import {
  activeAttributeCodesByPrefix,
  toFormState,
  type BuyerProfileFormState,
  type BuyerVerification,
} from "./types";

// ---------------------------------------------------------------------------
// 인증 상태
// ---------------------------------------------------------------------------

/** 전용 엔드포인트가 없을 때의 안전한 폴백. LIMITED/REJECTED/SUSPENDED는 서버만 알 수
 * 있는 운영 판단이라 여기서는 절대 유추하지 않는다(근거 없는 부정적 상태를 지어내지
 * 않는다 - AGENTS.md "AI/서버가 모르는 값은 UNKNOWN으로 남긴다" 원칙을 인증상태에도
 * 동일하게 적용). */
export function deriveVerificationStatus(profile: ProfileView): BuyerVerification {
  const need = profile.buyer_need;
  if (!need) {
    return {
      status: "UNVERIFIED",
      restriction_note: null,
      decision_reason: null,
      reviewed_at: null,
      is_authoritative: false,
    };
  }
  if (need.business_email_verified && need.company_verified) {
    return {
      status: "VERIFIED",
      restriction_note: null,
      decision_reason: null,
      reviewed_at: null,
      is_authoritative: false,
    };
  }
  return {
    status: "PENDING",
    restriction_note: null,
    decision_reason: null,
    reviewed_at: null,
    is_authoritative: false,
  };
}

export async function fetchBuyerVerification(
  profile: ProfileView,
  options?: RequestOptions,
): Promise<BuyerVerification> {
  try {
    const remote = await apiGet<Partial<BuyerVerification>>("/profiles/me/verification", options);
    return {
      status: (remote.status as BuyerVerification["status"]) ?? "UNVERIFIED",
      restriction_note: remote.restriction_note ?? null,
      decision_reason: remote.decision_reason ?? null,
      reviewed_at: remote.reviewed_at ?? null,
      is_authoritative: true,
    };
  } catch (err) {
    // 엔드포인트가 아직 없거나(404) 표준 오류 봉투를 따르지 않는 경우 모두 폴백한다.
    if (err instanceof ApiClientError) {
      return deriveVerificationStatus(profile);
    }
    throw err;
  }
}

// ---------------------------------------------------------------------------
// 온톨로지 선택지
// ---------------------------------------------------------------------------

export interface BuyerOntologyOptions {
  buyerTypes: OntologyConcept[];
  industries: OntologyConcept[];
  interests: OntologyConcept[];
  channels: OntologyConcept[];
  regions: OntologyConcept[];
  cooperationTypes: OntologyConcept[];
  supplyCapacityTypes: OntologyConcept[];
}

async function safeFetchConcepts(conceptType: string): Promise<OntologyConcept[]> {
  try {
    return await fetchOntologyConcepts({ conceptType });
  } catch {
    // 목록을 못 가져와도 화면 전체를 막지 않는다 - 해당 섹션만 빈 목록으로 비활성 안내.
    return [];
  }
}

export async function fetchBuyerOntologyOptions(): Promise<BuyerOntologyOptions> {
  const [buyerTypes, industries, interests, channels, regions, cooperationTypes, supplyCapacityTypes] =
    await Promise.all([
      safeFetchConcepts("BUYER_TYPE"),
      safeFetchConcepts("PROFILE_TYPE"),
      safeFetchConcepts("BUSINESS_GOAL"),
      safeFetchConcepts("CHANNEL"),
      safeFetchConcepts("REGION"),
      safeFetchConcepts("TRADE_TYPE"),
      safeFetchConcepts("SUPPLY_CAPACITY"),
    ]);
  return { buyerTypes, industries, interests, channels, regions, cooperationTypes, supplyCapacityTypes };
}

// ---------------------------------------------------------------------------
// 프로파일 조회
// ---------------------------------------------------------------------------

export interface BuyerProfileData {
  profile: ProfileView;
  verification: BuyerVerification;
  form: BuyerProfileFormState;
}

export async function fetchBuyerProfile(): Promise<BuyerProfileData> {
  const profile = await getProfile();
  const [verification] = await Promise.all([fetchBuyerVerification(profile)]);
  const cooperationTypeCodes = activeAttributeCodesByPrefix(profile.attributes, "TRADE.");
  const industryAttr = profile.attributes.find(
    (attr) => attr.active && attr.attribute_code.startsWith("PROFILE."),
  );
  const form = toFormState(profile, cooperationTypeCodes, industryAttr?.attribute_code ?? null);
  return { profile, verification, form };
}

// ---------------------------------------------------------------------------
// 저장
// ---------------------------------------------------------------------------

export interface SaveBuyerProfileResult {
  profileVersion: number;
}

/**
 * 폼 상태를 실제 저장 요청 여러 건으로 분해해 순차 실행한다(BuyerNeedsRequest 구조화
 * 필드 1건 + 범용 속성 attribute 1건). 부분 실패 시 어느 부분이 저장됐는지 호출부가
 * 판단할 수 있도록 에러를 그대로 전파한다(자동 롤백 없음 - `postAnswers`/
 * `patchProfileAttributes` 모두 독립 트랜잭션).
 */
export async function saveBuyerProfile(
  form: BuyerProfileFormState,
  previous: BuyerProfileFormState,
): Promise<SaveBuyerProfileResult> {
  const needsRequest: BuyerNeedsRequest = {
    organization_type: form.buyerTypeCode,
    distribution_channels: form.channelCodes,
    desired_categories: [],
    target_price: null,
    expected_order_volume: form.orderScale,
    supply_regions: form.regionCodes,
    business_interests: form.interestCodes,
    decision_timeline: form.decisionTimeline,
  };
  const needsResponse = await postAnswers({ step: "BUYER_NEEDS", data: needsRequest });

  const attributePatches: {
    attribute_code: string;
    action: "UPSERT" | "REMOVE";
    value?: unknown;
    requirement_level?: "REQUIRED" | "PREFERRED" | "ACCEPTABLE" | "EXCLUDED";
  }[] = [];

  // 협력 형태(TRADE_TYPE 다중선택): 추가/제거 diff.
  const cooperationAdd = form.cooperationTypeCodes.filter(
    (code) => !previous.cooperationTypeCodes.includes(code),
  );
  const cooperationRemove = previous.cooperationTypeCodes.filter(
    (code) => !form.cooperationTypeCodes.includes(code),
  );
  for (const code of cooperationAdd) {
    attributePatches.push({ attribute_code: code, action: "UPSERT", value: true, requirement_level: "PREFERRED" });
  }
  for (const code of cooperationRemove) {
    attributePatches.push({ attribute_code: code, action: "REMOVE" });
  }

  // 업종(PROFILE_TYPE 단일선택): 이전 선택이 있고 바뀌었으면 제거 후 새로 upsert.
  if (previous.industryCode && previous.industryCode !== form.industryCode) {
    attributePatches.push({ attribute_code: previous.industryCode, action: "REMOVE" });
  }
  if (form.industryCode && form.industryCode !== previous.industryCode) {
    attributePatches.push({ attribute_code: form.industryCode, action: "UPSERT", value: true, requirement_level: "PREFERRED" });
  }

  if (attributePatches.length > 0) {
    await patchProfileAttributes({ attributes: attributePatches });
  }

  return { profileVersion: needsResponse.profile_version };
}
