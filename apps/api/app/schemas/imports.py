"""배치 import·웹훅 수신용 Pydantic 스키마.

근거 문서
---------
- docs/2026-backju-ai-matching-service-design.md
    2.2절(관람객 사전등록 실제 필드), 2.3절(참가업체 신청 실제 필드) - 표준 필드명
    (identity.name, exhibitor.legal_name 등)의 1차 근거.
    8.1절(1차 연동): "import는 source_record_id와 source_updated_at으로 멱등 upsert한다",
    "매핑표는 코드에 하드코딩하지 않고 이벤트별 버전으로 관리한다."
    8.2절(실시간 연동): 웹훅 페이로드 구성 요소.
- docs/frontend-backend-ai-interface-spec.md 18절(원천 데이터 연계).

"매핑표는 코드에 하드코딩하지 않는다"는 원칙과 taxonomy 필드 설계
-----------------------------------------------------------------
원천 사이트의 코드값(poll4[] 관심분야, field1~10 전시분야 등)을 우리 온톨로지 개념으로
바꾸는 매핑표는 이벤트별로 달라질 수 있는 "데이터"이지, 이 파일에 하드코딩할 "코드"가
아니다. 그래서 이 스키마는 원천 코드값 자체를 받지 않고, 이미 (taxonomy_version_id,
concept_id)로 해석된 `TaxonomyAttributeRef` 목록을 받는다. 실제 배치 파이프라인에서는
CSV/API 원본 → (이벤트별 매핑표로 해석) → 이 스키마의 정규화된 형태, 순서로 변환한 뒤
이 API를 호출해야 한다. 그 매핑 해석 단계는 이 작업(import/webhook 라우터) 범위 밖이며,
`GET/POST /api/v1/ontology/*`(다른 에이전트가 구현한 라우터)를 활용해 별도 ETL 단계에서
수행하는 것을 전제로 한다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

# ---------------------------------------------------------------------------
# 공용 조각
# ---------------------------------------------------------------------------


class TaxonomyAttributeRef(BaseModel):
    """이미 해석된 온톨로지 개념 참조 1건.

    db-erd-table-spec.md 11절 "모든 업무 테이블은 개념을 참조할 때 concept_id만 저장하지
    않고 (taxonomy_version_id, concept_id)를 함께 FK로 둔다"는 규칙을 API 계약에도 그대로
    반영한다. attribute_code는 조회 편의용 비정규화 캐시이며, 저장 시 concept_id와의 일치는
    DB 복합 FK(예: fk_supply_profile_attribute_concept_code)가 강제한다.
    """

    model_config = ConfigDict(str_strip_whitespace=True)

    taxonomy_version_id: UUID
    concept_id: UUID
    attribute_code: str = Field(min_length=1, max_length=100)
    value: Any = True


class ImportRowError(BaseModel):
    """배치 처리 중 개별 행이 실패했을 때의 오류 항목.

    설계문서 8.1절 "잘못된 행은 전체 배치를 중단하지 않고 오류 격리 목록으로 보낸다"의
    응답 형태. message는 내부 예외 원문이 아니라 안전하게 마스킹된 설명이어야 한다
    (인터페이스 명세 4.4절).
    """

    row_index: Annotated[int, Field(ge=0)]
    source_record_id: str | None = None
    error_code: str
    message: str


class ImportBatchResult(BaseModel):
    """POST /admin/imports/{visitors|exhibitors|products} 공통 응답 형태."""

    import_id: UUID
    status: Literal["COMPLETED", "COMPLETED_WITH_ERRORS", "FAILED"]
    total_rows: int
    success_rows: int
    failed_rows: int
    errors: list[ImportRowError] = Field(default_factory=list)


class ImportStatusResponse(BaseModel):
    """GET /admin/imports/{import_id} 응답."""

    import_id: UUID
    job_type: str
    status: str
    total_rows: int
    success_rows: int
    failed_rows: int
    started_at: datetime | None = None
    completed_at: datetime | None = None
    created_at: datetime


class ImportErrorListResponse(BaseModel):
    """GET /admin/imports/{import_id}/errors 응답. 인터페이스 명세 4.3절의 불투명 커서
    페이지네이션 계약을 따른다."""

    import_id: UUID
    items: list[ImportRowError]
    next_cursor: str | None = None


class ExcelImportSheetSummary(BaseModel):
    """XLSX 한 입력 시트의 검증 집계. 원본 개인정보 값은 응답하지 않는다."""

    sheet_name: Literal["사전등록자", "참여기업"]
    total_rows: int = Field(ge=0)
    valid_rows: int = Field(ge=0)
    failed_rows: int = Field(ge=0)
    errors: list[ImportRowError] = Field(default_factory=list)


class ExcelImportResponse(BaseModel):
    """POST /admin/imports/excel 검증·실행 결과."""

    schema_version: Literal["meet-ai-excel-import-v1.0"]
    status: Literal[
        "VALID",
        "VALID_WITH_ERRORS",
        "INVALID",
        "IMPORTED",
        "IMPORTED_WITH_ERRORS",
    ]
    dry_run: bool
    visitors: ExcelImportSheetSummary
    exhibitors: ExcelImportSheetSummary
    visitor_import: ImportBatchResult | None = None
    exhibitor_import: ImportBatchResult | None = None


class ExcelMatchExportRequest(BaseModel):
    """Imported preregistrants to evaluate through the canonical recommendation pipeline."""

    model_config = ConfigDict(str_strip_whitespace=True)

    tenant_id: UUID
    event_id: UUID
    source_system_code: str = Field(default="EXCEL_UPLOAD", min_length=1, max_length=50)
    source_record_ids: list[Annotated[str, Field(min_length=1, max_length=255)]] = (
        Field(min_length=1, max_length=100)
    )
    top_n: int = Field(default=5, ge=1, le=10)

    @field_validator("source_record_ids")
    @classmethod
    def source_record_ids_must_be_unique(cls, values: list[str]) -> list[str]:
        if len(values) != len(set(values)):
            raise ValueError("source_record_ids must be unique")
        return values


# ---------------------------------------------------------------------------
# 방문객(관람객) import - 설계문서 2.2절 "표준 필드" 컬럼 기준
# ---------------------------------------------------------------------------


class VisitorImportRow(BaseModel):
    """참가신청 원천 시스템의 사전등록 레코드 1건 (이미 정규화된 형태).

    원본 필드 대응(설계문서 2.2절): mb_name→name, mb_gender→gender, mb_tel1~3→phone,
    mb_email1~2→email, poll1→home_region, mb_age→age_band, poll4[]→interest_categories,
    poll3[]→visit_goals, poll5[]→attribution_channels, agree1→consent_registration,
    agree3→consent_marketing, agree2→age_19_plus.
    """

    source_record_id: str = Field(min_length=1, max_length=255)
    source_updated_at: datetime

    name: str | None = Field(default=None, max_length=200)
    gender: str | None = Field(default=None, max_length=20)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=320)
    home_region: str | None = Field(default=None, max_length=100)
    age_band: str | None = Field(default=None, max_length=20)

    interest_categories: list[TaxonomyAttributeRef] = Field(default_factory=list)
    visit_goals: list[TaxonomyAttributeRef] = Field(default_factory=list)
    # 인지경로는 추천 제외 대상(마케팅 분석 전용, 설계문서 2.2절)이라 온톨로지 참조가 아닌
    # 단순 문자열로 받는다.
    attribution_channels: list[str] = Field(default_factory=list)

    consent_registration: bool
    consent_marketing: bool = False
    age_19_plus: bool


class VisitorImportRequest(BaseModel):
    """POST /admin/imports/visitors 요청 바디."""

    tenant_id: UUID
    event_id: UUID
    # integration.source_system.system_code. 없으면 새로 등록한다 (라우터 책임).
    source_system_code: str = Field(default="BACKJU_KR", max_length=50)
    rows: list[VisitorImportRow] = Field(min_length=1, max_length=1000)


# ---------------------------------------------------------------------------
# 참가업체 import - 설계문서 2.3절 표준 매핑 기준 (업체 상시정보만, 제품은 별도 엔드포인트)
# ---------------------------------------------------------------------------


class ExhibitorImportRow(BaseModel):
    """참가업체 신청 원천 레코드 1건 (업체 상시정보 부분).

    원본 필드 대응(설계문서 2.3절): company_name→legal_name, sign_kr→display_name,
    company_addr→region, website→website_url, manager_*→담당자 연락처, field1~10→categories
    (업체 유형/전시분야), etc_text→story, field25→promotion_description.
    """

    source_record_id: str = Field(min_length=1, max_length=255)
    source_updated_at: datetime

    legal_name: str = Field(min_length=1, max_length=200)
    display_name: str | None = Field(default=None, max_length=200)
    website_url: str | None = Field(default=None, max_length=2048)
    story: str | None = None

    manager_name: str | None = Field(default=None, max_length=100)
    manager_phone: str | None = Field(default=None, max_length=32)
    manager_email: str | None = Field(default=None, max_length=320)

    region: TaxonomyAttributeRef | None = None
    # 설계문서 4.2절 "한 업체는 복수 유형을 가질 수 있다" - field1~10을 여기로 매핑한다.
    categories: list[TaxonomyAttributeRef] = Field(default_factory=list)
    promotion_description: str | None = None


class ExhibitorImportRequest(BaseModel):
    """POST /admin/imports/exhibitors 요청 바디."""

    tenant_id: UUID
    event_id: UUID
    source_system_code: str = Field(default="BACKJU_KR", max_length=50)
    rows: list[ExhibitorImportRow] = Field(min_length=1, max_length=1000)


# ---------------------------------------------------------------------------
# 제품 import - 설계문서 2.3절 product_kr/main_img 등 제품 단위 필드
# ---------------------------------------------------------------------------


class ProductImportRow(BaseModel):
    """참가업체 신청 원천 레코드의 제품 단위 부분.

    exhibitor_source_record_id는 부모 업체 레코드의 source_record_id다 - 같은 배치 안에서
    업체보다 먼저 처리되어 있어야 하며, 없으면 integration.external_reference에서 이미
    동기화된 업체를 찾는다 (별도 배치로 업체를 먼저 올린 경우 지원).
    """

    source_record_id: str = Field(min_length=1, max_length=255)
    source_updated_at: datetime
    exhibitor_source_record_id: str = Field(min_length=1, max_length=255)

    product_name: str = Field(min_length=1, max_length=200)
    category: TaxonomyAttributeRef | None = None
    # 설계문서 2.3절 product_kr(전시품목 자유서술) - AI 구조화 이전의 원문.
    raw_description: str | None = None
    alcohol_percentage: float | None = Field(default=None, ge=0, le=100)
    # main_img/product_img* - 실제 파일 저장(오브젝트 스토리지 업로드)은 이 작업 범위 밖이다.
    # TODO(미디어 파이프라인 담당 에이전트): 이 URL 목록을 내려받아 exhibition.product_image로
    # 옮기는 별도 배치. 지금은 원문 참조만 raw_row_json에 보존한다.
    image_urls: list[str] = Field(default_factory=list)


class ProductImportRequest(BaseModel):
    """POST /admin/imports/products 요청 바디."""

    tenant_id: UUID
    event_id: UUID
    source_system_code: str = Field(default="BACKJU_KR", max_length=50)
    rows: list[ProductImportRow] = Field(min_length=1, max_length=1000)


# ---------------------------------------------------------------------------
# 웹훅 - 설계문서 8.2절 / 인터페이스 명세 18.2절
# ---------------------------------------------------------------------------

WebhookEventType = Literal["VISITOR_UPSERTED", "EXHIBITOR_UPSERTED", "PRODUCT_UPSERTED"]


class WebhookEnvelope(BaseModel):
    """POST /webhooks/backju 요청 바디.

    설계문서 8.2절 "웹훅에는 이벤트 ID, 이벤트 유형, 원천 레코드 ID, 변경시각, 페이로드
    버전을 포함한다"를 그대로 반영한다. `data`는 event_type에 대응하는 Visitor/Exhibitor/
    ProductImportRow와 동일한 필드 형태를 object로 받는다(공통 스키마 재사용은 라우터
    계층에서 event_type별로 재검증한다 - discriminated union 대신 라우터에서 명시적으로
    파싱해 오류 코드를 더 분명하게 준다).
    """

    tenant_id: UUID
    event_id: UUID
    event_type: WebhookEventType
    source_system_code: str = Field(default="BACKJU_KR", max_length=50)
    source_record_id: str = Field(min_length=1, max_length=255)
    changed_at: datetime
    payload_version: str = Field(default="1", max_length=20)
    data: dict[str, Any]


class WebhookAcceptedResponse(BaseModel):
    webhook_id: str
    event_type: WebhookEventType
    duplicate: bool
    internal_id: UUID | None = None
