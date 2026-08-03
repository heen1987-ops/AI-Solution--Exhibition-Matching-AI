"""create exhibition.kiosk_device/kiosk_config

이 마이그레이션은 `backend/app/models/kiosk.py`를 대상으로 `alembic revision
--autogenerate`를 실행한 결과를 정리한 것이다(0006_matching과 동일한 관례).

근거 문서: `.harness/contracts/domain-model.md` §15(CTR-008 WAVE-1 크로스워크) -
`profile.guest_session`(방문자 세션)과 물리 키오스크 단말기 등록·설정은 서로 다른
개념이라는 것을 확인한 뒤 신설한다. `docs/redesign-v2/kiosk/K-1-service-scope.md` §4
(자동 세션 초기화 유휴시간), `K-6-i18n-accessibility.md` §1(다국어)이 근거다.

Revision ID: 0010_kiosk
Revises: 0009_search
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0010_kiosk"
down_revision: str | None = "0009_search"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "kiosk_device",
        sa.Column("kiosk_device_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("event_zone_id", sa.UUID(), nullable=True),
        sa.Column("device_code", sa.String(length=50), nullable=False),
        sa.Column("hardware_model", sa.String(length=100), nullable=True),
        sa.Column("device_status", sa.String(length=20), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "registered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "device_status IN ('PROVISIONED', 'ACTIVE', 'MAINTENANCE', 'RETIRED')",
            name=op.f("ck_kiosk_device_device_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "event_zone_id"],
            [
                "exhibition.event_zone.tenant_id",
                "exhibition.event_zone.event_id",
                "exhibition.event_zone.event_zone_id",
            ],
            name="fk_kiosk_device_zone_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_kiosk_device_event_boundary",
        ),
        sa.PrimaryKeyConstraint("kiosk_device_id", name=op.f("pk_kiosk_device")),
        sa.UniqueConstraint(
            "tenant_id", "event_id", "device_code", name="uq_kiosk_device_event_code"
        ),
        schema="exhibition",
    )
    op.create_table(
        "kiosk_config",
        sa.Column("kiosk_config_id", sa.UUID(), nullable=False),
        sa.Column("kiosk_device_id", sa.UUID(), nullable=False),
        sa.Column(
            "default_locale",
            sa.String(length=10),
            server_default="ko-KR",
            nullable=False,
        ),
        sa.Column(
            "supported_locales", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "idle_timeout_seconds",
            sa.Integer(),
            server_default="90",
            nullable=False,
        ),
        sa.Column("session_reset_policy", sa.String(length=20), nullable=False),
        sa.Column(
            "feature_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "session_reset_policy IN ('IDLE_TIMEOUT', 'MANUAL_ONLY')",
            name=op.f("ck_kiosk_config_session_reset_policy_allowed"),
        ),
        sa.CheckConstraint(
            "idle_timeout_seconds > 0",
            name=op.f("ck_kiosk_config_idle_timeout_positive"),
        ),
        sa.ForeignKeyConstraint(
            ["kiosk_device_id"],
            ["exhibition.kiosk_device.kiosk_device_id"],
            name=op.f("fk_kiosk_config_kiosk_device_id_kiosk_device"),
        ),
        sa.PrimaryKeyConstraint("kiosk_config_id", name=op.f("pk_kiosk_config")),
        sa.UniqueConstraint("kiosk_device_id", name="uq_kiosk_config_device"),
        schema="exhibition",
    )


def downgrade() -> None:
    op.drop_table("kiosk_config", schema="exhibition")
    op.drop_table("kiosk_device", schema="exhibition")
