/**
 * 알림 -> 앱 내부 경로 변환 (내부 라우트 화이트리스트).
 *
 * 보안 원칙(작업 지시 그대로): "notification body/link fields를 다른 서버 제공 콘텐츠와
 * 동일하게 신뢰하지 않는 데이터로 취급한다. 알림이 내부 라우트를 가리킬 때만 내비게이션
 * 링크를 렌더링한다." 이 파일은 서버가 내려준 어떤 문자열(URL, path 등)도 직접 링크로
 * 쓰지 않는다 - `target_type`이 아래 화이트리스트에 있을 때만 이 파일이 직접 조립한
 * 상대경로를 반환한다. `target_id`는 이 앱의 실제 동적 라우트 세그먼트에 그대로 들어가므로
 * `encodeURIComponent`로 인코딩하고, 경로 구분자·프로토콜을 흉내낼 수 있는 문자가 섞이면
 * (예: `../`, `http://` 를 흉내내려는 값) 아예 링크를 만들지 않는다.
 */

import type { NotificationTarget, NotificationTargetType } from "./types";

/** `target_id`로 허용하는 문자만 통과시킨다(영문/숫자/하이픈/언더스코어). UUID·짧은 코드
 * 모두 이 형태다. 이 검사를 통과하지 못하면(예: 서버 응답이 오염됐거나 다른 스키마로 바뀐
 * 경우) 링크를 만들지 않고 조용히 내비게이션을 비활성화한다 - 깨진 링크보다 안전하다. */
const SAFE_ID_PATTERN = /^[A-Za-z0-9_-]+$/;

/** target_id가 필요 없는(고정 목적지) 유형. */
const FIXED_TARGET_PATHS: Partial<Record<NotificationTargetType, string>> = {
  RECOMMENDATION: "/recommendations",
  PROFILE: "/profile/preferences",
  BUYER_MATCHES: "/buyer/matches",
};

/** target_id가 반드시 필요한(상세 페이지) 유형. 값은 안전성 검사를 통과한 뒤에만 쓴다.
 * EXHIBITOR는 이 앱에 별도 업체 상세 라우트가 아직 없어(부스 상세만 존재) 가장 가까운
 * 기존 화면인 부스 상세로 매핑한다 - TODO(전용 업체 상세 라우트가 생기면 대조). */
const ID_TARGET_PATH_BUILDERS: Partial<Record<NotificationTargetType, (id: string) => string>> = {
  MEETING: (id) => `/meetings/${encodeURIComponent(id)}`,
  BOOTH: (id) => `/booths/${encodeURIComponent(id)}`,
  EXHIBITOR: (id) => `/booths/${encodeURIComponent(id)}`,
  PRODUCT: (id) => `/products/${encodeURIComponent(id)}`,
};

/**
 * 알림의 대상을 검증된 내부 경로로 변환한다. 아래 어느 경우든 `null`을 반환해 "이동할 수
 * 없는 알림"으로 취급한다(호출자는 링크 대신 안내 문구를 보여줘야 한다):
 *   - target이 없음
 *   - 서버가 대상이 삭제/접근불가라고 표시함(`target_deleted`)
 *   - target_type이 화이트리스트에 없는 값
 *   - id가 필요한 유형인데 id가 없거나 안전 패턴을 통과하지 못함
 */
export function resolveNotificationTarget(target: NotificationTarget | null | undefined): string | null {
  if (!target || target.target_deleted) return null;

  const fixed = FIXED_TARGET_PATHS[target.target_type as NotificationTargetType];
  if (fixed) return fixed;

  const builder = ID_TARGET_PATH_BUILDERS[target.target_type as NotificationTargetType];
  if (!builder) return null;
  if (!target.target_id || !SAFE_ID_PATTERN.test(target.target_id)) return null;
  return builder(target.target_id);
}
