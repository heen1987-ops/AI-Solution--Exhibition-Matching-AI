"""create ai document/extraction/approval/log/embedding tables

근거 문서: `.harness/contracts/domain-model.md` §11,
`docs/redesign-v2/common/C-2-content-collection-ai-structuring.md`,
`docs/redesign-v2/common/C-4-search-recommendation-engine.md`.

AI 출력은 승인 전 제안이므로 extracted_attribute.status와 content_approval 이력을 분리한다.
임베딩은 pgvector 확장을 사용하되 모델 차원이 확정되지 않은 상태를 고려해 `vector` 타입과
별도 `embedding_dimension` 컬럼으로 시작한다.

Revision ID: 0012_ai_schema
Revises: 0011_saved_recommendable
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op


class Vector(sa.types.UserDefinedType):
    cache_ok = True

    def __init__(self, dimensions: int | None = None) -> None:
        self.dimensions = dimensions

    def get_col_spec(self, **kw: object) -> str:
        del kw
        if self.dimensions is None:
            return "vector"
        return f"vector({self.dimensions})"


# revision identifiers, used by Alembic.
revision: str = "0012_ai_schema"
down_revision: str | None = "0011_saved_recommendable"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "source_document",
        sa.Column("source_document_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("exhibitor_id", sa.UUID(), nullable=True),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("event_product_id", sa.UUID(), nullable=True),
        sa.Column("uploaded_by_user_id", sa.UUID(), nullable=True),
        sa.Column("document_type", sa.String(length=30), nullable=False),
        sa.Column(
            "document_status",
            sa.String(length=20),
            server_default="STORED",
            nullable=False,
        ),
        sa.Column("storage_uri", sa.Text(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=True),
        sa.Column("content_type", sa.String(length=100), nullable=True),
        sa.Column("byte_size", sa.BigInteger(), nullable=True),
        sa.Column("checksum_sha256", sa.LargeBinary(), nullable=True),
        sa.Column("extracted_text_uri", sa.Text(), nullable=True),
        sa.Column(
            "document_metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "byte_size IS NULL OR byte_size >= 0",
            name=op.f("ck_source_document_byte_size_nonneg"),
        ),
        sa.CheckConstraint(
            "document_status IN ('STORED', 'REJECTED', 'DELETED')",
            name=op.f("ck_source_document_document_status_allowed"),
        ),
        sa.CheckConstraint(
            "document_type IN ('APPLICATION_FORM', 'COMPANY_PROFILE', "
            "'PRODUCT_MATERIAL', 'CATALOG', 'IMAGE', 'OTHER')",
            name=op.f("ck_source_document_document_type_allowed"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(exhibitor_id, product_id, event_product_id) >= 1",
            name=op.f("ck_source_document_source_document_target_required"),
        ),
        sa.ForeignKeyConstraint(
            ["event_product_id"],
            ["exhibition.event_product.event_product_id"],
            name=op.f("fk_source_document_event_product_id_event_product"),
        ),
        sa.ForeignKeyConstraint(
            ["exhibitor_id"],
            ["exhibition.exhibitor.exhibitor_id"],
            name=op.f("fk_source_document_exhibitor_id_exhibitor"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["exhibition.product.product_id"],
            name=op.f("fk_source_document_product_id_product"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_source_document_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by_user_id"],
            ["profile.user_account.user_id"],
            name=op.f("fk_source_document_uploaded_by_user_id_user_account"),
        ),
        sa.PrimaryKeyConstraint("source_document_id", name=op.f("pk_source_document")),
        schema="ai",
    )
    op.create_index(
        "idx_source_document_event",
        "source_document",
        ["tenant_id", "event_id", "created_at"],
        unique=False,
        schema="ai",
    )
    op.create_index(
        "idx_source_document_exhibitor",
        "source_document",
        ["exhibitor_id", "created_at"],
        unique=False,
        schema="ai",
    )

    op.create_table(
        "ai_execution_log",
        sa.Column("ai_execution_log_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("model_version", sa.String(length=100), nullable=True),
        sa.Column("task_type", sa.String(length=30), nullable=False),
        sa.Column("input_reference_type", sa.String(length=50), nullable=True),
        sa.Column("input_reference_id", sa.UUID(), nullable=True),
        sa.Column("input_hash", sa.LargeBinary(), nullable=True),
        sa.Column("schema_version", sa.String(length=30), nullable=True),
        sa.Column("prompt_version", sa.String(length=30), nullable=True),
        sa.Column(
            "validated_output_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("validation_status", sa.String(length=20), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("token_input", sa.Integer(), nullable=True),
        sa.Column("token_output", sa.Integer(), nullable=True),
        sa.Column("estimated_cost", sa.Numeric(precision=12, scale=6), nullable=True),
        sa.Column("error_code", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0",
            name=op.f("ck_ai_execution_log_latency_nonneg"),
        ),
        sa.CheckConstraint(
            "task_type IN ('ATTRIBUTE_EXTRACTION', 'INTENT_EXTRACTION', "
            "'EMBEDDING_GENERATION', 'EXPLANATION')",
            name=op.f("ck_ai_execution_log_task_type_allowed"),
        ),
        sa.CheckConstraint(
            "token_input IS NULL OR token_input >= 0",
            name=op.f("ck_ai_execution_log_token_input_nonneg"),
        ),
        sa.CheckConstraint(
            "token_output IS NULL OR token_output >= 0",
            name=op.f("ck_ai_execution_log_token_output_nonneg"),
        ),
        sa.CheckConstraint(
            "validation_status IN ('VALID', 'INVALID', 'REVIEW')",
            name=op.f("ck_ai_execution_log_validation_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_ai_execution_log_event_boundary",
        ),
        sa.PrimaryKeyConstraint(
            "ai_execution_log_id", name=op.f("pk_ai_execution_log")
        ),
        schema="ai",
    )
    op.create_index(
        "idx_ai_execution_log_event_task",
        "ai_execution_log",
        ["tenant_id", "event_id", "task_type"],
        unique=False,
        schema="ai",
    )

    op.create_table(
        "extracted_attribute",
        sa.Column("extracted_attribute_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("source_document_id", sa.UUID(), nullable=False),
        sa.Column("ai_execution_log_id", sa.UUID(), nullable=True),
        sa.Column("target_object_type", sa.String(length=30), nullable=False),
        sa.Column("target_object_id", sa.UUID(), nullable=False),
        sa.Column("taxonomy_version_id", sa.UUID(), nullable=False),
        sa.Column("concept_id", sa.UUID(), nullable=False),
        sa.Column("attribute_code", sa.String(length=100), nullable=False),
        sa.Column(
            "attribute_value_json",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("attribute_text", sa.Text(), nullable=True),
        sa.Column("confidence", sa.Numeric(precision=5, scale=4), nullable=False),
        sa.Column("evidence_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "status", sa.String(length=20), server_default="PENDING", nullable=False
        ),
        sa.Column("reviewed_by_user_id", sa.UUID(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name=op.f("ck_extracted_attribute_confidence_range"),
        ),
        sa.CheckConstraint(
            "status IN ('PENDING', 'CONFIRMED', 'REJECTED')",
            name=op.f("ck_extracted_attribute_status_allowed"),
        ),
        sa.CheckConstraint(
            "target_object_type IN ('EXHIBITOR', 'PRODUCT', 'EVENT_PRODUCT', "
            "'TRADE_CONDITION', 'RECOMMENDABLE')",
            name=op.f("ck_extracted_attribute_target_object_type_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["ai_execution_log_id"],
            ["ai.ai_execution_log.ai_execution_log_id"],
            name=op.f("fk_extracted_attribute_ai_execution_log_id_ai_execution_log"),
        ),
        sa.ForeignKeyConstraint(
            ["concept_id", "attribute_code"],
            ["ontology.concept.concept_id", "ontology.concept.concept_code"],
            name="fk_extracted_attribute_concept_code",
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by_user_id"],
            ["profile.user_account.user_id"],
            name=op.f("fk_extracted_attribute_reviewed_by_user_id_user_account"),
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["ai.source_document.source_document_id"],
            name=op.f("fk_extracted_attribute_source_document_id_source_document"),
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_extracted_attribute_ontology_revision",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_extracted_attribute_event_boundary",
        ),
        sa.PrimaryKeyConstraint(
            "extracted_attribute_id", name=op.f("pk_extracted_attribute")
        ),
        schema="ai",
    )
    op.create_index(
        "idx_extracted_attribute_source",
        "extracted_attribute",
        ["source_document_id", "created_at"],
        unique=False,
        schema="ai",
    )
    op.create_index(
        "idx_extracted_attribute_status",
        "extracted_attribute",
        ["tenant_id", "event_id", "status"],
        unique=False,
        schema="ai",
    )
    op.create_index(
        "idx_extracted_attribute_target",
        "extracted_attribute",
        ["target_object_type", "target_object_id"],
        unique=False,
        schema="ai",
    )

    op.create_table(
        "content_approval",
        sa.Column("content_approval_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("source_document_id", sa.UUID(), nullable=True),
        sa.Column("extracted_attribute_id", sa.UUID(), nullable=True),
        sa.Column("exhibitor_id", sa.UUID(), nullable=True),
        sa.Column("product_id", sa.UUID(), nullable=True),
        sa.Column("approval_scope", sa.String(length=20), nullable=False),
        sa.Column("approval_decision", sa.String(length=20), nullable=False),
        sa.Column("previous_master_approval_status", sa.String(length=20), nullable=True),
        sa.Column("new_master_approval_status", sa.String(length=20), nullable=False),
        sa.Column("approved_by_user_id", sa.UUID(), nullable=False),
        sa.Column(
            "approved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("approval_note", sa.Text(), nullable=True),
        sa.CheckConstraint(
            "approval_decision IN ('APPROVED', 'REJECTED')",
            name=op.f("ck_content_approval_approval_decision_allowed"),
        ),
        sa.CheckConstraint(
            "approval_scope IN ('DOCUMENT', 'ATTRIBUTE')",
            name=op.f("ck_content_approval_approval_scope_allowed"),
        ),
        sa.CheckConstraint(
            "new_master_approval_status IN ('DRAFT', 'APPROVED', 'REJECTED')",
            name=op.f("ck_content_approval_new_master_approval_status_allowed"),
        ),
        sa.CheckConstraint(
            "num_nonnulls(source_document_id, extracted_attribute_id) = 1",
            name=op.f("ck_content_approval_exactly_one_approval_target"),
        ),
        sa.CheckConstraint(
            "previous_master_approval_status IS NULL OR "
            "previous_master_approval_status IN ('DRAFT', 'APPROVED', 'REJECTED')",
            name=op.f("ck_content_approval_previous_master_approval_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["approved_by_user_id"],
            ["profile.user_account.user_id"],
            name=op.f("fk_content_approval_approved_by_user_id_user_account"),
        ),
        sa.ForeignKeyConstraint(
            ["exhibitor_id"],
            ["exhibition.exhibitor.exhibitor_id"],
            name=op.f("fk_content_approval_exhibitor_id_exhibitor"),
        ),
        sa.ForeignKeyConstraint(
            ["extracted_attribute_id"],
            ["ai.extracted_attribute.extracted_attribute_id"],
            name=op.f("fk_content_approval_extracted_attribute_id_extracted_attribute"),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["exhibition.product.product_id"],
            name=op.f("fk_content_approval_product_id_product"),
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["ai.source_document.source_document_id"],
            name=op.f("fk_content_approval_source_document_id_source_document"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_content_approval_event_boundary",
        ),
        sa.PrimaryKeyConstraint("content_approval_id", name=op.f("pk_content_approval")),
        schema="ai",
    )
    op.create_index(
        "idx_content_approval_event",
        "content_approval",
        ["tenant_id", "event_id", "approved_at"],
        unique=False,
        schema="ai",
    )
    op.create_index(
        "idx_content_approval_exhibitor",
        "content_approval",
        ["exhibitor_id", "approved_at"],
        unique=False,
        schema="ai",
    )

    op.create_table(
        "embedding_document",
        sa.Column("embedding_document_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("recommendable_id", sa.UUID(), nullable=False),
        sa.Column("source_document_id", sa.UUID(), nullable=True),
        sa.Column("content_type", sa.String(length=30), nullable=False),
        sa.Column("locale", sa.String(length=10), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column("content_excerpt", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "content_type IN ('SUMMARY', 'TRADE', 'PRODUCT', 'EXHIBITOR', 'BOOTH')",
            name=op.f("ck_embedding_document_content_type_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["recommendable_id"],
            ["exhibition.recommendable.recommendable_id"],
            name=op.f("fk_embedding_document_recommendable_id_recommendable"),
        ),
        sa.ForeignKeyConstraint(
            ["source_document_id"],
            ["ai.source_document.source_document_id"],
            name=op.f("fk_embedding_document_source_document_id_source_document"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_embedding_document_event_boundary",
        ),
        sa.PrimaryKeyConstraint(
            "embedding_document_id", name=op.f("pk_embedding_document")
        ),
        schema="ai",
    )
    op.create_index(
        "idx_embedding_document_event",
        "embedding_document",
        ["tenant_id", "event_id", "content_type"],
        unique=False,
        schema="ai",
    )
    op.create_index(
        "uq_embedding_document_active_content",
        "embedding_document",
        ["recommendable_id", "content_type", "locale"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("active"),
    )

    op.create_table(
        "embedding_vector",
        sa.Column("embedding_vector_id", sa.UUID(), nullable=False),
        sa.Column("embedding_document_id", sa.UUID(), nullable=False),
        sa.Column("embedding_model", sa.String(length=100), nullable=False),
        sa.Column("embedding_dimension", sa.Integer(), nullable=False),
        sa.Column("embedding", Vector(), nullable=False),
        sa.Column("content_hash", sa.LargeBinary(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "embedding_dimension > 0",
            name=op.f("ck_embedding_vector_embedding_dimension_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["embedding_document_id"],
            ["ai.embedding_document.embedding_document_id"],
            name=op.f("fk_embedding_vector_embedding_document_id_embedding_document"),
        ),
        sa.PrimaryKeyConstraint("embedding_vector_id", name=op.f("pk_embedding_vector")),
        schema="ai",
    )
    op.create_index(
        "uq_embedding_vector_active_model",
        "embedding_vector",
        ["embedding_document_id", "embedding_model"],
        unique=True,
        schema="ai",
        postgresql_where=sa.text("active"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_embedding_vector_active_model",
        table_name="embedding_vector",
        schema="ai",
    )
    op.drop_table("embedding_vector", schema="ai")
    op.drop_index(
        "uq_embedding_document_active_content",
        table_name="embedding_document",
        schema="ai",
    )
    op.drop_index(
        "idx_embedding_document_event",
        table_name="embedding_document",
        schema="ai",
    )
    op.drop_table("embedding_document", schema="ai")
    op.drop_index(
        "idx_content_approval_exhibitor",
        table_name="content_approval",
        schema="ai",
    )
    op.drop_index(
        "idx_content_approval_event",
        table_name="content_approval",
        schema="ai",
    )
    op.drop_table("content_approval", schema="ai")
    op.drop_index(
        "idx_extracted_attribute_target",
        table_name="extracted_attribute",
        schema="ai",
    )
    op.drop_index(
        "idx_extracted_attribute_status",
        table_name="extracted_attribute",
        schema="ai",
    )
    op.drop_index(
        "idx_extracted_attribute_source",
        table_name="extracted_attribute",
        schema="ai",
    )
    op.drop_table("extracted_attribute", schema="ai")
    op.drop_index(
        "idx_ai_execution_log_event_task",
        table_name="ai_execution_log",
        schema="ai",
    )
    op.drop_table("ai_execution_log", schema="ai")
    op.drop_index(
        "idx_source_document_exhibitor",
        table_name="source_document",
        schema="ai",
    )
    op.drop_index(
        "idx_source_document_event",
        table_name="source_document",
        schema="ai",
    )
    op.drop_table("source_document", schema="ai")
