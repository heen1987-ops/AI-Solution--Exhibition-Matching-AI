"""바이어 매칭 API(``/buyer/matches``, ``/buyer/compare``)의 Pydantic 요청·응답 스키마.

트랙: BACKEND-BUYER-MATCH (WAVE 2C). app/models/buyer_match.py 모듈 docstring의
"기존 코드와의 관계에 대한 중요한 메모"를 함께 참고한다.

Envelope/Meta/ErrorBody는 app/schemas/recommendation.py·app/schemas/meeting.py가 이미
정의한 것과 같은 모양이지만, 그 파일들과 마찬가지로 다른 트랙 파일을 import해 결합을
만들지 않고 이 파일 안에서 동일한 모양으로 다시 정의한다(통합 단계에서 공용
``app/schemas/common.py``로 합치는 것을 권장 - recommendation.py의 동일한 메모 참고).

``CompareField``에 대한 메모 (unknown 표시 원칙)
-------------------------------------------------
비교 API는 값을 모르는 항목을 절대 빈 값이나 "아니오"로 보여주면 안 된다(작업 지시 명시
요구사항). 그래서 단순 ``value: str | None`` 대신 ``known: bool`` 플래그를 항상 함께 내려,
프런트엔드가 ``known=False``일 때 명시적으로 "확인 필요/정보 없음" UI를 렌더링하도록
강제한다. ``known=True``이면서 ``value="UNKNOWN"``인 경우도 있을 수 있다 - 이는 업체가
거래조건에 스스로 "미정(UNKNOWN)"이라고 명시적으로 표시한 경우로, "데이터 자체가 없는 것"과는
다른 상태다(app/services/buyer_match/compare.py 참고).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, Field, field_validator

# ---------------------------------------------------------------------------
# 공통 응답 봉투
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


class ErrorEnvelope(BaseModel):
    success: Literal[False] = False
    error: ErrorBody
    meta: Meta


class Envelope(BaseModel, Generic[T]):
    success: Literal[True] = True
    data: T
    meta: Meta


# ---------------------------------------------------------------------------
# POST /buyer/matches 요청
# ---------------------------------------------------------------------------


class BuyerMatchFilters(BaseModel):
    """바이어가 이번 매칭 실행에 명시적으로 지정한 필터.

    비워둔 항목은 "이 조건은 평가하지 않는다"는 뜻이다 - 버퍼가 채우지 않은 필터를 서버가
    임의로 기본값(예: 전체 지역 허용)으로 단정하지 않고, buyer_profile의 BuyerNeed 저장값을
    services.buyer_match.orchestrator가 보강한다.
    """

    categories: list[str] = Field(default_factory=list, max_length=20)
    channels: list[str] = Field(default_factory=list, max_length=20)
    regions: list[str] = Field(default_factory=list, max_length=20)
    price_min: int | None = Field(default=None, ge=0)
    price_max: int | None = Field(default=None, ge=0)
    monthly_units_min: int | None = Field(default=None, ge=0)
    monthly_units_max: int | None = Field(default=None, ge=0)
    oem_required: bool | None = None
    private_label_required: bool | None = None
    export_required: bool | None = None

    @field_validator("price_max")
    @classmethod
    def _price_order(cls, value: int | None, info: Any) -> int | None:
        price_min = info.data.get("price_min")
        if value is not None and price_min is not None and value < price_min:
            raise ValueError("price_max must be >= price_min")
        return value


class BuyerMatchCreateRequest(BaseModel):
    filters: BuyerMatchFilters = Field(default_factory=BuyerMatchFilters)
    limit: int | None = Field(default=None, ge=1, le=50)


# ---------------------------------------------------------------------------
# POST /buyer/matches, GET /buyer/matches/{id} 응답
# ---------------------------------------------------------------------------


class BuyerMatchCandidateView(BaseModel):
    exhibitor_id: uuid.UUID
    participation_id: uuid.UUID | None
    rank: int
    score: float = Field(ge=0, le=1)
    grade: Literal["VERY_HIGH", "HIGH", "MEDIUM", "LOW"]
    reason_codes: list[str] = Field(default_factory=list)
    unknown_fields: list[str] = Field(default_factory=list)


class BuyerMatchSessionResponse(BaseModel):
    buyer_match_session_id: uuid.UUID
    buyer_profile_id: uuid.UUID
    profile_version: int
    policy_version: str
    verification_tier: Literal["VERIFIED", "LIMITED"]
    filters: BuyerMatchFilters
    candidate_count: int
    filtered_count: int
    result_count: int
    generated_at: datetime
    expires_at: datetime | None
    candidates: list[BuyerMatchCandidateView]


# ---------------------------------------------------------------------------
# POST /buyer/compare 요청/응답
# ---------------------------------------------------------------------------

MAX_COMPARE_EXHIBITORS = 4


class BuyerCompareRequest(BaseModel):
    exhibitor_ids: list[uuid.UUID] = Field(min_length=1, max_length=MAX_COMPARE_EXHIBITORS)

    @field_validator("exhibitor_ids")
    @classmethod
    def _unique_ids(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("exhibitor_ids must not contain duplicates")
        return value


class CompareField(BaseModel):
    """모듈 docstring "CompareField에 대한 메모" 참고 - known=False가 항상 UNKNOWN을 뜻한다."""

    known: bool
    value: Any = None


class BuyerCompareItem(BaseModel):
    exhibitor_id: uuid.UUID
    available: bool
    company_name: str | None
    product_tech: CompareField
    channel: CompareField
    order_scale: CompareField
    region: CompareField
    oem: CompareField
    private_label: CompareField
    export: CompareField
    meeting_availability: CompareField


class BuyerCompareResponse(BaseModel):
    items: list[BuyerCompareItem]
