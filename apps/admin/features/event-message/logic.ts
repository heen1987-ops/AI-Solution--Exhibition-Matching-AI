/**
 * 이벤트 메시지 순수 로직 - 상태머신 + 세그먼트 허용목록 미러링 + 표시용 포맷터.
 *
 * 여기서 구현하는 규칙은 전부 백엔드가 이미 강제하는 규칙의 **미러**다(빠른 UX 피드백 +
 * 네트워크 왕복 전 명백히 잘못된 조작 차단 목적). 정본은 언제나 백엔드
 * (`apps/api/app/services/event_message/{workflow,targeting}.py`)이고, 여기서의 검증
 * 실패는 서버 재검증을 건너뛰는 근거로 쓰지 않는다 - 모든 쓰기는 여전히 서버 응답을
 * 신뢰한다(`../api.ts`).
 */

import type { MessageStatus, TargetRoleCode, TargetSegment } from "./types";

// ---------------------------------------------------------------------------
// 상태머신 - apps/api/app/services/event_message/workflow.py 미러
// ---------------------------------------------------------------------------

const ALLOWED_TRANSITIONS: Record<MessageStatus, MessageStatus[]> = {
  DRAFT: ["PREVIEWED"],
  PREVIEWED: ["DRAFT", "APPROVED"],
  APPROVED: ["DRAFT", "SCHEDULED", "PUBLISHED", "CANCELLED"],
  SCHEDULED: ["PUBLISHED", "CANCELLED"],
  PUBLISHED: ["COMPLETED"],
  COMPLETED: [],
  CANCELLED: [],
};

export const EDITABLE_STATUSES: MessageStatus[] = ["DRAFT", "PREVIEWED", "APPROVED"];

const STATUSES_RESET_TO_DRAFT_ON_EDIT: MessageStatus[] = ["PREVIEWED", "APPROVED"];

export function canTransition(from: MessageStatus, to: MessageStatus): boolean {
  return ALLOWED_TRANSITIONS[from]?.includes(to) ?? false;
}

export class InvalidTransitionError extends Error {
  constructor(from: MessageStatus, to: MessageStatus) {
    super(`${from} → ${to} 전이는 허용되지 않습니다.`);
    this.name = "InvalidTransitionError";
  }
}

export function requireTransition(from: MessageStatus, to: MessageStatus): void {
  if (!canTransition(from, to)) throw new InvalidTransitionError(from, to);
}

export function isEditable(status: MessageStatus): boolean {
  return EDITABLE_STATUSES.includes(status);
}

/** 편집이 발생했을 때의 다음 상태. PREVIEWED/APPROVED는 DRAFT로 되돌아간다(미리보기 스냅샷이
 * 더 이상 최신 내용을 대표하지 않으므로). 편집 불가 상태면 null(호출부가 편집 UI 자체를
 * 숨겨야 한다는 신호). */
export function statusAfterEdit(current: MessageStatus): MessageStatus | null {
  if (!isEditable(current)) return null;
  return STATUSES_RESET_TO_DRAFT_ON_EDIT.includes(current) ? "DRAFT" : current;
}

export const STATUS_LABEL_KO: Record<MessageStatus, string> = {
  DRAFT: "초안",
  PREVIEWED: "미리보기 완료",
  APPROVED: "승인됨",
  SCHEDULED: "예약됨",
  PUBLISHED: "발행됨",
  COMPLETED: "종료됨",
  CANCELLED: "취소됨",
};

// ---------------------------------------------------------------------------
// 타겟 세그먼트 허용목록 - apps/api/app/models/event_message.py::EVENT_MESSAGE_TARGET_SEGMENTS
// 미러. 이 배열이 화면에서 선택 가능한 세그먼트의 유일한 소스다 - 어떤 컴포넌트도 이 목록
// 밖의 문자열을 세그먼트로 렌더링/전송해서는 안 된다.
// ---------------------------------------------------------------------------

export const TARGET_SEGMENTS: TargetSegment[] = [
  "ALL_REGISTERED_USERS",
  "PROFILE_UNCONFIRMED",
  "RECOMMENDATION_READY",
  "BUYERS",
  "EXHIBITOR_STAFF",
  "SPECIFIC_ROLE",
];

export const TARGET_SEGMENT_LABEL_KO: Record<TargetSegment, string> = {
  ALL_REGISTERED_USERS: "전체 등록 사용자",
  PROFILE_UNCONFIRMED: "프로필 미확인 사용자",
  RECOMMENDATION_READY: "추천 준비 완료 사용자",
  BUYERS: "바이어",
  EXHIBITOR_STAFF: "참가업체 담당자",
  SPECIFIC_ROLE: "특정 역할 지정",
};

export class TargetSegmentNotAllowedError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "TargetSegmentNotAllowedError";
  }
}

/** 세그먼트/역할코드 조합 검증 - apps/api/app/services/event_message/targeting.py의
 * validate_target_segment 미러. 허용목록 밖 문자열(민감속성/행동기반 등)은 여기서 즉시
 * 거부된다 - UI가 애초에 그런 값을 만들어낼 수 없더라도(select 기반 구성) 방어적으로
 * 한 번 더 막는다. */
export function validateTargetSegment(
  segment: string,
  targetRoleCode: string | null,
): asserts segment is TargetSegment {
  if (!TARGET_SEGMENTS.includes(segment as TargetSegment)) {
    throw new TargetSegmentNotAllowedError(
      `허용되지 않은 대상 세그먼트입니다: ${segment}. 세밀한 행동/속성 기반 타겟팅은 지원하지 않습니다.`,
    );
  }
  if (segment === "SPECIFIC_ROLE") {
    if (!targetRoleCode) {
      throw new TargetSegmentNotAllowedError("SPECIFIC_ROLE 타겟팅에는 역할을 선택해야 합니다.");
    }
  } else if (targetRoleCode) {
    throw new TargetSegmentNotAllowedError(
      "SPECIFIC_ROLE이 아닌 세그먼트에는 역할을 지정할 수 없습니다.",
    );
  }
}

// ---------------------------------------------------------------------------
// 소규모 대상 억제 - apps/api/app/services/event_message/targeting.py::display_target_count
// 미러. 서버가 이미 억제해 내려주므로(target_count: null when <5) 이 함수는 그 응답을 그대로
// 신뢰해 렌더링하는 헬퍼일 뿐, 클라이언트가 스스로 억제 여부를 재계산하지 않는다.
// ---------------------------------------------------------------------------

export const SMALL_AUDIENCE_THRESHOLD = 5;

export function formatTargetCount(targetCount: number | null, displayFromServer: string): string {
  if (targetCount === null) return displayFromServer;
  return `${targetCount.toLocaleString("ko-KR")}명`;
}

// ---------------------------------------------------------------------------
// 내부 목적지 화면 검증 - apps/api/app/services/event_message/content.py::
// validate_destination_screen 미러 (프로토콜 상대 URL "//host"도 외부로 취급).
// ---------------------------------------------------------------------------

export function isInternalDestinationScreen(destination: string): boolean {
  if (!destination.startsWith("/")) return false;
  if (destination.startsWith("//")) return false;
  if (destination.includes("://")) return false;
  return true;
}

// ---------------------------------------------------------------------------
// 콘텐츠 정책 - apps/api/app/services/event_message/content.py 미러 (빠른 1차 피드백용).
// 서버가 최종 정본이며, 이 검사를 통과해도 서버가 거부할 수 있다(예: 허용목록 외 외부 링크
// 호스트 판단은 서버 목록이 정본).
// ---------------------------------------------------------------------------

const ALLOWED_TAGS = new Set(["p", "br", "b", "strong", "i", "em", "ul", "ol", "li", "a", "span"]);

export interface ContentIssue {
  reasonCode: string;
  message: string;
}

/** 아주 단순한 태그 스캐너 - 서버의 html.parser 기반 검증을 대체하지 않는다(주석 참고).
 * 명백한 위반(허용되지 않은 태그, 이벤트 핸들러 속성, javascript: 링크)을 저장 전에 조기에
 * 잡아내는 용도. */
export function findContentIssues(body: string): ContentIssue[] {
  const issues: ContentIssue[] = [];
  const tagPattern = /<\/?([a-zA-Z][a-zA-Z0-9]*)([^>]*)>/g;
  let match: RegExpExecArray | null;
  while ((match = tagPattern.exec(body)) !== null) {
    const tag = match[1].toLowerCase();
    const attrs = match[2] ?? "";
    if (!ALLOWED_TAGS.has(tag)) {
      issues.push({ reasonCode: "TAG_NOT_ALLOWED", message: `허용되지 않은 태그입니다: <${tag}>` });
      continue;
    }
    if (/\son\w+\s*=/i.test(attrs)) {
      issues.push({
        reasonCode: "EVENT_HANDLER_ATTRIBUTE",
        message: "이벤트 핸들러 속성(on*)은 허용되지 않습니다.",
      });
    }
    const hrefMatch = /href\s*=\s*["']([^"']*)["']/i.exec(attrs);
    if (hrefMatch) {
      const href = hrefMatch[1].trim();
      const normalized = href.toLowerCase();
      if (
        normalized.startsWith("javascript:") ||
        normalized.startsWith("data:") ||
        normalized.startsWith("vbscript:")
      ) {
        issues.push({
          reasonCode: "DANGEROUS_URL_SCHEME",
          message: `허용되지 않은 링크 스킴입니다: ${href}`,
        });
      } else if (!isInternalDestinationScreen(href)) {
        // 내부 경로("/"로 시작, "//"·"://" 아님)가 아닌 모든 링크(절대 외부 URL, 프로토콜
        // 상대 URL "//host", 루트 아닌 상대경로)는 서버의 허용목록 판단에 맡긴다 - 클라이언트는
        // 존재만 경고한다.
        issues.push({
          reasonCode: "EXTERNAL_URL_NEEDS_SERVER_CHECK",
          message: `내부 경로가 아닌 링크는 서버 허용목록 검사를 통과해야 게시할 수 있습니다: ${href}`,
        });
      }
    }
  }
  return issues;
}
