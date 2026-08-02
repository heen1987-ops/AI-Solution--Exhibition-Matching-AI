"""상담(미팅) API 요청·응답 Pydantic 스키마.

근거 문서
---------
- docs/frontend-backend-ai-interface-spec.md 12절 "상담 API"(가능시간·요청·업체 응답),
  15절 "참가업체 포털 API"(E-02~E-04 대응) - 필드명·요청 형태의 1차 근거.
- docs/user-ia-wireframes.md 5.1절 U-14/U-15, 6.2절 상담 상태 모델, 8절 E-01~E-04
  참가업체 포털 화면 - 화면이 실제로 필요로 하는 데이터 항목의 근거.
- backend/app/models/meeting.py - 실제 컬럼·상태값·제약조건의 정본. 이 스키마는 그 모델이
  저장할 수 있는 값만 요청·응답에 노출한다(모델에 없는 필드는 요청에서 받지 않는다).

설계 메모
---------
- interface-spec 12.3절 예시는 ``exhibitor_id``로 업체를 지정하지만 실제 상담 레코드는
  행사 참가 단위(``exhibitor_participation``)에 연결된다(db-erd 14.2절, meeting.py
  participation_id). 라우터가 exhibitor_id + 현재 바이어 프로파일의 tenant/event로
  participation을 조회해 참가업체 이름 대신 참가 레코드를 찾는다. 이 스키마 계층에서는
  API 계약대로 exhibitor_id만 받는다.
- ``topic``은 자유 텍스트가 아니라 온톨로지 concept_code다(meeting.py: 상담 주제는
  (taxonomy_version_id, concept_id) 복합 컬럼으로만 저장되고 별도 자유텍스트 컬럼이 없음).
  U-14 화면의 상담주제 칩은 GET /api/v1/ontology/concepts?concept_type=BUSINESS_GOAL
  같은 조회로 채워지는 것을 전제로 한다.
- 연락처 공유 항목(``contact_share.fields``)의 정식 허용값 목록은 아직 별도 문서가 없어
  interface-spec 12.3절 예시(NAME/PHONE/BUSINESS_EMAIL)와 E-03절의 "휴대전화·이메일"을
  참고해 잠정 허용집합을 둔다. TODO(6단계 온톨로지 또는 동의 정책 상세설계 확정 후):
  consent_policy 또는 별도 코드 테이블 기준으로 교체한다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# interface-spec 12.3절 예시 + wireframes 8절 E-03 "휴대전화·이메일" 기준 잠정 허용값.
# TODO(동의 정책/6단계 온톨로지 확정 후): 정식 코드 테이블 참조로 교체.
ALLOWED_CONTACT_SHARE_FIELDS: tuple[str, ...] = ("NAME", "PHONE", "BUSINESS_EMAIL", "EMAIL")


class ContactShareRequest(BaseModel):
    """interface-spec 12.3절 ``contact_share`` 객체."""

    model_config = ConfigDict(extra="forbid")

    accepted: bool
    document_version: str | None = Field(default=None, max_length=50)
    fields: list[str] = Field(default_factory=list)

    @field_validator("fields")
    @classmethod
    def _fields_allowed(cls, value: list[str]) -> list[str]:
        unknown = sorted(set(value) - set(ALLOWED_CONTACT_SHARE_FIELDS))
        if unknown:
            raise ValueError(f"unsupported contact_share field(s): {unknown}")
        return value

    @model_validator(mode="after")
    def _require_details_when_accepted(self) -> "ContactShareRequest":
        if self.accepted and not self.document_version:
            raise ValueError(
                "contact_share.document_version is required when accepted is true"
            )
        if self.accepted and not self.fields:
            raise ValueError("contact_share.fields must not be empty when accepted is true")
        return self


class MeetingCreateRequest(BaseModel):
    """POST /api/v1/meetings 요청 본문 (interface-spec 12.3절)."""

    model_config = ConfigDict(extra="forbid")

    exhibitor_id: uuid.UUID
    # U-14 화면의 상담주제 칩 선택값(온톨로지 concept_code). 필수로 둔다 - 와이어프레임
    # 상 topic 선택에는 "건너뛰기"가 없다(U-04 방문목적과 달리).
    topic: str = Field(min_length=1, max_length=100)
    requested_slot_ids: list[uuid.UUID] = Field(min_length=1, max_length=5)
    message: str | None = Field(default=None, max_length=1000)
    contact_share: ContactShareRequest | None = None
    match_result_id: uuid.UUID | None = None

    @field_validator("requested_slot_ids")
    @classmethod
    def _unique_slots(cls, value: list[uuid.UUID]) -> list[uuid.UUID]:
        if len(set(value)) != len(value):
            raise ValueError("requested_slot_ids must not contain duplicates")
        return value


class SlotCandidate(BaseModel):
    """응답에 포함되는 후보/확정 슬롯 요약."""

    slot_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    preference_order: int | None = None
    request_status: str | None = None  # meeting_slot_request.status (PENDING/SELECTED/...)


class MeetingResponse(BaseModel):
    """상담 요청·조회 공통 응답 형태."""

    meeting_id: uuid.UUID
    status: str
    exhibitor_id: uuid.UUID
    participation_id: uuid.UUID
    topic_code: str | None
    message_preview: str | None
    candidate_slots: list[SlotCandidate]
    confirmed_start: datetime | None
    confirmed_end: datetime | None
    contact_share_accepted: bool
    contact_share_fields: list[str]
    viewed_at: datetime | None
    row_version: int
    created_at: datetime
    updated_at: datetime


class MeetingListResponse(BaseModel):
    items: list[MeetingResponse]
    next_cursor: str | None


class MeetingCancelRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=0)
    reason_code: str | None = Field(default=None, max_length=50)


class MeetingRespondRequest(BaseModel):
    """counter_proposed 상태에서 바이어의 응답 (wireframes 6.2절 "counter_proposed -> accepted")."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["ACCEPT_COUNTER", "DECLINE"]
    version: int = Field(ge=0)
    reason_code: str | None = Field(default=None, max_length=50)


class PartnerDecisionRequest(BaseModel):
    """POST /api/v1/partner/meetings/{meeting_id}/decision 요청 (interface-spec 12.4절)."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["ACCEPT", "REJECT", "COUNTER_PROPOSE"]
    slot_id: uuid.UUID | None = None
    version: int = Field(ge=0)
    reason_code: str | None = Field(default=None, max_length=50)

    @model_validator(mode="after")
    def _slot_required_unless_reject(self) -> "PartnerDecisionRequest":
        if self.action in ("ACCEPT", "COUNTER_PROPOSE") and self.slot_id is None:
            raise ValueError("slot_id is required for ACCEPT and COUNTER_PROPOSE")
        return self


class BuyerNeedSummary(BaseModel):
    """wireframes 8절 E-03 "희망 제품, 가격, 규모, 공급지역" 요약."""

    organization_type: str | None
    target_price_min_amount: int | None
    target_price_max_amount: int | None
    currency: str | None
    monthly_units_min: int | None
    monthly_units_max: int | None
    decision_timeline: str | None


class PartnerBuyerSummaryResponse(BaseModel):
    """GET /api/v1/partner/meetings/{meeting_id}/buyer-summary 응답 (E-03)."""

    meeting_id: uuid.UUID
    status: str
    topic_code: str | None
    message_preview: str | None
    buyer_need: BuyerNeedSummary | None
    # 확정 + 공유동의 + 열람권한 조건을 모두 만족할 때만 채워진다 (interface-spec 12.3/15절).
    contact: dict[str, str] | None
    contact_disclosed: bool


class PartnerMeetingListItem(BaseModel):
    """GET /api/v1/partner/meetings 목록 항목 (E-02)."""

    meeting_id: uuid.UUID
    status: str
    topic_code: str | None
    candidate_slots: list[SlotCandidate]
    confirmed_start: datetime | None
    confirmed_end: datetime | None
    viewed_at: datetime | None
    created_at: datetime


class PartnerMeetingListResponse(BaseModel):
    items: list[PartnerMeetingListItem]
    next_cursor: str | None


class FollowUpRequest(BaseModel):
    """wireframes 8절 E-04 "후속조치" 영역."""

    model_config = ConfigDict(extra="forbid")

    # 후보값 예시(E-04): 샘플/견적/추가 미팅/연락 없음. 정식 concept_code는 6단계 온톨로지
    # 시드 확정 전이라 자유 문자열로 받고 최선노력으로 온톨로지 해석을 시도한다
    # (meeting.py FollowUp 클래스 docstring TODO 참고).
    action_code: str = Field(min_length=1, max_length=100)
    due_date: date | None = None
    note: str | None = Field(default=None, max_length=1000)


class MeetingOutcomeRequest(BaseModel):
    """POST /api/v1/partner/meetings/{meeting_id}/outcome 요청 (E-04)."""

    model_config = ConfigDict(extra="forbid")

    # 후보값 예시(E-04): 유효 리드/추가 검토/정보 제공/조건 불일치. outcome_code는
    # FollowUpRequest.action_code와 동일한 이유로 자유 문자열 + 최선노력 온톨로지 해석이다.
    outcome_code: str = Field(min_length=1, max_length=100)
    is_qualified_lead: bool
    expected_amount: int | None = Field(default=None, ge=0)
    currency: str = Field(default="KRW", min_length=3, max_length=3)
    expected_probability_percent: float | None = Field(default=None, ge=0, le=100)
    memo: str | None = Field(default=None, max_length=2000)
    follow_up: FollowUpRequest | None = None


class MeetingOutcomeResponse(BaseModel):
    meeting_id: uuid.UUID
    meeting_outcome_id: uuid.UUID
    meeting_status: str
    is_qualified_lead: bool
    follow_up_action_id: uuid.UUID | None


class AvailabilitySlotItem(BaseModel):
    """GET /api/v1/exhibitors/{exhibitor_id}/availability 응답 항목 (interface-spec 12.2절)."""

    slot_id: uuid.UUID
    start_at: datetime
    end_at: datetime
    capacity: int
    reserved_count: int
    topic_code: str | None
    version: int


class AvailabilityListResponse(BaseModel):
    items: list[AvailabilitySlotItem]
