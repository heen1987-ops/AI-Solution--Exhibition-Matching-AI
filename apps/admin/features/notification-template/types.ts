/**
 * 알림 템플릿(작성 보조용 시작 문구 카탈로그) - ADMIN-NOTIFICATION, WAVE 2E.
 *
 * 백엔드 계약 공백 (Blocker Score < 7 - 로컬로 채우고 여기 기록, 재조정 필요)
 * ---------------------------------------------------------------------------
 * 이 작업 지시는 `apps/admin/features/notification-template/**`를 owned path로 지정했지만,
 * 이번 배치의 어떤 트랙 프롬프트에도 "재사용 가능한 알림 템플릿"을 저장/조회하는 백엔드
 * 엔드포인트가 없다(`apps/api/app/schemas/notification.py`의 `NotificationTemplate`은
 * BACKEND-NOTIFICATION 트랙 소유의 시스템 알림용 title/body 템플릿이지 이 화면이 쓸 수 있는
 * 관리자 CRUD API가 아니다 - 그 테이블은 `notification_type`+`channel`별 1개씩만 갖는 시스템
 * 템플릿이고, 이 화면이 필요로 하는 "작성 보조용 시작 문구 여러 개"와는 모양이 다르다).
 *
 * 그래서 이 모듈은 **클라이언트 로컬 카탈로그**(메시지 유형별 시작 제목/본문 초안)만
 * 제공한다 - 서버에 아무것도 쓰지 않고, 선택 시 `EventMessageForm`의 입력값을 채워주는
 * 순수 UX 보조 기능이다. 운영자간 공유되는 서버측 템플릿 저장소가 필요해지면 별도 계약
 * 협의(CONTRACT) 후 이 모듈을 API 연동으로 교체해야 한다 - 지금은 그런 척(가짜 저장)을
 * 하지 않는다.
 */

import type { MessageType } from "../event-message/types";

export interface StarterTemplate {
  id: string;
  message_type: MessageType;
  label_ko: string;
  title: string;
  body: string;
  destination_screen: string;
}
