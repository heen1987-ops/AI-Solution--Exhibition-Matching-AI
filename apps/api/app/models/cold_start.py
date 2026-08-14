"""Stage-16 cold-start state, questions, priors and exploration outcomes."""

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
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_MATCHING, Base
from app.models.common import new_uuid7


class ColdStartStatus(Base):
    """Append-only evaluation history; latest evaluated_at is current state."""

    __tablename__ = "cold_start_status"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_cold_start_status_event_boundary",
        ),
        CheckConstraint(
            "object_type IN ('USER', 'BUYER', 'EXHIBITOR', 'PRODUCT', 'PROGRAM')",
            name="object_type_allowed",
        ),
        CheckConstraint(
            "status IN ('COLD', 'WARMING', 'STABLE', 'RESET')",
            name="status_allowed",
        ),
        CheckConstraint(
            "stability_score >= 0 AND stability_score <= 1",
            name="stability_score_range",
        ),
        CheckConstraint(
            "profile_completeness >= 0 AND profile_completeness <= 100",
            name="profile_completeness_range",
        ),
        Index(
            "ix_cold_start_status_current",
            "tenant_id",
            "event_id",
            "object_type",
            "object_id",
            "evaluated_at",
        ),
        {"schema": SCHEMA_MATCHING},
    )

    cold_start_status_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_type: Mapped[str] = mapped_column(String(20), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    cold_start_type: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    previous_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    stability_score: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    signal_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    profile_completeness: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False
    )
    match_policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matching.match_policy_version.match_policy_version_id"),
        nullable=False,
    )
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    details_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    transitioned_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class QuestionDefinition(Base):
    __tablename__ = "question_definition"
    __table_args__ = (
        CheckConstraint(
            "user_type IN ('GENERAL_VISITOR', 'BUYER')", name="user_type_allowed"
        ),
        CheckConstraint("base_priority > 0", name="base_priority_positive"),
        {"schema": SCHEMA_MATCHING},
    )

    question_id: Mapped[str] = mapped_column(String(60), primary_key=True)
    user_type: Mapped[str] = mapped_column(String(30), nullable=False)
    attribute_code: Mapped[str] = mapped_column(String(100), nullable=False)
    question_text: Mapped[str] = mapped_column(String(500), nullable=False)
    option_json: Mapped[list] = mapped_column(JSONB, nullable=False)
    required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    base_priority: Mapped[int] = mapped_column(Integer, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    definition_version: Mapped[str] = mapped_column(String(30), nullable=False)


class QuestionResponse(Base):
    __tablename__ = "question_response"
    __table_args__ = (
        CheckConstraint(
            "response_source IN ('MINIMUM_PROFILE', 'NEXT_BEST_QUESTION', 'PAIRWISE')",
            name="response_source_allowed",
        ),
        CheckConstraint(
            "information_gain IS NULL OR (information_gain >= 0 AND information_gain <= 1)",
            name="information_gain_range",
        ),
        Index("ix_question_response_profile_time", "profile_id", "responded_at"),
        {"schema": SCHEMA_MATCHING},
    )

    response_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profile.user_profile.profile_id"), nullable=False
    )
    question_id: Mapped[str] = mapped_column(
        String(60), ForeignKey("matching.question_definition.question_id"), nullable=False
    )
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    answer_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    response_source: Mapped[str] = mapped_column(String(30), nullable=False)
    information_gain: Mapped[float | None] = mapped_column(
        Numeric(7, 6), nullable=True
    )
    responded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class ColdStartPrior(Base):
    __tablename__ = "cold_start_prior"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "group_type",
            "group_key",
            "metric_code",
            "model_version",
            name="uq_cold_start_prior_versioned_group",
        ),
        CheckConstraint("prior_mean >= 0 AND prior_mean <= 1", name="prior_mean_range"),
        CheckConstraint("prior_count >= 1", name="prior_count_positive"),
        CheckConstraint(
            "valid_until IS NULL OR valid_from <= valid_until", name="valid_period_order"
        ),
        {"schema": SCHEMA_MATCHING},
    )

    prior_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    group_type: Mapped[str] = mapped_column(String(40), nullable=False)
    group_key: Mapped[str] = mapped_column(String(200), nullable=False)
    metric_code: Mapped[str] = mapped_column(String(60), nullable=False)
    prior_mean: Mapped[float] = mapped_column(Numeric(9, 8), nullable=False)
    prior_count: Mapped[float] = mapped_column(Numeric(12, 3), nullable=False)
    model_version: Mapped[str] = mapped_column(String(40), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ExplorationResult(Base):
    __tablename__ = "exploration_result"
    __table_args__ = (
        CheckConstraint("slot_type IN ('NEW', 'PREFERENCE_LEARNING')", name="slot_type_allowed"),
        CheckConstraint("prior_score >= 0 AND prior_score <= 1", name="prior_score_range"),
        CheckConstraint("reward_value >= -1 AND reward_value <= 1", name="reward_value_range"),
        Index("ix_exploration_result_object_time", "object_type", "object_id", "occurred_at"),
        {"schema": SCHEMA_MATCHING},
    )

    exploration_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    object_type: Mapped[str] = mapped_column(String(20), nullable=False)
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profile.user_profile.profile_id"), nullable=False
    )
    recommendation_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("matching.recommendation_session.recommendation_session_id"), nullable=True
    )
    slot_type: Mapped[str] = mapped_column(String(30), nullable=False)
    prior_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("matching.cold_start_prior.prior_id"), nullable=True
    )
    prior_score: Mapped[float] = mapped_column(Numeric(9, 8), nullable=False)
    observed_event: Mapped[str | None] = mapped_column(String(60), nullable=True)
    reward_value: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False, default=0)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
