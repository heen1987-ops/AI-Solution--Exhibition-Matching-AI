"""create interaction-domain meeting tables

이 마이그레이션은 backend/app/models/meeting.py를 대상으로 `alembic revision
--autogenerate`를 실행한 결과를 정리한 것이다 (0006_matching과 같은 이유로 수기 작성 대신
autogenerate + 검토 방식을 택했다).

근거 문서: docs/db-erd-table-spec.md 14절(상담 가능시간과 상담). 대응하는 SQLAlchemy 모델:
backend/app/models/meeting.py (그 파일 docstring에 이 도메인이 왜 지금까지 존재하지
않았는지 - exhibitor.py가 "다른 에이전트가 이미 구현했다"고 잘못 가정하고 있었던 경위 -
정리되어 있다).

autogenerate가 감지했지만 이 마이그레이션에 포함하지 않은 변경 1건
------------------------------------------------------------------
`fk_supply_profile_attribute_concept_code` (exhibition.profile_attribute -> ontology.concept
복합 FK)도 함께 감지됐다. 0006_matching.py에서 이미 같은 이유로 제외한 것과 동일한, 이
파일(interaction 도메인)과 무관한 exhibition 도메인의 기존 갭이다.

Revision ID: 0007_meeting
Revises: 0006_matching
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0007_meeting"
down_revision: str | None = "0006_matching"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "availability_slot",
        sa.Column("availability_slot_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("participation_id", sa.UUID(), nullable=False),
        sa.Column("staff_id", sa.UUID(), nullable=True),
        sa.Column("booth_id", sa.UUID(), nullable=True),
        sa.Column("topic_taxonomy_version_id", sa.UUID(), nullable=True),
        sa.Column("topic_concept_id", sa.UUID(), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.SmallInteger(), nullable=False),
        sa.Column("reserved_count", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.CheckConstraint(
            "status IN ('OPEN', 'FULL', 'BLOCKED')",
            name=op.f("ck_availability_slot_status_allowed"),
        ),
        sa.CheckConstraint(
            "capacity > 0", name=op.f("ck_availability_slot_capacity_positive")
        ),
        sa.CheckConstraint(
            "reserved_count >= 0 AND reserved_count <= capacity",
            name=op.f("ck_availability_slot_reserved_count_within_capacity"),
        ),
        sa.CheckConstraint(
            "start_at < end_at", name=op.f("ck_availability_slot_time_range_order")
        ),
        sa.ForeignKeyConstraint(
            ["booth_id"],
            ["exhibition.booth.booth_id"],
            name=op.f("fk_availability_slot_booth_id_booth"),
        ),
        sa.ForeignKeyConstraint(
            ["participation_id"],
            ["exhibition.exhibitor_participation.participation_id"],
            name=op.f("fk_availability_slot_participation_id_exhibitor_participation"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["exhibition.exhibitor_staff.staff_id"],
            name=op.f("fk_availability_slot_staff_id_exhibitor_staff"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_availability_slot_event_boundary",
        ),
        sa.PrimaryKeyConstraint(
            "availability_slot_id", name=op.f("pk_availability_slot")
        ),
        schema="interaction",
    )
    op.create_index(
        "idx_availability_slot_participation_time",
        "availability_slot",
        ["participation_id", "start_at"],
        unique=False,
        schema="interaction",
    )
    op.create_index(
        "idx_availability_slot_staff_time",
        "availability_slot",
        ["staff_id", "start_at"],
        unique=False,
        schema="interaction",
    )

    op.create_table(
        "meeting",
        sa.Column("meeting_id", sa.UUID(), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("buyer_profile_id", sa.UUID(), nullable=False),
        sa.Column("participation_id", sa.UUID(), nullable=False),
        sa.Column("staff_id", sa.UUID(), nullable=True),
        sa.Column("booth_id", sa.UUID(), nullable=True),
        sa.Column("topic_taxonomy_version_id", sa.UUID(), nullable=True),
        sa.Column("topic_concept_id", sa.UUID(), nullable=True),
        sa.Column("message_enc", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(length=30), nullable=False),
        sa.Column("confirmed_slot_id", sa.UUID(), nullable=True),
        sa.Column("confirmed_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column("match_result_id", sa.UUID(), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('REQUESTED', 'VIEWED', 'COUNTER_PROPOSED', 'CONFIRMED', "
            "'COMPLETED', 'FOLLOW_UP', 'REJECTED', 'CANCELLED_BY_BUYER', "
            "'CANCELLED_BY_EXHIBITOR', 'NO_SHOW')",
            name=op.f("ck_meeting_status_allowed"),
        ),
        sa.CheckConstraint(
            "confirmed_start IS NULL OR confirmed_end IS NULL "
            "OR confirmed_start < confirmed_end",
            name=op.f("ck_meeting_confirmed_range_order"),
        ),
        sa.ForeignKeyConstraint(
            ["booth_id"],
            ["exhibition.booth.booth_id"],
            name=op.f("fk_meeting_booth_id_booth"),
        ),
        sa.ForeignKeyConstraint(
            ["buyer_profile_id"],
            ["profile.user_profile.profile_id"],
            name=op.f("fk_meeting_buyer_profile_id_user_profile"),
        ),
        sa.ForeignKeyConstraint(
            ["confirmed_slot_id"],
            ["interaction.availability_slot.availability_slot_id"],
            name=op.f("fk_meeting_confirmed_slot_id_availability_slot"),
        ),
        sa.ForeignKeyConstraint(
            ["match_result_id"],
            ["matching.match_result.match_result_id"],
            name=op.f("fk_meeting_match_result_id_match_result"),
        ),
        sa.ForeignKeyConstraint(
            ["participation_id"],
            ["exhibition.exhibitor_participation.participation_id"],
            name=op.f("fk_meeting_participation_id_exhibitor_participation"),
        ),
        sa.ForeignKeyConstraint(
            ["staff_id"],
            ["exhibition.exhibitor_staff.staff_id"],
            name=op.f("fk_meeting_staff_id_exhibitor_staff"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_meeting_event_boundary",
        ),
        sa.PrimaryKeyConstraint("meeting_id", name=op.f("pk_meeting")),
        schema="interaction",
    )
    op.create_index(
        "idx_meeting_buyer_time",
        "meeting",
        ["buyer_profile_id", "confirmed_start"],
        unique=False,
        schema="interaction",
    )
    op.create_index(
        "idx_meeting_staff_time",
        "meeting",
        ["staff_id", "confirmed_start"],
        unique=False,
        schema="interaction",
    )

    op.create_table(
        "follow_up_action",
        sa.Column("follow_up_action_id", sa.UUID(), nullable=False),
        sa.Column("meeting_id", sa.UUID(), nullable=False),
        sa.Column("action_code", sa.String(length=50), nullable=False),
        sa.Column("owner_user_id", sa.UUID(), nullable=True),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('OPEN', 'DONE', 'CANCELLED')",
            name=op.f("ck_follow_up_action_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["interaction.meeting.meeting_id"],
            name=op.f("fk_follow_up_action_meeting_id_meeting"),
        ),
        sa.ForeignKeyConstraint(
            ["owner_user_id"],
            ["profile.user_account.user_id"],
            name=op.f("fk_follow_up_action_owner_user_id_user_account"),
        ),
        sa.PrimaryKeyConstraint(
            "follow_up_action_id", name=op.f("pk_follow_up_action")
        ),
        schema="interaction",
    )
    op.create_index(
        "idx_follow_up_action_meeting",
        "follow_up_action",
        ["meeting_id", "status"],
        unique=False,
        schema="interaction",
    )

    op.create_table(
        "meeting_contact_share",
        sa.Column("meeting_contact_share_id", sa.UUID(), nullable=False),
        sa.Column("meeting_id", sa.UUID(), nullable=False),
        sa.Column("consent_policy_id", sa.UUID(), nullable=True),
        sa.Column(
            "shared_fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False
        ),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disclosed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("disclosed_to_user_id", sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(
            ["consent_policy_id"],
            ["profile.consent_policy.consent_policy_id"],
            name=op.f("fk_meeting_contact_share_consent_policy_id_consent_policy"),
        ),
        sa.ForeignKeyConstraint(
            ["disclosed_to_user_id"],
            ["profile.user_account.user_id"],
            name=op.f("fk_meeting_contact_share_disclosed_to_user_id_user_account"),
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["interaction.meeting.meeting_id"],
            name=op.f("fk_meeting_contact_share_meeting_id_meeting"),
        ),
        sa.PrimaryKeyConstraint(
            "meeting_contact_share_id", name=op.f("pk_meeting_contact_share")
        ),
        sa.UniqueConstraint(
            "meeting_id", name=op.f("uq_meeting_contact_share_meeting_id")
        ),
        schema="interaction",
    )

    op.create_table(
        "meeting_outcome",
        sa.Column("meeting_id", sa.UUID(), nullable=False),
        sa.Column("lead_status", sa.String(length=20), nullable=False),
        sa.Column("outcome_code", sa.String(length=50), nullable=True),
        sa.Column(
            "estimated_value_amount", sa.Numeric(precision=14, scale=0), nullable=True
        ),
        sa.Column(
            "estimated_probability", sa.Numeric(precision=5, scale=2), nullable=True
        ),
        sa.Column("notes_enc", sa.LargeBinary(), nullable=True),
        sa.Column(
            "completed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "lead_status IN ('QUALIFIED', 'UNQUALIFIED')",
            name=op.f("ck_meeting_outcome_lead_status_allowed"),
        ),
        sa.CheckConstraint(
            "estimated_probability IS NULL OR "
            "(estimated_probability >= 0 AND estimated_probability <= 100)",
            name=op.f("ck_meeting_outcome_estimated_probability_range"),
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["interaction.meeting.meeting_id"],
            name=op.f("fk_meeting_outcome_meeting_id_meeting"),
        ),
        sa.PrimaryKeyConstraint("meeting_id", name=op.f("pk_meeting_outcome")),
        schema="interaction",
    )

    op.create_table(
        "meeting_slot_request",
        sa.Column("meeting_slot_request_id", sa.UUID(), nullable=False),
        sa.Column("meeting_id", sa.UUID(), nullable=False),
        sa.Column("availability_slot_id", sa.UUID(), nullable=False),
        sa.Column("preference_order", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column(
            "snapshot_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('REQUESTED', 'ACCEPTED', 'REJECTED')",
            name=op.f("ck_meeting_slot_request_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["availability_slot_id"],
            ["interaction.availability_slot.availability_slot_id"],
            name=op.f("fk_meeting_slot_request_availability_slot_id_availability_slot"),
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["interaction.meeting.meeting_id"],
            name=op.f("fk_meeting_slot_request_meeting_id_meeting"),
        ),
        sa.PrimaryKeyConstraint(
            "meeting_slot_request_id", name=op.f("pk_meeting_slot_request")
        ),
        sa.UniqueConstraint(
            "meeting_id",
            "availability_slot_id",
            name="uq_meeting_slot_request_meeting_slot",
        ),
        schema="interaction",
    )

    op.create_table(
        "meeting_status_history",
        sa.Column("meeting_status_history_id", sa.UUID(), nullable=False),
        sa.Column("meeting_id", sa.UUID(), nullable=False),
        sa.Column("previous_status", sa.String(length=30), nullable=True),
        sa.Column("new_status", sa.String(length=30), nullable=False),
        sa.Column("changed_by", sa.UUID(), nullable=True),
        sa.Column("reason_code", sa.String(length=50), nullable=True),
        sa.Column("request_id", sa.UUID(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "new_status IN ('REQUESTED', 'VIEWED', 'COUNTER_PROPOSED', 'CONFIRMED', "
            "'COMPLETED', 'FOLLOW_UP', 'REJECTED', 'CANCELLED_BY_BUYER', "
            "'CANCELLED_BY_EXHIBITOR', 'NO_SHOW')",
            name=op.f("ck_meeting_status_history_new_status_allowed"),
        ),
        sa.CheckConstraint(
            "previous_status IS NULL OR previous_status IN ('REQUESTED', 'VIEWED', "
            "'COUNTER_PROPOSED', 'CONFIRMED', 'COMPLETED', 'FOLLOW_UP', 'REJECTED', "
            "'CANCELLED_BY_BUYER', 'CANCELLED_BY_EXHIBITOR', 'NO_SHOW')",
            name=op.f("ck_meeting_status_history_previous_status_allowed"),
        ),
        sa.ForeignKeyConstraint(
            ["changed_by"],
            ["profile.user_account.user_id"],
            name=op.f("fk_meeting_status_history_changed_by_user_account"),
        ),
        sa.ForeignKeyConstraint(
            ["meeting_id"],
            ["interaction.meeting.meeting_id"],
            name=op.f("fk_meeting_status_history_meeting_id_meeting"),
        ),
        sa.PrimaryKeyConstraint(
            "meeting_status_history_id", name=op.f("pk_meeting_status_history")
        ),
        schema="interaction",
    )
    op.create_index(
        "idx_meeting_status_history_meeting",
        "meeting_status_history",
        ["meeting_id", "created_at"],
        unique=False,
        schema="interaction",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_meeting_status_history_meeting",
        table_name="meeting_status_history",
        schema="interaction",
    )
    op.drop_table("meeting_status_history", schema="interaction")
    op.drop_table("meeting_slot_request", schema="interaction")
    op.drop_table("meeting_outcome", schema="interaction")
    op.drop_table("meeting_contact_share", schema="interaction")
    op.drop_index(
        "idx_follow_up_action_meeting",
        table_name="follow_up_action",
        schema="interaction",
    )
    op.drop_table("follow_up_action", schema="interaction")
    op.drop_index("idx_meeting_staff_time", table_name="meeting", schema="interaction")
    op.drop_index("idx_meeting_buyer_time", table_name="meeting", schema="interaction")
    op.drop_table("meeting", schema="interaction")
    op.drop_index(
        "idx_availability_slot_staff_time",
        table_name="availability_slot",
        schema="interaction",
    )
    op.drop_index(
        "idx_availability_slot_participation_time",
        table_name="availability_slot",
        schema="interaction",
    )
    op.drop_table("availability_slot", schema="interaction")
