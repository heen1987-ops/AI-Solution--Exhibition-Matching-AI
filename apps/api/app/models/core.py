"""Tenant and event boundary models.

The versioned ontology in ``ontology.*`` is the only taxonomy source of truth.
This module deliberately contains no legacy ``exhibition.taxonomy_*`` tables.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, time

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Numeric,
    String,
    Time,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SCHEMA_CORE, SCHEMA_EXHIBITION, SCHEMA_ONTOLOGY, Base
from app.models.common import new_uuid7

# Backward-compatible import for domain modules created before the shared helper.
_new_uuid = new_uuid7


class Tenant(Base):
    """Top-level organizer boundary for all event data."""

    __tablename__ = "tenant"
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE', 'SUSPENDED')", name="status_allowed"),
        {"schema": SCHEMA_CORE},
    )

    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_code: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    tenant_name: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ACTIVE"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    events: Mapped[list[Event]] = relationship(back_populates="tenant")


class Event(Base):
    """Exhibition event and its selected immutable ontology version."""

    __tablename__ = "event"
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_code", name="uq_event_tenant_code"),
        UniqueConstraint("tenant_id", "event_id", name="uq_event_tenant_id_event_id"),
        CheckConstraint("start_date <= end_date", name="start_date_before_end_date"),
        CheckConstraint(
            "event_status IN ('PREPARING', 'OPEN', 'CLOSED')",
            name="event_status_allowed",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    event_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"),
        nullable=False,
    )
    event_code: Mapped[str] = mapped_column(String(50), nullable=False)
    event_name: Mapped[str] = mapped_column(String(200), nullable=False)
    venue_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="Asia/Seoul"
    )
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    event_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PREPARING"
    )
    current_taxonomy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_ONTOLOGY}.taxonomy_version.taxonomy_version_id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    tenant: Mapped[Tenant] = relationship(back_populates="events")
    days: Mapped[list[EventDay]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )
    zones: Mapped[list[EventZone]] = relationship(
        back_populates="event", cascade="all, delete-orphan"
    )


class EventDay(Base):
    """Local operating hours for one event date."""

    __tablename__ = "event_day"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_event_day_event_boundary",
            ondelete="CASCADE",
        ),
        UniqueConstraint("event_id", "event_date", name="uq_event_day_event_date"),
        CheckConstraint(
            "status IN ('PLANNED', 'OPEN', 'CLOSED')", name="status_allowed"
        ),
        CheckConstraint(
            "open_at IS NULL OR close_at IS NULL OR open_at < close_at",
            name="operating_hours_order",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    event_day_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_date: Mapped[date] = mapped_column(Date, nullable=False)
    open_at: Mapped[time | None] = mapped_column(Time(timezone=True), nullable=True)
    close_at: Mapped[time | None] = mapped_column(Time(timezone=True), nullable=True)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PLANNED"
    )

    event: Mapped[Event] = relationship(back_populates="days")


class EventZone(Base):
    """Navigable physical zone within an event."""

    __tablename__ = "event_zone"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_event_zone_event_boundary",
            ondelete="CASCADE",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "parent_zone_id"],
            [
                f"{SCHEMA_EXHIBITION}.event_zone.tenant_id",
                f"{SCHEMA_EXHIBITION}.event_zone.event_id",
                f"{SCHEMA_EXHIBITION}.event_zone.event_zone_id",
            ],
            name="fk_event_zone_parent_same_event",
        ),
        UniqueConstraint(
            "tenant_id", "event_id", "zone_code", name="uq_event_zone_code"
        ),
        UniqueConstraint(
            "tenant_id", "event_id", "event_zone_id", name="uq_event_zone_boundary_id"
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    event_zone_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    zone_code: Mapped[str] = mapped_column(String(50), nullable=False)
    zone_name: Mapped[str] = mapped_column(String(200), nullable=False)
    floor_label: Mapped[str | None] = mapped_column(String(50), nullable=True)
    coordinate_x: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    coordinate_y: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    parent_zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    zone_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    event: Mapped[Event] = relationship(back_populates="zones")
    parent: Mapped[EventZone | None] = relationship(
        remote_side=[tenant_id, event_id, event_zone_id], overlaps="event,zones"
    )
