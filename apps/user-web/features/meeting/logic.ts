/**
 * 순수 로직 - React/브라우저 API 없이 단위테스트하기 위해 UI 컴포넌트와 분리한다.
 */

import { MAX_PREFERRED_SLOTS, MEETING_STATUS_GROUPS } from "./constants";
import type { MeetingResponse, MeetingStatus } from "./types";

/** 희망 시간 선택을 최대 개수로 제한한다(작업 지시 "up to 3"). 이미 선택된 슬롯을 다시
 * 누르면 항상 해제를 허용하고, 새 슬롯은 한도 미만일 때만 추가한다. */
export function toggleSlotSelection(
  selected: string[],
  slotId: string,
  max: number = MAX_PREFERRED_SLOTS,
): string[] {
  if (selected.includes(slotId)) {
    return selected.filter((id) => id !== slotId);
  }
  if (selected.length >= max) {
    return selected;
  }
  return [...selected, slotId];
}

/** 상태별로 상담 목록을 묶는다. 그룹 순서는 MEETING_STATUS_GROUPS를 따르고, 항목이 없는
 * 그룹은 결과에서 제외한다(빈 섹션을 화면에 그리지 않기 위해). */
export function groupMeetingsByStatus(
  meetings: MeetingResponse[],
): { status: MeetingStatus; label: string; items: MeetingResponse[] }[] {
  return MEETING_STATUS_GROUPS.map((group) => ({
    ...group,
    items: meetings.filter((m) => m.status === group.status),
  })).filter((group) => group.items.length > 0);
}

/** 작업 지시 항목 중 백엔드 상담 생성 계약(schemas/meeting.py MeetingCreateRequest)에
 * 없는 "제품/서비스", "예상 발주 규모"는 새 컬럼을 만들 수 없어(이 트랙 owned path 밖)
 * 기존 자유메모(message) 필드에 라벨을 붙여 함께 보낸다. 두 값이 모두 비어 있으면 원본
 * 메시지를 그대로 반환한다. */
export function buildMeetingMessage(input: {
  productOrService?: string | null;
  orderScale?: string | null;
  freeText?: string | null;
}): string | null {
  const lines: string[] = [];
  const product = input.productOrService?.trim();
  const orderScale = input.orderScale?.trim();
  const freeText = input.freeText?.trim();
  if (product) lines.push(`제품/서비스: ${product}`);
  if (orderScale) lines.push(`예상 발주 규모: ${orderScale}`);
  if (freeText) {
    if (lines.length > 0) lines.push("");
    lines.push(freeText);
  }
  return lines.length > 0 ? lines.join("\n") : null;
}

/** 연락처 카드를 그려도 되는지 판단한다: 상담이 확정 상태이고, 백엔드가 실제로 최소 1개
 * 이상의 연락처 값을 보내줬을 때만 true. 값이 없으면(현재 백엔드 계약처럼) false를 반환해
 * 호출자가 "깨진 것처럼 보이는 빈 카드" 대신 아무것도 렌더링하지 않게 한다. */
export function shouldShowContactCard(meeting: Pick<MeetingResponse, "status" | "contact">): boolean {
  if (meeting.status !== "accepted") return false;
  const contact = meeting.contact;
  if (!contact) return false;
  return Object.values(contact).some((value) => typeof value === "string" && value.trim().length > 0);
}

export interface NextAction {
  label: string;
  href: string;
}

/** 목록 화면(그룹별 next-action affordance)에서 상태별로 보여줄 다음 행동 링크. 액션이
 * 없는 상태(no_show 등)는 null을 반환한다. */
export function nextActionFor(meeting: Pick<MeetingResponse, "status" | "meeting_id" | "exhibitor_id">): NextAction | null {
  switch (meeting.status) {
    case "draft":
      return { label: "이어서 작성", href: `/meetings/new?exhibitorId=${encodeURIComponent(meeting.exhibitor_id)}` };
    case "requested":
      return { label: "요청 취소", href: `/meetings/${meeting.meeting_id}` };
    case "counter_proposed":
      return { label: "시간 확인", href: `/meetings/${meeting.meeting_id}` };
    case "accepted":
      return { label: "상세 보기", href: `/meetings/${meeting.meeting_id}` };
    case "rejected":
      return { label: "다른 업체 보기", href: "/explore" };
    case "cancelled":
      return { label: "다시 요청", href: `/meetings/new?exhibitorId=${encodeURIComponent(meeting.exhibitor_id)}` };
    case "completed":
      return { label: "다음 추천 보기", href: "/home" };
    case "no_show":
      return null;
    default:
      return null;
  }
}
