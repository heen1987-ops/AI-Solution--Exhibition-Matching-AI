"""Immutable scoring policies and event-specific activation overlays."""

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
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SCHEMA_EXHIBITION, SCHEMA_MATCHING, Base
from app.models.common import new_uuid7


class MatchPolicyVersion(Base):
    """One immutable formula/configuration artifact after publication."""

    __tablename__ = "match_policy_version"
    __table_args__ = (
        UniqueConstraint("policy_type", "version", name="uq_match_policy_type_version"),
        UniqueConstraint("version", name="uq_match_policy_version"),
        UniqueConstraint(
            "match_policy_version_id",
            "policy_type",
            name="uq_match_policy_id_type",
        ),
        CheckConstraint(
            "policy_type IN ('HARD_FILTER', 'CONSUMER_SCORE', 'BUYER_SCORE', "
            "'EXHIBITOR_SCORE', 'RECIPROCAL_SCORE', 'CONTEXT_RERANK', "
            "'SLATE_POLICY')",
            name="policy_type_allowed",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'PUBLISHED', 'RETIRED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "(status = 'DRAFT' AND published_at IS NULL) OR "
            "(status IN ('PUBLISHED', 'RETIRED') AND published_at IS NOT NULL)",
            name="publication_state",
        ),
        CheckConstraint(
            "retired_at IS NULL OR published_at IS NOT NULL",
            name="retirement_requires_publication",
        ),
        {"schema": SCHEMA_MATCHING},
    )

    match_policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    policy_type: Mapped[str] = mapped_column(String(30), nullable=False)
    audience: Mapped[str] = mapped_column(String(30), nullable=False)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    formula_name: Mapped[str] = mapped_column(String(80), nullable=False)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    weights: Mapped[list[MatchWeight]] = relationship(
        back_populates="policy", cascade="all, delete-orphan"
    )
    rules: Mapped[list[FilterRule]] = relationship(
        back_populates="policy", cascade="all, delete-orphan"
    )


class MatchWeight(Base):
    """One named component weight within a policy version."""

    __tablename__ = "match_weight"
    __table_args__ = (
        UniqueConstraint(
            "match_policy_version_id",
            "component",
            name="uq_match_weight_policy_component",
        ),
        CheckConstraint("weight >= 0 AND weight <= 1", name="weight_range"),
        CheckConstraint(
            "min_value IS NULL OR max_value IS NULL OR min_value <= max_value",
            name="min_max_order",
        ),
        {"schema": SCHEMA_MATCHING},
    )

    match_weight_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    match_policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA_MATCHING}.match_policy_version.match_policy_version_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    component: Mapped[str] = mapped_column(String(60), nullable=False)
    weight: Mapped[float] = mapped_column(Numeric(9, 8), nullable=False)
    min_value: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    max_value: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)

    policy: Mapped[MatchPolicyVersion] = relationship(back_populates="weights")


class FilterRule(Base):
    """Versioned hard/soft rule metadata; executable code remains deterministic."""

    __tablename__ = "filter_rule"
    __table_args__ = (
        UniqueConstraint(
            "match_policy_version_id", "rule_code", name="uq_filter_rule_policy_code"
        ),
        UniqueConstraint(
            "match_policy_version_id",
            "evaluation_order",
            name="uq_filter_rule_policy_order",
        ),
        CheckConstraint("rule_kind IN ('HARD', 'SOFT')", name="rule_kind_allowed"),
        CheckConstraint("evaluation_order > 0", name="evaluation_order_positive"),
        {"schema": SCHEMA_MATCHING},
    )

    filter_rule_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    match_policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(
            f"{SCHEMA_MATCHING}.match_policy_version.match_policy_version_id",
            ondelete="CASCADE",
        ),
        nullable=False,
    )
    rule_code: Mapped[str] = mapped_column(String(60), nullable=False)
    evaluation_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    rule_kind: Mapped[str] = mapped_column(String(10), nullable=False)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    policy: Mapped[MatchPolicyVersion] = relationship(back_populates="rules")


class EventPolicyBinding(Base):
    """Mutable event overlay selecting an immutable published policy."""

    __tablename__ = "event_policy_binding"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_event_policy_binding_event_boundary",
        ),
        ForeignKeyConstraint(
            ["match_policy_version_id", "policy_type"],
            [
                f"{SCHEMA_MATCHING}.match_policy_version.match_policy_version_id",
                f"{SCHEMA_MATCHING}.match_policy_version.policy_type",
            ],
            name="fk_event_policy_binding_policy_type",
        ),
        CheckConstraint(
            "deactivated_at IS NULL OR deactivated_at >= activated_at",
            name="activation_time_order",
        ),
        CheckConstraint(
            "(active AND deactivated_at IS NULL) OR "
            "(NOT active AND deactivated_at IS NOT NULL)",
            name="active_state_consistency",
        ),
        Index(
            "uq_event_policy_binding_active",
            "tenant_id",
            "event_id",
            "policy_type",
            unique=True,
            postgresql_where=text("active"),
        ),
        Index(
            "ix_event_policy_binding_history",
            "tenant_id",
            "event_id",
            "policy_type",
            "activated_at",
        ),
        {"schema": SCHEMA_MATCHING},
    )

    event_policy_binding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    policy_type: Mapped[str] = mapped_column(String(30), nullable=False)
    match_policy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    activated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
