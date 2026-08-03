"""create profile.saved_recommendable

근거 문서: `.harness/contracts/domain-model.md` §4, `docs/redesign-v2/web/
W-8-api-and-db-changes.md` §4. 관심 업체 저장은 지속 프로파일을 가진 사전등록 사용자
전용 기능이며, 중복 저장은 UNIQUE(profile_id, recommendable_id)로 막는다.

Revision ID: 0011_saved_recommendable
Revises: 0010_kiosk
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0011_saved_recommendable"
down_revision: str | None = "0010_kiosk"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "saved_recommendable",
        sa.Column("saved_recommendable_id", sa.UUID(), nullable=False),
        sa.Column("profile_id", sa.UUID(), nullable=False),
        sa.Column("recommendable_id", sa.UUID(), nullable=False),
        sa.Column(
            "saved_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "saved_context_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["profile.user_profile.profile_id"],
            name=op.f("fk_saved_recommendable_profile_id_user_profile"),
        ),
        sa.ForeignKeyConstraint(
            ["recommendable_id"],
            ["exhibition.recommendable.recommendable_id"],
            name=op.f("fk_saved_recommendable_recommendable_id_recommendable"),
        ),
        sa.PrimaryKeyConstraint(
            "saved_recommendable_id", name=op.f("pk_saved_recommendable")
        ),
        sa.UniqueConstraint(
            "profile_id",
            "recommendable_id",
            name="uq_saved_recommendable_profile_target",
        ),
        schema="profile",
    )
    op.create_index(
        "idx_saved_recommendable_profile",
        "saved_recommendable",
        ["profile_id", "saved_at"],
        unique=False,
        schema="profile",
    )
    op.create_index(
        "idx_saved_recommendable_target",
        "saved_recommendable",
        ["recommendable_id", "saved_at"],
        unique=False,
        schema="profile",
    )


def downgrade() -> None:
    op.drop_index(
        "idx_saved_recommendable_target",
        table_name="saved_recommendable",
        schema="profile",
    )
    op.drop_index(
        "idx_saved_recommendable_profile",
        table_name="saved_recommendable",
        schema="profile",
    )
    op.drop_table("saved_recommendable", schema="profile")
