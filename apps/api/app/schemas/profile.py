"""프로파일 온보딩 API의 Pydantic 요청/응답 스키마.

근거 문서
---------
- docs/frontend-backend-ai-interface-spec.md
    4.1~4.4절(API 공통 계약, 성공/오류 응답 봉투) - Envelope/Meta/ErrorBody 형태의 1차 근거.
    7.3절(사용자 유형), 7.4절(자격·동의 - 다만 동의 자체 스키마는 app/api/v1/routers/consent.py에
    둔다), 8.1~8.4절(방문 목적·취향·바이어 조건·방문 계획), 14절(프로파일 갱신 add/remove
    패치) - 각 엔드포인트 요청/응답 필드명의 1차 근거.
- docs/07-user-profile-model.md
    17.1~17.3절(완성도 가중치·구간), 22.1~22.5절(DB 컬럼명), 26.1~26.4절(프로파일
    조회/속성수정/완성도/버전 API), 27절(추천용 프로파일 출력 형태) - GET /profiles/me,
    PATCH /profiles/me/attributes, GET /profiles/me/completeness, GET /profiles/me/versions의
    1차 근거. 26절 자체 각주가 "경로 표기는 인터페이스 명세 우선"이라고 명시하므로 이 문서에서는
    필드 의미만 가져오고 실제 라우트는 /profiles/me/... 형태로 통일한다(작업 지시 우선순위 원칙).

코드값에 대한 메모
------------------
방문목적·주종·맛·채널·지역 등 taxonomy 코드는 이 스키마에서 하드코딩 Enum으로 제한하지 않는다.
6단계 매칭 온톨로지 문서가 아직 없고, 실제 코드 목록은 src/meet_ai/ontology/catalog.v1.json
(taxonomy_version 1.0.0) 시드 데이터로 관리되기 때문이다. 라우터가 요청 시점에 카탈로그를 통해
코드 존재 여부를 검증한다(app/api/v1/routers/profile.py의 _resolve_concept 참고). 이 스키마에서는
문자열(str)로만 받고, DB CHECK 제약으로 이미 고정된 값(예: user_type, requirement_level,
price_basis 등)만 Literal로 제한한다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, model_validator

# ---------------------------------------------------------------------------
# 공통 응답 봉투 (인터페이스 명세 4.3/4.4절)
# ---------------------------------------------------------------------------

T = TypeVar("T")


class Meta(BaseModel):
    request_id: str
    server_time: datetime


class FieldError(BaseModel):
    field: str
    reason: str


class ErrorBody(BaseModel):
    code: str
    message: str
    field_errors: list[FieldError] = Field(default_factory=list)
    retryable: bool = False
    retry_after_seconds: int | None = None


class Envelope(BaseModel, Generic[T]):
    """성공 응답 봉투. 각 엔드포인트는 이 제네릭을 response_model로 사용한다.

    주의: 이 프로젝트는 아직 app.main에 전역 예외 핸들러가 없다(main.py는 이 작업 범위 밖).
    그래서 오류 응답은 FastAPI 기본 HTTPException 처리(`{"detail": {...}}`) 형태로 나가며,
    detail에는 ErrorBody와 동일한 shape(code/message/field_errors/retryable/retry_after_seconds)를
    담는다. main.py를 소유한 에이전트가 이후 HTTPException -> {"success": false, "error": ...,
    "meta": ...} 전역 변환 핸들러를 등록하면 그대로 4.4절 오류 봉투와 맞아떨어지도록 설계했다.
    """

    success: Literal[True] = True
    data: T
    meta: Meta


# ---------------------------------------------------------------------------
# 공용 조각
# ---------------------------------------------------------------------------


class AddRemove(BaseModel):
    """14절 프로파일 갱신 예시의 {"add": [...], "remove": [...]} 패턴."""

    add: list[str] = Field(default_factory=list)
    remove: list[str] = Field(default_factory=list)


class PriceRange(BaseModel):
    min_amount: int | None = Field(default=None, ge=0)
    max_amount: int | None = Field(default=None, ge=0)
    currency: str = Field(default="KRW", min_length=3, max_length=3)

    @model_validator(mode="after")
    def _check_order(self) -> PriceRange:
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("min_amount must be <= max_amount")
        return self


class AlcoholPercentageRange(BaseModel):
    min: float | None = Field(default=None, ge=0, le=100)
    max: float | None = Field(default=None, ge=0, le=100)

    @model_validator(mode="after")
    def _check_order(self) -> AlcoholPercentageRange:
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must be <= max")
        return self


class AttributeView(BaseModel):
    """profile.profile_attribute 한 행을 API에 노출하는 형태 (07 22.2)."""

    profile_attribute_id: uuid.UUID
    attribute_code: str
    value_json: Any
    requirement_level: str
    priority: int | None
    source_type: str
    confidence: float
    active: bool


# ---------------------------------------------------------------------------
# 7.3 사용자 유형
# ---------------------------------------------------------------------------


class UserTypeUpdateRequest(BaseModel):
    user_type: Literal["GENERAL_VISITOR", "BUYER"]


class UserTypeUpdateResponse(BaseModel):
    profile_version: int
    user_type: str
    recommendation_refresh_required: bool
    invalidated_recommendation_session_ids: list[uuid.UUID]


# ---------------------------------------------------------------------------
# 8.1 방문 목적
# ---------------------------------------------------------------------------


class GoalItem(BaseModel):
    code: str = Field(min_length=1, max_length=100)
    priority: int = Field(ge=1, le=20)


class GoalsUpdateRequest(BaseModel):
    visit_goals: list[GoalItem] = Field(default_factory=list)
    free_text_goal: str | None = Field(default=None, max_length=500)


class SuggestedAttribute(BaseModel):
    """AI 보조 추출 결과. 8.1절: "AI 추출은 사용자의 명시적 선택을 덮어쓰지 않는다."

    TODO(AI 내부 인터페이스 통합, 인터페이스 명세 17.1절): free_text_goal을
    POST /internal/ai/ontology/extract 경계로 보내 실제 구조화 결과를 받아와야 한다.
    그 내부 API는 이 작업 범위 밖이라, 지금은 free_text_goal이 있어도 항상 빈 리스트를
    반환한다(사용자 선택 필드 저장은 100% 실동작하며, AI 제안만 보류 상태).
    """

    attribute: str
    value: str
    confidence: float
    evidence_text: str


class SelectedGoalView(BaseModel):
    attribute_code: str
    priority: int
    requirement_level: str


class GoalsUpdateResponse(BaseModel):
    profile_version: int
    selected_goals: list[SelectedGoalView]
    suggested_attributes: list[SuggestedAttribute]
    confirmation_required: bool


# ---------------------------------------------------------------------------
# 8.2 관람객 취향
# ---------------------------------------------------------------------------


class ConsumerPreferencesRequest(BaseModel):
    product_categories: list[str] = Field(default_factory=list)
    taste_preferences: list[str] = Field(default_factory=list)
    alcohol_percentage: AlcoholPercentageRange | None = None
    price: PriceRange | None = None
    purchase_intent: Literal["LIKELY", "UNLIKELY", "UNDECIDED"] | None = None
    preferred_activities: list[str] = Field(default_factory=list)
    # "잘 모르겠음"은 빈 배열과 다르다 (8.2절).
    preference_certainty: Literal["KNOWN", "UNKNOWN"] = "KNOWN"


class ConsumerPreferencesResponse(BaseModel):
    profile_version: int
    completeness_score: float


# ---------------------------------------------------------------------------
# 8.3 바이어 조건
# ---------------------------------------------------------------------------


class TargetPrice(BaseModel):
    min_amount: int | None = Field(default=None, ge=0)
    max_amount: int | None = Field(default=None, ge=0)
    basis: Literal["RETAIL_PRICE", "WHOLESALE_PRICE"] = "RETAIL_PRICE"
    currency: str = Field(default="KRW", min_length=3, max_length=3)

    @model_validator(mode="after")
    def _check_order(self) -> TargetPrice:
        if (
            self.min_amount is not None
            and self.max_amount is not None
            and self.min_amount > self.max_amount
        ):
            raise ValueError("min_amount must be <= max_amount")
        return self


class ExpectedOrderVolume(BaseModel):
    # db-erd/07 문서 모두 "REGULAR_SMALL 등"처럼 예시만 제공하는 개방형 코드다.
    type: str | None = Field(default=None, max_length=30)
    monthly_units_min: int | None = Field(default=None, ge=0)
    monthly_units_max: int | None = Field(default=None, ge=0)


class BuyerNeedsRequest(BaseModel):
    organization_type: str | None = Field(default=None, max_length=50)
    distribution_channels: list[str] = Field(default_factory=list)
    desired_categories: list[str] = Field(default_factory=list)
    target_price: TargetPrice | None = None
    expected_order_volume: ExpectedOrderVolume | None = None
    supply_regions: list[str] = Field(default_factory=list)
    business_interests: list[str] = Field(default_factory=list)
    decision_timeline: str | None = Field(default=None, max_length=30)


class BuyerNeedsResponse(BaseModel):
    profile_version: int
    completeness_score: float


# ---------------------------------------------------------------------------
# 8.4 방문 계획 (profile.visit_session + profile.context_profile)
# ---------------------------------------------------------------------------


class WalkingConstraints(BaseModel):
    minimize_distance: bool = False
    accessible_route: bool = False


class MeetingSlot(BaseModel):
    start: datetime
    end: datetime

    @model_validator(mode="after")
    def _check_order(self) -> MeetingSlot:
        if self.start >= self.end:
            raise ValueError("start must be before end")
        return self


class VisitPlanRequest(BaseModel):
    visit_date: date
    entry_time: datetime | None = None
    available_minutes: int | None = Field(default=None, ge=0)
    # 예: LOW_CONGESTION, SHORTEST 등 - 개방형 코드라 str로 받는다.
    route_preference: str | None = Field(default=None, max_length=30)
    walking_constraints: WalkingConstraints | None = None
    meeting_available_slots: list[MeetingSlot] = Field(default_factory=list)


class VisitPlanResponse(BaseModel):
    visit_session_id: uuid.UUID
    visit_date: date
    available_minutes: int | None
    route_preference: str | None
    context_profile_id: uuid.UUID


# ---------------------------------------------------------------------------
# 14절 프로파일 갱신 (일반 패치, add/remove 시맨틱)
# ---------------------------------------------------------------------------


class ProfileGeneralPatchRequest(BaseModel):
    taste_preferences: AddRemove | None = None
    product_categories: AddRemove | None = None
    preferred_activities: AddRemove | None = None
    distribution_channels: AddRemove | None = None
    desired_categories: AddRemove | None = None
    business_interests: AddRemove | None = None
    supply_regions: AddRemove | None = None
    price: PriceRange | None = None
    alcohol_percentage: AlcoholPercentageRange | None = None

    @model_validator(mode="after")
    def _at_least_one_field(self) -> ProfileGeneralPatchRequest:
        if not any(
            getattr(self, name) is not None for name in self.__class__.model_fields
        ):
            raise ValueError("at least one field must be provided")
        return self


class ProfileGeneralPatchResponse(BaseModel):
    profile_version: int
    recommendation_refresh_required: bool
    invalidated_recommendation_session_ids: list[uuid.UUID]


# ---------------------------------------------------------------------------
# 07 26.2 프로파일 속성 수정 (범용 온톨로지 속성 upsert/remove)
# ---------------------------------------------------------------------------


class AttributePatchItem(BaseModel):
    attribute_code: str = Field(min_length=1, max_length=100)
    action: Literal["UPSERT", "REMOVE"] = "UPSERT"
    value: Any = None
    requirement_level: Literal["REQUIRED", "PREFERRED", "ACCEPTABLE", "EXCLUDED"] = (
        "PREFERRED"
    )
    priority: int | None = Field(default=None, ge=1, le=100)

    @model_validator(mode="after")
    def _value_required_for_upsert(self) -> AttributePatchItem:
        # profile.profile_attribute.value_json은 NOT NULL이다(07 22.2절). UPSERT인데 값이
        # 없으면 DB IntegrityError(500)로 새는 대신 여기서 먼저 422로 걸러낸다.
        if self.action == "UPSERT" and self.value is None:
            raise ValueError("value is required when action is UPSERT")
        return self


class AttributesPatchRequest(BaseModel):
    attributes: list[AttributePatchItem] = Field(min_length=1)


class AttributesPatchResponse(BaseModel):
    profile_version: int
    attributes: list[AttributeView]


# ---------------------------------------------------------------------------
# 07 26.1 프로파일 조회 / 26.3 완성도 / 26.4 버전
# ---------------------------------------------------------------------------


class GoalView(BaseModel):
    attribute_code: str
    priority: int | None
    requirement_level: str
    confidence: float


class BuyerNeedView(BaseModel):
    organization_type: str | None
    target_price_min_amount: int | None
    target_price_max_amount: int | None
    currency: str
    price_basis: str | None
    monthly_units_min: int | None
    monthly_units_max: int | None
    decision_timeline: str | None
    business_email_verified: bool
    company_verified: bool


class ProfileView(BaseModel):
    profile_id: uuid.UUID
    user_type: str
    profile_status: str
    completeness_score: float
    current_version: int
    goals: list[GoalView]
    attributes: list[AttributeView]
    # alcohol_percentage/price/purchase_intent/preference_certainty처럼 온톨로지 코드가 아닌
    # 스칼라·범위값은 profile_attribute에 넣을 FK 대상 개념이 없어(app/api/v1/routers/profile.py
    # 모듈 docstring 참고) 최신 profile_version.snapshot_json에서 병합해 보여준다.
    consumer_preferences: dict[str, Any] = Field(default_factory=dict)
    buyer_need: BuyerNeedView | None = None
    updated_at: datetime


class CompletenessResponse(BaseModel):
    profile_id: uuid.UUID
    completeness_score: float
    band: Literal["PRECISE", "GENERAL", "EXPLORATORY", "NEEDS_MORE_INFO"]
    breakdown: dict[str, float]


class ProfileVersionItem(BaseModel):
    profile_version_id: uuid.UUID
    version_number: int
    change_reason: str
    created_at: datetime


class ProfileVersionsResponse(BaseModel):
    items: list[ProfileVersionItem]
    next_cursor: str | None = None
