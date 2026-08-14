"""참가업체 파트너 포털 API용 Pydantic 스키마.

근거 문서
---------
- docs/08-exhibitor-product-profile-model.md 28절(공급 프로파일 API) - 이 파일이 구현하는
  다섯 엔드포인트(28.1·28.2·28.3·28.4·28.5·28.6)의 1차 근거. 4~14절의 필드 구조(공급
  프로파일 전체 구조, 업체 역량, 제품 관능 프로파일, 가격, 거래조건, 유통채널, 검증)를
  Pydantic 필드로 옮긴다.
- backend/app/models/exhibitor.py - 실제 컬럼 확인 결과. 08 문서의 일부 필드(브랜드명 등)는
  exhibitor.py 모델에 대응 컬럼이 없어 이 스키마에도 포함하지 않았다 - 각 클래스 docstring에
  구체적으로 표시했다.

taxonomy 코드값에 대한 원칙
----------------------------
업체 유형·지역·유통채널·바이어 유형 등은 하드코딩 enum이 아니라 `TaxonomyRef`
(taxonomy_version_id + concept_id)로 받는다 - 코드 목록 자체는 6단계 온톨로지 시드 데이터로
채운다는 작업 지시 원칙을 따른다. 프런트엔드는 `GET /api/v1/ontology/concepts`로 선택지를
가져와 이 값을 채워야 한다.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

TradeAvailabilityStatus = Literal["YES", "NO", "CONDITIONAL", "NEGOTIABLE", "UNKNOWN"]
BuyerPreferenceLevel = Literal["REQUIRED", "PREFERRED", "EXCLUDED"]


class TaxonomyRef(BaseModel):
    """이미 해석된 온톨로지 개념 참조. db-erd-table-spec.md 11절 복합 FK 원칙과 대응한다."""

    taxonomy_version_id: UUID
    concept_id: UUID


# ---------------------------------------------------------------------------
# 28.1/28.2 - 업체 프로파일 조회/수정
# ---------------------------------------------------------------------------


class ExhibitorSupplyProfileRead(BaseModel):
    """exhibition.exhibitor_profile(08 27.1절) 스냅샷."""

    model_config = ConfigDict(from_attributes=True)

    exhibitor_profile_id: UUID
    business_type: list[str] | None = None
    capability_json: dict[str, Any] | None = None
    preferred_buyer_json: dict[str, Any] | None = None
    trade_readiness_score: float | None = None
    consumer_completeness: float
    buyer_completeness: float
    current_version: int
    approval_status: str
    updated_at: datetime


class ExhibitorProfileRead(BaseModel):
    """GET /api/v1/exhibitors/{exhibitor_id}/profile 응답 (08 28.1절).

    exhibition.exhibitor(상시 마스터) + exhibition.exhibitor_profile(공급 프로파일)을 합쳐
    보여준다. "브랜드명"(08 4.1절)은 exhibitor.py 모델에 대응 컬럼이 없어 포함하지 않는다
    (app/services/ingestion.py의 upsert_exhibitor 주석 참고).

    공개 범위에 대한 TODO: 08 2.3절은 조회자가 일반 관람객/인증 바이어/상담 수락 후 바이어인지에
    따라 노출 필드를 3단계로 나눈다. 이 라우터는 세션/역할 미들웨어가 아직 없어(개발 순서
    1번) 우선 PUBLIC 등급 필드만 반환한다 - buyer_completeness 이상 세부 거래정보는 인증
    바이어 전용 뷰가 준비되면 별도 응답 모델로 분리해야 한다.
    """

    exhibitor_id: UUID
    company_name: str
    company_summary: str | None = None
    website_url: str | None = None
    region: TaxonomyRef | None = None
    business_types: list[TaxonomyRef] = Field(default_factory=list)
    master_approval_status: str
    data_completeness_percent: float
    current_profile_version: int
    supply_profile: ExhibitorSupplyProfileRead | None = None


class ExhibitorProfileUpdate(BaseModel):
    """PATCH /api/v1/partner/exhibitors/{exhibitor_id}/profile 요청 (08 28.2절).

    업체 담당자가 직접 고칠 수 있는 항목만 받는다. company_name(법인명)처럼 원천 신뢰가
    필요한 필드는 이 엔드포인트로 바꾸지 않는다(운영자 승인 대상, 08 31.1절 "업체·운영자
    충돌" 원칙).
    """

    company_summary: str | None = None
    website_url: str | None = Field(default=None, max_length=2048)
    region: TaxonomyRef | None = None
    # 08 4.2절 "복수 유형 가능" - 전달하면 대표 업체 유형 전체 목록을 교체한다. None이면
    # 기존 값을 유지한다(PATCH 부분수정 의미).
    business_types: list[TaxonomyRef] | None = None
    # 08 4.3절 제조·유통·사업화역량 체크리스트. 08 문서가 항목을 코드가 아닌 산문으로
    # 나열해 하드코딩 필드 대신 자유 JSON으로 받는다.
    capability_json: dict[str, Any] | None = None


# ---------------------------------------------------------------------------
# 28.3 - 제품 등록
# ---------------------------------------------------------------------------


class ProductCreateRequest(BaseModel):
    """POST /api/v1/partner/products 요청 (08 28.3절, 5절 제품 프로파일)."""

    exhibitor_id: UUID
    # 함께 전시할 행사. 지정하면 exhibition.event_product도 함께 생성한다(08 11.2절
    # "전시제품 지정" - 업체 보유 제품 전부가 전시되는 것은 아니므로 선택 항목이다).
    event_id: UUID | None = None

    product_name: str = Field(min_length=1, max_length=200)
    category: TaxonomyRef | None = None
    product_summary: str | None = None
    alcohol_percentage: float | None = Field(default=None, ge=0, le=100)
    production_method: str | None = None
    main_ingredients: list[str] = Field(default_factory=list)

    # 08 5.2절 {"TASTE.DRY": 4, ...} 0~5 강도.
    taste: dict[str, int] = Field(default_factory=dict)
    aroma: dict[str, int] = Field(default_factory=dict)
    # 08 5.3절 USE.* 코드, 08 5.4절 차별성 코드. 코드 목록은 6단계 온톨로지 시드 예정이라
    # 여기서는 문자열 배열로만 받는다.
    usage: list[str] = Field(default_factory=list)
    features: list[str] = Field(default_factory=list)


class ProductSupplyProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    taste_json: dict[str, Any] | None = None
    aroma_json: dict[str, Any] | None = None
    usage_json: list[Any] | None = None
    feature_json: list[Any] | None = None
    consumer_score: float
    buyer_score: float
    current_version: int
    approval_status: str


class ProductRead(BaseModel):
    product_id: UUID
    exhibitor_id: UUID
    product_name: str
    product_summary: str | None = None
    category: TaxonomyRef | None = None
    alcohol_percentage: float | None = None
    master_approval_status: str
    supply_profile: ProductSupplyProfileRead | None = None


# ---------------------------------------------------------------------------
# 28.4 - 거래조건 등록
# ---------------------------------------------------------------------------


class TradeConditionUpsert(BaseModel):
    """PUT /api/v1/partner/products/{product_id}/trade-conditions 요청 (08 7·27.3절).

    exhibition.trade_condition은 참가(event_id별) 단위로 저장되므로 event_id가 필요하다
    (exhibitor.py TradeCondition.participation_id FK 참고). 이 엔드포인트는 "제품별 조건"을
    등록하는 것이라 event_product_id를 채운 행으로 저장한다(모델 docstring: "event_product_id가
    NULL이면 업체 공통조건, 채워지면 제품별 조건").
    """

    event_id: UUID

    min_order_quantity: int | None = Field(default=None, ge=0)
    max_order_quantity: int | None = Field(default=None, ge=0)
    monthly_capacity: int | None = Field(default=None, ge=0)
    wholesale_price_min_amount: int | None = Field(default=None, ge=0)
    wholesale_price_max_amount: int | None = Field(default=None, ge=0)
    currency: str = Field(default="KRW", min_length=3, max_length=3)

    # 08 2.4절 "미등록과 불가능 분리" - boolean이 아니라 5단계 상태.
    oem_status: TradeAvailabilityStatus = "UNKNOWN"
    private_label_status: TradeAvailabilityStatus = "UNKNOWN"
    export_status: TradeAvailabilityStatus = "UNKNOWN"
    exclusive_distribution_considered: bool = False

    lead_time_days: int | None = Field(default=None, ge=0)
    valid_from: date | None = None
    valid_until: date | None = None

    # db-erd 12.8절 "지역·채널·국가는 trade_condition_term으로 정규화" - PUT은 전체 교체다.
    supply_regions: list[TaxonomyRef] = Field(default_factory=list)
    channels: list[TaxonomyRef] = Field(default_factory=list)
    countries: list[TaxonomyRef] = Field(default_factory=list)


class TradeConditionRead(BaseModel):
    trade_condition_id: UUID
    product_id: UUID
    event_id: UUID
    min_order_quantity: int | None = None
    max_order_quantity: int | None = None
    monthly_capacity: int | None = None
    wholesale_price_min_amount: int | None = None
    wholesale_price_max_amount: int | None = None
    currency: str
    oem_status: TradeAvailabilityStatus
    private_label_status: TradeAvailabilityStatus
    export_status: TradeAvailabilityStatus
    exclusive_distribution_considered: bool
    lead_time_days: int | None = None
    valid_from: date | None = None
    valid_until: date | None = None
    supply_regions: list[TaxonomyRef] = Field(default_factory=list)
    channels: list[TaxonomyRef] = Field(default_factory=list)
    countries: list[TaxonomyRef] = Field(default_factory=list)
    approval_status: str


# ---------------------------------------------------------------------------
# 28.5 - 희망 바이어 등록
# ---------------------------------------------------------------------------


class BuyerPreferenceItem(BaseModel):
    """08 8.3절 "업체 희망 바이어 프로파일" 예시 1건."""

    buyer_type: TaxonomyRef | None = None
    channel: TaxonomyRef | None = None
    region: TaxonomyRef | None = None
    volume_min: int | None = Field(default=None, ge=0)
    volume_max: int | None = Field(default=None, ge=0)
    preference_level: BuyerPreferenceLevel = "PREFERRED"


class BuyerPreferenceReplaceRequest(BaseModel):
    """PUT /api/v1/partner/exhibitors/{exhibitor_id}/buyer-preferences 요청.

    전체 교체(PUT) 의미다 - 비어 있는 목록을 보내면 기존 희망 바이어 조건을 모두 비활성화한다.
    """

    preferences: list[BuyerPreferenceItem] = Field(default_factory=list)


class BuyerPreferenceRead(BaseModel):
    exhibitor_buyer_preference_id: UUID
    buyer_type: TaxonomyRef | None = None
    channel: TaxonomyRef | None = None
    region: TaxonomyRef | None = None
    volume_min: int | None = None
    volume_max: int | None = None
    preference_level: BuyerPreferenceLevel
    active: bool


class BuyerPreferenceListResponse(BaseModel):
    exhibitor_id: UUID
    items: list[BuyerPreferenceRead]


# ---------------------------------------------------------------------------
# 28.6 - 검수 제출
# ---------------------------------------------------------------------------


class SubmitResponse(BaseModel):
    """POST /api/v1/partner/exhibitors/{exhibitor_id}/submit 응답.

    08 17절 완성도 등급·18절 거래 준비도를 엄밀히 계산하려면 6단계 온톨로지 가중치가
    확정되어야 한다(작업 지시 "6~30단계 중 아직 설계 안 된 부분"). 지금은 08 17.1/17.2절
    가중치를 그대로 반영한 근사 계산(app/api/v1/routers/partner.py 참고)을 쓰고, 제출 자체를
    막는 "필수" 기준은 08 4.1절 필수 표시가 없는 항목까지 과도하게 차단하지 않도록 최소한만
    검사한다.
    """

    exhibitor_id: UUID
    approval_status: str
    consumer_completeness: float
    buyer_completeness: float
    submitted_at: datetime
    blocking_issues: list[str] = Field(default_factory=list)
