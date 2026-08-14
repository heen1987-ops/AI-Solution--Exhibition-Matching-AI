/**
 * 무응답 검색 운영 - 순수 로직 (원인 분류 카탈로그, 액션 어포던스, 태스크 상태머신).
 *
 * 불변조건 (스펙 명시, `./tests/logic.test.ts`가 기계 검증)
 * ---------------------------------------------------------
 * AI/시스템은 온톨로지·업체 데이터를 절대 자동 수정하지 않는다. 이 모듈의 모든 개선 액션은
 * "사람에게 가는 요청/플래그 레코드"(`ImprovementActionRequest`, kind:
 * "HUMAN_ACTION_REQUEST")를 만들 뿐이다 - 온톨로지 카탈로그, 업체 데이터, 검색 인덱스를
 * 변경하는 함수는 이 모듈에 존재하지 않으며 존재해서도 안 된다.
 */

import type {
  ImprovementActionCode,
  ImprovementActionDefinition,
  ImprovementActionRequest,
  NoResultCause,
  NoResultOperationsRow,
  NoResultQueryItem,
  OperationsTask,
  OperationsTaskStatus,
} from "./types";

// ---------------------------------------------------------------------------
// 원인 분류 카탈로그
// ---------------------------------------------------------------------------

export const NO_RESULT_CAUSES: NoResultCause[] = [
  "ONTOLOGY_MISSING",
  "SYNONYM_MISSING",
  "EXHIBITOR_DATA_MISSING",
  "NO_ELIGIBLE_EXHIBITOR",
  "FILTER_TOO_STRICT",
  "QUERY_AMBIGUOUS",
  "INDEXING_DELAY",
  "UNKNOWN",
];

export const CAUSE_LABEL_KO: Record<NoResultCause, string> = {
  ONTOLOGY_MISSING: "온톨로지 개념 없음",
  SYNONYM_MISSING: "동의어 누락",
  EXHIBITOR_DATA_MISSING: "업체 데이터 누락",
  NO_ELIGIBLE_EXHIBITOR: "해당 업체 자체가 없음",
  FILTER_TOO_STRICT: "필터 과도",
  QUERY_AMBIGUOUS: "질의 모호",
  INDEXING_DELAY: "인덱싱 지연",
  UNKNOWN: "원인 미상",
};

// ---------------------------------------------------------------------------
// 개선 액션 카탈로그 - 전부 requires_human: true / auto_fixes_data: false
// ---------------------------------------------------------------------------

export const IMPROVEMENT_ACTIONS: ImprovementActionDefinition[] = [
  {
    code: "REQUEST_SYNONYM_ADDITION",
    label_ko: "동의어 추가 요청",
    requires_human: true,
    auto_fixes_data: false,
    target: "ONTOLOGY_REVIEWER",
    terminal: false,
  },
  {
    code: "FLAG_ONTOLOGY_REVIEW",
    label_ko: "온톨로지 검토 플래그",
    requires_human: true,
    auto_fixes_data: false,
    target: "ONTOLOGY_REVIEWER",
    terminal: false,
  },
  {
    code: "REQUEST_EXHIBITOR_DATA",
    label_ko: "업체 데이터 보완 요청",
    requires_human: true,
    auto_fixes_data: false,
    target: "EXHIBITOR_CONTACT",
    terminal: false,
  },
  {
    code: "REQUEST_REINDEX",
    label_ko: "재인덱싱 요청",
    requires_human: true,
    auto_fixes_data: false,
    target: "SEARCH_OPERATOR",
    terminal: false,
  },
  {
    code: "IMPROVE_EXAMPLE_QUERIES",
    label_ko: "예시 질의 개선",
    requires_human: true,
    auto_fixes_data: false,
    target: "CONTENT_OPERATOR",
    terminal: false,
  },
  {
    code: "MARK_RESOLVED",
    label_ko: "해결됨으로 표시",
    requires_human: true,
    auto_fixes_data: false,
    target: "NONE_TASK_ONLY",
    terminal: true,
  },
  {
    code: "MARK_IGNORED",
    label_ko: "무시로 표시",
    requires_human: true,
    auto_fixes_data: false,
    target: "NONE_TASK_ONLY",
    terminal: true,
  },
];

export const ACTION_LABEL_KO: Record<ImprovementActionCode, string> = Object.fromEntries(
  IMPROVEMENT_ACTIONS.map((a) => [a.code, a.label_ko]),
) as Record<ImprovementActionCode, string>;

/** 원인별 권장 액션(어포던스). 종결 액션(MARK_RESOLVED/MARK_IGNORED)은 항상 포함된다. */
const CAUSE_ACTION_AFFORDANCES: Record<NoResultCause, ImprovementActionCode[]> = {
  ONTOLOGY_MISSING: ["FLAG_ONTOLOGY_REVIEW", "IMPROVE_EXAMPLE_QUERIES"],
  SYNONYM_MISSING: ["REQUEST_SYNONYM_ADDITION", "FLAG_ONTOLOGY_REVIEW"],
  EXHIBITOR_DATA_MISSING: ["REQUEST_EXHIBITOR_DATA"],
  // 도메인상 매칭될 업체 자체가 없는 경우 - 데이터로 고칠 게 없어 종결 액션만 남는다.
  NO_ELIGIBLE_EXHIBITOR: [],
  FILTER_TOO_STRICT: ["IMPROVE_EXAMPLE_QUERIES"],
  QUERY_AMBIGUOUS: ["IMPROVE_EXAMPLE_QUERIES", "REQUEST_SYNONYM_ADDITION"],
  INDEXING_DELAY: ["REQUEST_REINDEX"],
  // 원인 미상이면 판단을 좁히지 않고 모든 비종결 액션을 열어둔다.
  UNKNOWN: [
    "REQUEST_SYNONYM_ADDITION",
    "FLAG_ONTOLOGY_REVIEW",
    "REQUEST_EXHIBITOR_DATA",
    "REQUEST_REINDEX",
    "IMPROVE_EXAMPLE_QUERIES",
  ],
};

export function allowedActionsForCause(cause: NoResultCause): ImprovementActionCode[] {
  return [...CAUSE_ACTION_AFFORDANCES[cause], "MARK_RESOLVED", "MARK_IGNORED"];
}

// ---------------------------------------------------------------------------
// 백엔드 최소 계약 -> 운영 화면 행 매핑 (없는 축은 null = "아직 모름")
// ---------------------------------------------------------------------------

export function toOperationsRow(item: NoResultQueryItem): NoResultOperationsRow {
  return {
    query_norm: item.query,
    resolved_concept_codes: null, // 계약 공백 1번 (types.ts) - 0개로 해석됐다는 뜻이 아님
    occurrence_count: item.count,
    channel: null, // 계약 공백 1번
    first_seen_at: null, // 계약 공백 1번
    last_seen_at: item.last_seen_at ?? null,
    // suppression.py가 서버측 방어 마스킹을 항상 적용함을 확인했다 (types.ts 공백 2번).
    pii_masking_status: "SERVER_MASKED",
  };
}

// ---------------------------------------------------------------------------
// 태스크 상태머신
// ---------------------------------------------------------------------------

export const OPERATIONS_TASK_STATUSES: OperationsTaskStatus[] = [
  "OPEN",
  "IN_REVIEW",
  "ACTION_REQUIRED",
  "RESOLVED",
  "IGNORED",
];

export const TASK_STATUS_LABEL_KO: Record<OperationsTaskStatus, string> = {
  OPEN: "미처리",
  IN_REVIEW: "검토중",
  ACTION_REQUIRED: "조치 필요",
  RESOLVED: "해결됨",
  IGNORED: "무시됨",
};

/** 허용 전이 표. RESOLVED/IGNORED에서의 유일한 출구는 재오픈(OPEN)이다. */
const ALLOWED_TRANSITIONS: Record<OperationsTaskStatus, OperationsTaskStatus[]> = {
  OPEN: ["IN_REVIEW", "IGNORED"],
  IN_REVIEW: ["ACTION_REQUIRED", "RESOLVED", "IGNORED", "OPEN"],
  ACTION_REQUIRED: ["IN_REVIEW", "RESOLVED", "IGNORED"],
  RESOLVED: ["OPEN"],
  IGNORED: ["OPEN"],
};

export function canTransition(from: OperationsTaskStatus, to: OperationsTaskStatus): boolean {
  return ALLOWED_TRANSITIONS[from]?.includes(to) ?? false;
}

/** 사유가 필수인 전이: 무시 처리(어떤 상태에서든 IGNORED로), 종결 상태에서의 재오픈. */
export function transitionRequiresReason(
  from: OperationsTaskStatus,
  to: OperationsTaskStatus,
): boolean {
  if (to === "IGNORED") return true;
  if ((from === "RESOLVED" || from === "IGNORED") && to === "OPEN") return true;
  return false;
}

export class TaskTransitionError extends Error {
  readonly code: "INVALID_TRANSITION" | "REASON_REQUIRED";

  constructor(code: "INVALID_TRANSITION" | "REASON_REQUIRED", message: string) {
    super(message);
    this.name = "TaskTransitionError";
    this.code = code;
  }
}

export interface TransitionInput {
  to: OperationsTaskStatus;
  actor: string;
  reason?: string | null;
  at: string;
}

/** 불변 적용: 원본 task를 수정하지 않고, 이력(history)에 전이 항목을 덧붙인 새 task를
 * 돌려준다. 잘못된 전이·사유 누락은 TaskTransitionError로 던진다. */
export function applyTransition(task: OperationsTask, input: TransitionInput): OperationsTask {
  const { to, actor, at } = input;
  const reason = input.reason?.trim() ? input.reason.trim() : null;

  if (!canTransition(task.status, to)) {
    throw new TaskTransitionError(
      "INVALID_TRANSITION",
      `${task.status} → ${to} 전이는 허용되지 않습니다.`,
    );
  }
  if (transitionRequiresReason(task.status, to) && !reason) {
    throw new TaskTransitionError(
      "REASON_REQUIRED",
      `${task.status} → ${to} 전이에는 사유 입력이 필요합니다.`,
    );
  }

  return {
    ...task,
    status: to,
    reason,
    history: [
      ...task.history,
      { from_status: task.status, to_status: to, actor, reason, at },
    ],
    updated_at: at,
  };
}

export function assignTask(task: OperationsTask, assignee: string | null): OperationsTask {
  return { ...task, assignee };
}

export function createTask(input: {
  task_id: string;
  query_norm: string;
  cause?: NoResultCause;
  at: string;
}): OperationsTask {
  return {
    task_id: input.task_id,
    query_norm: input.query_norm,
    status: "OPEN",
    cause: input.cause ?? "UNKNOWN",
    assignee: null,
    reason: null,
    history: [],
    created_at: input.at,
    updated_at: input.at,
  };
}

export function setTaskCause(task: OperationsTask, cause: NoResultCause): OperationsTask {
  return { ...task, cause };
}

// ---------------------------------------------------------------------------
// 개선 액션 적용 - 사람 요청 레코드 생성 + 상태 전이(이력 포함). 데이터 변경 없음.
// ---------------------------------------------------------------------------

export interface ApplyActionResult {
  task: OperationsTask;
  /** 사람에게 전달될 요청 레코드. 종결 액션(MARK_RESOLVED/MARK_IGNORED)은 태스크 상태만
   * 바꾸므로 null. */
  request: ImprovementActionRequest | null;
}

export function applyImprovementAction(
  task: OperationsTask,
  action: ImprovementActionCode,
  input: { actor: string; at: string; note?: string | null },
): ApplyActionResult {
  const definition = IMPROVEMENT_ACTIONS.find((a) => a.code === action);
  if (!definition) {
    throw new TaskTransitionError("INVALID_TRANSITION", `알 수 없는 액션: ${action}`);
  }
  const note = input.note?.trim() ? input.note.trim() : null;

  if (action === "MARK_RESOLVED") {
    let next = task;
    // OPEN에서 바로 RESOLVED는 상태머신상 불가 - 검토(IN_REVIEW)를 거친 것으로 이력을 남긴다.
    if (next.status === "OPEN") {
      next = applyTransition(next, { to: "IN_REVIEW", actor: input.actor, at: input.at });
    }
    next = applyTransition(next, {
      to: "RESOLVED",
      actor: input.actor,
      reason: note,
      at: input.at,
    });
    return { task: next, request: null };
  }

  if (action === "MARK_IGNORED") {
    const next = applyTransition(task, {
      to: "IGNORED",
      actor: input.actor,
      reason: note, // 사유 필수 - 없으면 applyTransition이 REASON_REQUIRED로 던진다
      at: input.at,
    });
    return { task: next, request: null };
  }

  // 비종결 개선 액션: 사람 요청 레코드를 만들고 태스크를 ACTION_REQUIRED로 옮긴다.
  let next = task;
  if (next.status === "OPEN") {
    next = applyTransition(next, { to: "IN_REVIEW", actor: input.actor, at: input.at });
  }
  if (next.status === "IN_REVIEW") {
    next = applyTransition(next, {
      to: "ACTION_REQUIRED",
      actor: input.actor,
      reason: note,
      at: input.at,
    });
  } else if (next.status !== "ACTION_REQUIRED") {
    throw new TaskTransitionError(
      "INVALID_TRANSITION",
      `${next.status} 상태에서는 개선 액션을 실행할 수 없습니다. 먼저 재오픈하세요.`,
    );
  }

  const request: ImprovementActionRequest = {
    kind: "HUMAN_ACTION_REQUEST",
    action,
    target: definition.target,
    query_norm: task.query_norm,
    requested_by: input.actor,
    requested_at: input.at,
    note,
  };
  return { task: next, request };
}
