"""publish extraction/review workflow tables (BACKEND-EXTRACTION, WAVE 2D)

Revision ID: 0025_extraction_review
Revises: 0024_document_storage
Create Date: 2026-08-02

새 스키마를 만들지 않는다 - ``document`` 스키마는 ``app/models/document.py``(BACKEND-DOCUMENT
트랙)가 ``app/db/base.py``의 ``SCHEMA_DOCUMENT``에 이미 추가해 뒀지만 그 트랙 자신의
마이그레이션은 아직 없다(모델만 존재). 그래서 이 마이그레이션이 방어적으로
``CREATE SCHEMA IF NOT EXISTS "document"``를 실행한다(0013/0015/0016이 각자의 신규 스키마에
대해 이미 채택한 관례와 동일 - 최초 마이그레이션의 ``ALL_SCHEMAS`` 루프는 신선 설치에서만
자동으로 이 스키마를 만든다).

``document.source_document``에 대한 하드 FK를 걸지 않는 이유는
``app/models/extraction.py`` 모듈 docstring "document_id/entity_reference에 FK를 걸지 않는
이유"를 참고 - BACKEND-DOCUMENT 트랙의 마이그레이션이 아직 이 체인에 없어 병합 순서를
이 마이그레이션이 통제할 수 없다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0025_extraction_review"
down_revision: str | None = "0024_document_storage"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "document"


def upgrade() -> None:
    op.execute('CREATE SCHEMA IF NOT EXISTS "document"')

    op.create_table(
        "extracted_attribute",
        sa.Column("extraction_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exhibitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("ai_run_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("entity_reference", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("temporary_entity_ref", sa.String(100), nullable=True),
        sa.Column("attribute_code", sa.String(100), nullable=False),
        sa.Column("proposed_value", postgresql.JSONB(), nullable=True),
        sa.Column("normalized_value", postgresql.JSONB(), nullable=True),
        sa.Column("concept_codes", postgresql.JSONB(), nullable=True),
        sa.Column("fact_type", sa.String(20), nullable=False),
        sa.Column("temporal_validity", sa.String(20), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=True),
        sa.Column("review_status", sa.String(30), nullable=False, server_default="PROPOSED"),
        sa.Column("visibility", sa.String(30), nullable=True),
        sa.Column("edited_by_exhibitor", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("reviewed_by_exhibitor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_by_exhibitor_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reviewed_by_operator_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_by_operator_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        sa.Column("superseded_by_extraction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            ["exhibition.exhibitor.tenant_id", "exhibition.exhibitor.exhibitor_id"],
            name="fk_extracted_attribute_exhibitor_boundary",
        ),
        sa.ForeignKeyConstraint(["ai_run_id"], ["ai.ai_run.ai_run_id"]),
        sa.ForeignKeyConstraint(
            ["superseded_by_extraction_id"],
            [f"{_SCHEMA}.extracted_attribute.extraction_id"],
            name="fk_extracted_attribute_superseded_by",
        ),
        sa.CheckConstraint(
            "entity_type IN ('EXHIBITOR', 'PRODUCT', 'TRADE_CONDITION', 'CERTIFICATE')",
            name=op.f("ck_extracted_attribute_entity_type_allowed"),
        ),
        sa.CheckConstraint(
            "fact_type IN ('SOURCE_FACT', 'SELF_DECLARED', 'AI_INFERRED', 'CALCULATED', 'UNKNOWN')",
            name=op.f("ck_extracted_attribute_fact_type_allowed"),
        ),
        sa.CheckConstraint(
            "temporal_validity IS NULL OR temporal_validity IN "
            "('CURRENT_CAPABILITY', 'PAST_EXPERIENCE', 'FUTURE_PLAN', 'UNKNOWN')",
            name=op.f("ck_extracted_attribute_temporal_validity_allowed"),
        ),
        sa.CheckConstraint(
            "review_status IN ('PROPOSED', 'CONFIRMED_BY_EXHIBITOR', 'MODIFIED_BY_EXHIBITOR', "
            "'REJECTED_BY_EXHIBITOR', 'APPROVED_BY_OPERATOR', 'REJECTED_BY_OPERATOR', "
            "'CONFLICTED', 'SUPERSEDED')",
            name=op.f("ck_extracted_attribute_review_status_allowed"),
        ),
        sa.CheckConstraint(
            "visibility IS NULL OR visibility IN "
            "('PUBLIC', 'REGISTERED_USER', 'VERIFIED_BUYER', 'MEETING_ACCEPTED', 'OPERATOR_ONLY')",
            name=op.f("ck_extracted_attribute_visibility_allowed"),
        ),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name=op.f("ck_extracted_attribute_confidence_range"),
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_extracted_attribute_document",
        "extracted_attribute",
        ["document_id"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_extracted_attribute_exhibitor_status",
        "extracted_attribute",
        ["exhibitor_id", "review_status"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_extracted_attribute_entity",
        "extracted_attribute",
        ["entity_type", "entity_reference", "attribute_code"],
        schema=_SCHEMA,
    )

    op.create_table(
        "source_evidence",
        sa.Column("evidence_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("extraction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("segment_ref", sa.String(150), nullable=True),
        sa.Column("page_number", sa.Integer(), nullable=True),
        sa.Column("section_title", sa.String(200), nullable=True),
        sa.Column("text_start", sa.Integer(), nullable=True),
        sa.Column("text_end", sa.Integer(), nullable=True),
        sa.Column("evidence_text", sa.Text(), nullable=False),
        sa.Column("evidence_hash", sa.String(71), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            [f"{_SCHEMA}.extracted_attribute.extraction_id"],
            name="fk_source_evidence_extraction",
        ),
        sa.CheckConstraint(
            "text_start IS NULL OR text_end IS NULL OR text_end > text_start",
            name=op.f("ck_source_evidence_text_span_ordered"),
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_source_evidence_extraction", "source_evidence", ["extraction_id"], schema=_SCHEMA
    )

    op.create_table(
        "extraction_conflict",
        sa.Column("conflict_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exhibitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("entity_reference", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("temporary_entity_ref", sa.String(100), nullable=True),
        sa.Column("attribute_code", sa.String(100), nullable=False),
        sa.Column("member_extraction_ids", postgresql.JSONB(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("winning_extraction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolution_note", sa.String(500), nullable=True),
        sa.Column("resolved_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            ["exhibition.exhibitor.tenant_id", "exhibition.exhibitor.exhibitor_id"],
            name="fk_extraction_conflict_exhibitor_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["winning_extraction_id"],
            [f"{_SCHEMA}.extracted_attribute.extraction_id"],
            name="fk_extraction_conflict_winning_extraction",
        ),
        sa.CheckConstraint(
            "status IN ('OPEN', 'RESOLVED')", name=op.f("ck_extraction_conflict_status_allowed")
        ),
        sa.CheckConstraint(
            "jsonb_array_length(member_extraction_ids) >= 2",
            name=op.f("ck_extraction_conflict_member_count_minimum"),
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_extraction_conflict_exhibitor_status",
        "extraction_conflict",
        ["exhibitor_id", "status"],
        schema=_SCHEMA,
    )

    op.create_table(
        "content_review_request",
        sa.Column("review_request_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exhibitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("document_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="SUBMITTED"),
        sa.Column("submitted_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "submitted_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("claimed_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("operator_comment", sa.String(1000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            ["exhibition.exhibitor.tenant_id", "exhibition.exhibitor.exhibitor_id"],
            name="fk_content_review_request_exhibitor_boundary",
        ),
        sa.CheckConstraint(
            "status IN ('SUBMITTED', 'IN_OPERATOR_REVIEW', 'CHANGES_REQUESTED', 'APPROVED', "
            "'REJECTED')",
            name=op.f("ck_content_review_request_status_allowed"),
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_content_review_request_status",
        "content_review_request",
        ["status", "submitted_at"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_content_review_request_document",
        "content_review_request",
        ["document_id"],
        schema=_SCHEMA,
    )

    op.create_table(
        "content_review_action",
        sa.Column("action_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("review_request_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("extraction_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("actor_role", sa.String(20), nullable=False),
        sa.Column("action_type", sa.String(30), nullable=False),
        sa.Column("previous_value", postgresql.JSONB(), nullable=True),
        sa.Column("new_value", postgresql.JSONB(), nullable=True),
        sa.Column("reason", sa.String(500), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.ForeignKeyConstraint(
            ["review_request_id"],
            [f"{_SCHEMA}.content_review_request.review_request_id"],
            name="fk_content_review_action_review_request",
        ),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            [f"{_SCHEMA}.extracted_attribute.extraction_id"],
            name="fk_content_review_action_extraction",
        ),
        sa.CheckConstraint(
            "actor_role IN ('EXHIBITOR', 'OPERATOR', 'SYSTEM')",
            name=op.f("ck_content_review_action_actor_role_allowed"),
        ),
        sa.CheckConstraint(
            "action_type IN ('CONFIRM', 'MODIFY', 'REJECT', 'SUBMIT_FOR_REVIEW', 'CLAIM', "
            "'APPROVE', 'REJECT_REVIEW', 'REQUEST_CHANGES', 'ACKNOWLEDGE_UNKNOWN', "
            "'RESOLVE_CONFLICT')",
            name=op.f("ck_content_review_action_action_type_allowed"),
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_content_review_action_extraction",
        "content_review_action",
        ["extraction_id", "created_at"],
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_content_review_action_review_request",
        "content_review_action",
        ["review_request_id", "created_at"],
        schema=_SCHEMA,
    )

    op.create_table(
        "published_content_version",
        sa.Column("version_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("extraction_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exhibitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("entity_type", sa.String(30), nullable=False),
        sa.Column("entity_reference", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("attribute_code", sa.String(100), nullable=False),
        sa.Column("value", postgresql.JSONB(), nullable=False),
        sa.Column("concept_codes", postgresql.JSONB(), nullable=True),
        sa.Column("visibility", sa.String(30), nullable=False),
        sa.Column("version_no", sa.Integer(), nullable=False),
        sa.Column("published_by_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "published_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("superseded_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["extraction_id"],
            [f"{_SCHEMA}.extracted_attribute.extraction_id"],
            name="fk_published_content_version_extraction",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            ["exhibition.exhibitor.tenant_id", "exhibition.exhibitor.exhibitor_id"],
            name="fk_published_content_version_exhibitor_boundary",
        ),
        sa.UniqueConstraint(
            "extraction_id", "version_no", name="uq_published_content_version_no"
        ),
        sa.CheckConstraint(
            "version_no > 0", name=op.f("ck_published_content_version_version_no_positive")
        ),
        sa.CheckConstraint(
            "visibility IN ('PUBLIC', 'REGISTERED_USER', 'VERIFIED_BUYER', 'MEETING_ACCEPTED', "
            "'OPERATOR_ONLY')",
            name=op.f("ck_published_content_version_visibility_allowed"),
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_published_content_version_entity",
        "published_content_version",
        ["entity_type", "entity_reference", "attribute_code", "superseded_at"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_table("published_content_version", schema=_SCHEMA)
    op.drop_table("content_review_action", schema=_SCHEMA)
    op.drop_table("content_review_request", schema=_SCHEMA)
    op.drop_table("extraction_conflict", schema=_SCHEMA)
    op.drop_table("source_evidence", schema=_SCHEMA)
    op.drop_table("extracted_attribute", schema=_SCHEMA)
    # 스키마 자체는 지우지 않는다 - BACKEND-DOCUMENT 트랙(app/models/document.py)이 이미
    # 같은 스키마를 소유하고 있어, 이 마이그레이션이 만들지 않은 다른 테이블을 함께 날릴 수
    # 있다(0015/0016 downgrade가 각자 소유한 신규 스키마만 지우는 것과 다른 점 - 여기는
    # 스키마를 새로 만든 트랙이 아니라 재사용한 트랙이라 스키마 소유권이 없다).
