"""Public (unauthenticated) event/exhibitor/product/booth response schemas.

Field allow-list rationale
---------------------------
docs/08-exhibitor-product-profile-model.md 2.3절이 정의하는 세 단계 공개범위 중 이 모듈은
"공개정보"(로그인/인증 없는 일반 관람객 대상) 단계만 구현한다:

    업체명, 브랜드명, 업체 소개, 제품명, 제품 이미지, 주종, 도수, 소비자가,
    시음·구매 가능 여부, 부스번호

"인증 바이어 공개정보"(취급 유통채널, 공급지역, MOQ 범위, 월 생산가능량 범주, OEM·PB 가능
여부, 수출 가능 여부, 상담주제)와 "상담 수락 이후 공개정보"(상세 공급가격, 담당자 연락처,
구체적 납기, 제품별 재고, 거래계약 조건, 샘플 제공 조건)에 속하는 필드는 이 스키마들에
절대 포함하지 않는다. 특히 exhibition.trade_condition(도매가/MOQ/OEM 등)과
exhibition.event_product.inventory_status("제품별 재고" - 상담 수락 이후 단계)는 이 모듈이
의도적으로 참조하지 않는다.

"브랜드명"은 db-erd-table-spec.md/08 문서 어디에도 대응 컬럼이 없어(Exhibitor는
company_name만 가진다) 노출하지 않는다 - TODO(브랜드명 컬럼이 추가되면 PublicExhibitor*에
brand_name을 반영).

부스 운영상태·혼잡도·좌표는 2.3절 목록에 문자 그대로 나열되어 있지 않지만, 이 작업이 명시적으로
요구하는 GET /events/{event_id}/map, GET /booths/{booth_id} 엔드포인트의 존재 목적 자체가 "지금
가서 볼 수 있는 부스"를 안내하는 것이므로 부스번호와 같은 급의 공개정보로 취급한다(거래조건이
아니라 현장 운영정보다 - 08 2.2절 "현장 운영정보" 행 참고).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from pydantic import BaseModel, Field

BoothOperatingStatus = str
BoothCongestionLevel = str


class PublicEventDay(BaseModel):
    event_date: date
    open_at: time | None = None
    close_at: time | None = None
    status: str


class PublicEventDetail(BaseModel):
    event_id: uuid.UUID
    event_code: str
    event_name: str
    venue_name: str | None = None
    timezone: str
    start_date: date
    end_date: date
    event_status: str
    days: list[PublicEventDay] = Field(default_factory=list)


class PublicZone(BaseModel):
    event_zone_id: uuid.UUID
    zone_code: str
    zone_name: str
    floor_label: str | None = None
    zone_type: str | None = None
    parent_zone_id: uuid.UUID | None = None


class PublicProductImage(BaseModel):
    product_image_id: uuid.UUID
    storage_key: str
    image_type: str | None = None
    alt_text: str | None = None
    display_order: int


class PublicProductSummary(BaseModel):
    """08 2.3절 공개정보: 제품명, 제품 이미지, 주종, 도수, 소비자가, 시음·구매 가능 여부."""

    product_id: uuid.UUID
    product_name: str
    product_summary: str | None = None
    category_code: str | None = None
    alcohol_percentage: float | None = None
    retail_price_amount: int | None = None
    event_price_amount: int | None = None
    currency: str
    tasting_status: str
    purchase_status: str
    primary_image: PublicProductImage | None = None


class PublicProductDetail(PublicProductSummary):
    images: list[PublicProductImage] = Field(default_factory=list)


class PublicBoothSummary(BaseModel):
    booth_id: uuid.UUID
    booth_number: str
    zone: PublicZone | None = None
    operating_status: BoothOperatingStatus
    congestion_level: BoothCongestionLevel
    estimated_wait_minutes: int | None = Field(default=None, ge=0)
    map_x: float | None = None
    map_y: float | None = None


class PublicExhibitorSummary(BaseModel):
    """08 2.3절 공개정보: 업체명, 업체 소개, 부스번호(부스 요약으로 포함)."""

    exhibitor_id: uuid.UUID
    company_name: str
    company_summary: str | None = None
    data_quality_score: float = Field(ge=0, le=100)
    booth: PublicBoothSummary | None = None
    product_count: int = Field(ge=0)


class PublicExhibitorListItem(PublicExhibitorSummary):
    products: list[PublicProductSummary] = Field(default_factory=list)


class PublicExhibitorListResponse(BaseModel):
    items: list[PublicExhibitorListItem]
    next_cursor: str | None = None
    has_more: bool = False


class PublicExhibitorDetail(PublicExhibitorSummary):
    products: list[PublicProductSummary] = Field(default_factory=list)


class PublicBoothDetail(PublicBoothSummary):
    exhibitor_id: uuid.UUID
    company_name: str
    company_summary: str | None = None
    products: list[PublicProductSummary] = Field(default_factory=list)


class PublicBoothListResponse(BaseModel):
    items: list[PublicBoothDetail]
    next_cursor: str | None = None
    has_more: bool = False


class PublicMapResponse(BaseModel):
    event_id: uuid.UUID
    generated_at: datetime
    zones: list[PublicZone] = Field(default_factory=list)
    booths: list[PublicBoothDetail] = Field(default_factory=list)
