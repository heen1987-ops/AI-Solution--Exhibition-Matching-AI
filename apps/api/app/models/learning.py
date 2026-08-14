"""Stage-17 append-only behavior evidence and reversible profile inference."""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
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

from app.db.base import SCHEMA_LEARNING, SCHEMA_PROFILE, Base
from app.models.common import new_uuid7


class BehaviorSignal(Base):
    __tablename__ = "behavior_signal"
    __table_args__ = (
        ForeignKeyConstraint(
            ["event_date", "event_log_id"],
            ["interaction.interaction_event.event_date", "interaction.interaction_event.interaction_event_id"],
            name="fk_behavior_signal_event",
        ),
        UniqueConstraint("event_date", "event_log_id", name="uq_behavior_signal_event"),
        CheckConstraint("signal_type IN ('POSITIVE', 'NEGATIVE', 'NEUTRAL')", name="signal_type_allowed"),
        CheckConstraint("signal_strength >= -1 AND signal_strength <= 1", name="signal_strength_range"),
        CheckConstraint("decayed_signal >= -1 AND decayed_signal <= 1", name="decayed_signal_range"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("validation_status IN ('VALID', 'INVALID')", name="validation_status_allowed"),
        Index("ix_behavior_signal_profile_time", "profile_id", "processed_at"),
        {"schema": SCHEMA_LEARNING},
    )

    behavior_signal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid7)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_log_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profile.user_profile.profile_id"), nullable=False)
    match_policy_version_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("matching.match_policy_version.match_policy_version_id"), nullable=False)
    signal_type: Mapped[str] = mapped_column(String(10), nullable=False)
    signal_strength: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    decayed_signal: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    cause_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    cause_scope: Mapped[str] = mapped_column(String(40), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    validation_status: Mapped[str] = mapped_column(String(10), nullable=False)
    invalid_reason_codes: Mapped[list] = mapped_column(JSONB, nullable=False, default=list)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    processed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class AttributeEvidence(Base):
    __tablename__ = "attribute_evidence"
    __table_args__ = (
        CheckConstraint("propagation_weight >= 0 AND propagation_weight <= 1", name="propagation_weight_range"),
        CheckConstraint("decayed_value >= -1 AND decayed_value <= 1", name="decayed_value_range"),
        Index("ix_attribute_evidence_code_time", "attribute_code", "created_at"),
        {"schema": SCHEMA_LEARNING},
    )

    attribute_evidence_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid7)
    behavior_signal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("learning.behavior_signal.behavior_signal_id"), nullable=False)
    attribute_code: Mapped[str] = mapped_column(String(100), nullable=False)
    target_level: Mapped[str] = mapped_column(String(30), nullable=False)
    propagation_weight: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    decayed_value: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    positive: Mapped[bool] = mapped_column(Boolean, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ProfileAdjustment(Base):
    __tablename__ = "profile_adjustment"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("application_status IN ('APPLIED', 'CONFIRMATION_REQUIRED', 'SKIPPED')", name="application_status_allowed"),
        Index("ix_profile_adjustment_profile_time", "profile_id", "created_at"),
        {"schema": SCHEMA_LEARNING},
    )

    profile_adjustment_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid7)
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profile.user_profile.profile_id"), nullable=False)
    attribute_code: Mapped[str] = mapped_column(String(100), nullable=False)
    previous_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    adjustment_value: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    new_value: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_reference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    application_status: Mapped[str] = mapped_column(String(30), nullable=False)
    applied: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class FeedbackReason(Base):
    __tablename__ = "feedback_reason"
    __table_args__ = (
        CheckConstraint("sentiment IN ('POSITIVE', 'NEGATIVE', 'NEUTRAL')", name="sentiment_allowed"),
        CheckConstraint("intensity >= 0 AND intensity <= 1", name="intensity_range"),
        CheckConstraint("source IN ('USER', 'RULE', 'AI')", name="source_allowed"),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        {"schema": SCHEMA_LEARNING},
    )

    feedback_reason_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid7)
    behavior_signal_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("learning.behavior_signal.behavior_signal_id"), nullable=False)
    reason_code: Mapped[str] = mapped_column(String(60), nullable=False)
    sentiment: Mapped[str] = mapped_column(String(10), nullable=False)
    intensity: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    source: Mapped[str] = mapped_column(String(10), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())


class ModelReward(Base):
    __tablename__ = "model_reward"
    __table_args__ = (
        CheckConstraint("raw_reward >= -1 AND raw_reward <= 1", name="raw_reward_range"),
        CheckConstraint("adjusted_reward >= -1 AND adjusted_reward <= 1", name="adjusted_reward_range"),
        CheckConstraint("position_adjustment > 0", name="position_adjustment_positive"),
        Index("ix_model_reward_session_time", "recommendation_session_id", "occurred_at"),
        {"schema": SCHEMA_LEARNING},
    )

    reward_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid7)
    recommendation_session_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("matching.recommendation_session.recommendation_session_id"), nullable=False)
    match_result_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("matching.match_result.match_result_id"), nullable=False)
    reward_type: Mapped[str] = mapped_column(String(40), nullable=False)
    raw_reward: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    adjusted_reward: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    position_adjustment: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    valid: Mapped[bool] = mapped_column(Boolean, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class ProfileInference(Base):
    __tablename__ = "inference"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint("evidence_count >= 0", name="evidence_count_nonneg"),
        CheckConstraint("status IN ('CANDIDATE', 'APPLIED', 'CONFIRMED', 'DELETED')", name="status_allowed"),
        Index("ix_profile_inference_profile_status", "profile_id", "status"),
        {"schema": SCHEMA_PROFILE},
    )

    inference_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=new_uuid7)
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey("profile.user_profile.profile_id"), nullable=False)
    attribute_code: Mapped[str] = mapped_column(String(100), nullable=False)
    inferred_value: Mapped[dict] = mapped_column(JSONB, nullable=False)
    condition_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    confidence: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    evidence_count: Mapped[int] = mapped_column(Integer, nullable=False)
    first_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_observed_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    user_confirmed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    source_policy_version: Mapped[str] = mapped_column(String(40), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
