"""publish verified-buyer trade profile (profile.buyer_profile, profile.buyer_profile_code)

WAVE2C BACKEND-BUYER-PROFILE. See app/models/buyer_profile.py's module docstring for the full
design rationale (why this is a new table distinct from profile.buyer_need, and why the
ontology-code fields are normalized into a child table rather than a JSONB array).

Revision ID: 0022_buyer_profile
Revises: 0021_exhibitor_preference
Create Date: 2026-08-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0022_buyer_profile"
down_revision: str | None = "0021_exhibitor_preference"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_BUYER_TYPES = (
    "DISTRIBUTOR",
    "RETAILER",
    "ONLINE_COMMERCE",
    "IMPORTER",
    "EXPORTER",
    "MANUFACTURER",
    "PUBLIC_BUYER",
    "CORPORATE_BUYER",
    "INVESTOR",
    "OTHER",
)
_VERIFICATION_STATUSES = (
    "UNVERIFIED",
    "PENDING",
    "VERIFIED",
    "LIMITED",
    "REJECTED",
    "SUSPENDED",
    "EXPIRED",
)
_CODE_GROUPS = ("INDUSTRY", "INTEREST", "CHANNEL", "PREFERRED_REGION", "COOPERATION")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "buyer_profile",
        sa.Column("buyer_profile_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "buyer_type", sa.String(30), nullable=False, server_default="OTHER"
        ),
        sa.Column("order_scale_code", sa.String(50), nullable=True),
        sa.Column("decision_timeline", sa.String(30), nullable=True),
        sa.Column(
            "verification_status",
            sa.String(20),
            nullable=False,
            server_default="UNVERIFIED",
        ),
        sa.Column("verification_reason", sa.String(500), nullable=True),
        sa.Column(
            "verification_reviewed_by_user_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "verification_reviewed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
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
            ["tenant_id"],
            ["core.tenant.tenant_id"],
            name="fk_buyer_profile_tenant_id_tenant",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["profile.user_account.user_id"],
            name="fk_buyer_profile_user_id_user_account",
        ),
        sa.ForeignKeyConstraint(
            ["verification_reviewed_by_user_id"],
            ["profile.user_account.user_id"],
            name="fk_buyer_profile_verification_reviewed_by_user_id_user_account",
        ),
        sa.UniqueConstraint(
            "tenant_id", "user_id", name="uq_buyer_profile_tenant_user"
        ),
        sa.CheckConstraint(
            f"buyer_type IN ({_in_list(_BUYER_TYPES)})",
            name=op.f("ck_buyer_profile_buyer_type_allowed"),
        ),
        sa.CheckConstraint(
            f"verification_status IN ({_in_list(_VERIFICATION_STATUSES)})",
            name=op.f("ck_buyer_profile_verification_status_allowed"),
        ),
        sa.CheckConstraint(
            "version >= 1", name=op.f("ck_buyer_profile_version_positive")
        ),
        schema="profile",
    )

    op.create_table(
        "buyer_profile_code",
        sa.Column("buyer_profile_code_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("buyer_profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("code_group", sa.String(20), nullable=False),
        sa.Column("taxonomy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("attribute_code", sa.String(100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["buyer_profile_id"],
            ["profile.buyer_profile.buyer_profile_id"],
            name="fk_buyer_profile_code_buyer_profile_id_buyer_profile",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_buyer_profile_code_ontology_revision",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id", "attribute_code"],
            ["ontology.concept.concept_id", "ontology.concept.concept_code"],
            name="fk_buyer_profile_code_concept_code",
        ),
        sa.UniqueConstraint(
            "buyer_profile_id",
            "code_group",
            "concept_id",
            name="uq_buyer_profile_code_group_concept",
        ),
        sa.CheckConstraint(
            f"code_group IN ({_in_list(_CODE_GROUPS)})",
            name=op.f("ck_buyer_profile_code_code_group_allowed"),
        ),
        schema="profile",
    )
    op.create_index(
        "ix_buyer_profile_code_lookup",
        "buyer_profile_code",
        ["buyer_profile_id", "code_group"],
        schema="profile",
    )


def downgrade() -> None:
    op.drop_index(
        "ix_buyer_profile_code_lookup", table_name="buyer_profile_code", schema="profile"
    )
    op.drop_table("buyer_profile_code", schema="profile")
    op.drop_table("buyer_profile", schema="profile")
