"""AI 구조화·승인·임베딩 도메인 SQLAlchemy 모델 (ai 스키마).

근거 문서:
    - docs/redesign-v2/common/C-2-content-collection-ai-structuring.md
    - docs/redesign-v2/common/C-4-search-recommendation-engine.md
    - .harness/contracts/domain-model.md §11

AI 출력은 정본 데이터가 아니라 검수 전 제안이다. 이 모듈은 원본 문서, 검증된 AI 출력,
업체/운영자 승인 이력, AI 호출 로그, 검색용 임베딩을 저장하되 승인 전 데이터가 검색·추천에
노출되지 않도록 상태값을 명시한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import UserDefinedType

from app.db.base import SCHEMA_AI, SCHEMA_EXHIBITION, Base
from app.models.common import new_uuid7

_new_uuid = new_uuid7


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class Vector(UserDefinedType):
    """Minimal pgvector column type without adding a Python package dependency."""

    cache_ok = True

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: object) -> str:
        del kw
        if self.dimensions is None:
            return "vector"
        return f"vector({self.dimensions})"


DOCUMENT_TYPES: tuple[str, ...] = (
    "APPLICATION_FORM",
    "COMPANY_PROFILE",
    "PRODUCT_MATERIAL",
    "CATALOG",
    "IMAGE",
    "OTHER",
)
DOCUMENT_STATUSES: tuple[str, ...] = ("STORED", "REJECTED", "DELETED")
AI_TASK_TYPES: tuple[str, ...] = (
    "ATTRIBUTE_EXTRACTION",
    "INTENT_EXTRACTION",
    "EMBEDDING_GENERATION",
    "EXPLANATION",
)
VALIDATION_STATUSES: tuple[str, ...] = ("VALID", "INVALID", "REVIEW")
EXTRACTED_ATTRIBUTE_TARGET_TYPES: tuple[str, ...] = (
    "EXHIBITOR",
    "PRODUCT",
    "EVENT_PRODUCT",
    "TRADE_CONDITION",
    "RECOMMENDABLE",
)
EXTRACTED_ATTRIBUTE_STATUSES: tuple[str, ...] = (
    "PENDING",
    "CONFIRMED",
    "REJECTED",
)
APPROVAL_SCOPES: tuple[str, ...] = ("DOCUMENT", "ATTRIBUTE")
APPROVAL_DECISIONS: tuple[str, ...] = ("APPROVED", "REJECTED")
MASTER_APPROVAL_STATUSES: tuple[str, ...] = ("DRAFT", "APPROVED", "REJECTED")
EMBEDDING_CONTENT_TYPES: tuple[str, ...] = (
    "SUMMARY",
    "TRADE",
    "PRODUCT",
    "EXHIBITOR",
    "BOOTH",
)


class SourceDocument(Base):
    """ai.source_document - 참가신청서·업체소개·제품자료 원본 메타데이터."""

    __tablename__ = "source_document"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_source_document_event_boundary",
        ),
        CheckConstraint(
            f"document_type IN ({_in_list(DOCUMENT_TYPES)})",
            name="document_type_allowed",
        ),
        CheckConstraint(
            f"document_status IN ({_in_list(DOCUMENT_STATUSES)})",
            name="document_status_allowed",
        ),
        CheckConstraint(
            "num_nonnulls(exhibitor_id, product_id, event_product_id) >= 1",
            name="source_document_target_required",
        ),
        CheckConstraint("byte_size IS NULL OR byte_size >= 0", name="byte_size_nonneg"),
        Index("idx_source_document_event", "tenant_id", "event_id", "created_at"),
        Index("idx_source_document_exhibitor", "exhibitor_id", "created_at"),
        {"schema": SCHEMA_AI},
    )

    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    exhibitor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id"),
        nullable=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.product.product_id"),
        nullable=True,
    )
    event_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.event_product.event_product_id"),
        nullable=True,
    )
    uploaded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profile.user_account.user_id"), nullable=True
    )
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    document_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="STORED"
    )
    storage_uri: Mapped[str] = mapped_column(Text, nullable=False)
    original_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    content_type: Mapped[str | None] = mapped_column(String(100), nullable=True)
    byte_size: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    checksum_sha256: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    extracted_text_uri: Mapped[str | None] = mapped_column(Text, nullable=True)
    document_metadata_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    extracted_attributes: Mapped[list[ExtractedAttribute]] = relationship(
        back_populates="source_document", cascade="all, delete-orphan"
    )
    approvals: Mapped[list[ContentApproval]] = relationship(
        back_populates="source_document"
    )
    embedding_documents: Mapped[list[EmbeddingDocument]] = relationship(
        back_populates="source_document"
    )


class AiExecutionLog(Base):
    """ai.ai_execution_log - AI 호출 감사 로그."""

    __tablename__ = "ai_execution_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_ai_execution_log_event_boundary",
        ),
        CheckConstraint(
            f"task_type IN ({_in_list(AI_TASK_TYPES)})", name="task_type_allowed"
        ),
        CheckConstraint(
            f"validation_status IN ({_in_list(VALIDATION_STATUSES)})",
            name="validation_status_allowed",
        ),
        CheckConstraint("latency_ms IS NULL OR latency_ms >= 0", name="latency_nonneg"),
        CheckConstraint(
            "token_input IS NULL OR token_input >= 0", name="token_input_nonneg"
        ),
        CheckConstraint(
            "token_output IS NULL OR token_output >= 0", name="token_output_nonneg"
        ),
        Index("idx_ai_execution_log_event_task", "tenant_id", "event_id", "task_type"),
        {"schema": SCHEMA_AI},
    )

    ai_execution_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    model_name: Mapped[str] = mapped_column(String(100), nullable=False)
    model_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    input_reference_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    input_reference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    input_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(30), nullable=True)
    validated_output_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    extracted_attributes: Mapped[list[ExtractedAttribute]] = relationship(
        back_populates="ai_execution_log"
    )


class ExtractedAttribute(Base):
    """ai.extracted_attribute - AI가 문서에서 추출한 속성 후보."""

    __tablename__ = "extracted_attribute"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_extracted_attribute_event_boundary",
        ),
        ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_extracted_attribute_ontology_revision",
        ),
        ForeignKeyConstraint(
            ["concept_id", "attribute_code"],
            ["ontology.concept.concept_id", "ontology.concept.concept_code"],
            name="fk_extracted_attribute_concept_code",
        ),
        CheckConstraint(
            f"target_object_type IN ({_in_list(EXTRACTED_ATTRIBUTE_TARGET_TYPES)})",
            name="target_object_type_allowed",
        ),
        CheckConstraint(
            f"status IN ({_in_list(EXTRACTED_ATTRIBUTE_STATUSES)})",
            name="status_allowed",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        Index("idx_extracted_attribute_source", "source_document_id", "created_at"),
        Index("idx_extracted_attribute_target", "target_object_type", "target_object_id"),
        Index("idx_extracted_attribute_status", "tenant_id", "event_id", "status"),
        {"schema": SCHEMA_AI},
    )

    extracted_attribute_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_AI}.source_document.source_document_id"),
        nullable=False,
    )
    ai_execution_log_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_AI}.ai_execution_log.ai_execution_log_id"),
        nullable=True,
    )
    target_object_type: Mapped[str] = mapped_column(String(30), nullable=False)
    target_object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    attribute_code: Mapped[str] = mapped_column(String(100), nullable=False)
    attribute_value_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    attribute_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    evidence_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    reviewed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profile.user_account.user_id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source_document: Mapped[SourceDocument] = relationship(
        back_populates="extracted_attributes"
    )
    ai_execution_log: Mapped[AiExecutionLog | None] = relationship(
        back_populates="extracted_attributes"
    )
    approvals: Mapped[list[ContentApproval]] = relationship(
        back_populates="extracted_attribute"
    )


class ContentApproval(Base):
    """ai.content_approval - 운영자 최종 승인·반려 이력."""

    __tablename__ = "content_approval"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_content_approval_event_boundary",
        ),
        CheckConstraint(
            "num_nonnulls(source_document_id, extracted_attribute_id) = 1",
            name="exactly_one_approval_target",
        ),
        CheckConstraint(
            f"approval_scope IN ({_in_list(APPROVAL_SCOPES)})",
            name="approval_scope_allowed",
        ),
        CheckConstraint(
            f"approval_decision IN ({_in_list(APPROVAL_DECISIONS)})",
            name="approval_decision_allowed",
        ),
        CheckConstraint(
            f"previous_master_approval_status IS NULL OR previous_master_approval_status "
            f"IN ({_in_list(MASTER_APPROVAL_STATUSES)})",
            name="previous_master_approval_status_allowed",
        ),
        CheckConstraint(
            f"new_master_approval_status IN ({_in_list(MASTER_APPROVAL_STATUSES)})",
            name="new_master_approval_status_allowed",
        ),
        Index("idx_content_approval_event", "tenant_id", "event_id", "approved_at"),
        Index("idx_content_approval_exhibitor", "exhibitor_id", "approved_at"),
        {"schema": SCHEMA_AI},
    )

    content_approval_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_AI}.source_document.source_document_id"),
        nullable=True,
    )
    extracted_attribute_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_AI}.extracted_attribute.extracted_attribute_id"),
        nullable=True,
    )
    exhibitor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id"),
        nullable=True,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.product.product_id"),
        nullable=True,
    )
    approval_scope: Mapped[str] = mapped_column(String(20), nullable=False)
    approval_decision: Mapped[str] = mapped_column(String(20), nullable=False)
    previous_master_approval_status: Mapped[str | None] = mapped_column(
        String(20), nullable=True
    )
    new_master_approval_status: Mapped[str] = mapped_column(String(20), nullable=False)
    approved_by_user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profile.user_account.user_id"), nullable=False
    )
    approved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    approval_note: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_document: Mapped[SourceDocument | None] = relationship(
        back_populates="approvals"
    )
    extracted_attribute: Mapped[ExtractedAttribute | None] = relationship(
        back_populates="approvals"
    )


class EmbeddingDocument(Base):
    """ai.embedding_document - 검색 임베딩의 텍스트 단위."""

    __tablename__ = "embedding_document"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_embedding_document_event_boundary",
        ),
        CheckConstraint(
            f"content_type IN ({_in_list(EMBEDDING_CONTENT_TYPES)})",
            name="content_type_allowed",
        ),
        Index(
            "uq_embedding_document_active_content",
            "recommendable_id",
            "content_type",
            "locale",
            unique=True,
            postgresql_where=text("active"),
        ),
        Index("idx_embedding_document_event", "tenant_id", "event_id", "content_type"),
        {"schema": SCHEMA_AI},
    )

    embedding_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    recommendable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.recommendable.recommendable_id"),
        nullable=False,
    )
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_AI}.source_document.source_document_id"),
        nullable=True,
    )
    content_type: Mapped[str] = mapped_column(String(30), nullable=False)
    locale: Mapped[str] = mapped_column(String(10), nullable=False, default="ko-KR")
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    content_excerpt: Mapped[str | None] = mapped_column(Text, nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    source_document: Mapped[SourceDocument | None] = relationship(
        back_populates="embedding_documents"
    )
    vectors: Mapped[list[EmbeddingVector]] = relationship(
        back_populates="embedding_document", cascade="all, delete-orphan"
    )


class EmbeddingVector(Base):
    """ai.embedding_vector - pgvector 검색 벡터."""

    __tablename__ = "embedding_vector"
    __table_args__ = (
        CheckConstraint(
            "embedding_dimension > 0", name="embedding_dimension_positive"
        ),
        Index(
            "uq_embedding_vector_active_model",
            "embedding_document_id",
            "embedding_model",
            unique=True,
            postgresql_where=text("active"),
        ),
        Index(
            "idx_embedding_vector_model_dimension_active",
            "embedding_model",
            "embedding_dimension",
            postgresql_where=text("active"),
        ),
        # The 1536-dimension partial ANN HNSW cosine index is created manually
        # in 0013 because SQLAlchemy cannot fully reflect pgvector operator-class
        # expression indexes for autogenerate.
        {"schema": SCHEMA_AI},
    )

    embedding_vector_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    embedding_document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_AI}.embedding_document.embedding_document_id"),
        nullable=False,
    )
    embedding_model: Mapped[str] = mapped_column(String(100), nullable=False)
    embedding_dimension: Mapped[int] = mapped_column(Integer, nullable=False)
    embedding: Mapped[object] = mapped_column(Vector(), nullable=False)
    content_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    embedding_document: Mapped[EmbeddingDocument] = relationship(
        back_populates="vectors"
    )
