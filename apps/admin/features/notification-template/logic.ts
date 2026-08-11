/**
 * 클라이언트 로컬 시작 템플릿 카탈로그 - `./types.ts` 모듈 docstring의 계약 공백 참고.
 *
 * 여기 담긴 모든 본문은 이미 `apps/api/app/services/event_message/content.py`의 안전한
 * 태그 허용목록만 사용한다(<p>, <b> 등) - 운영자가 그대로 저장해도 서버 콘텐츠 검증을
 * 통과하도록 미리 맞춰뒀다. 그렇다고 서버 검증을 건너뛰지는 않는다(방어적 이중 검증
 * 원칙, `EventMessageForm`이 여전히 저장 전 로컬 검사를 돌린다).
 */

import type { StarterTemplate } from "./types";

export const STARTER_TEMPLATES: StarterTemplate[] = [
  {
    id: "event-operation-notice-default",
    message_type: "EVENT_OPERATION_NOTICE",
    label_ko: "일반 운영 공지",
    title: "[운영 공지] 안내드립니다",
    body: "<p>안녕하세요, 운영팀입니다.</p><p>아래 내용을 안내드립니다.</p>",
    destination_screen: "/notifications",
  },
  {
    id: "event-start-reminder-default",
    message_type: "EVENT_START_REMINDER",
    label_ko: "행사 시작 리마인더",
    title: "행사가 곧 시작됩니다",
    body: "<p>행사 시작이 얼마 남지 않았습니다. 준비물을 확인해 주세요.</p>",
    destination_screen: "/events/current",
  },
  {
    id: "profile-confirmation-reminder-default",
    message_type: "PROFILE_CONFIRMATION_REMINDER",
    label_ko: "프로필 확인 요청",
    title: "프로필을 확인해 주세요",
    body: "<p>아직 프로필 확인이 완료되지 않았습니다. 확인 후 맞춤 추천을 받아보세요.</p>",
    destination_screen: "/profile/confirm",
  },
  {
    id: "recommendation-ready-notice-default",
    message_type: "RECOMMENDATION_READY_NOTICE",
    label_ko: "추천 준비 완료 안내",
    title: "맞춤 추천이 준비되었습니다",
    body: "<p>회원님을 위한 부스 추천이 준비되었습니다. 지금 확인해 보세요.</p>",
    destination_screen: "/recommendations",
  },
  {
    id: "post-event-resource-notice-default",
    message_type: "POST_EVENT_RESOURCE_NOTICE",
    label_ko: "행사 종료 후 자료 안내",
    title: "행사 자료를 확인하세요",
    body: "<p>행사에 참여해 주셔서 감사합니다. 발표 자료와 후기를 확인해 보세요.</p>",
    destination_screen: "/resources/post-event",
  },
];

export function templatesForMessageType(messageType: string): StarterTemplate[] {
  return STARTER_TEMPLATES.filter((t) => t.message_type === messageType);
}

export function findTemplate(templateId: string): StarterTemplate | undefined {
  return STARTER_TEMPLATES.find((t) => t.id === templateId);
}
