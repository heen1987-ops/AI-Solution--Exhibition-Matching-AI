"""publish interaction.route / route_item / indoor_checkpoint_scan (U-13 AI 추천 방문 동선)

Revision ID: 0032_route_positioning
Revises: 0031_integration_source_sync
Create Date: 2026-08-12

app/models/route.py와 app/models/indoor_positioning.py가 선언한 세 테이블을 그대로 옮긴다
(app/db/base.py NAMING_CONVENTION 없이 순수 MetaData로 ``op.create_table``을 쓰므로 모든
제약 이름을 직접 명시한다 - 이 리포지토리의 기존 관례, 예: 20260803_0031과 동일).

``interaction`` 스키마는 이미 0001_create_schemas에서 만들어졌으므로 여기서는 스키마를
새로 만들지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0032_route_positioning"
down_revision: str | None = "0031_integration_source_sync"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SCHEMA = "interaction"

# app/models/route.py의 상수를 그대로 옮긴다 - 마이그레이션은 적용 당시 스키마를 기록하며
# 이후 모델 파일 수정을 따라가지 않는다 (이 리포지토리 전체 관례).
_ROUTE_STATUSES = ("ACTIVE", "COMPLETED", "CANCELLED")
_ROUTE_ITEM_STATUSES = ("PENDING", "ARRIVED", "SKIPPED", "COMPLETED")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "route",
        sa.Column("route_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("route_preference", sa.String(30), nullable=True),
        sa.Column("total_minutes", sa.Integer(), nullable=True),
        sa.Column("walking_minutes", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column("context_snapshot", postgresql.JSONB(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("row_version", sa.Integer(), nullable=False, server_default="1"),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["core.tenant.tenant_id"],
            name="fk_route_tenant_id_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_route_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "visit_session_id"],
            [
                "profile.visit_session.tenant_id",
                "profile.visit_session.event_id",
                "profile.visit_session.visit_session_id",
            ],
            name="fk_route_visit_session_boundary",
        ),
        sa.CheckConstraint(
            f"status IN ({_in_list(_ROUTE_STATUSES)})", name=op.f("ck_route_status_allowed")
        ),
        sa.CheckConstraint(
            "total_minutes IS NULL OR total_minutes >= 0",
            name=op.f("ck_route_total_minutes_nonneg"),
        ),
        sa.CheckConstraint(
            "walking_minutes IS NULL OR walking_minutes >= 0",
            name=op.f("ck_route_walking_minutes_nonneg"),
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_route_visit_session_status",
        "route",
        ["visit_session_id", "status"],
        schema=_SCHEMA,
    )

    op.create_table(
        "route_item",
        sa.Column("route_item_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("route_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("recommendable_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("meeting_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expected_arrival_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("expected_stay_minutes", sa.Integer(), nullable=True),
        sa.Column("actual_arrival_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["route_id"],
            ["interaction.route.route_id"],
            name="fk_route_item_route_id_route",
        ),
        sa.ForeignKeyConstraint(
            ["recommendable_id"],
            ["exhibition.recommendable.recommendable_id"],
            name="fk_route_item_recommendable_id_recommendable",
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["interaction.meeting.meeting_id"],
            name="fk_route_item_meeting_id_meeting",
        ),
        sa.UniqueConstraint(
            "route_id", "sequence", name="uq_route_item_route_sequence"
        ),
        sa.CheckConstraint(
            "num_nonnulls(recommendable_id, meeting_id) = 1",
            name=op.f("ck_route_item_exactly_one_target"),
        ),
        sa.CheckConstraint(
            f"status IN ({_in_list(_ROUTE_ITEM_STATUSES)})",
            name=op.f("ck_route_item_status_allowed"),
        ),
        sa.CheckConstraint(
            "expected_stay_minutes IS NULL OR expected_stay_minutes >= 0",
            name=op.f("ck_route_item_expected_stay_minutes_nonneg"),
        ),
        sa.CheckConstraint(
            "sequence >= 0", name=op.f("ck_route_item_sequence_nonneg")
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_route_item_route_sequence",
        "route_item",
        ["route_id", "sequence"],
        schema=_SCHEMA,
    )

    op.create_table(
        "indoor_checkpoint_scan",
        sa.Column("indoor_checkpoint_scan_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("visit_session_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("booth_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("booth_qr_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "scanned_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id"],
            ["core.tenant.tenant_id"],
            name="fk_indoor_checkpoint_scan_tenant_id_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_indoor_checkpoint_scan_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "visit_session_id"],
            [
                "profile.visit_session.tenant_id",
                "profile.visit_session.event_id",
                "profile.visit_session.visit_session_id",
            ],
            name="fk_indoor_checkpoint_scan_visit_session_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["booth_id"],
            ["exhibition.booth.booth_id"],
            name="fk_indoor_checkpoint_scan_booth_id_booth",
        ),
        sa.ForeignKeyConstraint(
            ["booth_qr_id"],
            ["exhibition.booth_qr.booth_qr_id"],
            name="fk_indoor_checkpoint_scan_booth_qr_id_booth_qr",
        ),
        schema=_SCHEMA,
    )
    op.create_index(
        "ix_indoor_checkpoint_scan_visit_session_scanned",
        "indoor_checkpoint_scan",
        ["visit_session_id", "scanned_at"],
        schema=_SCHEMA,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_indoor_checkpoint_scan_visit_session_scanned",
        table_name="indoor_checkpoint_scan",
        schema=_SCHEMA,
    )
    op.drop_table("indoor_checkpoint_scan", schema=_SCHEMA)

    op.drop_index("ix_route_item_route_sequence", table_name="route_item", schema=_SCHEMA)
    op.drop_table("route_item", schema=_SCHEMA)

    op.drop_index(
        "ix_route_visit_session_status", table_name="route", schema=_SCHEMA
    )
    op.drop_table("route", schema=_SCHEMA)
