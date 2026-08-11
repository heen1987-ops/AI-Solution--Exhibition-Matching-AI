/**
 * AI 검수 화면의 판정 로직 - 순수 함수만 둔다(테스트 용이성, `./tests/logic.test.ts` 참고).
 *
 * 2026-08-03 재조정: 이 파일은 원래 라우터가 착지하기 전의 잠정 계약
 * (`AiReviewAttribute`, `attribute_id`, `value_type: "TRADE_AVAILABILITY"`, `current_value` 등)을
 * 대상으로 작성되어 있었다. BACKEND-EXTRACTION의 `extraction.py` 라우터가 실제로 착지하면서
 * `./types.ts`가 그 실제 계약(`ExtractedAttributeRead` - `extraction_id`, `proposed_value`/
 * `normalized_value`, `concept_codes`, `entity_type` 등)으로 다시 맞춰졌는데, 이 파일은 갱신되지
 * 않아 `types.ts`가 더 이상 내보내지 않는 이름(`AiReviewAttribute`, `TaxonomyRef`)을 계속 import
 * 하고 있었다 - 컴파일이 깨진 상태였다(vitest 재현: `isTradeConditionAttributeCode is not a
 * function`, 그 위층에서는 타입 자체가 없어 `tsc --noEmit`도 실패). 이 파일을 실제 착지한
 * `ExtractedAttributeRead` 모양에 맞춰 다시 썼다.
 *
 * 작업 지시 필수 요구사항을 여기서 강제한다:
 *   1. 신뢰도는 "단정적 사실"이 아니라 완곡한 지표로만 보여준다 -> confidenceTone/confidenceLabel.
 *   2. UNKNOWN -> YES 전이는 침묵 토글 금지, 명시적 확인(+ 가능하면 사유) 필요 ->
 *      requiresExplicitUnknownToYesConfirmation.
 *   3. 거래조건 필드는 시각적으로 강조 -> isTradeConditionAttribute.
 *
 * `requiresExplicitUnknownToYesConfirmation`는 오직 "수정(modify)" 경로에서만 의미가 있다는
 * 점에 주의: 착지한 백엔드 계약(`POST .../confirm`)은 값을 받지 않는다 - 이미 행에 있는
 * `normalized_value`(없으면 `proposed_value`)를 그대로 확정할 뿐이다. 즉 "AI 제안값을 그대로
 * 확인"하는 작업의 baseline과 resultingValue는 수학적으로 항상 같은 값이라 이 함수가 절대
 * true를 반환할 수 없다(같은 값이 "UNKNOWN"이면서 동시에 "긍정값"일 수는 없다) - 그래서
 * `../api.ts`의 `confirmProposedValue`는 이 가드를 호출하지 않는다. 실제로 게이트가 걸리는
 * 지점은 오직 `saveModifiedValue`(PATCH로 값을 바꾼 뒤 confirm)뿐이며, 이는 작업 지시의
 * 문구("전시업체가 UNKNOWN을 YES로 **바꾸려** 할 때")와도 정확히 일치한다. */

import { CAPABILITY_ENUM_ATTRIBUTE_CODES, isTradeConditionAttributeCode } from "./types";
import type { ExtractedAttributeRead, JsonValue } from "./types";

export { isTradeConditionAttributeCode };

export function isTradeConditionAttribute(
  attribute: Pick<ExtractedAttributeRead, "attribute_code" | "entity_type">,
): boolean {
  return (
    attribute.entity_type === "TRADE_CONDITION" || isTradeConditionAttributeCode(attribute.attribute_code)
  );
}

// ---------------------------------------------------------------------------
// 신뢰도 - 절대 "사실"처럼 보이면 안 된다. 정확한 %를 강조하지 않고 3단계 완곡 지표 +
// 원 수치는 보조 정보로만 작게 덧붙인다.
// ---------------------------------------------------------------------------

export type ConfidenceTone = "low" | "medium" | "high" | "unknown";

export function confidenceTone(confidence: number | null): ConfidenceTone {
  if (confidence === null || Number.isNaN(confidence)) return "unknown";
  if (confidence < 0.5) return "low";
  if (confidence < 0.8) return "medium";
  return "high";
}

const CONFIDENCE_LABEL_KO: Record<ConfidenceTone, string> = {
  low: "AI 확신도 낮음 - 꼭 확인해 주세요",
  medium: "AI 확신도 보통",
  high: "AI 확신도 높음 (그래도 확인 필요)",
  unknown: "신뢰도 정보 없음",
};

/** 절대 "정확도 XX%" 같은 단정적 문구를 만들지 않는다 - 완곡한 라벨 뒤에 참고용 수치만 괄호로
 * 덧붙인다(작업 지시: "확신에 찬 사실처럼 표시하지 말 것"). */
export function confidenceLabel(confidence: number | null): string {
  const tone = confidenceTone(confidence);
  const base = CONFIDENCE_LABEL_KO[tone];
  if (confidence === null) return base;
  const percentHint = Math.round(confidence * 100);
  return `${base} (참고치 ${percentHint}%)`;
}

// ---------------------------------------------------------------------------
// UNKNOWN -> YES 전이 판정
//
// 실제 착지한 스키마에는 (구 잠정계약의) `value_type: "TRADE_AVAILABILITY"` 판별자가 없다.
// 대신 `types.ts`의 `CAPABILITY_ENUM_ATTRIBUTE_CODES`(trade.oem_capability /
// trade.private_label_capability / trade.export_capability - 작업 지시의 OEM/PB/수출 항목과
// 정확히 대응)가 SUPPORTED/NOT_SUPPORTED/UNKNOWN 3단계 능력치 값을 갖는 필드 목록이다. 이
// 목록에 속한 필드에서만 "UNKNOWN -> 긍정값" 전이 가드가 의미를 갖는다 - 숫자(MOQ,
// lead_time_days)·텍스트·온톨로지참조 필드는 이 규칙과 무관하다.
// ---------------------------------------------------------------------------

const POSITIVE_CAPABILITY_VALUES = new Set(["SUPPORTED", "YES"]);

function isUnknownCapabilityValue(value: JsonValue | undefined): boolean {
  return value === null || value === undefined || value === "UNKNOWN";
}

function isPositiveCapabilityValue(value: JsonValue | undefined): boolean {
  return typeof value === "string" && POSITIVE_CAPABILITY_VALUES.has(value);
}

/** 이 속성을 confirm(제안값 그대로) 또는 modify(PATCH 후 confirm)했을 때 "결과값"이
 * UNKNOWN에서 YES(=SUPPORTED)로 바뀌는 전이인지 판정한다. 기준값(before)은 이미 업체가 PATCH로
 * 고친 `normalized_value`가 있으면 그것을, 없으면 AI 원 제안값(`proposed_value`)을 쓴다 - 둘 다
 * 없으면(null) UNKNOWN으로 취급한다. */
export function requiresExplicitUnknownToYesConfirmation(
  attribute: Pick<ExtractedAttributeRead, "attribute_code" | "normalized_value" | "proposed_value">,
  resultingValue: JsonValue | undefined,
): boolean {
  if (!(CAPABILITY_ENUM_ATTRIBUTE_CODES as readonly string[]).includes(attribute.attribute_code)) {
    return false;
  }
  const baseline =
    attribute.normalized_value !== null && attribute.normalized_value !== undefined
      ? attribute.normalized_value
      : attribute.proposed_value;
  return isUnknownCapabilityValue(baseline) && isPositiveCapabilityValue(resultingValue);
}

/** 정책: UNKNOWN->YES 전이에서는 자유서술 사유(justification)가 비어 있으면 네트워크 호출
 * 자체를 막는다 - "가능하면" 요구가 아니라 이 화면에서는 필수로 강제한다(작업 지시가 이상적
 * 형태로 언급했지만, 침묵 토글을 확실히 막으려면 사유 없는 확인은 의미가 약하다고 판단). */
export function validateUnknownToYesJustification(justification: string | null | undefined): string | null {
  if (!justification || !justification.trim()) {
    return "미확인(UNKNOWN) 상태를 '가능(YES)'으로 바꾸려면 확인 사유를 입력해야 합니다.";
  }
  return null;
}
