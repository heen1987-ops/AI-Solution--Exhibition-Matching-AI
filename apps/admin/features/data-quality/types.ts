/**
 * 업체별 데이터 품질 화면(ADMIN-OPERATIONS, WAVE 2E) - 원시 데이터 계약.
 *
 * 근거 (2026-08-03 재조정 - 이전 초안과의 차이는 아래 참고)
 * -----------------------------------------------------------
 * 1. `apps/api/app/schemas/analytics.py::DataQualityAnalyticsResponse` -
 *    `GET /admin/analytics/data-quality`의 실제 확정 스키마. 그 파일의
 *    "Reconciliation note"에 명시된 대로, 이 응답은 존재하지 않는
 *    `quality.data_quality_issue`(이슈코드별 open/resolved 집계) 테이블을 가정한
 *    초기 초안에서 WORKER-ANALYTICS가 실제로 착지시킨 유일한 데이터품질 소스인
 *    `analytics.data_quality_snapshot`(파이프라인 헬스체크: 수집 지연,
 *    지연도착률, 중복률, 주체불명률, 억제비율)을 그대로 미러링하는 형태로
 *    reshape되었다. 즉 "이슈 코드별 open/resolved 집계"가 아니라 "체크 코드별
 *    OK/WARN/FAIL 상태"다. `DataQualityCheckSummary`/`DataQualityAnalyticsResponse`가
 *    새 스키마와 1:1이다(과거 `DataQualityIssueSummary`/`total_open`/`total_resolved`/
 *    `issues`는 삭제됨 - 되살리지 말 것, 백엔드에 대응 필드가 없다).
 * 2. 업체별 상세 행(`ExhibitorDataQualityRow`)을 주는 엔드포인트는 어느 트랙에도 아직
 *    없다 - REST 관례 추정 경로 `GET /admin/analytics/data-quality/exhibitors`를 쓴다
 *    (`./api.ts`, 재조정 플래그). 라우터 자체(`app/api/v1/routers/analytics.py`)는 이제
 *    존재하지만 `app/api/v1/api.py`에는 아직 등록되지 않았으므로(통합 단계 전) 호출 시
 *    NOT_IMPLEMENTED 오류가 그대로 표시된다.
 *
 * 완성도 점수 불변조건 (스펙 명시, `./tests/logic.test.ts`가 기계 검증)
 * --------------------------------------------------------------------
 * 완성도 점수는 오직 "데이터 존재 여부" 요소(필수 필드 + 제품 + 관심 코드 + 부스 + 공개
 * 소개문 + 승인 상태)로만 계산한다. 클릭률(CTR)·조회수·인기도 등 행동/트래픽 신호는 절대
 * 섞지 않는다 - `CompletenessInput` 타입 자체에 그런 필드가 없고(컴파일 타임),
 * `computeCompletenessScore`는 알 수 없는 키를 무시하며(런타임 테스트),
 * `COMPLETENESS_FACTORS` 목록이 허용 요소 전체를 열거한다(스냅샷 테스트).
 */

export type OpenEnum<Known extends string> = Known | (string & {});

export type IsoDateTime = string;
export type Uuid = string;

// ---------------------------------------------------------------------------
// GET /admin/analytics/data-quality - apps/api/app/schemas/analytics.py 1:1
// (WORKER-ANALYTICS pipeline-health checks, analytics.data_quality_snapshot)
// ---------------------------------------------------------------------------

export type DataQualityCheckStatus = "OK" | "WARN" | "FAIL";

export interface DataQualityCheckSummary {
  check_code: string;
  status: DataQualityCheckStatus;
  metric_value: number | null;
  threshold_value: number | null;
  affected_count: number | null;
}

export interface DataQualityAnalyticsResponse {
  event_id: Uuid;
  period_start: string;
  period_end: string;
  role: string;
  /** 기간 내 전체 체크 중 최악 상태(FAIL > WARN > OK), 또는 스냅샷이 없으면 OK. */
  overall_status: DataQualityCheckStatus;
  checks: DataQualityCheckSummary[];
}

// ---------------------------------------------------------------------------
// 업체별 데이터 품질 행 (백엔드 미확정 - types.ts docstring 근거 2번)
// ---------------------------------------------------------------------------

export type DocumentReviewStatus = OpenEnum<
  "NONE" | "PENDING" | "IN_REVIEW" | "APPROVED" | "REJECTED"
>;

export type SearchIndexStatus = OpenEnum<"NOT_INDEXED" | "PENDING" | "INDEXED" | "STALE">;

export type ApprovalStatus = OpenEnum<
  "DRAFT" | "SUBMITTED" | "OPERATOR_REVIEW" | "APPROVED" | "PUBLISHED" | "REJECTED"
>;

export interface ExhibitorDataQualityRow {
  exhibitor_id: Uuid;
  exhibitor_name: string | null;
  required_fields_present: number;
  required_fields_total: number;
  product_count: number;
  interest_code_count: number;
  /** 거래조건 UNKNOWN 미해소 건수 - UNKNOWN은 UNKNOWN으로 남는다(YES/NO로 절대 강제 변환
   * 금지, AGENTS.md 상위 규칙). 이 수치는 "업체에 확인을 요청해야 할 건수"다. */
  unresolved_trade_condition_unknown_count: number;
  document_review_status: DocumentReviewStatus;
  search_index_status: SearchIndexStatus;
  has_booth: boolean;
  has_public_intro: boolean;
  approval_status: ApprovalStatus;
  last_modified_at: IsoDateTime | null;
}

export interface ExhibitorDataQualityListResponse {
  items: ExhibitorDataQualityRow[];
}

// ---------------------------------------------------------------------------
// 완성도 점수 - 데이터 존재 요소만 (모듈 docstring 불변조건)
// ---------------------------------------------------------------------------

/** 완성도 점수 입력. 여기에 CTR/클릭/조회수/인기도 필드를 추가하는 변경은 스펙 위반이다 -
 * `./tests/logic.test.ts`의 요소 목록 스냅샷 테스트가 깨지도록 설계되어 있다. */
export interface CompletenessInput {
  required_fields_present: number;
  required_fields_total: number;
  product_count: number;
  interest_code_count: number;
  has_booth: boolean;
  has_public_intro: boolean;
  approval_status: ApprovalStatus;
}

export interface CompletenessFactorScore {
  factor: string;
  weight: number;
  /** 0..1 달성률. */
  attainment: number;
  points: number;
}

export interface CompletenessScore {
  /** 0..100 정수. */
  score: number;
  factors: CompletenessFactorScore[];
}
