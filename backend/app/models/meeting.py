"""상담 가능시간·상담 도메인 SQLAlchemy 모델 (interaction 스키마).

근거 문서: docs/db-erd-table-spec.md 14절(상담 가능시간과 상담).

발견 경위
----------
app/models/exhibitor.py 모듈 docstring은 "interaction.availability_slot : db-erd 14.1.
app/models/meeting.py가 이미 정의했다(스키마도 exhibition이 아니라 interaction)"이라고
적어 두었지만, 이 커밋 이전에는 이 파일 자체가 존재하지 않았다 - app/models/matching.py의
exhibition.recommendable과 같은 종류의 갭이다(그쪽은 docs/09-10-matching-implementation.md에
기록했다). 이 커밋에서 처음 만든다.

이 파일에서 구현하는 테이블
---------------------------
1. interaction.availability_slot   - db-erd 14.1
2. interaction.meeting              - db-erd 14.2
3. interaction.meeting_slot_request - db-erd 14.3
4. interaction.meeting_contact_share - db-erd 14.4
5. interaction.meeting_status_history - db-erd 14.5
6. interaction.meeting_outcome       - db-erd 14.5
7. interaction.follow_up_action      - db-erd 14.5

topic_term_id 해석 메모
-------------------------
db-erd 14.1/14.2절은 topic_term_id를 "UUID FK | 주제"라고만 적고 대상 테이블을 명시하지
않는다. 이 리포지토리의 지배적 관례(exhibitor.py의 Product.category_concept_id,
staff_topic 등)는 단일 개념 참조를 새 "term" 테이블로 만들지 않고 온톨로지의
(taxonomy_version_id, concept_id) 복합 FK로 직접 표현하는 것이므로, 여기서도
topic_taxonomy_version_id/topic_concept_id 쌍으로 구현한다. exhibition.staff_topic이
담당자당 여러 주제를 담당할 수 있음을 표현하는 반면, 이 쌍은 상담 슬롯/상담 1건이
정확히 하나의 주제를 갖는다는 뜻이다(db-erd가 단수형 "주제"로 표기한 것과 일치).

의도적으로 지금 구현하지 않은 것
----------------------------------
- 확정 상담 겹침 방지 EXCLUDE 제약(db-erd 14.5절 예시 SQL)은 문서 자체가 "실제 상태 enum과
  NULL 정책 확정 후 적용"이라고 명시한 유보사항이라 이 마이그레이션에 포함하지 않았다.
  btree_gist 익스텐션과 status 확정 이후 별도 마이그레이션으로 추가해야 한다.
- ai.ai_run(추천 이유 생성 관련) 등 아직 없는 도메인 참조는 app/models/matching.py와 같은
  방식으로 FK 없이 값만 저장한다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SCHEMA_EXHIBITION, SCHEMA_INTERACTION, Base
from app.models.common import new_uuid7

_new_uuid = new_uuid7


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


#: db-erd 14.1절.
AVAILABILITY_SLOT_STATUSES: tuple[str, ...] = ("OPEN", "FULL", "BLOCKED")

#: db-erd 14.2절 "REQUESTED, COUNTER_PROPOSED, CONFIRMED 등". 10단계 상세설계 11.3절의
#: 상담 상태 흐름(REQUESTED -> VIEWED -> ACCEPTED -> RESCHEDULE_PROPOSED -> CONFIRMED ->
#: COMPLETED -> FOLLOW_UP, 예외: REJECTED/CANCELLED_BY_BUYER/CANCELLED_BY_EXHIBITOR/
#: NO_SHOW)를 그대로 채택한다 - db-erd는 "등"으로 예시만 들었다.
MEETING_STATUSES: tuple[str, ...] = (
    "REQUESTED",
    "VIEWED",
    "COUNTER_PROPOSED",
    "CONFIRMED",
    "COMPLETED",
    "FOLLOW_UP",
    "REJECTED",
    "CANCELLED_BY_BUYER",
    "CANCELLED_BY_EXHIBITOR",
    "NO_SHOW",
)

#: db-erd 14.3절.
MEETING_SLOT_REQUEST_STATUSES: tuple[str, ...] = ("REQUESTED", "ACCEPTED", "REJECTED")

#: db-erd 14.4절 shared_fields 값 예시.
CONTACT_SHARE_FIELDS: tuple[str, ...] = ("NAME", "PHONE", "BUSINESS_EMAIL")

#: db-erd 14.5절.
MEETING_LEAD_STATUSES: tuple[str, ...] = ("QUALIFIED", "UNQUALIFIED")
FOLLOW_UP_ACTION_STATUSES: tuple[str, ...] = ("OPEN", "DONE", "CANCELLED")


# ============================================================================
# 1. 상담 가능시간 (db-erd 14.1)
# ============================================================================


class AvailabilitySlot(Base):
    """interaction.availability_slot - db-erd 14.1.

    reserved_count는 meeting_slot_request 확정 건수의 캐시 카운터다(14.1절 본문). 실제
    예약 처리는 09단계 17.1절 "예약 처리" 절차(SELECT FOR UPDATE 또는 낙관적 잠금 ->
    reserved_count < capacity 확인 -> meeting 생성 -> reserved_count 증가)를 서비스
    계층에서 하나의 트랜잭션으로 수행해야 한다 - 이 모델은 그 불변식을 CHECK로만 보강한다.
    """

    __tablename__ = "availability_slot"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_availability_slot_event_boundary",
        ),
        CheckConstraint("start_at < end_at", name="time_range_order"),
        CheckConstraint("capacity > 0", name="capacity_positive"),
        CheckConstraint(
            "reserved_count >= 0 AND reserved_count <= capacity",
            name="reserved_count_within_capacity",
        ),
        CheckConstraint(
            f"status IN ({_in_list(AVAILABILITY_SLOT_STATUSES)})",
            name="status_allowed",
        ),
        Index(
            "idx_availability_slot_participation_time", "participation_id", "start_at"
        ),
        Index("idx_availability_slot_staff_time", "staff_id", "start_at"),
        {"schema": SCHEMA_INTERACTION},
    )

    availability_slot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    participation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor_participation.participation_id"),
        nullable=False,
    )
    staff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor_staff.staff_id"),
        nullable=True,
    )
    booth_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.booth.booth_id"),
        nullable=True,
    )
    topic_taxonomy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    topic_concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    reserved_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)

    slot_requests: Mapped[list[MeetingSlotRequest]] = relationship(
        back_populates="availability_slot"
    )


# ============================================================================
# 2. 상담 (db-erd 14.2)
# ============================================================================


class Meeting(Base):
    """interaction.meeting - db-erd 14.2.

    message_enc는 08 27.5절/db-erd 6절의 개인정보·민감정보 암호화 원칙을 따라 애플리케이션
    계층에서 암호화한 바이트만 저장한다(평문 컬럼을 두지 않는다).
    """

    __tablename__ = "meeting"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_meeting_event_boundary",
        ),
        CheckConstraint(
            f"status IN ({_in_list(MEETING_STATUSES)})", name="status_allowed"
        ),
        CheckConstraint(
            "confirmed_start IS NULL OR confirmed_end IS NULL "
            "OR confirmed_start < confirmed_end",
            name="confirmed_range_order",
        ),
        Index("idx_meeting_buyer_time", "buyer_profile_id", "confirmed_start"),
        Index("idx_meeting_staff_time", "staff_id", "confirmed_start"),
        {"schema": SCHEMA_INTERACTION},
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    buyer_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.user_profile.profile_id"),
        nullable=False,
    )
    participation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor_participation.participation_id"),
        nullable=False,
    )
    staff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor_staff.staff_id"),
        nullable=True,
    )
    booth_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.booth.booth_id"),
        nullable=True,
    )
    topic_taxonomy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    topic_concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    message_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="REQUESTED")
    confirmed_slot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_INTERACTION}.availability_slot.availability_slot_id"),
        nullable=True,
    )
    confirmed_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # ai 도메인이 아직 없어 FK 없이 값만 저장한다 (모듈 docstring 참고).
    match_result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matching.match_result.match_result_id"),
        nullable=True,
    )
    viewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    slot_requests: Mapped[list[MeetingSlotRequest]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    contact_share: Mapped[MeetingContactShare | None] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", uselist=False
    )
    status_history: Mapped[list[MeetingStatusHistory]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )
    outcome: Mapped[MeetingOutcome | None] = relationship(
        back_populates="meeting", cascade="all, delete-orphan", uselist=False
    )
    follow_up_actions: Mapped[list[FollowUpAction]] = relationship(
        back_populates="meeting", cascade="all, delete-orphan"
    )


class MeetingSlotRequest(Base):
    """interaction.meeting_slot_request - db-erd 14.3.

    "임의 start/end를 중복 저장하지 않는다"(14.3절 본문) - 시간은 availability_slot을
    통해서만 참조하고, 필요하면 snapshot_json에 요청 당시 슬롯 스냅샷만 남긴다.
    """

    __tablename__ = "meeting_slot_request"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "availability_slot_id",
            name="uq_meeting_slot_request_meeting_slot",
        ),
        CheckConstraint(
            f"status IN ({_in_list(MEETING_SLOT_REQUEST_STATUSES)})",
            name="status_allowed",
        ),
        {"schema": SCHEMA_INTERACTION},
    )

    meeting_slot_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_INTERACTION}.meeting.meeting_id"),
        nullable=False,
    )
    availability_slot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_INTERACTION}.availability_slot.availability_slot_id"),
        nullable=False,
    )
    preference_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="REQUESTED")
    snapshot_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    meeting: Mapped[Meeting] = relationship(back_populates="slot_requests")
    availability_slot: Mapped[AvailabilitySlot] = relationship(
        back_populates="slot_requests"
    )


class MeetingContactShare(Base):
    """interaction.meeting_contact_share - db-erd 14.4.

    "accepted_at만으로 연락처를 공개하지 않는다. meeting.status = CONFIRMED와 disclosed
    권한 검사를 함께 적용한다"(14.4절 본문) - 이 규칙은 서비스 계층 책임이며, 이 테이블은
    동의·실제 공개 시점을 분리해서 저장하는 데까지만 책임진다.
    """

    __tablename__ = "meeting_contact_share"
    __table_args__ = ({"schema": SCHEMA_INTERACTION},)

    meeting_contact_share_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_INTERACTION}.meeting.meeting_id"),
        nullable=False,
        unique=True,
    )
    consent_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.consent_policy.consent_policy_id"),
        nullable=True,
    )
    shared_fields: Mapped[dict] = mapped_column(JSONB, nullable=False)
    accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disclosed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disclosed_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.user_account.user_id"),
        nullable=True,
    )

    meeting: Mapped[Meeting] = relationship(back_populates="contact_share")


class MeetingStatusHistory(Base):
    """interaction.meeting_status_history - db-erd 14.5. Append-only."""

    __tablename__ = "meeting_status_history"
    __table_args__ = (
        CheckConstraint(
            f"previous_status IS NULL OR previous_status IN ({_in_list(MEETING_STATUSES)})",
            name="previous_status_allowed",
        ),
        CheckConstraint(
            f"new_status IN ({_in_list(MEETING_STATUSES)})", name="new_status_allowed"
        ),
        Index("idx_meeting_status_history_meeting", "meeting_id", "created_at"),
        {"schema": SCHEMA_INTERACTION},
    )

    meeting_status_history_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_INTERACTION}.meeting.meeting_id"),
        nullable=False,
    )
    previous_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.user_account.user_id"),
        nullable=True,
    )
    reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    meeting: Mapped[Meeting] = relationship(back_populates="status_history")


class MeetingOutcome(Base):
    """interaction.meeting_outcome - db-erd 14.5."""

    __tablename__ = "meeting_outcome"
    __table_args__ = (
        CheckConstraint(
            f"lead_status IN ({_in_list(MEETING_LEAD_STATUSES)})",
            name="lead_status_allowed",
        ),
        CheckConstraint(
            "estimated_probability IS NULL OR "
            "(estimated_probability >= 0 AND estimated_probability <= 100)",
            name="estimated_probability_range",
        ),
        {"schema": SCHEMA_INTERACTION},
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_INTERACTION}.meeting.meeting_id"),
        primary_key=True,
    )
    lead_status: Mapped[str] = mapped_column(String(20), nullable=False)
    outcome_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    estimated_value_amount: Mapped[int | None] = mapped_column(
        Numeric(14, 0), nullable=True
    )
    estimated_probability: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    notes_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    completed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    meeting: Mapped[Meeting] = relationship(back_populates="outcome")


class FollowUpAction(Base):
    """interaction.follow_up_action - db-erd 14.5."""

    __tablename__ = "follow_up_action"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_in_list(FOLLOW_UP_ACTION_STATUSES)})",
            name="status_allowed",
        ),
        Index("idx_follow_up_action_meeting", "meeting_id", "status"),
        {"schema": SCHEMA_INTERACTION},
    )

    follow_up_action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_INTERACTION}.meeting.meeting_id"),
        nullable=False,
    )
    action_code: Mapped[str] = mapped_column(String(50), nullable=False)
    owner_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.user_account.user_id"),
        nullable=True,
    )
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    meeting: Mapped[Meeting] = relationship(back_populates="follow_up_actions")
