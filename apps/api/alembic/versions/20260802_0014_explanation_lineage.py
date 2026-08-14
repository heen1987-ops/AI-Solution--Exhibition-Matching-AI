"""publish grounded recommendation-explanation lineage

Revision ID: 0014_explanation_lineage
Revises: 0013_behavior_learning
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014_explanation_lineage"
down_revision: str | None = "0013_behavior_learning"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_LEGACY_FINGERPRINT = "0" * 64


def upgrade() -> None:
    op.add_column(
        "match_reason",
        sa.Column(
            "explanation_policy_version",
            sa.String(length=100),
            nullable=False,
            server_default="explain-template-v1.0-legacy",
        ),
        schema="matching",
    )
    op.add_column(
        "match_reason",
        sa.Column(
            "input_fingerprint",
            sa.String(length=64),
            nullable=False,
            server_default=_LEGACY_FINGERPRINT,
        ),
        schema="matching",
    )
    op.alter_column(
        "match_reason",
        "explanation_policy_version",
        server_default=None,
        schema="matching",
    )
    op.alter_column(
        "match_reason",
        "input_fingerprint",
        server_default=None,
        schema="matching",
    )


def downgrade() -> None:
    op.drop_column("match_reason", "input_fingerprint", schema="matching")
    op.drop_column(
        "match_reason",
        "explanation_policy_version",
        schema="matching",
    )
