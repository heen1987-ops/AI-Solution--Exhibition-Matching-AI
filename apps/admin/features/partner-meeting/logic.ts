/**
 * 상담 요청함의 순수 판정 로직. 컴포넌트에서 분리해 vitest로 직접 검증한다
 * (tests/logic.test.ts).
 */

import type { PartnerBuyerSummaryResponse, PartnerDecisionAction } from "./types";

export const MEETING_CONFIRMED_STATUS = "accepted" as const;

/**
 * 연락처를 화면에 그려도 되는지 판정한다.
 *
 * `GET /partner/meetings/{id}/buyer-summary`가 이미 "확정 + 공유동의"를 만족할 때만
 * `contact`를 채워 보낸다(meetings.py 12.3/15절 주석). 이 함수는 그 서버 판단을 다시
 * 신뢰하지 않고 상태값까지 함께 검사하는 방어적 이중 확인이다 - 캐시된 오래된 응답을
 * 재사용하거나 향후 리팩터링 실수로 `contact`가 채워진 채 남아 있어도, `status`가
 * accepted가 아니면 화면에는 절대 노출하지 않는다("상담 확정 전 연락처 비공개"는
 * 작업 지시의 핵심 요구사항).
 */
export function shouldRevealContact(
  summary: Pick<PartnerBuyerSummaryResponse, "status" | "contact">,
): boolean {
  return summary.status === MEETING_CONFIRMED_STATUS && summary.contact !== null;
}

export interface DecisionFormInput {
  action: PartnerDecisionAction;
  slotId: string | null;
  reasonCode: string | null;
}

export interface DecisionFieldError {
  field: "slotId" | "reasonCode";
  reason: string;
}

/**
 * `POST /partner/meetings/{id}/decision` 제출 전 클라이언트 검증.
 *
 * - ACCEPT/COUNTER_PROPOSE: 시간 슬롯 선택 필수(PartnerDecisionRequest 검증자
 *   `_slot_required_unless_reject`와 동일한 규칙을 프론트에서도 미리 적용해, 필드
 *   오류를 서버 왕복 없이 바로 보여준다).
 * - REJECT: 사유코드 필수(작업 지시 "reason-code required on reject" - 백엔드
 *   PartnerDecisionRequest.reason_code 자체는 선택 필드이지만, 이 화면 정책으로 반려만은
 *   강제한다).
 */
export function validateDecisionInput(input: DecisionFormInput): DecisionFieldError[] {
  const errors: DecisionFieldError[] = [];
  if (input.action !== "REJECT" && !input.slotId) {
    errors.push({
      field: "slotId",
      reason: "수락/시간재제안에는 시간 슬롯 선택이 필요합니다.",
    });
  }
  if (input.action === "REJECT" && !input.reasonCode) {
    errors.push({ field: "reasonCode", reason: "반려 사유를 선택해야 합니다." });
  }
  return errors;
}

/** wireframes 8절 E-02 반려 사유 후보(잠정). TODO(6단계 온톨로지 REJECT_REASON.* 네임스페이스
 * 시드 확정 후): 정식 concept_code 목록으로 교체. 지금은 PartnerDecisionRequest.reason_code가
 * 자유 문자열(최대 50자)이라 이 코드값이 그대로 저장·조회된다. */
export const REJECT_REASON_CODES: { code: string; label: string }[] = [
  { code: "CAPACITY_SHORTAGE", label: "공급 여력 부족" },
  { code: "PRICE_MISMATCH", label: "희망 가격대 불일치" },
  { code: "REGION_NOT_SUPPORTED", label: "희망 공급지역 미지원" },
  { code: "DUPLICATE_REQUEST", label: "중복 요청" },
  { code: "SCHEDULE_CONFLICT", label: "일정 불가" },
  { code: "OTHER", label: "기타" },
];

export const OUTCOME_CODES: { code: string; label: string }[] = [
  { code: "QUALIFIED_LEAD", label: "유효 리드" },
  { code: "NEEDS_FOLLOW_UP", label: "추가 검토" },
  { code: "INFO_PROVIDED", label: "정보 제공" },
  { code: "CONDITION_MISMATCH", label: "조건 불일치" },
];

export const FOLLOW_UP_CODES: { code: string; label: string }[] = [
  { code: "SAMPLE", label: "샘플 발송" },
  { code: "QUOTE", label: "견적 제공" },
  { code: "ADDITIONAL_MEETING", label: "추가 미팅" },
  { code: "NO_CONTACT", label: "연락 없음" },
];

export function decisionActionLabel(action: PartnerDecisionAction): string {
  switch (action) {
    case "ACCEPT":
      return "수락";
    case "REJECT":
      return "거절";
    case "COUNTER_PROPOSE":
      return "시간 재제안";
    default:
      return action;
  }
}
