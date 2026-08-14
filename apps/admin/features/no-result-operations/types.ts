/**
 * 무응답(0건) 검색 운영 화면(ADMIN-OPERATIONS, WAVE 2E) - 원시 데이터 계약.
 *
 * 근거 (우선순위 순)
 * -------------------
 * 1. `apps/api/app/schemas/analytics.py` (BACKEND-ANALYTICS, WAVE 2E) -
 *    `GET /admin/analytics/no-results`의 실제 Pydantic 응답 스키마
 *    (`NoResultQueryResponse { items: [{query, count, last_seen_at}] }`). 이 파일의
 *    `NoResultQueryItem`/`NoResultQueryResponse`는 그 스키마와 1:1이다.
 * 2. `apps/api/app/models/analytics.py` (WORKER-ANALYTICS, WAVE 2E) -
 *    `analytics.search_no_result_summary` 집계 테이블. `query_norm`(정규화 질의),
 *    `channel_code`, `occurrence_count`, `last_occurred_at`, `suppressed`가 실제 컬럼이다.
 *    즉 데이터마트에는 이 화면이 원하는 축이 대부분 있지만, 읽기 API 계약(위 1번)이 아직
 *    `{query, count, last_seen_at}` 3필드만 노출한다.
 *
 * 라우터 미등록 (중요 - `../ai-review/types.ts`와 동일 상황, 2026-08-03 갱신)
 * ----------------------------------------------------------
 * `apps/api/app/api/v1/routers/analytics.py`는 이제 존재하고 `build_analytics_router()`를
 * 노출한다(BACKEND-ANALYTICS 착지). 다만 `app/api/v1/api.py`(공유 라우터 집계 파일)에는
 * 아직 등록되지 않았다 - 그 파일은 통합 단계에서만 수정되는 것이 규칙(AGENTS.md 절대 금지
 * 사항)이라 이 트랙이 직접 등록할 수 없다. 등록 전까지 호출은 FastAPI 전역 404 →
 * `ApiClientError(code: "NOT_IMPLEMENTED")`. 화면은 그 오류를 그대로 보여준다(가짜 성공
 * 표시 금지).
 *
 * 알려진 계약 공백 (Blocker Score < 7 - 로컬 nullable로 채우고 여기 기록, 재조정 필요)
 * ------------------------------------------------------------------------------------
 * 1. **정규화 질의/채널/최초발생/온톨로지 코드가 응답에 없다.** 데이터마트
 *    (`analytics.search_no_result_summary`)에는 `query_norm`/`channel_code`/
 *    `occurrence_count`가 있지만 `NoResultQueryItem`은 `{query, count, last_seen_at}`뿐이다.
 *    "해석된 온톨로지 코드"와 "최초 발생 시점(first_seen_at)"은 데이터마트에도 아직 없다.
 *    → `NoResultOperationsRow`는 이 필드들을 전부 nullable로 갖고, 값을 모르는 컬럼은
 *    화면에서 "정보 없음"으로 명시한다("값이 0/없음"과 "아직 모름"을 혼동시키지 않는다 -
 *    `../ai-review/types.ts` 계약 공백 4번과 동일 원칙). BACKEND-ANALYTICS 재조정 대상.
 * 2. **PII 마스킹 상태 필드가 없다.** 다만 `apps/api/app/services/analytics/suppression.py`가
 *    "질의 원문은 업스트림에서 이미 PII 마스킹되고, 서버가 방어적 재마스킹(`[masked]`)을
 *    한 번 더 적용한다"고 명시·구현하고 있어, 이 엔드포인트에서 온 질의문은
 *    `SERVER_MASKED`로 표시한다. 그 외 출처(직접 입력 등)는 `UNKNOWN`.
 * 3. **운영 태스크(원인 분류·개선 액션·상태머신) 백엔드가 전혀 없다.** 이 트랙 소유 경로에는
 *    백엔드가 없으므로(`apps/api/**`는 BACKEND 트랙 소유) 상태머신·이력은 순수 함수로
 *    구현하고(`./logic.ts`), 저장은 REST 관례로 추정한 `/admin/operations/no-result-tasks*`
 *    경로를 호출한다(`./api.ts`) - 등록 전까지 NOT_IMPLEMENTED 오류가 그대로 표시된다.
 */

/** 개방형 코드 타입 - `../ai-review/types.ts`와 동일 규약(공유 lib/types.ts를 import하지
 * 않고 로컬 재정의한다). */
export type OpenEnum<Known extends string> = Known | (string & {});

export type IsoDateTime = string;
export type Uuid = string;

// ---------------------------------------------------------------------------
// GET /admin/analytics/no-results - apps/api/app/schemas/analytics.py 1:1
// ---------------------------------------------------------------------------

export interface NoResultQueryItem {
  query: string;
  count: number;
  last_seen_at: IsoDateTime;
}

export interface NoResultQueryResponse {
  items: NoResultQueryItem[];
}

// ---------------------------------------------------------------------------
// 운영 화면 행 - 백엔드가 아직 주지 않는 축은 전부 nullable (모듈 docstring 공백 1·2번)
// ---------------------------------------------------------------------------

export type SearchChannel = OpenEnum<"WEB" | "KIOSK">;

export type PiiMaskingStatus = "SERVER_MASKED" | "UNKNOWN";

export interface NoResultOperationsRow {
  /** 정규화(소문자·공백정리) 질의문. 백엔드 응답의 `query`를 그대로 신뢰한다(서버가 이미
   * 정규화·마스킹 - 공백 2번). */
  query_norm: string;
  /** TODO(BACKEND-ANALYTICS 재조정): 해석된 온톨로지 개념 코드 - 응답에도 데이터마트에도
   * 아직 없다. null = "아직 모름"(코드 0개로 해석됐다는 뜻이 아님). */
  resolved_concept_codes: string[] | null;
  occurrence_count: number;
  /** TODO(BACKEND-ANALYTICS 재조정): 채널(`analytics.search_no_result_summary.channel_code`는
   * 존재하나 API 계약에 없음). */
  channel: SearchChannel | null;
  /** TODO(BACKEND-ANALYTICS 재조정): 최초 발생 시점 - 데이터마트에도 없음. */
  first_seen_at: IsoDateTime | null;
  last_seen_at: IsoDateTime | null;
  pii_masking_status: PiiMaskingStatus;
}

// ---------------------------------------------------------------------------
// 원인 분류 - 운영자가 수동 지정 (AI 자동 분류·자동 수정 금지, 스펙 명시 사항)
// ---------------------------------------------------------------------------

export type NoResultCause =
  | "ONTOLOGY_MISSING"
  | "SYNONYM_MISSING"
  | "EXHIBITOR_DATA_MISSING"
  | "NO_ELIGIBLE_EXHIBITOR"
  | "FILTER_TOO_STRICT"
  | "QUERY_AMBIGUOUS"
  | "INDEXING_DELAY"
  | "UNKNOWN";

// ---------------------------------------------------------------------------
// 개선 액션 - 전부 "사람에게 요청/플래그"이며, 어떤 액션도 온톨로지·업체 데이터를 직접
// 수정하지 않는다 (스펙의 명시적 금지 - ./logic.ts의 IMPROVEMENT_ACTIONS와 테스트 참고).
// ---------------------------------------------------------------------------

export type ImprovementActionCode =
  | "REQUEST_SYNONYM_ADDITION"
  | "FLAG_ONTOLOGY_REVIEW"
  | "REQUEST_EXHIBITOR_DATA"
  | "REQUEST_REINDEX"
  | "IMPROVE_EXAMPLE_QUERIES"
  | "MARK_RESOLVED"
  | "MARK_IGNORED";

/** 사람 액션 요청 대상 - 액션이 만들어내는 결과물은 언제나 이 대상에게 가는 "요청 기록"이지
 * 데이터 변경이 아니다. */
export type HumanActionTarget =
  | "ONTOLOGY_REVIEWER"
  | "EXHIBITOR_CONTACT"
  | "SEARCH_OPERATOR"
  | "CONTENT_OPERATOR"
  | "NONE_TASK_ONLY";

export interface ImprovementActionDefinition {
  code: ImprovementActionCode;
  label_ko: string;
  /** 항상 true - AI/시스템 자동 수정 금지 불변조건의 기계 검증 지점(logic.test.ts). */
  requires_human: true;
  /** 항상 false - 위와 동일. */
  auto_fixes_data: false;
  target: HumanActionTarget;
  /** 태스크를 종결시키는 액션인지 (MARK_RESOLVED/MARK_IGNORED). */
  terminal: boolean;
}

/** 액션 실행 결과물 - 사람에게 전달될 요청 레코드. 데이터 변경 페이로드가 아니다. */
export interface ImprovementActionRequest {
  kind: "HUMAN_ACTION_REQUEST";
  action: ImprovementActionCode;
  target: HumanActionTarget;
  query_norm: string;
  requested_by: string;
  requested_at: IsoDateTime;
  note: string | null;
}

// ---------------------------------------------------------------------------
// 운영 태스크 상태머신 - OPEN / IN_REVIEW / ACTION_REQUIRED / RESOLVED / IGNORED
// ---------------------------------------------------------------------------

export type OperationsTaskStatus =
  | "OPEN"
  | "IN_REVIEW"
  | "ACTION_REQUIRED"
  | "RESOLVED"
  | "IGNORED";

export interface OperationsTaskHistoryEntry {
  from_status: OperationsTaskStatus;
  to_status: OperationsTaskStatus;
  actor: string;
  reason: string | null;
  at: IsoDateTime;
}

export interface OperationsTask {
  task_id: string;
  query_norm: string;
  status: OperationsTaskStatus;
  cause: NoResultCause;
  assignee: string | null;
  /** 최신 상태 사유(IGNORED/재오픈 시 필수 - logic.ts가 강제). */
  reason: string | null;
  history: OperationsTaskHistoryEntry[];
  created_at: IsoDateTime;
  updated_at: IsoDateTime;
}
