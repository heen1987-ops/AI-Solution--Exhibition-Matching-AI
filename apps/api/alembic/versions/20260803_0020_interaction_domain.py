"""create meeting/lead/follow-up (interaction) domain tables

이 마이그레이션이 생성하는 테이블은 backend/app/models/meeting.py의 AvailabilitySlot·
MeetingRequest·MeetingSlotRequest·MeetingContactShare·MeetingStatusHistory·Lead·FollowUp에
1:1로 대응한다. 테이블·컬럼·제약조건 이름은 그 모델 정의와 그대로 맞춘다.

명시적으로 name=을 준 제약(ForeignKeyConstraint/UniqueConstraint/CheckConstraint/Index/
ExcludeConstraint)은 app/db/base.py의 NAMING_CONVENTION이 적용되지 않으므로(Alembic
op.create_table은 그 커스텀 naming_convention이 없는 기본 MetaData에 테이블을 붙인다)
모델에 적힌 리터럴 이름을 그대로 재사용한다. 반대로 모델에서 이름을 주지 않은 단독 컬럼
ForeignKey(예: participation_id, staff_id, booth_id 등)는 app/db/base.py의 NAMING_CONVENTION
규칙(fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s)을 손으로 재현해 명시적으로
이름을 준다 - 20260801144653_profile_domain 마이그레이션이 이미 같은 이유로 채택한 방식이다
(그 마이그레이션의 모듈 docstring 참고).

이 파일은 2026-08-01에 alembic/pending/에 보류(parking)돼 있었다. 보류 사유는 작성 시점에
아래 FK 대상 테이블이 아직 어떤 마이그레이션으로도 만들어지지 않았다는 것이었다. 그 사유는
2026-08-03 통합 시점에 모두 해소됐고(아래 [해소] 표기), 그래서 이 리비전을 체인에 정식
편입한다(down_revision = 0019_notification_outbox):

    - exhibition.exhibitor_participation(participation_id)  [해소: 0005_exhibition]
      availability_slot.participation_id, meeting.participation_id
    - exhibition.exhibitor_staff(staff_id)                   [해소: 0005_exhibition]
      availability_slot.staff_id, meeting.staff_id
    - exhibition.booth(booth_id)                             [해소: 0005_exhibition]
      availability_slot.booth_id, meeting.booth_id
    - exhibition.product(product_id)                         [해소: 0005_exhibition]
      meeting.product_id
    - matching.match_result(match_result_id)                 [해소: 0008_matching_runtime]
      meeting.match_result_id

그 외 참조 대상은 처음부터 존재했다:

    - exhibition.event(tenant_id, event_id)                 [존재: 0003_foundation]
    - profile.user_profile(profile_id)                       [존재: 0004_profile_domain]
    - profile.consent_policy(consent_policy_id)              [존재: 0003_foundation]
    - profile.user_account(user_id)                          [존재: 0003_foundation]
    - ontology.concept_revision(taxonomy_version_id, concept_id) [존재: 0002_ontology]

WAVE 2C(BACKEND-MEETING 트랙)가 별도 마이그레이션(0017_meeting_buyer_extension)으로 추가하려
했던 네 개의 컬럼 - meeting.product_id / meeting.order_scale_code /
meeting_contact_share.exhibitor_enabled_at / meeting_contact_share.exhibitor_enabled_by_staff_id -
은 이 리비전이 애초에 테이블을 만드는 리비전이므로 ALTER가 아니라 CREATE TABLE 안으로 접어
넣었다. 그 별도 마이그레이션은 폐기했고, 두 FK의 리터럴 이름(fk_meeting_product,
fk_meeting_contact_share_exhibitor_enabled_by)만 여기로 옮겨왔다. 규약 파생 이름은
PostgreSQL 식별자 한계(63바이트)를 넘겨 autogenerate가 매번 차이를 보고하게 된다.

taxonomy(개념) 참조에 대하여: availability_slot.(taxonomy_version_id, concept_id),
meeting.(taxonomy_version_id, concept_id), meeting_outcome.(taxonomy_version_id, concept_id),
follow_up_action.(taxonomy_version_id, concept_id)는 단일 term_id 컬럼이 아니라
ontology.concept_revision을 향하는 복합 FK다. app/models/meeting.py 모듈 docstring
"taxonomy 참조에 대하여" 절 참고.

meeting 테이블의 확정 상담 겹침 방지(EXCLUDE ... USING gist)는 UUID 컬럼에 '=' 연산자를
쓰므로 btree_gist 확장이 필요하다. 이 마이그레이션의 upgrade()에서
CREATE EXTENSION IF NOT EXISTS btree_gist를 실행한다(다른 스키마가 이미 이 확장을
설치했더라도 안전하게 재사용된다). downgrade()에서는 다른 도메인이 이 확장을 이미 쓰고
있을 수 있으므로 DROP EXTENSION을 실행하지 않는다.

근거 문서: docs/db-erd-table-spec.md 2절(원안 대비 필수 보정 - "상담 슬롯"·"연락처 공유"),
14절(상담 가능시간과 상담), 22.1절(상담 확정 트랜잭션 경계).
docs/user-ia-wireframes.md 6.2절(상담 상태 머신), 8절 E-02~E-04.
docs/frontend-backend-ai-interface-spec.md 12절(상담 API).
대응하는 SQLAlchemy 모델: backend/app/models/meeting.py.

Revision ID: 0020_interaction_domain
Revises: 0019_notification_outbox
Create Date: 2026-08-01 (작성) / 2026-08-03 (체인 편입)
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.base import SCHEMA_EXHIBITION, SCHEMA_INTERACTION, SCHEMA_MATCHING, SCHEMA_PROFILE

# revision identifiers, used by Alembic.
revision: str = "0020_interaction_domain"
down_revision: str | None = "0019_notification_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# --------------------------------------------------------------------------
# app/models/meeting.py의 상태값 상수를 그대로 하드코딩한다. 마이그레이션은 적용된 시점의
# 스키마를 영구히 기록하는 역사적 기록이므로, 이후 모델 파일의 상수가 바뀌더라도 이 파일이
# 함께 바뀌면 안 된다 - 그래서 import 대신 리터럴로 복제한다(다른 도메인 마이그레이션들의
# 기존 관례와 동일).
# --------------------------------------------------------------------------

_MEETING_STATUSES = (
    "draft",
    "requested",
    "accepted",
    "counter_proposed",
    "rejected",
    "cancelled",
    "completed",
    "no_show",
)
_MEETING_CONFIRMED_STATUS = "accepted"
_AVAILABILITY_SLOT_STATUSES = ("OPEN", "FULL", "BLOCKED")
_MEETING_SLOT_REQUEST_STATUSES = ("PENDING", "SELECTED", "DECLINED", "WITHDRAWN")
_FOLLOW_UP_ACTION_STATUSES = ("PENDING", "IN_PROGRESS", "DONE", "CANCELLED")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


# 0003_foundation의 _uuid() 헬퍼와 동일한 형태.
def _uuid_column(
    name: str, *, nullable: bool = False, primary_key: bool = False
) -> sa.Column:
    return sa.Column(
        name,
        postgresql.UUID(as_uuid=True),
        nullable=False if primary_key else nullable,
        primary_key=primary_key,
    )


def _timestamptz(name: str, *, nullable: bool = False, server_default_now: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.DateTime(timezone=True),
        nullable=nullable,
        server_default=sa.text("now()") if server_default_now else None,
    )


def upgrade() -> None:
    # meeting의 확정 상담 겹침 방지 EXCLUDE 제약(UUID '=' + tstzrange '&&')에 필요하다.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")

    # ------------------------------------------------------------------
    # interaction.availability_slot - db-erd-table-spec.md 14.1절
    # ------------------------------------------------------------------
    op.create_table(
        "availability_slot",
        _uuid_column("availability_slot_id", primary_key=True),
        _uuid_column("tenant_id"),
        _uuid_column("event_id"),
        sa.Column(
            "participation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_EXHIBITION}.exhibitor_participation.participation_id",
                name="fk_availability_slot_participation_id_exhibitor_participation",
            ),
            nullable=False,
        ),
        sa.Column(
            "staff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_EXHIBITION}.exhibitor_staff.staff_id",
                name="fk_availability_slot_staff_id_exhibitor_staff",
            ),
            nullable=True,
        ),
        sa.Column(
            "booth_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_EXHIBITION}.booth.booth_id",
                name="fk_availability_slot_booth_id_booth",
            ),
            nullable=True,
        ),
        # 상담 주제 개념. 단일 term_id가 아니라 (taxonomy_version_id, concept_id) 복합 FK다
        # (아래 fk_availability_slot_ontology_revision).
        sa.Column("taxonomy_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("start_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("capacity", sa.SmallInteger(), nullable=False, server_default="1"),
        sa.Column("reserved_count", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="OPEN"),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        _timestamptz("created_at", nullable=False, server_default_now=True),
        _timestamptz("updated_at", nullable=False, server_default_now=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [f"{SCHEMA_EXHIBITION}.event.tenant_id", f"{SCHEMA_EXHIBITION}.event.event_id"],
            name="fk_availability_slot_tenant_event",
        ),
        sa.CheckConstraint("start_at < end_at", name="time_range"),
        sa.CheckConstraint("capacity > 0", name="capacity_positive"),
        sa.CheckConstraint(
            "reserved_count >= 0 AND reserved_count <= capacity",
            name="reserved_count_within_capacity",
        ),
        sa.CheckConstraint(
            f"status IN ({_in_list(_AVAILABILITY_SLOT_STATUSES)})",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "(taxonomy_version_id IS NULL) = (concept_id IS NULL)",
            name="topic_concept_pair",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_availability_slot_ontology_revision",
        ),
        schema=SCHEMA_INTERACTION,
    )
    op.create_index(
        "ix_availability_slot_participation_start",
        "availability_slot",
        ["participation_id", "start_at"],
        schema=SCHEMA_INTERACTION,
    )

    # ------------------------------------------------------------------
    # interaction.meeting - db-erd-table-spec.md 14.2절
    # ------------------------------------------------------------------
    op.create_table(
        "meeting",
        _uuid_column("meeting_id", primary_key=True),
        _uuid_column("tenant_id"),
        _uuid_column("event_id"),
        sa.Column(
            "buyer_profile_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_PROFILE}.user_profile.profile_id",
                name="fk_meeting_buyer_profile_id_user_profile",
            ),
            nullable=False,
        ),
        sa.Column(
            "participation_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_EXHIBITION}.exhibitor_participation.participation_id",
                name="fk_meeting_participation_id_exhibitor_participation",
            ),
            nullable=False,
        ),
        sa.Column(
            "staff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_EXHIBITION}.exhibitor_staff.staff_id",
                name="fk_meeting_staff_id_exhibitor_staff",
            ),
            nullable=True,
        ),
        sa.Column(
            "booth_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_EXHIBITION}.booth.booth_id",
                name="fk_meeting_booth_id_booth",
            ),
            nullable=True,
        ),
        sa.Column("taxonomy_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("message_enc", sa.LargeBinary(), nullable=True),
        sa.Column("status", sa.String(30), nullable=False, server_default="draft"),
        sa.Column(
            "confirmed_slot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_INTERACTION}.availability_slot.availability_slot_id",
                name="fk_meeting_confirmed_slot_id_availability_slot",
            ),
            nullable=True,
        ),
        sa.Column("confirmed_start", sa.DateTime(timezone=True), nullable=True),
        sa.Column("confirmed_end", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "match_result_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_MATCHING}.match_result.match_result_id",
                name="fk_meeting_match_result_id_match_result",
            ),
            nullable=True,
        ),
        # WAVE 2C(BACKEND-MEETING) 확장 컬럼. 폐기된 0017_meeting_buyer_extension이
        # ALTER로 붙이려던 것을 CREATE TABLE 안으로 접어 넣었다. FK 이름은 그 파일의
        # 리터럴을 그대로 옮겨왔다(규약 파생 이름은 63바이트 한계를 넘긴다).
        sa.Column(
            "product_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_EXHIBITION}.product.product_id",
                name="fk_meeting_product",
            ),
            nullable=True,
        ),
        sa.Column("order_scale_code", sa.String(50), nullable=True),
        sa.Column("viewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("row_version", sa.BigInteger(), nullable=False, server_default="0"),
        _timestamptz("created_at", nullable=False, server_default_now=True),
        _timestamptz("updated_at", nullable=False, server_default_now=True),
        sa.ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [f"{SCHEMA_EXHIBITION}.event.tenant_id", f"{SCHEMA_EXHIBITION}.event.event_id"],
            name="fk_meeting_tenant_event",
        ),
        sa.CheckConstraint(
            f"status IN ({_in_list(_MEETING_STATUSES)})", name="status_allowed"
        ),
        sa.CheckConstraint(
            "confirmed_start IS NULL OR confirmed_end IS NULL "
            "OR confirmed_start < confirmed_end",
            name="confirmed_range",
        ),
        sa.CheckConstraint(
            "(taxonomy_version_id IS NULL) = (concept_id IS NULL)",
            name="topic_concept_pair",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_meeting_ontology_revision",
        ),
        # docs/db-erd-table-spec.md 14.5절 "확정 상담 겹침 방지". 상태값은 app/models/meeting.py
        # 모듈 docstring에서 설명한 이유로 CONFIRMED 대신 'accepted'를 쓴다.
        postgresql.ExcludeConstraint(
            ("staff_id", "="),
            (
                sa.func.tstzrange(
                    sa.literal_column("confirmed_start"),
                    sa.literal_column("confirmed_end"),
                    "[)",
                ),
                "&&",
            ),
            where=sa.text(
                f"status = '{_MEETING_CONFIRMED_STATUS}' AND staff_id IS NOT NULL"
            ),
            using="gist",
            name="ex_meeting_staff_confirmed_overlap",
        ),
        postgresql.ExcludeConstraint(
            ("buyer_profile_id", "="),
            (
                sa.func.tstzrange(
                    sa.literal_column("confirmed_start"),
                    sa.literal_column("confirmed_end"),
                    "[)",
                ),
                "&&",
            ),
            where=sa.text(f"status = '{_MEETING_CONFIRMED_STATUS}'"),
            using="gist",
            name="ex_meeting_buyer_confirmed_overlap",
        ),
        schema=SCHEMA_INTERACTION,
    )
    op.create_index(
        "idx_meeting_buyer_time",
        "meeting",
        ["buyer_profile_id", "confirmed_start"],
        schema=SCHEMA_INTERACTION,
        postgresql_where=sa.text(f"status = '{_MEETING_CONFIRMED_STATUS}'"),
    )
    op.create_index(
        "idx_meeting_staff_time",
        "meeting",
        ["staff_id", "confirmed_start"],
        schema=SCHEMA_INTERACTION,
        postgresql_where=sa.text(f"status = '{_MEETING_CONFIRMED_STATUS}'"),
    )
    op.create_index(
        "idx_meeting_participation_status",
        "meeting",
        ["participation_id", "status"],
        schema=SCHEMA_INTERACTION,
    )

    # ------------------------------------------------------------------
    # interaction.meeting_slot_request - db-erd-table-spec.md 14.3절
    # ------------------------------------------------------------------
    op.create_table(
        "meeting_slot_request",
        _uuid_column("meeting_slot_request_id", primary_key=True),
        sa.Column(
            "meeting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_INTERACTION}.meeting.meeting_id",
                name="fk_meeting_slot_request_meeting_id_meeting",
            ),
            nullable=False,
        ),
        sa.Column(
            "availability_slot_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_INTERACTION}.availability_slot.availability_slot_id",
                name="fk_meeting_slot_request_availability_slot_id_availability_slot",
            ),
            nullable=False,
        ),
        sa.Column("preference_order", sa.SmallInteger(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("snapshot_json", postgresql.JSONB(), nullable=True),
        _timestamptz("created_at", nullable=False, server_default_now=True),
        sa.UniqueConstraint(
            "meeting_id",
            "availability_slot_id",
            name="uq_meeting_slot_request_meeting_slot",
        ),
        sa.UniqueConstraint(
            "meeting_id",
            "preference_order",
            name="uq_meeting_slot_request_meeting_preference",
        ),
        sa.CheckConstraint("preference_order > 0", name="preference_order_positive"),
        sa.CheckConstraint(
            f"status IN ({_in_list(_MEETING_SLOT_REQUEST_STATUSES)})",
            name="status_allowed",
        ),
        schema=SCHEMA_INTERACTION,
    )

    # ------------------------------------------------------------------
    # interaction.meeting_contact_share - db-erd-table-spec.md 14.4절
    # ------------------------------------------------------------------
    op.create_table(
        "meeting_contact_share",
        _uuid_column("meeting_contact_share_id", primary_key=True),
        sa.Column(
            "meeting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_INTERACTION}.meeting.meeting_id",
                name="fk_meeting_contact_share_meeting_id_meeting",
            ),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "consent_policy_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_PROFILE}.consent_policy.consent_policy_id",
                name="fk_meeting_contact_share_consent_policy_id_consent_policy",
            ),
            nullable=False,
        ),
        sa.Column("shared_fields", postgresql.JSONB(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("disclosed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "disclosed_to_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_PROFILE}.user_account.user_id",
                name="fk_meeting_contact_share_disclosed_to_user_id_user_account",
            ),
            nullable=True,
        ),
        # WAVE 2C(BACKEND-MEETING) 확장 - 연락처 공개 3번째 게이트("업체가 이 상담에 한해
        # 공유를 켰다"). 폐기된 0017_meeting_buyer_extension에서 접어 넣었다.
        sa.Column("exhibitor_enabled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "exhibitor_enabled_by_staff_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_EXHIBITION}.exhibitor_staff.staff_id",
                name="fk_meeting_contact_share_exhibitor_enabled_by",
            ),
            nullable=True,
        ),
        sa.CheckConstraint(
            "disclosed_at IS NULL OR disclosed_to_user_id IS NOT NULL",
            name="disclosure_requires_viewer",
        ),
        schema=SCHEMA_INTERACTION,
    )

    # ------------------------------------------------------------------
    # interaction.meeting_status_history - db-erd-table-spec.md 14.5절 (append-only)
    # ------------------------------------------------------------------
    op.create_table(
        "meeting_status_history",
        _uuid_column("meeting_status_history_id", primary_key=True),
        sa.Column(
            "meeting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_INTERACTION}.meeting.meeting_id",
                name="fk_meeting_status_history_meeting_id_meeting",
            ),
            nullable=False,
        ),
        sa.Column("previous_status", sa.String(30), nullable=True),
        sa.Column("new_status", sa.String(30), nullable=False),
        sa.Column(
            "changed_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_PROFILE}.user_account.user_id",
                name="fk_meeting_status_history_changed_by_user_id_user_account",
            ),
            nullable=True,
        ),
        sa.Column("reason_code", sa.String(50), nullable=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), nullable=True),
        _timestamptz("created_at", nullable=False, server_default_now=True),
        sa.CheckConstraint(
            f"previous_status IS NULL OR previous_status IN ({_in_list(_MEETING_STATUSES)})",
            name="previous_status_allowed",
        ),
        sa.CheckConstraint(
            f"new_status IN ({_in_list(_MEETING_STATUSES)})",
            name="new_status_allowed",
        ),
        schema=SCHEMA_INTERACTION,
    )
    op.create_index(
        "ix_meeting_status_history_meeting_created",
        "meeting_status_history",
        ["meeting_id", "created_at"],
        schema=SCHEMA_INTERACTION,
    )

    # ------------------------------------------------------------------
    # interaction.meeting_outcome (Lead) - db-erd-table-spec.md 14.5절
    # ------------------------------------------------------------------
    op.create_table(
        "meeting_outcome",
        _uuid_column("meeting_outcome_id", primary_key=True),
        sa.Column(
            "meeting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_INTERACTION}.meeting.meeting_id",
                name="fk_meeting_outcome_meeting_id_meeting",
            ),
            nullable=False,
            unique=True,
        ),
        sa.Column(
            "is_qualified_lead", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("taxonomy_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("expected_amount", sa.BigInteger(), nullable=True),
        sa.Column("currency", sa.CHAR(3), nullable=True, server_default=sa.text("'KRW'")),
        sa.Column("expected_probability_percent", sa.Numeric(5, 2), nullable=True),
        sa.Column("memo_enc", sa.LargeBinary(), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "recorded_by_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_PROFILE}.user_account.user_id",
                name="fk_meeting_outcome_recorded_by_user_id_user_account",
            ),
            nullable=True,
        ),
        _timestamptz("created_at", nullable=False, server_default_now=True),
        _timestamptz("updated_at", nullable=False, server_default_now=True),
        sa.CheckConstraint(
            "expected_probability_percent IS NULL OR "
            "(expected_probability_percent >= 0 AND expected_probability_percent <= 100)",
            name="probability_range",
        ),
        sa.CheckConstraint(
            "(taxonomy_version_id IS NULL) = (concept_id IS NULL)",
            name="outcome_concept_pair",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_meeting_outcome_ontology_revision",
        ),
        schema=SCHEMA_INTERACTION,
    )

    # ------------------------------------------------------------------
    # interaction.follow_up_action (FollowUp) - db-erd-table-spec.md 14.5절
    # ------------------------------------------------------------------
    op.create_table(
        "follow_up_action",
        _uuid_column("follow_up_action_id", primary_key=True),
        sa.Column(
            "meeting_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_INTERACTION}.meeting.meeting_id",
                name="fk_follow_up_action_meeting_id_meeting",
            ),
            nullable=False,
        ),
        sa.Column("taxonomy_version_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("concept_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "assignee_user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey(
                f"{SCHEMA_PROFILE}.user_account.user_id",
                name="fk_follow_up_action_assignee_user_id_user_account",
            ),
            nullable=True,
        ),
        sa.Column("due_date", sa.Date(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="PENDING"),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("note_enc", sa.LargeBinary(), nullable=True),
        _timestamptz("created_at", nullable=False, server_default_now=True),
        _timestamptz("updated_at", nullable=False, server_default_now=True),
        sa.CheckConstraint(
            f"status IN ({_in_list(_FOLLOW_UP_ACTION_STATUSES)})",
            name="status_allowed",
        ),
        sa.CheckConstraint(
            "(taxonomy_version_id IS NULL) = (concept_id IS NULL)",
            name="action_concept_pair",
        ),
        sa.ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_follow_up_action_ontology_revision",
        ),
        schema=SCHEMA_INTERACTION,
    )
    op.create_index(
        "ix_follow_up_action_meeting_status",
        "follow_up_action",
        ["meeting_id", "status"],
        schema=SCHEMA_INTERACTION,
    )


def downgrade() -> None:
    for table in (
        "follow_up_action",
        "meeting_outcome",
        "meeting_status_history",
        "meeting_contact_share",
        "meeting_slot_request",
        "meeting",
        "availability_slot",
    ):
        op.drop_table(table, schema=SCHEMA_INTERACTION)
    # btree_gist는 다른 스키마도 함께 쓸 수 있으므로 여기서 DROP EXTENSION을 실행하지 않는다.
