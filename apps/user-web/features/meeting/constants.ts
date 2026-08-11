import type { ContactShareField, MeetingStatus, TopicOptionLike } from "./types";

/** docs/user-ia-wireframes.md 6.2절 상태값 한글 라벨. */
export const MEETING_STATUS_LABEL: Record<MeetingStatus, string> = {
  draft: "임시 저장",
  requested: "업체 확인 중",
  counter_proposed: "시간 변경 제안",
  accepted: "확정",
  rejected: "거절됨",
  cancelled: "취소됨",
  completed: "완료",
  no_show: "노쇼 처리됨",
};

/** 목록 화면(U-15 계열)에서 상태를 묶어 보여줄 때의 그룹 순서.
 * 작업 지시 표기(requested/time-proposed/confirmed/rejected/cancelled/completed)를
 * 실제 백엔드 상태값에 매핑하고, 백엔드에만 있는 draft/no_show도 빠뜨리지 않는다. */
export const MEETING_STATUS_GROUPS: { status: MeetingStatus; label: string }[] = [
  { status: "requested", label: "업체 확인 중" },
  { status: "counter_proposed", label: "시간 변경 제안" },
  { status: "accepted", label: "확정" },
  { status: "draft", label: "임시 저장" },
  { status: "rejected", label: "거절됨" },
  { status: "cancelled", label: "취소됨" },
  { status: "completed", label: "완료" },
  { status: "no_show", label: "노쇼 처리됨" },
];

// U-14 와이어프레임 그대로의 기본 상담주제. TODO(6단계 온톨로지 문서 확정 후 대조 - 이미
// app/meetings/new/page.tsx 이전 버전이 쓰던 값과 동일하게 유지한다).
export const DEFAULT_TOPICS: TopicOptionLike[] = [
  { code: "DISTRIBUTION", label: "입점·유통" },
  { code: "OEM_PB", label: "OEM·PB" },
  { code: "EXPORT", label: "수출" },
  { code: "PRODUCT_PRICE", label: "제품·가격" },
  { code: "TECH_FACILITY", label: "기술·설비" },
];

export const CONTACT_FIELD_LABEL: Record<ContactShareField, string> = {
  NAME: "이름",
  PHONE: "휴대전화",
  BUSINESS_EMAIL: "업무용 이메일",
  EMAIL: "이메일",
};

/** 확정 연락처 카드(MeetingResponse.contact)에서 알려진 키에 붙일 한글 라벨.
 * 모르는 키가 와도 키 자체를 라벨로 보여줘 데이터를 숨기지 않는다(types.ts의 forward-compat
 * `contact` 필드 설명 참고). */
export const EXHIBITOR_CONTACT_FIELD_LABEL: Record<string, string> = {
  NAME: "담당자 이름",
  BUSINESS_EMAIL: "업무용 이메일",
  EMAIL: "이메일",
  PHONE: "업무용 전화",
  BUSINESS_PHONE: "업무용 전화",
  AFFILIATION: "소속",
  COMPANY: "소속",
};

export const CANCEL_REASON_OPTIONS = [
  { code: "SCHEDULE_CONFLICT", label: "일정이 맞지 않아요" },
  { code: "DECIDED_ELSEWHERE", label: "다른 업체와 진행하기로 했어요" },
  { code: "CHANGED_MIND", label: "단순 변심" },
  { code: "OTHER", label: "기타" },
];

/** 작업 지시: "up to 3 preferred time slots". 백엔드(schemas/meeting.py)는 1~5개까지
 * 허용하지만 이 화면은 UX상 3개로 더 좁힌다. */
export const MAX_PREFERRED_SLOTS = 3;
