"""publish buyer-only matching session/candidate tables (BACKEND-BUYER-MATCH, WAVE 2C)

Revision ID: 0023_buyer_match
Revises: 0022_buyer_profile
Create Date: 2026-08-02

See app/models/buyer_match.py module docstring for why this track publishes a dedicated
matching.buyer_match_session/buyer_match_candidate pair instead of reusing
matching.recommendation_session/match_result - this needs reconciliation with DECISION-005
at integration time.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0023_buyer_match"
down_revision: str | None = "0022_buyer_profile"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "buyer_match_session",
        sa.Column("buyer_match_session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "buyer_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("profile.user_profile.profile_id"),
            nullable=False,
        ),
        sa.Column("profile_version", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.String(100), nullable=False),
        sa.Column("verification_tier", sa.String(20), nullable=False),
        sa.Column("filters_json", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("candidate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("filtered_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("result_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="ACTIVE"),
        sa.Column(
            "generated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_buyer_match_session_event_boundary",
        ),
        sa.CheckConstraint(
            "status IN ('ACTIVE', 'EXPIRED')",
            name=op.f("ck_buyer_match_session_status_allowed"),
        ),
        sa.CheckConstraint(
            "verification_tier IN ('VERIFIED', 'LIMITED')",
            name=op.f("ck_buyer_match_session_verification_tier_allowed"),
        ),
        sa.CheckConstraint(
            "candidate_count >= 0", name=op.f("ck_buyer_match_session_candidate_count_nonneg")
        ),
        sa.CheckConstraint(
            "filtered_count >= 0", name=op.f("ck_buyer_match_session_filtered_count_nonneg")
        ),
        sa.CheckConstraint(
            "result_count >= 0", name=op.f("ck_buyer_match_session_result_count_nonneg")
        ),
        sa.CheckConstraint(
            "profile_version >= 1",
            name=op.f("ck_buyer_match_session_profile_version_positive"),
        ),
        schema="matching",
    )
    op.create_index(
        "ix_buyer_match_session_buyer",
        "buyer_match_session",
        ["buyer_profile_id", "created_at"],
        schema="matching",
    )
    op.create_index(
        "ix_buyer_match_session_tenant_event",
        "buyer_match_session",
        ["tenant_id", "event_id"],
        schema="matching",
    )

    op.create_table(
        "buyer_match_candidate",
        sa.Column("buyer_match_candidate_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "buyer_match_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("matching.buyer_match_session.buyer_match_session_id"),
            nullable=False,
        ),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("exhibitor_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "participation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("exhibition.exhibitor_participation.participation_id"),
            nullable=True,
        ),
        sa.Column("rank", sa.Integer(), nullable=False),
        sa.Column("score", sa.Numeric(5, 4), nullable=False),
        sa.Column("grade", sa.String(20), nullable=False),
        sa.Column("hard_filter_passed", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reason_codes", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column("unknown_fields", postgresql.JSONB(), nullable=False, server_default="[]"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            ["exhibition.exhibitor.tenant_id", "exhibition.exhibitor.exhibitor_id"],
            name="fk_buyer_match_candidate_exhibitor_boundary",
        ),
        sa.UniqueConstraint(
            "buyer_match_session_id", "rank", name="uq_buyer_match_candidate_session_rank"
        ),
        sa.UniqueConstraint(
            "buyer_match_session_id",
            "exhibitor_id",
            name="uq_buyer_match_candidate_session_exhibitor",
        ),
        sa.CheckConstraint("rank > 0", name=op.f("ck_buyer_match_candidate_rank_positive")),
        sa.CheckConstraint(
            "score >= 0 AND score <= 1", name=op.f("ck_buyer_match_candidate_score_range")
        ),
        sa.CheckConstraint(
            "grade IN ('VERY_HIGH', 'HIGH', 'MEDIUM', 'LOW')",
            name=op.f("ck_buyer_match_candidate_grade_allowed"),
        ),
        schema="matching",
    )
    op.create_index(
        "ix_buyer_match_candidate_session_rank",
        "buyer_match_candidate",
        ["buyer_match_session_id", "rank"],
        schema="matching",
    )


def downgrade() -> None:
    op.drop_table("buyer_match_candidate", schema="matching")
    op.drop_table("buyer_match_session", schema="matching")
