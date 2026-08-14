"""Append-only stage-10 hard-filter evaluation records."""

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
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    SCHEMA_CORE,
    SCHEMA_EXHIBITION,
    SCHEMA_MATCHING,
    SCHEMA_PROFILE,
    Base,
)
from app.models.common import new_uuid7


class FilterEvaluation(Base):
    """One immutable eligibility run over a candidate set."""

    __tablename__ = "filter_evaluation"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_filter_evaluation_event_boundary",
        ),
        ForeignKeyConstraint(
            ["profile_id", "profile_version_id"],
            [
                f"{SCHEMA_PROFILE}.profile_version.profile_id",
                f"{SCHEMA_PROFILE}.profile_version.profile_version_id",
            ],
            name="fk_filter_evaluation_profile_version",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "profile_id"],
            [
                f"{SCHEMA_PROFILE}.user_profile.tenant_id",
                f"{SCHEMA_PROFILE}.user_profile.event_id",
                f"{SCHEMA_PROFILE}.user_profile.profile_id",
            ],
            name="fk_filter_evaluation_profile_boundary",
        ),
        CheckConstraint(
            "candidate_count >= 0 AND eligible_count >= 0 AND rejected_count >= 0",
            name="counts_nonnegative",
        ),
        CheckConstraint(
            "candidate_count = eligible_count + rejected_count",
            name="counts_balance",
        ),
        CheckConstraint(
            "evaluation_status IN ('COMPLETED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "completed_at >= started_at",
            name="time_order",
        ),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "request_id",
            name="uq_filter_evaluation_request",
        ),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "filter_evaluation_id",
            name="uq_filter_evaluation_boundary_id",
        ),
        Index(
            "uq_filter_evaluation_idempotency",
            "tenant_id",
            "event_id",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
        Index(
            "ix_filter_evaluation_profile_created",
            "profile_id",
            "created_at",
        ),
        {"schema": SCHEMA_MATCHING},
    )

    filter_evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"),
        nullable=False,
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    profile_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    request_id: Mapped[str] = mapped_column(String(100), nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True)
    filter_policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    context_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_count: Mapped[int] = mapped_column(Integer, nullable=False)
    rejected_count: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="COMPLETED"
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    results: Mapped[list[FilterResult]] = relationship(
        back_populates="evaluation",
        cascade="all, delete-orphan",
    )


class FilterResult(Base):
    """Final pass/fail decision for one candidate in an evaluation."""

    __tablename__ = "filter_result"
    __table_args__ = (
        CheckConstraint(
            "(passed AND filter_code IS NULL) OR "
            "(NOT passed AND filter_code IS NOT NULL)",
            name="pass_code_consistency",
        ),
        UniqueConstraint(
            "filter_evaluation_id",
            "object_type",
            "object_id",
            name="uq_filter_result_candidate",
        ),
        Index("ix_filter_result_code", "filter_code"),
        {"schema": SCHEMA_MATCHING},
    )

    filter_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    filter_evaluation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA_MATCHING}.filter_evaluation.filter_evaluation_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    object_type: Mapped[str] = mapped_column(String(20), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    recommendable_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    passed: Mapped[bool] = mapped_column(Boolean, nullable=False)
    filter_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    details_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    evidence_refs: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    candidate_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )

    evaluation: Mapped[FilterEvaluation] = relationship(back_populates="results")
