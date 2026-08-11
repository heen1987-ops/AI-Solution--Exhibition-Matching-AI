/**
 * 바이어 매칭 결과 화면 전용 타입.
 *
 * 요구사항 (작업 지시 원문)
 * --------------------------
 * "exhibitor result cards showing grade (HIGH/MEDIUM/POSSIBLE - do not show raw numeric
 * scores to the end user) + human-readable reason, info needed fields clearly marked."
 *
 * `lib/types.ts`의 `RecommendationItem.match_level`은 이미 VERY_HIGH/HIGH/MEDIUM/LOW
 * 4단계로 존재한다(백엔드 `app/schemas/recommendation.py`). 이 화면이 요구하는 3단계
 * 등급(HIGH/MEDIUM/POSSIBLE)으로 그대로 재사용하기 위해 `gradeFromMatchLevel`로
 * 변환한다 - 새 백엔드 필드를 요구하지 않는다.
 */

import type { MatchLevel, RecommendationItem } from "@/lib/types";

export type MatchGrade = "HIGH" | "MEDIUM" | "POSSIBLE";

/** VERY_HIGH/HIGH -> HIGH(강하게 확신), MEDIUM -> MEDIUM, LOW -> POSSIBLE(가능성 있음).
 * 원본 `match_level`은 절대 화면에 숫자·퍼센트로 노출하지 않는다(작업 지시: "do not show
 * raw numeric scores"). */
export function gradeFromMatchLevel(level: MatchLevel): MatchGrade {
  switch (level) {
    case "VERY_HIGH":
    case "HIGH":
      return "HIGH";
    case "MEDIUM":
      return "MEDIUM";
    case "LOW":
    default:
      return "POSSIBLE";
  }
}

export const GRADE_LABEL: Record<MatchGrade, string> = {
  HIGH: "매칭 가능성 높음",
  MEDIUM: "매칭 가능성 보통",
  POSSIBLE: "매칭 가능성 있음",
};

export const GRADE_TONE: Record<MatchGrade, "positive" | "info" | "neutral"> = {
  HIGH: "positive",
  MEDIUM: "info",
  POSSIBLE: "neutral",
};

/** 08 2.3절 "공개정보" 범위만 노출하는 `GET /exhibitors/{id}`(exhibition_public 라우터,
 * `exhibitors.py`로 재노출됨)에 대응하는 최소 프런트 뷰. 백엔드 스키마
 * (`app/schemas/exhibition_public.py`)와 1:1은 아니고 이 화면이 실제로 쓰는 필드만
 * 옮겨 담는다. */
export interface ExhibitorPublicSummary {
  exhibitor_id: string;
  company_name: string;
  company_summary: string | null;
  product_count: number;
  booth_id: string | null;
  booth_number: string | null;
}

export interface MatchingCardData {
  item: RecommendationItem;
  grade: MatchGrade;
  exhibitor: ExhibitorPublicSummary | null;
  exhibitorLoadFailed: boolean;
  /** 카드에 보여줄 "정보 확인 중" 필드 이름 목록(예: "업체 소개", "취급 제품"). 빈
   * 배열/공백이 아니라 항상 존재하는 배열로 둬 "필드가 없어서 안 보이는 것"과
   * "값이 아직 없어서 확인 필요로 표시하는 것"을 구분한다(작업 지시: never rendered as
   * blank or as a false negative). */
  infoNeededFields: string[];
}

export function buildInfoNeededFields(exhibitor: ExhibitorPublicSummary | null): string[] {
  if (!exhibitor) return ["업체 정보"];
  const fields: string[] = [];
  if (!exhibitor.company_summary) fields.push("업체 소개");
  if (exhibitor.product_count === 0) fields.push("취급 제품");
  if (!exhibitor.booth_number) fields.push("부스 위치");
  return fields;
}
