"""Pydantic 스키마 - BACKEND-EXTRACTION (WAVE 2D) 라우터의 요청/응답 모델.

모양은 ``.harness/contracts/document-structuring.md`` §6-§7을 따르되, 같은 문서의
"의도적 예외" 정신에 따라 이 트랙이 실제로 다루는 두 축(§4 fact_type, ``ai/extraction``의
temporal_validity)을 모두 노출한다 - ``app/models/extraction.py`` 모듈 docstring 참고.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

EntityType = Literal["EXHIBITOR", "PRODUCT", "TRADE_CONDITION", "CERTIFICATE"]
FactType = Literal["SOURCE_FACT", "SELF_DECLARED", "AI_INFERRED", "CALCULATED", "UNKNOWN"]
TemporalValidity = Literal[
    "CURRENT_CAPABILITY", "PAST_EXPERIENCE", "FUTURE_PLAN", "UNKNOWN"
]
ReviewStatus = Literal[
    "PROPOSED",
    "CONFIRMED_BY_EXHIBITOR",
    "MODIFIED_BY_EXHIBITOR",
    "REJECTED_BY_EXHIBITOR",
    "APPROVED_BY_OPERATOR",
    "REJECTED_BY_OPERATOR",
    "CONFLICTED",
    "SUPERSEDED",
]
Visibility = Literal[
    "PUBLIC", "REGISTERED_USER", "VERIFIED_BUYER", "MEETING_ACCEPTED", "OPERATOR_ONLY"
]


class EvidenceRead(BaseModel):
    """WAVE2D-CONTRACTS §6 evidence shape 1건."""

    evidence_id: UUID
    document_id: UUID | None = None
    segment_ref: str | None = None
    page_number: int | None = None
    section_title: str | None = None
    text_start: int | None = None
    text_end: int | None = None
    evidence_text: str
    evidence_hash: str


class ExtractedAttributeRead(BaseModel):
    """WAVE2D-CONTRACTS §7 extracted-attribute shape. ``GET .../extractions`` 목록 항목이자
    ``PATCH .../extractions/{id}`` 응답 본문."""

    extraction_id: UUID
    document_id: UUID | None = None
    ai_run_id: UUID | None = None
    entity_type: EntityType
    entity_reference: UUID | None = None
    temporary_entity_ref: str | None = None
    attribute_code: str
    proposed_value: Any = None
    normalized_value: Any = None
    concept_codes: list[str] | None = None
    fact_type: FactType
    temporal_validity: TemporalValidity | None = None
    confidence: float | None = None
    review_status: ReviewStatus
    visibility: Visibility | None = None
    edited_by_exhibitor: bool
    evidence: list[EvidenceRead] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    reviewed_by_exhibitor_user_id: UUID | None = None
    reviewed_by_exhibitor_at: datetime | None = None
    reviewed_by_operator_user_id: UUID | None = None
    reviewed_by_operator_at: datetime | None = None
    rejection_reason: str | None = None
    superseded_by_extraction_id: UUID | None = None


class ExtractionListResponse(BaseModel):
    document_id: UUID
    items: list[ExtractedAttributeRead]


class ExtractionPatchRequest(BaseModel):
    """WAVE2D-CONTRACTS §9 PATCH - 확인 전 편집. 단독으로는 review_status를 절대 바꾸지
    않는다(``app/services/extraction/review.py`` 참고)."""

    normalized_value: Any = None
    visibility: Visibility | None = None
    reason: str | None = Field(
        default=None, description="편집 사유 - content_review_action 감사로그에 기록"
    )


class ExtractionConfirmRequest(BaseModel):
    """WAVE2D-CONTRACTS §9 confirm - 확인/거절을 한 엔드포인트가 함께 처리한다."""

    decision: Literal["confirm", "reject"]
    reason: str | None = None


class SubmitReviewRequest(BaseModel):
    document_id: UUID


class SubmitReviewCheck(BaseModel):
    """§9 submit-review 검증 실패 상세 한 건 - 여러 개를 한 번에 반환해 왕복을 줄인다."""

    code: str
    message: str
    extraction_id: UUID | None = None
    attribute_code: str | None = None


class SubmitReviewResponse(BaseModel):
    review_request_id: UUID
    document_id: UUID
    status: str
    submitted_at: datetime


class SubmitReviewRejected(BaseModel):
    code: str = "EXTRACTIONS_PENDING_REVIEW"
    message: str = "일부 추출 항목이 아직 검수를 마치지 않았습니다."
    checks: list[SubmitReviewCheck]


class AdminReviewQueueItem(BaseModel):
    """``GET /admin/ai-review`` 큐 항목 - 문서 단위 검수요청 + 하위 추출요약."""

    review_request_id: UUID
    document_id: UUID | None = None
    exhibitor_id: UUID
    status: str
    submitted_at: datetime
    claimed_by_user_id: UUID | None = None
    pending_extraction_count: int
    ai_inferred_count: int
    has_unresolved_conflict: bool


class AdminReviewQueueResponse(BaseModel):
    items: list[AdminReviewQueueItem]


class AdminReviewClaimRequest(BaseModel):
    """``POST /admin/ai-review`` - WAVE2D-CONTRACTS §9 "문서/추출 id에 묶이지 않은 운영자
    액션" 중 하나로 일괄 클레임(재큐잉)을 구현한다."""

    review_request_ids: list[UUID]


class AdminReviewClaimResponse(BaseModel):
    claimed: list[UUID]
    already_claimed: list[UUID]


class AdminDecisionRequest(BaseModel):
    reason: str | None = None


class AdminDecisionResponse(BaseModel):
    extraction_id: UUID
    review_status: ReviewStatus
    published_version_id: UUID | None = None


class AdminRequestChangesRequest(BaseModel):
    comment: str = Field(min_length=1)


class AdminRequestChangesResponse(BaseModel):
    review_request_id: UUID
    status: str
    operator_comment: str
