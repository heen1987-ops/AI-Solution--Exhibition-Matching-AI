/**
 * 업체별 데이터 품질 - 순수 로직 (완성도 점수 산식, 라벨 매핑).
 *
 * 불변조건 (스펙 명시, `./tests/logic.test.ts`가 기계 검증)
 * ---------------------------------------------------------
 * 완성도 점수는 오직 "데이터 존재 여부" 요소만으로 계산한다: 필수 필드 충족률, 제품/서비스
 * 등록 여부, 관심 코드 등록 여부, 부스 배정 여부, 공개 소개문 존재 여부, 승인 상태. 클릭률
 * (CTR)·조회수·인기도·즐겨찾기수 등 행동/트래픽 신호는 이 파일 어디에도 입력으로 들어오지
 * 않는다 - `CompletenessInput`(`./types.ts`) 자체가 그런 필드를 갖지 않고,
 * `COMPLETENESS_FACTORS`가 허용 요소 6개 전체를 열거하며, `computeCompletenessScore`는
 * 그 6개 키만 읽는다(다른 키가 섞여 들어와도 무시 - 런타임 방어).
 */

import type {
  ApprovalStatus,
  CompletenessFactorScore,
  CompletenessInput,
  CompletenessScore,
  DataQualityCheckStatus,
  DataQualityCheckSummary,
  DocumentReviewStatus,
  ExhibitorDataQualityRow,
  SearchIndexStatus,
} from "./types";

// ---------------------------------------------------------------------------
// 완성도 점수 - 데이터 존재 요소 6개, 가중치 합계 100
// ---------------------------------------------------------------------------

/** 데이터 존재 요소 카탈로그 - 순서와 가중치가 산식의 유일한 정본이다. 이 목록에 CTR/클릭/
 * 조회수/인기도 관련 요소를 추가하는 변경은 스펙 위반이다(스냅샷 테스트가 깨진다). */
export const COMPLETENESS_FACTORS: { factor: string; weight: number; label_ko: string }[] = [
  { factor: "required_fields", weight: 30, label_ko: "필수 필드 충족률" },
  { factor: "product_count", weight: 15, label_ko: "제품/서비스 등록" },
  { factor: "interest_code_count", weight: 15, label_ko: "관심 코드 등록" },
  { factor: "has_booth", weight: 15, label_ko: "부스 배정" },
  { factor: "has_public_intro", weight: 15, label_ko: "공개 소개문" },
  { factor: "approval_status", weight: 10, label_ko: "승인 상태" },
];

const TOTAL_WEIGHT = COMPLETENESS_FACTORS.reduce((sum, f) => sum + f.weight, 0);

/** 제품/관심코드는 "1개라도 있으면 완료"가 아니라 이 개수까지는 늘어날수록 완성도가
 * 오른다고 본다(그래도 행동 신호는 아니다 - 등록된 데이터 개수 자체는 데이터 존재량이다). */
const PRESENCE_COUNT_TARGET = 3;

function clamp01(value: number): number {
  if (Number.isNaN(value)) return 0;
  return Math.max(0, Math.min(1, value));
}

function requiredFieldsAttainment(present: number, total: number): number {
  if (total <= 0) return 1; // 필수 필드 정의 자체가 없으면 결손이 있을 수 없다.
  return clamp01(present / total);
}

function countAttainment(count: number): number {
  return clamp01(count / PRESENCE_COUNT_TARGET);
}

function approvalAttainment(status: ApprovalStatus): number {
  return status === "APPROVED" || status === "PUBLISHED" ? 1 : 0;
}

/** 완성도 점수 계산 - 순수 함수, 데이터 존재 요소 6개만 읽는다.
 * `input`에 CTR/클릭/조회수/인기도 같은 다른 키가 섞여 들어와도(백엔드 응답 결함 등)
 * 이 함수는 그 키를 참조하지 않으므로 결과에 영향이 없다(logic.test.ts가 이를 직접 검증). */
export function computeCompletenessScore(input: CompletenessInput): CompletenessScore {
  const attainments: Record<string, number> = {
    required_fields: requiredFieldsAttainment(input.required_fields_present, input.required_fields_total),
    product_count: countAttainment(input.product_count),
    interest_code_count: countAttainment(input.interest_code_count),
    has_booth: input.has_booth ? 1 : 0,
    has_public_intro: input.has_public_intro ? 1 : 0,
    approval_status: approvalAttainment(input.approval_status),
  };

  const factors: CompletenessFactorScore[] = COMPLETENESS_FACTORS.map(({ factor, weight }) => {
    const attainment = attainments[factor] ?? 0;
    return { factor, weight, attainment, points: weight * attainment };
  });

  const rawScore = factors.reduce((sum, f) => sum + f.points, 0);
  const score = Math.round((rawScore / TOTAL_WEIGHT) * 100);

  return { score, factors };
}

export function toCompletenessInput(row: ExhibitorDataQualityRow): CompletenessInput {
  return {
    required_fields_present: row.required_fields_present,
    required_fields_total: row.required_fields_total,
    product_count: row.product_count,
    interest_code_count: row.interest_code_count,
    has_booth: row.has_booth,
    has_public_intro: row.has_public_intro,
    approval_status: row.approval_status,
  };
}

// ---------------------------------------------------------------------------
// 라벨 매핑 (화면용)
// ---------------------------------------------------------------------------

export const DOCUMENT_REVIEW_STATUS_LABEL_KO: Record<string, string> = {
  NONE: "문서 없음",
  PENDING: "검토 대기",
  IN_REVIEW: "검토중",
  APPROVED: "승인",
  REJECTED: "반려",
};

export const SEARCH_INDEX_STATUS_LABEL_KO: Record<string, string> = {
  NOT_INDEXED: "미색인",
  PENDING: "색인 대기",
  INDEXED: "색인됨",
  STALE: "색인 오래됨",
};

export const APPROVAL_STATUS_LABEL_KO: Record<string, string> = {
  DRAFT: "작성중",
  SUBMITTED: "제출됨",
  OPERATOR_REVIEW: "운영자 검수중",
  APPROVED: "승인",
  PUBLISHED: "게시됨",
  REJECTED: "반려",
};

export function documentReviewStatusLabel(status: DocumentReviewStatus): string {
  return DOCUMENT_REVIEW_STATUS_LABEL_KO[status] ?? status;
}

export function searchIndexStatusLabel(status: SearchIndexStatus): string {
  return SEARCH_INDEX_STATUS_LABEL_KO[status] ?? status;
}

export function approvalStatusLabel(status: ApprovalStatus): string {
  return APPROVAL_STATUS_LABEL_KO[status] ?? status;
}

export function requiredFieldsPercentLabel(present: number, total: number): string {
  if (total <= 0) return "해당 없음";
  return `${present}/${total} (${Math.round(clamp01(present / total) * 100)}%)`;
}

// ---------------------------------------------------------------------------
// 파이프라인 헬스체크 롤업 (GET /admin/analytics/data-quality 요약) - 표시 보조
//
// 2026-08-03 재조정: 백엔드가 "이슈 코드별 open/resolved 집계"에서 "체크 코드별
// OK/WARN/FAIL 상태"(analytics.data_quality_snapshot)로 reshape됨 - `./types.ts`
// 모듈 docstring 참고. 아래 두 헬퍼가 예전 issueResolutionRate/
// sortIssuesBySeverityThenOpenCount를 대체한다.
// ---------------------------------------------------------------------------

const CHECK_STATUS_RANK: Record<DataQualityCheckStatus, number> = { FAIL: 0, WARN: 1, OK: 2 };

export const DATA_QUALITY_CHECK_STATUS_LABEL_KO: Record<DataQualityCheckStatus, string> = {
  FAIL: "실패",
  WARN: "경고",
  OK: "정상",
};

export function dataQualityCheckStatusLabel(status: DataQualityCheckStatus): string {
  return DATA_QUALITY_CHECK_STATUS_LABEL_KO[status] ?? status;
}

/** 실패(FAIL)를 최우선으로, 그 다음 경고(WARN), 정상(OK) 순으로 정렬한다. 동일
 * 상태 내에서는 체크 코드 알파벳 순(안정적인 표시 순서). */
export function sortChecksByStatusSeverity(
  checks: DataQualityCheckSummary[],
): DataQualityCheckSummary[] {
  return [...checks].sort((a, b) => {
    const rankA = CHECK_STATUS_RANK[a.status] ?? 99;
    const rankB = CHECK_STATUS_RANK[b.status] ?? 99;
    if (rankA !== rankB) return rankA - rankB;
    return a.check_code.localeCompare(b.check_code);
  });
}

/** metric_value/threshold_value가 둘 다 있을 때만 "관측치가 허용 임계값 대비 몇 배인지"를
 * 계산한다(예: 1.5 = 임계값의 150%). 값이 없으면 아직 관측되지 않은 것이므로 null - 0이나
 * 1로 임의 대체하지 않는다(AGENTS.md: 없는 값을 만들어내지 않는다). */
export function thresholdRatio(check: DataQualityCheckSummary): number | null {
  if (check.metric_value === null || check.threshold_value === null || check.threshold_value === 0) {
    return null;
  }
  return check.metric_value / check.threshold_value;
}

// ---------------------------------------------------------------------------
// 정렬/필터 - 업체별 표
// ---------------------------------------------------------------------------

export function sortByCompletenessAscending(
  rows: ExhibitorDataQualityRow[],
): (ExhibitorDataQualityRow & { completeness: CompletenessScore })[] {
  return rows
    .map((row) => ({ ...row, completeness: computeCompletenessScore(toCompletenessInput(row)) }))
    .sort((a, b) => a.completeness.score - b.completeness.score);
}
