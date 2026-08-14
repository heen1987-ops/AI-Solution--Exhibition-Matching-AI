"""추천/행동이벤트 API의 Pydantic 요청·응답 스키마.

근거 문서
---------
- docs/frontend-backend-ai-interface-spec.md 4.3~4.4절(성공/오류 응답 봉투), 9절(추천 API
  요청/응답 필드명), 16.1~16.2절(행동 이벤트 수집 요청 형태·표준 이벤트 이름) - 1차 근거.
- docs/05-ai-matching-engine-architecture.md 13절(매칭엔진 입출력 계약), 7.2절(추천 행동
  코드 목록) - 인터페이스 명세에 없는 세부 필드(예: recommended_action 허용값)의 보강 근거.
- backend/app/models/matching.py - 응답 필드가 실제로 어떤 테이블/컬럼에서 나오는지의 근거
  (match_result_id, reasons[].code/text/evidence_refs 등).

Envelope/Meta/ErrorBody는 app/schemas/profile.py가 이미 정의한 것과 같은 모양이지만, 여러
에이전트가 동시에 각자의 스키마 파일을 작성하는 중이라 그 파일을 import해 결합을 만들지
않고 이 파일 안에 동일한 모양으로 다시 정의한다. 통합 단계에서 공용
``app/schemas/common.py`` 같은 모듈로 합치는 것을 권장한다.

taxonomy 코드값에 대한 메모
---------------------------
recommendation_type/recommended_action처럼 DB CHECK 제약으로 이미 고정된 값만 Literal로
제한한다. object_type/reason.code 등 온톨로지·개방형 코드는 문자열로만 받는다(작업 지시
원칙: 하드코딩 enum 금지, 코드 목록은 src/meet_ai/ontology/catalog.v1.json 시드 데이터로 관리).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Generic, Literal, TypeVar

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.services.matching.types import RECOMMENDATION_TYPES

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


class ErrorEnvelope(BaseModel):
    success: Literal[False] = False
    error: ErrorBody
    meta: Meta


class Envelope(BaseModel, Generic[T]):
    success: Literal[True] = True
    data: T
    meta: Meta


# ---------------------------------------------------------------------------
# 9.1 추천 생성 요청
# ---------------------------------------------------------------------------


class RecommendationContextRequest(BaseModel):
    """인터페이스 명세 9.1절 요청 본문의 ``context`` 객체.

    ``current_time``은 서버 시각만 신뢰한다(9.1절: "클라이언트 값은 진단용으로만 받을 수
    있다"). 이 스키마는 그 값을 아예 받지 않는다 - 클라이언트가 보내도 무시된다.
    """

    current_zone: str | None = Field(default=None, max_length=50)
    remaining_minutes: int | None = Field(default=None, ge=0)
    exclude_visited: bool = True
    include_meetings: bool = True
    slate_preference: Literal[
        "BALANCED",
        "ACCURACY_FIRST",
        "DIVERSE",
        "NEARBY_FIRST",
        "NEW_DISCOVERY",
    ] = "BALANCED"


class RecommendationRequest(BaseModel):
    recommendation_type: Literal[*RECOMMENDATION_TYPES] = "MIXED"  # type: ignore[valid-type]
    context: RecommendationContextRequest = Field(
        default_factory=RecommendationContextRequest
    )
    limit: int | None = Field(default=None, ge=1, le=50)


# ---------------------------------------------------------------------------
# 9.1 추천 생성 응답
# ---------------------------------------------------------------------------


class ReasonView(BaseModel):
    code: str
    text: str
    evidence_refs: list[str] = Field(default_factory=list)


class AvailabilityView(BaseModel):
    model_config = ConfigDict(extra="allow")

    open: bool | None = None
    tasting: bool | None = None
    purchase: bool | None = None
    meeting: bool | None = None


class RecommendationItem(BaseModel):
    match_result_id: uuid.UUID | None
    rank: int
    object_type: str
    object_id: str
    exhibitor_id: uuid.UUID | None = None
    match_level: Literal["VERY_HIGH", "HIGH", "MEDIUM", "LOW"]
    reasons: list[ReasonView]
    distance_meters: float | None = None
    estimated_walk_minutes: int | None = None
    estimated_wait_minutes: int | None = None
    status_observed_at: datetime | None = None
    availability: AvailabilityView
    recommended_action: str
    slot_type: str = "CORE"
    related_object_ids: list[str] = Field(default_factory=list)
    recommendation_confidence: float | None = Field(default=None, ge=0, le=1)
    cold_start_status: str | None = None
    cold_start_reason_codes: list[str] = Field(default_factory=list)


class RecommendationResponse(BaseModel):
    recommendation_session_id: uuid.UUID
    generated_at: datetime
    expires_at: datetime
    profile_version: int
    ranking_version: str
    explanation_version: str
    policy_version: str
    items: list[RecommendationItem]
    stale: bool = False


# ---------------------------------------------------------------------------
# 9.4 추천 목록 (GET /recommendation-sessions/{id}/items)
# ---------------------------------------------------------------------------


class RecommendationSessionItemsResponse(BaseModel):
    items: list[RecommendationItem]
    next_cursor: str | None = None
    stale: bool = False


# ---------------------------------------------------------------------------
# 16.1 행동 이벤트 수집 (조회·저장·제외 등)
# ---------------------------------------------------------------------------


class InteractionEventIn(BaseModel):
    client_event_id: uuid.UUID | None = None
    # 인터페이스 명세 16.2절 표준 이름 - 6단계 온톨로지 event_mappings로 검증 가능한
    # concept_code(ACTION.*)와 짝을 이루지만, 이 스키마 자체는 문자열로만 받고 라우터가
    # meet_ai.ontology 카탈로그로 대조한다(하드코딩 enum 금지 원칙).
    event_type: str = Field(min_length=1, max_length=60)
    object_type: str | None = Field(default=None, max_length=20)
    object_id: str | None = Field(default=None, max_length=100)
    recommendation_session_id: uuid.UUID | None = None
    match_result_id: uuid.UUID | None = None
    rank_at_event: int | None = Field(default=None, gt=0)
    visible_duration_ms: int | None = Field(default=None, ge=0)
    screen: str | None = Field(default=None, max_length=30)
    zone: str | None = Field(default=None, max_length=50)
    #: 클라이언트가 제출한 검색 자유입력 원문. 절대 원문 그대로 저장하지 않는다 -
    #: 라우터가 app/services/interaction_event/masking.py::mask_search_query로
    #: 전화번호/이메일/주민등록번호/계좌번호 형태를 마스킹한 뒤에만 context_json에 담는다.
    search_query: str | None = Field(default=None, max_length=500)
    occurred_at: datetime
    consent_snapshot_id: uuid.UUID | None = None
    # 16.2절 마지막 문단: "직접 식별정보, 자유메모 원문, OTP, 토큰, 전체 URL query string을
    # 이벤트 속성에 넣지 않는다." 스키마 차원에서는 강제할 수 없어 라우터가 허용 키만
    # context_json에 옮겨 담는다.
    context: dict[str, Any] | None = None

    @field_validator("occurred_at")
    @classmethod
    def _occurred_at_must_include_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("occurred_at must include a timezone offset")
        return value

    @model_validator(mode="after")
    def _linked_identifiers_are_complete(self) -> InteractionEventIn:
        if (self.object_type is None) != (self.object_id is None):
            raise ValueError("object_type and object_id must be provided together")
        if self.match_result_id is not None and self.recommendation_session_id is None:
            raise ValueError(
                "recommendation_session_id is required with match_result_id"
            )
        if self.event_type == "RECOMMENDATION_IMPRESSION" and (
            self.client_event_id is None
            or self.match_result_id is None
            or self.recommendation_session_id is None
            or self.rank_at_event is None
            or self.visible_duration_ms is None
        ):
            raise ValueError(
                "recommendation impression requires client event, session, result, rank, and visible duration"
            )
        return self


class InteractionBatchRequest(BaseModel):
    events: list[InteractionEventIn] = Field(min_length=1, max_length=100)


class InteractionEventResult(BaseModel):
    client_event_id: uuid.UUID | None
    interaction_event_id: uuid.UUID | None
    accepted: bool
    reason: str | None = None


class InteractionBatchResponse(BaseModel):
    accepted: int
    rejected: int
    results: list[InteractionEventResult]
