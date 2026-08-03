/**
 * ADM-GROUP-001: catalogue of admin console areas.
 *
 * The console now exposes the W-9 MVP operations first. Lower-priority
 * areas remain listed as planned so the scope boundary stays visible.
 */
export type AdminAreaStatus = "LIVE" | "CONTRACT_PENDING" | "PLANNED";

export interface AdminArea {
  /** Stable machine key, used as React key + test target. */
  key: string;
  /** Korean label shown in the nav shell. */
  title: string;
  /** One-line scope description. */
  description: string;
  /** Implementation status in this app. */
  status: AdminAreaStatus;
  /** Source doc this area's scope is defined by, for traceability. */
  docRef?: string;
}

export const ADMIN_AREAS: AdminArea[] = [
  {
    key: "event-settings",
    title: "행사 설정",
    description: "행사 기본 정보, 진행 기간, 노출 범위 등 운영 설정.",
    status: "PLANNED",
  },
  {
    key: "pre-registration-import",
    title: "사전등록 Import",
    description: "사전등록 데이터 연계 건수와 실패 건수 조회.",
    status: "CONTRACT_PENDING",
    docRef: "docs/redesign-v2/web/W-9-admin-operations.md §2",
  },
  {
    key: "exhibitor-list",
    title: "업체 목록",
    description: "등록된 참가업체 목록 열람 및 상태 확인.",
    status: "PLANNED",
  },
  {
    key: "exhibitor-product-review",
    title: "업체·제품 검수",
    description: "업체·제품 정보 승인/반려. 승인 전 데이터는 추천·검색에서 제외.",
    status: "LIVE",
    docRef: "docs/redesign-v2/web/W-9-admin-operations.md §3",
  },
  {
    key: "ai-extraction-review",
    title: "AI 추출 검수",
    description: "AI가 구조화한 업체 자료(source_document/extracted_attribute)의 검수.",
    status: "LIVE",
    docRef: "docs/redesign-v2/common/C-2-content-collection-ai-structuring.md",
  },
  {
    key: "booth-map-management",
    title: "부스·지도 관리",
    description: "부스 배치 및 지도 데이터 관리(정밀 실내 내비게이션은 제외범위).",
    status: "LIVE",
  },
  {
    key: "interest-ontology-codes",
    title: "관심영역 코드",
    description: "관심영역 온톨로지 코드/유사어 카탈로그 운영 관리 화면.",
    status: "PLANNED",
    docRef: "docs/redesign-v2/common/C-3-ontology.md",
  },
  {
    key: "kiosk-settings",
    title: "키오스크 설정",
    description: "키오스크 시작화면 다국어 옵션 등 현장 단말 설정.",
    status: "PLANNED",
  },
  {
    key: "buyer-verification",
    title: "바이어 검증",
    description: "BuyerNeed.business_email_verified / company_verified 플래그 수동 승인.",
    status: "CONTRACT_PENDING",
    docRef: "docs/redesign-v2/web/W-9-admin-operations.md §4",
  },
  {
    key: "consultation-operations",
    title: "간단 상담 운영",
    description: "Meeting/MeetingStatusHistory/MeetingContactShare 상담 요청·수락 현황 운영.",
    status: "CONTRACT_PENDING",
    docRef: "docs/redesign-v2/web/W-7-buyer-matching-consultation.md",
  },
  {
    key: "search-statistics",
    title: "검색 통계",
    description: "사전등록 연계 건수, 프로파일 완성도 분포, 상담 요청/수락 건수 등 기본 통계.",
    status: "CONTRACT_PENDING",
    docRef: "docs/redesign-v2/web/W-9-admin-operations.md §5",
  },
  {
    key: "zero-result-queries",
    title: "무결과 검색어",
    description: "검색 결과 0건 질의 로그 - Fallback 시나리오 개선 근거 자료.",
    status: "PLANNED",
  },
  {
    key: "users-and-permissions",
    title: "사용자·권한",
    description: "EVENT_ADMIN/EXHIBITOR_ADMIN 등 역할 및 권한 스코프 관리.",
    status: "PLANNED",
    docRef: "docs/redesign-v2/web/W-9-admin-operations.md §1",
  },
  {
    key: "audit-log",
    title: "감사로그",
    description: "승인·권한 변경 등 관리자 조작 이력 조회(공통 플랫폼 C-6 소관).",
    status: "PLANNED",
  },
];
