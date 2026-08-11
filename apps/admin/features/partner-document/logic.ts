/**
 * 문서 목록 화면의 표시 로직 - 상태 라벨/톤, 추출 진행률, 오류 요약.
 * 순수 함수만 둔다(테스트 용이성 - `./logic.test.ts` 참고).
 */

import type { DocumentRead, DocumentStatus, ProcessingJobRead, ProcessingJobStatus } from "./types";

export const DOCUMENT_STATUS_LABEL_KO: Record<DocumentStatus, string> = {
  UPLOADED: "업로드됨",
  PROCESSING: "AI 처리중",
  PROCESSED: "처리 완료",
  PROCESSING_FAILED: "처리 실패",
};

export const DOCUMENT_TYPE_LABEL_KO: Record<string, string> = {
  CATALOG: "카탈로그",
  CERTIFICATE: "인증서",
  PRICE_LIST: "가격표",
  COMPANY_PROFILE: "회사소개",
  PRODUCT_SPEC: "제품 사양서",
  OTHER: "기타",
};

export function documentStatusLabel(status: DocumentStatus): string {
  return DOCUMENT_STATUS_LABEL_KO[status] ?? status;
}

export function documentTypeLabel(documentType: string): string {
  return DOCUMENT_TYPE_LABEL_KO[documentType] ?? documentType;
}

/** 목록/카드에 보여줄 "추출 진행률" - 처리작업 상태 기반 대략치.
 * PENDING/RUNNING 작업이 하나라도 있으면 진행중, COMPLETED만 있으면 100%, FAILED가
 * 섞이면 그 사실을 별도로 노출한다(진행률 %로 오류를 감추지 않는다). */
export interface ExtractionProgress {
  percent: number;
  label: string;
  hasError: boolean;
}

const TERMINAL_STATUSES: ProcessingJobStatus[] = ["COMPLETED", "FAILED"];

export function computeExtractionProgress(
  documentStatus: DocumentStatus,
  jobs: ProcessingJobRead[] | undefined,
): ExtractionProgress {
  if (!jobs || jobs.length === 0) {
    if (documentStatus === "PROCESSED") return { percent: 100, label: "완료", hasError: false };
    if (documentStatus === "PROCESSING_FAILED") return { percent: 0, label: "실패", hasError: true };
    if (documentStatus === "PROCESSING") return { percent: 0, label: "처리 대기중(작업 상세 없음)", hasError: false };
    return { percent: 0, label: "미처리", hasError: false };
  }

  const latest = jobs[jobs.length - 1];
  const failed = jobs.some((job) => job.status === "FAILED");
  const completedCount = jobs.filter((job) => job.status === "COMPLETED").length;
  const terminalCount = jobs.filter((job) => TERMINAL_STATUSES.includes(job.status)).length;
  const percent = jobs.length === 0 ? 0 : Math.round((terminalCount / jobs.length) * 100);

  if (failed && latest.status === "FAILED") {
    return { percent, label: `실패 (재시도 ${jobs.length}회 중)`, hasError: true };
  }
  if (completedCount === jobs.length) {
    return { percent: 100, label: "완료", hasError: false };
  }
  if (latest.status === "RUNNING") {
    return { percent, label: "AI 처리중…", hasError: failed };
  }
  return { percent, label: "대기중", hasError: failed };
}

/** own-company-only 스코프 필터 - 백엔드가 강제해야 할 규칙(파트너.py
 * `_require_exhibitor_access`와 동일 원칙)을 화면에서도 한 번 더 방어적으로 적용한다.
 * EXHIBITOR_ADMIN 역할일 때만 의미 있고, 그 외 역할(EVENT_ADMIN/DATA_REVIEWER)은 검수 목적상
 * 임의 업체를 조회할 수 있어야 하므로 필터하지 않는다. */
/** 통합 시 재작성(fail-closed): 원래는 `role !== "EXHIBITOR_ADMIN"`이면 무조건
 * 필터링 없이 전체 목록을 반환했다 - 하이드레이션 전의 `null` 역할도 그 "그 외 전부"에
 * 걸려 익명 방문자에게 모든 참가업체의 문서가 그대로 노출되는 fail-OPEN 결함이었다.
 * `role`이 없으면 무조건 빈 배열을 반환해 막는다. */
export function filterOwnCompanyOnly(
  items: DocumentRead[],
  role: string | null,
  sessionExhibitorId: string | null,
): DocumentRead[] {
  if (!role) return [];
  if (role !== "EXHIBITOR_ADMIN") return items;
  if (!sessionExhibitorId) return [];
  return items.filter((item) => item.exhibitor_id === sessionExhibitorId);
}
