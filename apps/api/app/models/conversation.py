"""Stage-19 privacy-minimized conversation and extraction ledger."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Numeric,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_CONVERSATION, Base
from app.models.common import new_uuid7


class ConversationSession(Base):
    __tablename__ = "conversation_session"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "profile_id"],
            [
                "profile.user_profile.tenant_id",
                "profile.user_profile.event_id",
                "profile.user_profile.profile_id",
            ],
            name="fk_conversation_session_profile_boundary",
        ),
        CheckConstraint(
            "user_type IN ('GENERAL_VISITOR', 'BUYER')",
            name="user_type_allowed",
        ),
        CheckConstraint(
            "status IN ('ACTIVE', 'COMPLETED', 'EXPIRED', 'CANCELLED')",
            name="status_allowed",
        ),
        Index(
            "ix_conversation_session_profile_status",
            "profile_id",
            "status",
            "last_activity_at",
        ),
        {"schema": SCHEMA_CONVERSATION},
    )

    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    profile_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    visit_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.visit_session.visit_session_id"),
        nullable=True,
    )
    user_type: Mapped[str] = mapped_column(String(30), nullable=False)
    language: Mapped[str] = mapped_column(String(10), nullable=False, default="ko")
    dialog_state: Mapped[str] = mapped_column(
        String(40), nullable=False, default="COLLECT_GOAL"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    state_json: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    last_activity_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class ConversationMessage(Base):
    __tablename__ = "message"
    __table_args__ = (
        CheckConstraint(
            "sender_type IN ('USER', 'ASSISTANT', 'SYSTEM')",
            name="sender_type_allowed",
        ),
        Index("ix_conversation_message_order", "conversation_id", "created_at"),
        {"schema": SCHEMA_CONVERSATION},
    )

    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation.conversation_session.conversation_id"),
        nullable=False,
    )
    sender_type: Mapped[str] = mapped_column(String(20), nullable=False)
    masked_text: Mapped[str] = mapped_column(String(2000), nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    message_type: Mapped[str] = mapped_column(
        String(20), nullable=False, default="TEXT"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EntityExtraction(Base):
    __tablename__ = "entity_extraction"
    __table_args__ = (
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "status IN ('PROPOSED', 'CONFIRMED', 'REJECTED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "requirement_level IN ('REQUIRED', 'PREFERRED', 'ACCEPTABLE', 'EXCLUDED')",
            name="requirement_level_allowed",
        ),
        Index("ix_entity_extraction_message", "message_id", "status"),
        {"schema": SCHEMA_CONVERSATION},
    )

    extraction_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    message_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("conversation.message.message_id"),
        nullable=False,
    )
    attribute_code: Mapped[str] = mapped_column(String(100), nullable=False)
    operator_code: Mapped[str] = mapped_column(String(40), nullable=False)
    value_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    unit_code: Mapped[str | None] = mapped_column(String(20), nullable=True)
    requirement_level: Mapped[str] = mapped_column(String(20), nullable=False)
    source_text: Mapped[str] = mapped_column(String(300), nullable=False)
    confidence: Mapped[float] = mapped_column(Numeric(7, 6), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    input_fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    applied_profile_attribute_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.profile_attribute.profile_attribute_id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    decided_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
