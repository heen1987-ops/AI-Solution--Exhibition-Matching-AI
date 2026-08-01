"""create versioned user-profile domain tables

REBASE 이력: 이 마이그레이션을 처음 작성한 시점(2026-08-01 14:54)에는 core/identity
마이그레이션이 아직 존재하지 않아 down_revision을 None으로 두고 "NEEDS_REBASE" 주석을
남겼었다. 그 뒤 backend/alembic/versions/20260801_0002_0003_foundation.py(revision
"0003_foundation")가 core.tenant, exhibition.event/event_day/event_zone,
profile.user_account/role/user_role/guest_session/consent_policy/user_consent,
identity.user_identity/authentication_method, privacy.*, audit.audit_log를 생성하는 것으로
확인되어, 아래처럼 down_revision을 "0003_foundation"으로 연결했다. profile_attribute·
inferred_preference가 참조하는 ontology.concept_revision은 0003_foundation이 의존하는
"0002_ontology"에서 생성되므로 이 체인으로 문제 없이 도달한다.

이 마이그레이션이 생성하는 테이블 중 다음 컬럼은 다른 도메인이 만든 테이블을 참조하는
ForeignKey/ForeignKeyConstraint다 (전부 0003_foundation 또는 그 조상 리비전에서 생성됨):
    - core.tenant(tenant_id)                              - user_profile, visit_session
    - exhibition.event(tenant_id, event_id)                - user_profile, visit_session (복합 FK)
    - exhibition.event_zone(tenant_id, event_id,
      event_zone_id)                                       - visit_session (복합 FK, 같은 행사
                                                              소속 구역만 허용)
    - exhibition.event_zone(event_zone_id)                 - context_profile (단순 FK)
    - profile.user_account(user_id)                        - user_profile, visit_session
    - profile.guest_session(guest_session_id)               - user_profile, visit_session
    - ontology.concept_revision(taxonomy_version_id,
      concept_id)                                          - profile_attribute, inferred_preference
    - ontology.concept(concept_id, concept_code)            - profile_attribute, inferred_preference
      (attribute_code 비정규화 컬럼이 concept_id의 실제 concept_code와 항상 일치하도록
      복합 FK로 강제한다; ontology.concept은 UNIQUE(concept_id, concept_code)를 갖는다)

근거 문서: docs/07-user-profile-model.md 22절, docs/db-erd-table-spec.md 8.4·10절.
대응하는 SQLAlchemy 모델: backend/app/models/profile.py. 테이블·컬럼·제약조건 이름을 그
모델 정의와 1:1로 맞춘다(특히 CheckConstraint/UniqueConstraint/ForeignKeyConstraint는
모델에서 이미 명시적 name=을 부여했으므로 여기서도 동일한 리터럴 이름을 그대로 쓴다 -
app/db/base.py의 NAMING_CONVENTION은 이름이 없는 제약에만 적용되고, 명시적으로 이름을 준
제약에는 적용되지 않기 때문이다). 단독 컬럼 FK처럼 모델에서 이름을 명시하지 않은 제약은
app/db/base.py NAMING_CONVENTION 규칙(fk_%(table_name)s_%(column_0_name)s_
%(referred_table_name)s)을 그대로 손으로 재현해 이후 alembic autogenerate가 불필요한
rename diff를 만들지 않게 한다.

Revision ID: 0004_profile_domain
Revises: 0003_foundation
Create Date: 2026-08-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from app.db.base import SCHEMA_PROFILE
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0004_profile_domain"
down_revision: str | None = "0003_foundation"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # 1) profile.user_profile - 07 22.1 + db-erd 10.1 (app/models/profile.py: UserProfile)
    op.create_table(
        "user_profile",
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "core.tenant.tenant_id", name="fk_user_profile_tenant_id_tenant"
            ),
            nullable=False,
        ),
        # event_id는 단독 FK가 없다 - fk_user_profile_event_boundary 복합 FK로만 검증한다.
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "profile.user_account.user_id",
                name="fk_user_profile_user_id_user_account",
            ),
            nullable=True,
        ),
        sa.Column(
            "guest_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "profile.guest_session.guest_session_id",
                name="fk_user_profile_guest_session_id_guest_session",
            ),
            nullable=True,
        ),
        sa.Column("user_type", sa.String(30), nullable=False),
        sa.Column(
            "profile_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'DRAFT'"),
        ),
        sa.Column("primary_goal_code", sa.String(50), nullable=True),
        sa.Column(
            "completeness_score", sa.Numeric(5, 2), nullable=False, server_default="0"
        ),
        sa.Column("current_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="1"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_user_profile_event_boundary",
        ),
        sa.CheckConstraint(
            "num_nonnulls(user_id, guest_session_id) = 1",
            name="exactly_one_owner",
        ),
        sa.CheckConstraint(
            "completeness_score >= 0 AND completeness_score <= 100",
            name="completeness_score_range",
        ),
        sa.CheckConstraint(
            "user_type IN ('GENERAL_VISITOR', 'BUYER')",
            name="user_type_allowed",
        ),
        sa.CheckConstraint(
            "profile_status IN ('DRAFT', 'COMPLETE', 'INACTIVE')",
            name="profile_status_allowed",
        ),
        schema=SCHEMA_PROFILE,
    )
    # db-erd 10.1 부분 유일성 (인증/익명 각각).
    op.create_index(
        "uq_user_profile_user_event_type",
        "user_profile",
        ["tenant_id", "event_id", "user_id", "user_type"],
        unique=True,
        schema=SCHEMA_PROFILE,
        postgresql_where=sa.text("deleted_at IS NULL AND user_id IS NOT NULL"),
    )
    op.create_index(
        "uq_user_profile_guest_event_type",
        "user_profile",
        ["tenant_id", "event_id", "guest_session_id", "user_type"],
        unique=True,
        schema=SCHEMA_PROFILE,
        postgresql_where=sa.text("deleted_at IS NULL AND guest_session_id IS NOT NULL"),
    )

    # 2) profile.profile_attribute - 07 22.2 (app/models/profile.py: ProfileAttribute)
    op.create_table(
        "profile_attribute",
        sa.Column(
            "profile_attribute_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_PROFILE}.user_profile.profile_id",
                name="fk_profile_attribute_profile_id_user_profile",
            ),
            nullable=False,
        ),
        # taxonomy_version_id/concept_id는 단독 FK가 없다 -
        # fk_profile_attribute_ontology_revision 복합 FK로만 검증한다.
        sa.Column("taxonomy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        # 07 22.2 비정규화 컬럼(조회·API용 개념 코드). app/models/profile.py ProfileAttribute
        # docstring 참고 - 정본은 ontology.concept.concept_code이며, 아래
        # fk_profile_attribute_concept_code 복합 FK가 일치를 DB 레벨에서 강제한다.
        sa.Column("attribute_code", sa.String(100), nullable=False),
        sa.Column("value_json", postgresql.JSONB(), nullable=False),
        sa.Column("requirement_level", sa.String(20), nullable=False),
        sa.Column("priority", sa.SmallInteger(), nullable=True),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("source_reference_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="1"),
        sa.Column("freshness_score", sa.Numeric(4, 3), nullable=True),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("valid_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "active", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "requirement_level IN ('REQUIRED', 'PREFERRED', 'ACCEPTABLE', 'EXCLUDED')",
            name="requirement_level_allowed",
        ),
        sa.CheckConstraint(
            "source_type IN ("
            "'USER_SELECTED', 'USER_TYPED', 'USER_EDITED', 'REGISTRATION', "
            "'BEHAVIOR_SINGLE', 'BEHAVIOR_AGGREGATED', 'FEEDBACK', 'AI_EXTRACTED', "
            "'OPERATOR_CONFIRMED', 'DEFAULT', 'EXTERNAL_SYNC'"
            ")",
            name="source_type_allowed",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="confidence_range",
        ),
        sa.CheckConstraint(
            "freshness_score IS NULL OR (freshness_score >= 0 AND freshness_score <= 1)",
            name="freshness_score_range",
        ),
        sa.CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until",
            name="valid_period_order",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_profile_attribute_ontology_revision",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id", "attribute_code"],
            ["ontology.concept.concept_id", "ontology.concept.concept_code"],
            name="fk_profile_attribute_concept_code",
        ),
        schema=SCHEMA_PROFILE,
    )
    op.create_index(
        "ix_profile_attribute_lookup",
        "profile_attribute",
        ["profile_id", "taxonomy_version_id", "concept_id", "active"],
        schema=SCHEMA_PROFILE,
    )

    # 3) profile.inferred_preference - 07 22.3 (app/models/profile.py: InferredPreference)
    op.create_table(
        "inferred_preference",
        sa.Column(
            "inferred_preference_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_PROFILE}.user_profile.profile_id",
                name="fk_inferred_preference_profile_id_user_profile",
            ),
            nullable=False,
        ),
        sa.Column("taxonomy_version_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=False),
        # 07 22.3 비정규화 컬럼 - profile_attribute.attribute_code와 동일한 근거.
        sa.Column("attribute_code", sa.String(100), nullable=False),
        sa.Column(
            "inferred_score", sa.Numeric(5, 4), nullable=False, server_default="0"
        ),
        sa.Column(
            "positive_evidence_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column(
            "negative_evidence_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("confidence", sa.Numeric(4, 3), nullable=False, server_default="0"),
        sa.Column("first_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_observed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "profile_id",
            "taxonomy_version_id",
            "concept_id",
            name="uq_inferred_preference_concept",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_inferred_preference_ontology_revision",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id", "attribute_code"],
            ["ontology.concept.concept_id", "ontology.concept.concept_code"],
            name="fk_inferred_preference_concept_code",
        ),
        sa.CheckConstraint(
            "inferred_score >= -1 AND inferred_score <= 1",
            name="inferred_score_range",
        ),
        sa.CheckConstraint(
            "confidence >= 0 AND confidence <= 1",
            name="confidence_range",
        ),
        sa.CheckConstraint(
            "positive_evidence_count >= 0",
            name="positive_evidence_count_nonneg",
        ),
        sa.CheckConstraint(
            "negative_evidence_count >= 0",
            name="negative_evidence_count_nonneg",
        ),
        schema=SCHEMA_PROFILE,
    )

    # 4) profile.profile_version - 07 22.5 + db-erd 10.7 (app/models/profile.py: ProfileVersion)
    op.create_table(
        "profile_version",
        sa.Column(
            "profile_version_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_PROFILE}.user_profile.profile_id",
                name="fk_profile_version_profile_id_user_profile",
            ),
            nullable=False,
        ),
        sa.Column("version_number", sa.Integer(), nullable=False),
        sa.Column("snapshot_json", postgresql.JSONB(), nullable=False),
        sa.Column("snapshot_hash", sa.LargeBinary(), nullable=True),
        sa.Column("change_reason", sa.String(30), nullable=False),
        sa.Column("source_event_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.UniqueConstraint(
            "profile_id", "version_number", name="uq_profile_version_number"
        ),
        sa.CheckConstraint("version_number >= 1", name="version_number_positive"),
        schema=SCHEMA_PROFILE,
    )

    # 5) profile.visit_session - db-erd 8.4 (app/models/profile.py: VisitSession)
    op.create_table(
        "visit_session",
        sa.Column("visit_session_id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "tenant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "core.tenant.tenant_id", name="fk_visit_session_tenant_id_tenant"
            ),
            nullable=False,
        ),
        # event_id는 단독 FK가 없다 - fk_visit_session_event_boundary 복합 FK로만 검증한다.
        sa.Column("event_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "profile.user_account.user_id",
                name="fk_visit_session_user_id_user_account",
            ),
            nullable=True,
        ),
        sa.Column(
            "guest_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "profile.guest_session.guest_session_id",
                name="fk_visit_session_guest_session_id_guest_session",
            ),
            nullable=True,
        ),
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_PROFILE}.user_profile.profile_id",
                name="fk_visit_session_profile_id_user_profile",
            ),
            nullable=True,
        ),
        sa.Column("visit_date", sa.Date(), nullable=False),
        sa.Column("entry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("exit_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("available_minutes", sa.Integer(), nullable=True),
        # current_zone_id는 단독 FK가 없다 - fk_visit_session_zone_same_event 복합 FK로 "같은
        # 행사에 속한 구역만" 허용한다 (event_zone.tenant_id/event_id/event_zone_id는
        # 0003_foundation의 uq_event_zone_boundary_id UNIQUE로 뒷받침된다).
        sa.Column(
            "current_zone_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
        sa.Column(
            "current_zone_observed_at", sa.DateTime(timezone=True), nullable=True
        ),
        sa.Column("route_preference", sa.String(30), nullable=True),
        sa.Column(
            "session_status",
            sa.String(20),
            nullable=False,
            server_default=sa.text("'PLANNED'"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_visit_session_event_boundary",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id", "current_zone_id"],
            [
                "exhibition.event_zone.tenant_id",
                "exhibition.event_zone.event_id",
                "exhibition.event_zone.event_zone_id",
            ],
            name="fk_visit_session_zone_same_event",
        ),
        sa.CheckConstraint(
            "num_nonnulls(user_id, guest_session_id) = 1",
            name="exactly_one_owner",
        ),
        sa.CheckConstraint(
            "session_status IN ('PLANNED', 'ACTIVE', 'COMPLETED', 'CANCELLED')",
            name="session_status_allowed",
        ),
        sa.CheckConstraint(
            "entry_at IS NULL OR exit_at IS NULL OR entry_at <= exit_at",
            name="entry_exit_order",
        ),
        sa.CheckConstraint(
            "available_minutes IS NULL OR available_minutes >= 0",
            name="available_minutes_nonneg",
        ),
        schema=SCHEMA_PROFILE,
    )
    op.create_index(
        "ix_visit_session_event_date",
        "visit_session",
        ["tenant_id", "event_id", "visit_date"],
        schema=SCHEMA_PROFILE,
    )

    # 6) profile.context_profile - 07 22.4 (visit_session에 딸리므로 그 뒤에 생성)
    # (app/models/profile.py: ContextProfile)
    op.create_table(
        "context_profile",
        sa.Column(
            "context_profile_id", postgresql.UUID(as_uuid=True), primary_key=True
        ),
        sa.Column(
            "visit_session_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_PROFILE}.visit_session.visit_session_id",
                name="fk_context_profile_visit_session_id_visit_session",
            ),
            nullable=False,
        ),
        sa.Column(
            "current_zone_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                "exhibition.event_zone.event_zone_id",
                name="fk_context_profile_current_zone_id_event_zone",
            ),
            nullable=True,
        ),
        sa.Column("remaining_minutes", sa.Integer(), nullable=True),
        sa.Column("max_walk_minutes", sa.Integer(), nullable=True),
        sa.Column(
            "avoid_congestion",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column("next_schedule_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("context_json", postgresql.JSONB(), nullable=True),
        sa.Column(
            "captured_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "remaining_minutes IS NULL OR remaining_minutes >= 0",
            name="remaining_minutes_nonneg",
        ),
        sa.CheckConstraint(
            "max_walk_minutes IS NULL OR max_walk_minutes >= 0",
            name="max_walk_minutes_nonneg",
        ),
        schema=SCHEMA_PROFILE,
    )
    op.create_index(
        "ix_context_profile_session_captured",
        "context_profile",
        ["visit_session_id", "captured_at"],
        schema=SCHEMA_PROFILE,
    )

    # 7) profile.buyer_need - db-erd 10.5 (user_profile의 1:1 확장)
    # (app/models/profile.py: BuyerNeed)
    op.create_table(
        "buyer_need",
        sa.Column(
            "profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_PROFILE}.user_profile.profile_id",
                name="fk_buyer_need_profile_id_user_profile",
            ),
            primary_key=True,
        ),
        sa.Column("organization_type", sa.String(50), nullable=True),
        sa.Column("target_price_min_amount", sa.BigInteger(), nullable=True),
        sa.Column("target_price_max_amount", sa.BigInteger(), nullable=True),
        sa.Column(
            "currency", sa.CHAR(3), nullable=False, server_default=sa.text("'KRW'")
        ),
        sa.Column("price_basis", sa.String(30), nullable=True),
        sa.Column("monthly_units_min", sa.Integer(), nullable=True),
        sa.Column("monthly_units_max", sa.Integer(), nullable=True),
        sa.Column("decision_timeline", sa.String(30), nullable=True),
        sa.Column(
            "business_email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "company_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint(
            "target_price_min_amount IS NULL OR target_price_min_amount >= 0",
            name="target_price_min_nonneg",
        ),
        sa.CheckConstraint(
            "target_price_max_amount IS NULL OR target_price_max_amount >= 0",
            name="target_price_max_nonneg",
        ),
        sa.CheckConstraint(
            "target_price_min_amount IS NULL OR target_price_max_amount IS NULL "
            "OR target_price_min_amount <= target_price_max_amount",
            name="target_price_order",
        ),
        sa.CheckConstraint(
            "monthly_units_min IS NULL OR monthly_units_min >= 0",
            name="monthly_units_min_nonneg",
        ),
        sa.CheckConstraint(
            "monthly_units_max IS NULL OR monthly_units_max >= 0",
            name="monthly_units_max_nonneg",
        ),
        sa.CheckConstraint(
            "monthly_units_min IS NULL OR monthly_units_max IS NULL "
            "OR monthly_units_min <= monthly_units_max",
            name="monthly_units_order",
        ),
        sa.CheckConstraint(
            "price_basis IS NULL OR price_basis IN ('RETAIL_PRICE', 'WHOLESALE_PRICE')",
            name="price_basis_allowed",
        ),
        schema=SCHEMA_PROFILE,
    )


def downgrade() -> None:
    # 생성 역순으로 제거한다. 각 테이블에 딸린 인덱스는 DROP TABLE 시 함께 제거된다.
    op.drop_table("buyer_need", schema=SCHEMA_PROFILE)
    op.drop_table("context_profile", schema=SCHEMA_PROFILE)
    op.drop_table("visit_session", schema=SCHEMA_PROFILE)
    op.drop_table("profile_version", schema=SCHEMA_PROFILE)
    op.drop_table("inferred_preference", schema=SCHEMA_PROFILE)
    op.drop_table("profile_attribute", schema=SCHEMA_PROFILE)
    op.drop_table("user_profile", schema=SCHEMA_PROFILE)
