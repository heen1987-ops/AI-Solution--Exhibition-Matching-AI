"""document 도메인 확장 - AI 추출결과 검수/승인/게시버전 SQLAlchemy 모델.

트랙: BACKEND-EXTRACTION (WAVE 2D). GOAL: AI-EXTRACTION(``ai/extraction/**``)의 산출물과
비즈니스 테이블(``exhibition.exhibitor``/``exhibition.product``/``exhibition.trade_condition``)
사이에 끼는 영속화·워크플로 계층. 이 파일의 어떤 테이블도 비즈니스 테이블이 아니다 - 승인된
행이라도 여기서 멈추고, 실제 exhibitor/product 테이블에 쓰는 것은 이후 별도 트랙
(BACKEND-INDEXING)의 몫이다(``tests/test_extraction_api.py``의
``test_no_router_path_ever_touches_business_tables``가 이를 코드로 강제한다).

테이블 이름에 대한 메모 (작업 지시와의 의도적 차이)
----------------------------------------------------
작업 지시(OWNED PATHS)는 "extracted_attributes, source_evidences, extraction_conflicts,
content_review_requests, content_review_actions, published_content_versions"라는 복수형
이름을 나열했지만, 이 저장소의 기존 93개 테이블은 예외 없이 단수형이다(``exhibitor``,
``product``, ``conversation_session``, ``source_document`` 등 - ``app/models/exhibitor.py``,
``app/models/conversation.py``, ``app/models/document.py`` 참고). ASSUMPTION-003이 이미
"외부(Codex) 프롬프트의 표기를 기존 평면 레이아웃 관례에 맞춰 매핑한다"고 정했으므로, 같은
원칙을 테이블 명명에도 적용해 아래처럼 단수형으로 만든다(6개 논리 테이블은 그대로 유지):

    extracted_attributes      -> extracted_attribute
    source_evidences          -> source_evidence
    extraction_conflicts      -> extraction_conflict
    content_review_requests   -> content_review_request
    content_review_actions    -> content_review_action
    published_content_versions -> published_content_version

스키마 선택: ``document`` 스키마(``app/db/base.py``의 ``SCHEMA_DOCUMENT`` - 이미
``app/models/document.py``가 추가해 둔 상수를 그대로 재사용한다, 새 스키마를 만들지 않음).
``.harness/contracts/document-structuring.md`` §8이 "ai 또는 새 document 스키마, 구현자
재량"이라고 명시적으로 열어 뒀고, 이미 존재하는 ``document`` 스키마를 재사용하는 편이
``app/db/base.py``(내 소유 경로 아님)를 건드리지 않아도 되는 더 안전한 선택이다.

두 개의 서로 다른 "fact_type" 계약을 어떻게 화해시켰는가 (핵심 설계 결정)
--------------------------------------------------------------------------
이 트랙에 앞서 두 개의 서로 다른 상위 트랙이 이미 "fact_type"이라는 같은 이름을 서로 다른
뜻으로 정의해 뒀다:

1. ``.harness/contracts/document-structuring.md`` §4 (CONTRACTS-STRUCTURING, 이 작업 지시가
   "fact_type은 CONTRACTS-STRUCTURING 문서대로"라고 명시적으로 지정한 근거) -
   **출처 신뢰도** 축: SOURCE_FACT/SELF_DECLARED/AI_INFERRED/CALCULATED/UNKNOWN. "이 값이
   문서에 그대로 쓰여 있는가, AI가 추론했는가"를 구분해 게시 자격을 가른다.
2. ``ai/extraction/types.py``의 ``Attribute.fact_type`` (실제 AI-EXTRACTION 트랙 구현) -
   **시점** 축: CURRENT_CAPABILITY/PAST_EXPERIENCE/FUTURE_PLAN/UNKNOWN. "지금도 가능한지,
   예전 얘기인지, 계획인지"를 구분한다(거래조건류 속성에 특히 중요).

이름은 같지만 서로 다른 정보라 하나를 버리면 AGENTS.md 불변식 5("provenance ... 필요한
append-only 활동을 저장한다")를 어긴다. 그래서 이 테이블은 둘 다 별도 컬럼으로 보존한다:
``fact_type``(계약 1, 이 파일의 게시자격 판단에 실제로 쓰이는 축)과
``temporal_validity``(계약 2, ``ai/extraction`` 산출물을 그대로 옮겨 적기만 하는 축, 이
파이프라인의 상태전이 로직은 이 값을 읽지 않는다 - 손실 없이 보존만 한다).

``app/services/extraction/ingestion.py``의 ``ingest_extraction_result()``가
``ai.extraction.types.ExtractionResult``를 이 테이블 행으로 변환할 때, AI-EXTRACTION 산출물
자체에는 "이 값이 문서에 그대로 쓰여 있는지 추론인지"를 밝히는 필드가 없으므로(그 트랙은 그
축을 다루지 않는다) 보수적 기본값으로 전부 ``fact_type='AI_INFERRED'``를 매긴다 - AGENTS.md
"AI는 원문에 없는 값을 주장해서는 안 된다"를 지키는 안전한 방향(과소분류가 아니라 과다심사
쪽으로 치우침, 즉 모든 행이 전체 확인+승인 경로를 강제로 통과한다)이다. Blocker Score < 7
(가역적 - 나중에 AI-EXTRACTION이 verbatim 여부를 명시적으로 표시하기 시작하면 이 기본값만
바꾸면 된다)이므로 여기 기록하고 계속 진행한다.

document_id/entity_reference에 FK를 걸지 않는 이유
----------------------------------------------------
- ``document_id``: ``document.source_document``(``app/models/document.py``, BACKEND-DOCUMENT
  트랙)를 참조하지만, 그 테이블은 아직 Alembic 마이그레이션이 없다(모델만 존재). 이 트랙의
  마이그레이션이 먼저 병합되면 하드 FK가 마이그레이션 적용 시점에 깨진다 - 두 트랙의 병합
  순서를 이 트랙이 통제할 수 없으므로, ``document.py``의 ``DocumentAccessLog``가 이미 같은
  이유로 채택한 것과 동일한 "FK 없는 UUID 참조" 패턴을 재사용한다(정합성은 서비스 계층
  책임 - ``app/services/extraction/ingestion.py``가 호출 시점에 ``SourceDocument``를 조회해
  존재를 확인한다).
- ``entity_reference``: ``.harness/handoffs/contracts/WAVE2D-CONTRACTS.md`` "결정 3"이 이미
  명시한 의도적 예외(polymorphic, ``matching.recommendable`` 레지스트리를 타지 않음, 승인 전
  초안 엔티티를 가리켜야 하므로) 그대로 따른다.
- ``ai_run_id``(``ai.ai_run``)와 ``exhibitor_id``(``exhibition.exhibitor``)는 반대로 이미
  마이그레이션이 적용된 테이블이라 하드 FK를 건다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_AI, SCHEMA_DOCUMENT, SCHEMA_EXHIBITION, Base
from app.models.common import new_uuid7

_new_uuid = new_uuid7


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


#: WAVE2D-CONTRACTS §7 entity_type — exhibitor.py가 이미 갖고 있는 엔티티만 참조한다.
ENTITY_TYPES: tuple[str, ...] = ("EXHIBITOR", "PRODUCT", "TRADE_CONDITION", "CERTIFICATE")

#: document-structuring.md §4 — 출처 신뢰도 축 (모듈 docstring "핵심 설계 결정" 참고).
FACT_TYPES: tuple[str, ...] = (
    "SOURCE_FACT",
    "SELF_DECLARED",
    "AI_INFERRED",
    "CALCULATED",
    "UNKNOWN",
)

#: fact_type 중 추가 심사 없이 확인만으로 게시 가능한 값. AI_INFERRED/CALCULATED/UNKNOWN은
#: 항상 전체 확인+승인 경로를 통과해야 한다(document-structuring.md §4 binding rule).
LOW_SCRUTINY_FACT_TYPES: tuple[str, ...] = ("SOURCE_FACT", "SELF_DECLARED")

#: ai/extraction/types.py FACT_TYPES — 시점 축, 손실 없이 보존만 하는 별도 컬럼.
TEMPORAL_VALIDITY_VALUES: tuple[str, ...] = (
    "CURRENT_CAPABILITY",
    "PAST_EXPERIENCE",
    "FUTURE_PLAN",
    "UNKNOWN",
)

#: document-structuring.md §3.
REVIEW_STATUSES: tuple[str, ...] = (
    "PROPOSED",
    "CONFIRMED_BY_EXHIBITOR",
    "MODIFIED_BY_EXHIBITOR",
    "REJECTED_BY_EXHIBITOR",
    "APPROVED_BY_OPERATOR",
    "REJECTED_BY_OPERATOR",
    "CONFLICTED",
    "SUPERSEDED",
)

#: 운영자 승인 직전에 있어야 하는 review_status 집합 (§3 전이표: CONFIRMED_BY_EXHIBITOR |
#: MODIFIED_BY_EXHIBITOR -> APPROVED_BY_OPERATOR, CONFLICTED -> APPROVED_BY_OPERATOR).
APPROVABLE_REVIEW_STATUSES: tuple[str, ...] = (
    "CONFIRMED_BY_EXHIBITOR",
    "MODIFIED_BY_EXHIBITOR",
    "CONFLICTED",
)

#: document-structuring.md §5.
VISIBILITY_TIERS: tuple[str, ...] = (
    "PUBLIC",
    "REGISTERED_USER",
    "VERIFIED_BUYER",
    "MEETING_ACCEPTED",
    "OPERATOR_ONLY",
)

CONFLICT_STATUSES: tuple[str, ...] = ("OPEN", "RESOLVED")

REVIEW_REQUEST_STATUSES: tuple[str, ...] = (
    "SUBMITTED",
    "IN_OPERATOR_REVIEW",
    "CHANGES_REQUESTED",
    "APPROVED",
    "REJECTED",
)

ACTOR_ROLES: tuple[str, ...] = ("EXHIBITOR", "OPERATOR", "SYSTEM")

ACTION_TYPES: tuple[str, ...] = (
    "CONFIRM",
    "MODIFY",
    "REJECT",
    "SUBMIT_FOR_REVIEW",
    "CLAIM",
    "APPROVE",
    "REJECT_REVIEW",
    "REQUEST_CHANGES",
    "ACKNOWLEDGE_UNKNOWN",
    "RESOLVE_CONFLICT",
)


class ExtractedAttribute(Base):
    """document.extracted_attribute - AI 추출/자가입력 속성 제안 한 건.

    ``proposed_value``는 AI/입력 원본을 그대로 보존한다(수정 후에도 지우지 않음).
    ``normalized_value``가 채워지기 전에는 이 행이 구조화 데이터를 쓰는 어떤 폼으로도
    진행할 수 없다(WAVE2D-CONTRACTS §7).
    """

    __tablename__ = "extracted_attribute"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            [f"{SCHEMA_EXHIBITION}.exhibitor.tenant_id", f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id"],
            name="fk_extracted_attribute_exhibitor_boundary",
        ),
        ForeignKeyConstraint(
            ["superseded_by_extraction_id"],
            [f"{SCHEMA_DOCUMENT}.extracted_attribute.extraction_id"],
            name="fk_extracted_attribute_superseded_by",
        ),
        CheckConstraint(f"entity_type IN ({_in_list(ENTITY_TYPES)})", name="entity_type_allowed"),
        CheckConstraint(f"fact_type IN ({_in_list(FACT_TYPES)})", name="fact_type_allowed"),
        CheckConstraint(
            f"temporal_validity IS NULL OR temporal_validity IN ({_in_list(TEMPORAL_VALIDITY_VALUES)})",
            name="temporal_validity_allowed",
        ),
        CheckConstraint(
            f"review_status IN ({_in_list(REVIEW_STATUSES)})", name="review_status_allowed"
        ),
        CheckConstraint(
            f"visibility IS NULL OR visibility IN ({_in_list(VISIBILITY_TIERS)})",
            name="visibility_allowed",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        Index("ix_extracted_attribute_document", "document_id"),
        Index("ix_extracted_attribute_exhibitor_status", "exhibitor_id", "review_status"),
        Index(
            "ix_extracted_attribute_entity",
            "entity_type",
            "entity_reference",
            "attribute_code",
        ),
        {"schema": SCHEMA_DOCUMENT},
    )

    extraction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    exhibitor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # 소프트 참조 - 모듈 docstring "document_id/entity_reference에 FK를 걸지 않는 이유" 참고.
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA_AI}.ai_run.ai_run_id"), nullable=True
    )

    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_reference: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # ai/extraction/types.py Entity.temporary_entity_id - entity_reference가 아직 정규화되지
    # 않았을 때(운영자 승인 이전) 원본 임시 식별자를 그대로 보존한다.
    temporary_entity_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)

    attribute_code: Mapped[str] = mapped_column(String(100), nullable=False)
    proposed_value: Mapped[dict | list | str | float | bool | None] = mapped_column(
        JSONB, nullable=True
    )
    normalized_value: Mapped[dict | list | str | float | None] = mapped_column(
        JSONB, nullable=True
    )
    concept_codes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)

    fact_type: Mapped[str] = mapped_column(String(20), nullable=False)
    temporal_validity: Mapped[str | None] = mapped_column(String(20), nullable=True)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)

    review_status: Mapped[str] = mapped_column(String(30), nullable=False, default="PROPOSED")
    visibility: Mapped[str | None] = mapped_column(String(30), nullable=True)
    # PATCH가 review_status를 조용히 바꾸지 않도록(WAVE2D-CONTRACTS §9 PATCH 설명) 별도로
    # "편집됨" 사실만 추적한다 - confirm 호출 시 이 값을 보고 MODIFIED_BY_EXHIBITOR/
    # CONFIRMED_BY_EXHIBITOR 중 무엇으로 갈지 결정한다 (app/services/extraction/review.py).
    edited_by_exhibitor: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )
    reviewed_by_exhibitor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    reviewed_by_exhibitor_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    reviewed_by_operator_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    reviewed_by_operator_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    superseded_by_extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class SourceEvidence(Base):
    """document.source_evidence - extracted_attribute 한 행이 인용하는 원문 근거 스팬.

    WAVE2D-CONTRACTS §6은 평가당 근거 1개짜리 임베디드 객체를 예시로 들지만, 실제
    ``ai/extraction/types.py``의 ``Attribute.evidence_segment_ids``는 세그먼트 여러 개를
    동시에 인용할 수 있다(문장 하나가 아니라 문단 여러 개에 걸친 근거) - 그래서 1:1이
    아니라 1(extraction):N(evidence) 관계로 만든다(unique 제약 없음).
    """

    __tablename__ = "source_evidence"
    __table_args__ = (
        ForeignKeyConstraint(
            ["extraction_id"],
            [f"{SCHEMA_DOCUMENT}.extracted_attribute.extraction_id"],
            name="fk_source_evidence_extraction",
        ),
        CheckConstraint(
            "text_start IS NULL OR text_end IS NULL OR text_end > text_start",
            name="text_span_ordered",
        ),
        Index("ix_source_evidence_extraction", "extraction_id"),
        {"schema": SCHEMA_DOCUMENT},
    )

    evidence_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    extraction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # 소프트 참조 (모듈 docstring 참고).
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # ai/extraction/types.py TextSegment.segment_id ("{document_id}:{order}") - 원본 세그먼트
    # 추적용, 오프셋 재계산 없이 바로 대조 가능하게 한다.
    segment_ref: Mapped[str | None] = mapped_column(String(150), nullable=True)
    page_number: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section_title: Mapped[str | None] = mapped_column(String(200), nullable=True)
    text_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    text_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    evidence_text: Mapped[str] = mapped_column(Text, nullable=False)
    # "sha256:" + 64자 hex (services/ingestion.py hash_payload와 동일한 평문 해시 관례 -
    # 보안 목적이 아니라 변경감지 목적, WAVE2D-CONTRACTS §6).
    evidence_hash: Mapped[str] = mapped_column(String(71), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ExtractionConflict(Base):
    """document.extraction_conflict - 같은 (entity, attribute_code)를 두고 서로 다른 값을
    주장하는 2개 이상의 extracted_attribute 행 묶음.

    document-structuring.md §3은 개별 행의 review_status='CONFLICTED'만으로 충돌을
    표현하지만, 이 트랙의 작업 지시가 별도 conflict 테이블을 명시적으로 요구했고(그리고
    ``ai/extraction/types.py``의 ``Conflict``가 2개 이상의 값-근거 쌍을 담을 수 있어 단순한
    A/B 두 컬럼으로는 부족하다), ``member_extraction_ids``에 관련된 모든 extraction_id를
    담는 배열로 N개 충돌을 지원한다.
    """

    __tablename__ = "extraction_conflict"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            [f"{SCHEMA_EXHIBITION}.exhibitor.tenant_id", f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id"],
            name="fk_extraction_conflict_exhibitor_boundary",
        ),
        ForeignKeyConstraint(
            ["winning_extraction_id"],
            [f"{SCHEMA_DOCUMENT}.extracted_attribute.extraction_id"],
            name="fk_extraction_conflict_winning_extraction",
        ),
        CheckConstraint(f"status IN ({_in_list(CONFLICT_STATUSES)})", name="status_allowed"),
        CheckConstraint(
            "jsonb_array_length(member_extraction_ids) >= 2", name="member_count_minimum"
        ),
        Index("ix_extraction_conflict_exhibitor_status", "exhibitor_id", "status"),
        {"schema": SCHEMA_DOCUMENT},
    )

    conflict_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    exhibitor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_reference: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    temporary_entity_ref: Mapped[str | None] = mapped_column(String(100), nullable=True)
    attribute_code: Mapped[str] = mapped_column(String(100), nullable=False)
    member_extraction_ids: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    winning_extraction_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    resolution_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    resolved_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ContentReviewRequest(Base):
    """document.content_review_request - 문서 단위 검수 게이트(§1의 EXHIBITOR_REVIEW ->
    OPERATOR_REVIEW -> APPROVED/REJECTED 전이를 이 트랙 소유 테이블 안에서 추적한다).

    ``app/models/document.py``의 ``SourceDocument.status``(UPLOADED/PROCESSING/PROCESSED/
    PROCESSING_FAILED)를 재사용하거나 확장하지 않는다 - 그 필드는 "문서를 파싱할 수
    있었는가"(BACKEND-DOCUMENT 트랙 소유)를 다루고, 이 테이블은 "추출된 내용을 검수해
    승인했는가"(이 트랙 소유)를 다룬다. 서로 다른 관심사를 같은 컬럼에 욱여넣지 않기 위한
    의도적 분리다.
    """

    __tablename__ = "content_review_request"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            [f"{SCHEMA_EXHIBITION}.exhibitor.tenant_id", f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id"],
            name="fk_content_review_request_exhibitor_boundary",
        ),
        CheckConstraint(
            f"status IN ({_in_list(REVIEW_REQUEST_STATUSES)})", name="status_allowed"
        ),
        Index("ix_content_review_request_status", "status", "submitted_at"),
        Index("ix_content_review_request_document", "document_id"),
        {"schema": SCHEMA_DOCUMENT},
    )

    review_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    exhibitor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    document_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="SUBMITTED")
    submitted_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    claimed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    decided_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    operator_comment: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now(), onupdate=func.now()
    )


class ContentReviewAction(Base):
    """document.content_review_action - append-only 검수 행위 로그.

    ``document_access_log``(app/models/document.py)와 같은 이유로 이 로그 자체는 대상
    행(extraction/review_request)이 지워져도 남아야 하는 감사 성격이지만, 이 파이프라인
    안에서는 extraction/review_request가 하드삭제되지 않으므로(REJECTED도 행을 남긴다) 여기는
    FK를 걸어 무결성을 함께 챙긴다.
    """

    __tablename__ = "content_review_action"
    __table_args__ = (
        ForeignKeyConstraint(
            ["review_request_id"],
            [f"{SCHEMA_DOCUMENT}.content_review_request.review_request_id"],
            name="fk_content_review_action_review_request",
        ),
        ForeignKeyConstraint(
            ["extraction_id"],
            [f"{SCHEMA_DOCUMENT}.extracted_attribute.extraction_id"],
            name="fk_content_review_action_extraction",
        ),
        CheckConstraint(f"actor_role IN ({_in_list(ACTOR_ROLES)})", name="actor_role_allowed"),
        CheckConstraint(
            f"action_type IN ({_in_list(ACTION_TYPES)})", name="action_type_allowed"
        ),
        Index("ix_content_review_action_extraction", "extraction_id", "created_at"),
        Index("ix_content_review_action_review_request", "review_request_id", "created_at"),
        {"schema": SCHEMA_DOCUMENT},
    )

    action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    review_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    extraction_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    actor_role: Mapped[str] = mapped_column(String(20), nullable=False)
    action_type: Mapped[str] = mapped_column(String(30), nullable=False)
    previous_value: Mapped[dict | list | str | float | None] = mapped_column(
        JSONB, nullable=True
    )
    new_value: Mapped[dict | list | str | float | None] = mapped_column(JSONB, nullable=True)
    reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class PublishedContentVersion(Base):
    """document.published_content_version - 운영자 승인 시점의 불변 스냅샷.

    AGENTS.md 불변식 3("불변 게시 아티팩트를 버전화한다; 이력을 다시 쓰지 않고 새 버전을
    만든다")을 이 파이프라인에 적용한 것이다. 같은 extraction_id가 재승인되는 일은 없지만
    (REJECTED_BY_OPERATOR는 종결, 새 값은 새 extraction_id로 들어온다 - §3), 같은 논리적
    사실(entity_type, entity_reference, attribute_code)에 대해 나중에 다른 extraction_id가
    새로 승인되면 이전 버전의 ``superseded_at``을 채우고 새 행을 추가한다(행을 덮어쓰지
    않음). BACKEND-INDEXING 트랙이 검색/추천 색인을 채울 때 읽어야 할 유일한 표면이다 - 이
    테이블에 쓰는 것 자체는 exhibitor/product 비즈니스 테이블에 쓰는 것이 아니다(모듈
    docstring 맨 위 참고).
    """

    __tablename__ = "published_content_version"
    __table_args__ = (
        ForeignKeyConstraint(
            ["extraction_id"],
            [f"{SCHEMA_DOCUMENT}.extracted_attribute.extraction_id"],
            name="fk_published_content_version_extraction",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            [f"{SCHEMA_EXHIBITION}.exhibitor.tenant_id", f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id"],
            name="fk_published_content_version_exhibitor_boundary",
        ),
        UniqueConstraint("extraction_id", "version_no", name="uq_published_content_version_no"),
        CheckConstraint("version_no > 0", name="version_no_positive"),
        CheckConstraint(f"visibility IN ({_in_list(VISIBILITY_TIERS)})", name="visibility_allowed"),
        Index(
            "ix_published_content_version_entity",
            "entity_type",
            "entity_reference",
            "attribute_code",
            "superseded_at",
        ),
        {"schema": SCHEMA_DOCUMENT},
    )

    version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    extraction_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    exhibitor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(30), nullable=False)
    entity_reference: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    attribute_code: Mapped[str] = mapped_column(String(100), nullable=False)
    value: Mapped[dict | list | str | float | bool] = mapped_column(JSONB, nullable=False)
    concept_codes: Mapped[list[str] | None] = mapped_column(JSONB, nullable=True)
    visibility: Mapped[str] = mapped_column(String(30), nullable=False)
    version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    published_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    superseded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
