/**
 * 알림 설정(`/notifications/preferences`) 도메인 - 로컬 타입.
 *
 * `apps/user-web/lib/api-client.ts`/`lib/types.ts` 편집 범위 밖 - 근거와 백엔드 계약
 * 공백에 대한 판단은 `features/notifications/types.ts` docstring과 동일하다(같은
 * WAVE 2E 작업 지시, 같은 "가정 계약" 판단). 이 화면의 가정 계약:
 *
 *   GET /api/v1/notifications/preferences  -> NotificationPreferencesResponse
 *   PUT /api/v1/notifications/preferences  -> NotificationPreferencesResponse
 *
 * 카테고리 목록·라벨·설명·필수 여부는 전부 서버가 내려주는 데이터로 취급한다(작업
 * 지시의 하드코딩 enum 회피 원칙 - 상담주제 등 다른 화면과 같은 태도). 클라이언트는
 * "필수/선택"을 각 항목의 `mandatory` 값으로만 판단하고, 특정 category_code를 이름으로
 * 특별 취급하지 않는다.
 */

export interface NotificationCategoryPreference {
  category_code: string;
  label: string;
  description: string;
  /** true면 운영상 필수 알림 - 사용자가 끌 수 없다(작업 지시: "mandatory operational
   * notices (cannot be disabled)"). 화면은 이 값이 true인 항목에 토글 대신 잠금 상태를
   * 보여준다. */
  mandatory: boolean;
  in_app_enabled: boolean;
  /** 이 카테고리가 이메일 채널 자체를 지원하지 않으면 `null`(토글을 아예 보여주지 않는다).
   * 지원하면 현재 on/off 값을 boolean으로 받는다 - 실제로 토글을 조작할 수 있는지는 아래
   * `NotificationPreferencesResponse.email_on_file`로 별도 판단한다("이메일이 있을 때만
   * 제공"은 지원 여부가 아니라 사용 가능 여부의 문제이기 때문). */
  email_enabled: boolean | null;
}

export interface NotificationPreferencesResponse {
  /** 사용자에게 등록된 이메일이 있는지. false면 이메일 토글이 존재하더라도(위 필드가
   * boolean이더라도) 비활성 상태로 보여주고 "이메일을 등록하면 사용할 수 있어요" 안내를
   * 붙인다(작업 지시: "email is only offered if the user has an email on file"). */
  email_on_file: boolean;
  categories: NotificationCategoryPreference[];
}

export interface NotificationCategoryPatch {
  category_code: string;
  in_app_enabled?: boolean;
  email_enabled?: boolean;
}

export interface NotificationPreferencesPatchRequest {
  categories: NotificationCategoryPatch[];
}
