"""AI model registry and append-only validated execution records."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    LargeBinary,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_AI, SCHEMA_EXHIBITION, Base
from app.models.common import new_uuid7


class ModelVersion(Base):
    """Provider-neutral immutable model/deployment configuration."""

    __tablename__ = "model_version"
    __table_args__ = (
        UniqueConstraint("model_type", "version", name="uq_model_version_type_version"),
        CheckConstraint(
            "model_type IN ('RANKING', 'EXPLANATION', 'EXTRACTION', 'EMBEDDING')",
            name="model_type_allowed",
        ),
        CheckConstraint(
            "status IN ('DRAFT', 'DEPLOYED', 'RETIRED')",
            name="status_allowed",
        ),
        CheckConstraint(
            "(status = 'DRAFT' AND deployed_at IS NULL) OR "
            "(status IN ('DEPLOYED', 'RETIRED') AND deployed_at IS NOT NULL)",
            name="deployment_state",
        ),
        CheckConstraint(
            "retired_at IS NULL OR deployed_at IS NOT NULL",
            name="retirement_requires_deployment",
        ),
        {"schema": SCHEMA_AI},
    )

    model_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    model_type: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str] = mapped_column(String(30), nullable=False)
    model_name: Mapped[str] = mapped_column(String(120), nullable=False)
    provider_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    version: Mapped[str] = mapped_column(String(80), nullable=False)
    gateway_adapter: Mapped[str | None] = mapped_column(String(50), nullable=True)
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    config_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="DRAFT")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    deployed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    retired_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )


class AiRun(Base):
    """One append-only AI invocation containing only validated safe output."""

    __tablename__ = "ai_run"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_ai_run_event_boundary",
        ),
        CheckConstraint(
            "task_type IN ('ATTRIBUTE_EXTRACTION', 'EXPLANATION', 'EMBEDDING')",
            name="task_type_allowed",
        ),
        CheckConstraint(
            "validation_status IN ('VALID', 'INVALID', 'REVIEW', 'FAILED')",
            name="validation_status_allowed",
        ),
        CheckConstraint(
            "latency_ms IS NULL OR latency_ms >= 0", name="latency_nonnegative"
        ),
        CheckConstraint(
            "token_input IS NULL OR token_input >= 0", name="token_input_nonnegative"
        ),
        CheckConstraint(
            "token_output IS NULL OR token_output >= 0",
            name="token_output_nonnegative",
        ),
        CheckConstraint(
            "estimated_cost IS NULL OR estimated_cost >= 0",
            name="estimated_cost_nonnegative",
        ),
        {"schema": SCHEMA_AI},
    )

    ai_run_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    model_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_AI}.model_version.model_version_id"),
        nullable=False,
    )
    task_type: Mapped[str] = mapped_column(String(30), nullable=False)
    input_reference_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    input_reference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    input_hash: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(30), nullable=False)
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    validated_output_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    validation_status: Mapped[str] = mapped_column(String(20), nullable=False)
    latency_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_input: Mapped[int | None] = mapped_column(Integer, nullable=True)
    token_output: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimated_cost: Mapped[float | None] = mapped_column(Numeric(14, 6), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
