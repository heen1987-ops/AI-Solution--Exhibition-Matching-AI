"""상담(미팅)·리드·후속조치 도메인 SQLAlchemy 모델 (interaction 스키마).

참고 문서
---------
- docs/db-erd-table-spec.md 2절 "원안 대비 필수 보정" 중 "상담 슬롯"·"연락처 공유" 보정사항
- docs/db-erd-table-spec.md 14절 "상담 가능시간과 상담" (availability_slot, meeting,
  meeting_slot_request, meeting_contact_share, meeting_status_history, meeting_outcome,
  follow_up_action)
- docs/db-erd-table-spec.md 22.1절 "상담 확정" 트랜잭션 경계
- docs/user-ia-wireframes.md 6.2절 "상담" 상태 머신, 8절 E-02~E-04 참가업체 포털 화면
- docs/frontend-backend-ai-interface-spec.md 12절 "상담 API"
- docs/2026-backju-ai-matching-service-design.md 5.1절 (엔터티 이름 MeetingRequest·Lead·FollowUp)

클래스 이름과 테이블 이름이 다른 이유
--------------------------------------
이 프로젝트의 문서 우선순위 규칙상 필드·테이블 명세는
docs/frontend-backend-ai-interface-spec.md > docs/db-erd-table-spec.md 순으로 따른다.
db-erd-table-spec.md 14절은 물리 테이블명을 meeting / meeting_outcome / follow_up_action으로
정의하므로 __tablename__은 그 이름을 그대로 쓴다. 다만 이 도메인을 지시한 상위 설계 문서
(2026-backju-ai-matching-service-design.md)와 작업 지시가 파이썬 클래스 이름으로
MeetingRequest·Lead·FollowUp을 명시적으로 요구하므로, 클래스 이름만 그 이름을 따르고
물리 스키마는 db-erd-table-spec.md를 그대로 따르는 방식으로 두 요구를 함께 만족시킨다.

상담 상태값 표기(대문자 vs 소문자)에 대한 문서 간 불일치 처리
--------------------------------------------------------------
- docs/user-ia-wireframes.md 6.2절은 상담 상태를 draft/requested/accepted/counter_proposed/
  rejected/cancelled/completed/no_show로 소문자로 정의한다.
- docs/frontend-backend-ai-interface-spec.md 12.1절과 docs/db-erd-table-spec.md 14.2절·22.1절
  예시는 DRAFT/REQUESTED/CONFIRMED 등 대문자를 쓰고, CANCELLED를 CANCELLED_BY_BUYER /
  CANCELLED_BY_EXHIBITOR로 더 세분화하며 ACCEPTED 대신 CONFIRMED라는 이름을 쓴다.
  이 문서는 이 파일 작성 지시에서 명시적으로 우선 참고 대상으로 지정되지 않았다.
- 이 파일을 작성하라는 지시가 "docs/user-ia-wireframes.md 6.2절 참고"로 상태 머신을 명시적으로
  지정했으므로, status 컬럼 값은 6.2절의 8개 상태(draft/requested/accepted/counter_proposed/
  rejected/cancelled/completed/no_show)를 그대로 따른다. 다른 두 문서의 CONFIRMED /
  CANCELLED_BY_BUYER / CANCELLED_BY_EXHIBITOR 표기와 다르다는 점을 후속 통합 작업자가 알 수
  있도록 이 주석에 남긴다. API 계층(다른 에이전트 담당)에서 문서별 표기를 매핑해야 한다면
  이 상수(MEETING_STATUSES)를 단일 진실 공급원으로 삼는다.

taxonomy 참조에 대하여
------------------------
작업 지시 시점에는 6단계(매칭 분류체계·온톨로지) 문서가 아직 없다고 전제했으나, 이 파일을
작성하는 시점에는 docs/06-matching-ontology.md가 이미 존재하고 db-erd-table-spec.md 11절도
"모든 업무 테이블은 개념을 참조할 때 concept_id만 저장하지 않고 (taxonomy_version_id,
concept_id)를 함께 FK로 둔다"고 명시한다. 즉 코드값 목록은 "taxonomy_term"이라는 단일 테이블이
아니라 ontology.concept(안정 ID·concept_code)와 ontology.concept_revision(버전별 스냅샷,
PK가 (taxonomy_version_id, concept_id))의 조합으로 정규화되며, 참조하는 쪽은 항상
(taxonomy_version_id, concept_id) 복합 FK를 둔다. 이 패턴은 이미 profile 도메인
(app/models/profile.py의 ProfileAttribute·InferredPreference)에 적용되어 있으므로 이 파일도
동일한 패턴을 따른다. db-erd-table-spec.md 14.1·14.2절의 "topic_term_id" 표기는 열 목록상의
축약일 뿐 실제 컬럼 구조가 아니다.

이에 따라 AvailabilitySlot·MeetingRequest의 주제, Lead의 결과코드, FollowUp의 조치코드는
모두 하나의 term_id 컬럼이 아니라 taxonomy_version_id·concept_id 한 쌍의 nullable 컬럼과
ontology.concept_revision을 향하는 복합 ForeignKeyConstraint로 표현한다(두 컬럼은 함께
NULL이거나 함께 NOT NULL이어야 하므로 CHECK 제약을 별도로 둔다 — PostgreSQL 복합 FK는
기본적으로 MATCH SIMPLE이라 한쪽만 NULL이면 제약이 아예 적용되지 않기 때문이다).

값 자체(concept_code)는 ontology.concept.concept_code의 형식 제약(대문자·점 구분 네임스페이스,
예: "MEETING_OUTCOME.QUALIFIED_LEAD")을 따라야 한다. 후보 값은
docs/user-ia-wireframes.md 8절 E-04 화면의 버튼 라벨(유효 리드/추가 검토/정보 제공/
조건 불일치, 샘플/견적/추가 미팅/연락 없음)을 참고해 시드 데이터로 나중에 채운다
(concept_code 네임스페이스 제안: MEETING_OUTCOME.*, FOLLOW_UP_ACTION.*). TODO(6단계 온톨로지
시드 확정 후): 실제 concept_code 값과 taxonomy_version을 확정하고 ontology.concept·
concept_revision 시드 마이그레이션을 추가한다.

상태 값 자체(meeting.status, availability_slot.status, meeting_slot_request.status,
follow_up_action.status)는 taxonomy 코드값이 아니라 애플리케이션 상태 머신이므로
CHECK 제약으로 고정한다. meeting.status는 문서(6.2절)에 정확히 정의되어 있고,
availability_slot.status는 db-erd-table-spec.md 14.1절이 OPEN/FULL/BLOCKED로 명시한다.
meeting_slot_request.status와 follow_up_action.status는 두 문서 모두 값 목록을 명시하지
않으므로 합리적 기본값(PENDING 등)을 두고 TODO로 표시한다.

다른 도메인 모델과의 관계
--------------------------
이 모듈은 여러 에이전트가 동시에 다른 도메인 모델 파일을 작성 중이라는 전제 하에,
다른 스키마의 테이블은 app/db/base.py가 안내하는 대로 "스키마명.테이블명.컬럼명" 문자열
ForeignKey 경로만 사용하고 다른 모델 모듈을 import하지 않는다. ORM relationship()은 이
파일 안에서 함께 정의되는 클래스 사이에만 사용한다.

RLS(행 수준 보안)와 identity/audit 스키마 접근 통제는 인프라/운영 작업 범위이며 이
모델 파일에서 다루지 않는다 (app/db/base.py 하단 설명 참고).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CHAR,
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
    literal_column,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID, ExcludeConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base, SCHEMA_INTERACTION

# --------------------------------------------------------------------------
# 상태값 상수. CHECK 제약과 애플리케이션 코드가 같은 값을 참조하도록 단일 진실 공급원으로 둔다.
# --------------------------------------------------------------------------

#: docs/user-ia-wireframes.md 6.2절 상담 상태 머신.
#: draft -> requested -> (accepted|counter_proposed|rejected|cancelled) -> (completed|no_show)
MEETING_STATUSES: tuple[str, ...] = (
    "draft",
    "requested",
    "accepted",
    "counter_proposed",
    "rejected",
    "cancelled",
    "completed",
    "no_show",
)

#: 상담이 실제로 "확정"된 것으로 간주되는 상태. confirmed_start/confirmed_end가 채워지고
#: 겹침 방지 EXCLUDE 제약이 적용되는 상태다. db-erd-table-spec.md 22.1절의 "meeting CONFIRMED"
#: 단계에 해당하며, 이 프로젝트에서는 6.2절 표기를 따라 "accepted"로 부른다.
MEETING_CONFIRMED_STATUS = "accepted"

#: docs/db-erd-table-spec.md 14.1절.
AVAILABILITY_SLOT_STATUSES: tuple[str, ...] = ("OPEN", "FULL", "BLOCKED")

#: 문서에 값 목록이 없어 잠정 정의. TODO(6단계 또는 API 상세설계 확정 후 재검토):
#: 바이어가 여러 슬롯을 우선순위로 요청할 때(preference_order) 각 후보의 처리 상태.
MEETING_SLOT_REQUEST_STATUSES: tuple[str, ...] = (
    "PENDING",
    "SELECTED",
    "DECLINED",
    "WITHDRAWN",
)

#: 문서에 값 목록이 없어 잠정 정의. TODO(6단계 또는 API 상세설계 확정 후 재검토): 후속조치 진행상태.
FOLLOW_UP_ACTION_STATUSES: tuple[str, ...] = (
    "PENDING",
    "IN_PROGRESS",
    "DONE",
    "CANCELLED",
)


def _sql_in_list(values: tuple[str, ...]) -> str:
    """CHECK 제약의 'col IN (...)' 리터럴 목록 문자열을 상수 튜플에서 생성한다."""

    return ", ".join(f"'{value}'" for value in values)


class AvailabilitySlot(Base):
    """interaction.availability_slot — docs/db-erd-table-spec.md 14.1절.

    업체 담당자가 상담 가능하다고 열어둔 시간 슬롯. MeetingRequest는 임의의 시작·종료 시각을
    직접 저장하지 않고 이 테이블의 행을 FK로 참조한 뒤(요청) 확정 시 원자적으로 점유한다
    (2절 "상담 슬롯" 보정사항).
    """

    __tablename__ = "availability_slot"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_availability_slot_tenant_event",
        ),
        CheckConstraint("start_at < end_at", name="time_range"),
        CheckConstraint("capacity > 0", name="capacity_positive"),
        CheckConstraint(
            "reserved_count >= 0 AND reserved_count <= capacity",
            name="reserved_count_within_capacity",
        ),
        CheckConstraint(
            f"status IN ({_sql_in_list(AVAILABILITY_SLOT_STATUSES)})",
            name="status_allowed",
        ),
        # 주제 개념 참조. 모듈 docstring "taxonomy 참조에 대하여" 참고 — 단일 term_id가 아니라
        # (taxonomy_version_id, concept_id) 복합 FK다.
        CheckConstraint(
            "(taxonomy_version_id IS NULL) = (concept_id IS NULL)",
            name="topic_concept_pair",
        ),
        ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_availability_slot_ontology_revision",
        ),
        # 문서에 명시된 인덱스는 아니지만, 업체 담당자가 특정 기간의 자기 슬롯을 조회하는
        # 흔한 조회 패턴(참가업체 포털 일정 화면)을 지원하기 위해 추가한다.
        Index(
            "ix_availability_slot_participation_start",
            "participation_id",
            "start_at",
        ),
        {"schema": SCHEMA_INTERACTION},
    )

    availability_slot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    participation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exhibition.exhibitor_participation.participation_id"),
        nullable=False,
    )
    staff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exhibition.exhibitor_staff.staff_id"),
        nullable=True,
    )
    booth_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exhibition.booth.booth_id"), nullable=True
    )
    # 상담 주제 개념. 단일 term_id가 아니라 (taxonomy_version_id, concept_id) 복합 컬럼으로
    # __table_args__의 ForeignKeyConstraint를 통해 ontology.concept_revision을 참조한다.
    taxonomy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    capacity: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=1)
    reserved_count: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="OPEN")
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    slot_requests: Mapped[list["MeetingSlotRequest"]] = relationship(
        "MeetingSlotRequest", back_populates="slot"
    )


class MeetingRequest(Base):
    """interaction.meeting — docs/db-erd-table-spec.md 14.2절.

    상담 요청·확정 본문. 파이썬 클래스 이름은 작업 지시와
    docs/2026-backju-ai-matching-service-design.md 5.1절 표기(MeetingRequest)를 따르고,
    물리 테이블명은 db-erd-table-spec.md 14.2절이 정의한 "meeting"을 그대로 쓴다.

    상태 머신은 MEETING_STATUSES(docs/user-ia-wireframes.md 6.2절)를 따른다.
    확정(accepted) 시점에 confirmed_slot_id/confirmed_start/confirmed_end를 채우고,
    담당자·바이어 각각에 대해 같은 시간대 중복 확정을 EXCLUDE 제약으로 원자적으로 차단한다
    (db-erd-table-spec.md 14.5절, 22.1절).
    """

    __tablename__ = "meeting"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            ["exhibition.event.tenant_id", "exhibition.event.event_id"],
            name="fk_meeting_tenant_event",
        ),
        CheckConstraint(
            f"status IN ({_sql_in_list(MEETING_STATUSES)})", name="status_allowed"
        ),
        CheckConstraint(
            "confirmed_start IS NULL OR confirmed_end IS NULL "
            "OR confirmed_start < confirmed_end",
            name="confirmed_range",
        ),
        # 주제 개념 참조. 모듈 docstring "taxonomy 참조에 대하여" 참고 — 단일 term_id가 아니라
        # (taxonomy_version_id, concept_id) 복합 FK다.
        CheckConstraint(
            "(taxonomy_version_id IS NULL) = (concept_id IS NULL)",
            name="topic_concept_pair",
        ),
        ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_meeting_ontology_revision",
        ),
        # docs/db-erd-table-spec.md 14.5절 "확정 상담 겹침 방지" 예시를 그대로 반영하되,
        # 상태값은 이 파일 상단 주석에서 설명한 이유로 CONFIRMED 대신 'accepted'를 쓴다.
        # UUID 컬럼에 대한 '=' 연산자를 GiST 인덱스에서 쓰려면 btree_gist 확장이 필요하다
        # (해당 마이그레이션에서 CREATE EXTENSION IF NOT EXISTS btree_gist 실행).
        ExcludeConstraint(
            ("staff_id", "="),
            (
                func.tstzrange(
                    literal_column("confirmed_start"),
                    literal_column("confirmed_end"),
                    "[)",
                ),
                "&&",
            ),
            where=text(f"status = '{MEETING_CONFIRMED_STATUS}' AND staff_id IS NOT NULL"),
            using="gist",
            name="ex_meeting_staff_confirmed_overlap",
        ),
        # "바이어 profile에도 같은 시간범위 exclusion을 적용한다" (14.5절).
        ExcludeConstraint(
            ("buyer_profile_id", "="),
            (
                func.tstzrange(
                    literal_column("confirmed_start"),
                    literal_column("confirmed_end"),
                    "[)",
                ),
                "&&",
            ),
            where=text(f"status = '{MEETING_CONFIRMED_STATUS}'"),
            using="gist",
            name="ex_meeting_buyer_confirmed_overlap",
        ),
        Index(
            "idx_meeting_buyer_time",
            "buyer_profile_id",
            "confirmed_start",
            postgresql_where=text(f"status = '{MEETING_CONFIRMED_STATUS}'"),
        ),
        Index(
            "idx_meeting_staff_time",
            "staff_id",
            "confirmed_start",
            postgresql_where=text(f"status = '{MEETING_CONFIRMED_STATUS}'"),
        ),
        # docs/frontend-backend-ai-interface-spec.md 15절 GET /partner/meetings?status=... 조회 지원.
        Index("idx_meeting_participation_status", "participation_id", "status"),
        {"schema": SCHEMA_INTERACTION},
    )

    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
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
        ForeignKey("exhibition.exhibitor_participation.participation_id"),
        nullable=False,
    )
    staff_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exhibition.exhibitor_staff.staff_id"),
        nullable=True,
    )
    booth_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("exhibition.booth.booth_id"), nullable=True
    )
    # 상담 주제 개념. 단일 term_id가 아니라 (taxonomy_version_id, concept_id) 복합 컬럼으로
    # __table_args__의 ForeignKeyConstraint를 통해 ontology.concept_revision을 참조한다.
    taxonomy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    # 상담 자유메모 원문. 애플리케이션 계층에서 봉투암호화 후 저장한다(identity 스키마의
    # name_enc/phone_enc와 동일한 패턴). 이 모델은 암복호화를 수행하지 않는다.
    message_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, default="draft")
    confirmed_slot_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interaction.availability_slot.availability_slot_id"),
        nullable=True,
    )
    confirmed_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    confirmed_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    match_result_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("matching.match_result.match_result_id"),
        nullable=True,
    )
    viewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    row_version: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    confirmed_slot: Mapped["AvailabilitySlot | None"] = relationship(
        "AvailabilitySlot", foreign_keys=[confirmed_slot_id]
    )
    slot_requests: Mapped[list["MeetingSlotRequest"]] = relationship(
        "MeetingSlotRequest", back_populates="meeting"
    )
    contact_share: Mapped["MeetingContactShare | None"] = relationship(
        "MeetingContactShare", back_populates="meeting", uselist=False
    )
    status_history: Mapped[list["MeetingStatusHistory"]] = relationship(
        "MeetingStatusHistory", back_populates="meeting"
    )
    outcome: Mapped["Lead | None"] = relationship(
        "Lead", back_populates="meeting", uselist=False
    )
    follow_ups: Mapped[list["FollowUp"]] = relationship(
        "FollowUp", back_populates="meeting"
    )


class MeetingSlotRequest(Base):
    """interaction.meeting_slot_request — docs/db-erd-table-spec.md 14.3절.

    바이어가 상담 요청 시 우선순위를 매겨 제시한 후보 슬롯들. "임의 start/end를 중복
    저장하지 않는다"는 지침에 따라 시간 자체는 저장하지 않고 availability_slot을 FK로
    참조하며, 요청 당시 슬롯 스냅샷이 필요할 때만 snapshot_json에 담는다.
    """

    __tablename__ = "meeting_slot_request"
    __table_args__ = (
        UniqueConstraint(
            "meeting_id",
            "availability_slot_id",
            name="uq_meeting_slot_request_meeting_slot",
        ),
        UniqueConstraint(
            "meeting_id",
            "preference_order",
            name="uq_meeting_slot_request_meeting_preference",
        ),
        CheckConstraint("preference_order > 0", name="preference_order_positive"),
        CheckConstraint(
            f"status IN ({_sql_in_list(MEETING_SLOT_REQUEST_STATUSES)})",
            name="status_allowed",
        ),
        {"schema": SCHEMA_INTERACTION},
    )

    meeting_slot_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interaction.meeting.meeting_id"),
        nullable=False,
    )
    availability_slot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interaction.availability_slot.availability_slot_id"),
        nullable=False,
    )
    preference_order: Mapped[int] = mapped_column(SmallInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    # 요청 당시 슬롯 스냅샷(시작·종료·담당자 등). 재현·감사 목적, 선택적.
    snapshot_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    meeting: Mapped["MeetingRequest"] = relationship(
        "MeetingRequest", back_populates="slot_requests"
    )
    slot: Mapped["AvailabilitySlot"] = relationship(
        "AvailabilitySlot", back_populates="slot_requests"
    )


class MeetingContactShare(Base):
    """interaction.meeting_contact_share — docs/db-erd-table-spec.md 14.4절.

    2절 "연락처 공유" 보정사항: 단순 boolean 동의가 아니라 상담별로 공유하기로 한 항목
    (shared_fields), 동의 문서 버전(consent_policy_id), 실제 공개 시각(disclosed_at)을
    각각 저장한다. accepted_at은 상담 요청 시점의 "동의 선택"만 기록하며, 실제 연락처
    공개 여부는 meeting.status가 확정 상태(MEETING_CONFIRMED_STATUS)인지와 별도 권한
    검사를 함께 적용해 API 계층에서 판단한다(14.4절: "accepted_at만으로 연락처를 공개하지
    않는다").
    """

    __tablename__ = "meeting_contact_share"
    __table_args__ = (
        CheckConstraint(
            "disclosed_at IS NULL OR disclosed_to_user_id IS NOT NULL",
            name="disclosure_requires_viewer",
        ),
        {"schema": SCHEMA_INTERACTION},
    )

    meeting_contact_share_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interaction.meeting.meeting_id"),
        nullable=False,
        unique=True,
    )
    consent_policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.consent_policy.consent_policy_id"),
        nullable=False,
    )
    # 예: ["NAME", "PHONE", "BUSINESS_EMAIL"] (docs/frontend-backend-ai-interface-spec.md 12.3절).
    shared_fields: Mapped[list[str]] = mapped_column(JSONB, nullable=False)
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    disclosed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disclosed_to_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.user_account.user_id"),
        nullable=True,
    )

    meeting: Mapped["MeetingRequest"] = relationship(
        "MeetingRequest", back_populates="contact_share"
    )


class MeetingStatusHistory(Base):
    """interaction.meeting_status_history — docs/db-erd-table-spec.md 14.5절.

    append-only 상태 전이 이력. 이전·신규 상태, 변경자, 사유코드, request_id(멱등키 등
    상관관계 추적용)를 남긴다. 이 클래스는 업데이트·삭제를 막는 DB 트리거를 만들지 않는다
    (트리거/권한 설정은 인프라 작업 범위); 리포지토리 계층에서 INSERT 전용으로 다뤄야 한다.
    """

    __tablename__ = "meeting_status_history"
    __table_args__ = (
        CheckConstraint(
            f"previous_status IS NULL OR previous_status IN ({_sql_in_list(MEETING_STATUSES)})",
            name="previous_status_allowed",
        ),
        CheckConstraint(
            f"new_status IN ({_sql_in_list(MEETING_STATUSES)})",
            name="new_status_allowed",
        ),
        Index("ix_meeting_status_history_meeting_created", "meeting_id", "created_at"),
        {"schema": SCHEMA_INTERACTION},
    )

    meeting_status_history_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interaction.meeting.meeting_id"),
        nullable=False,
    )
    previous_status: Mapped[str | None] = mapped_column(String(30), nullable=True)
    new_status: Mapped[str] = mapped_column(String(30), nullable=False)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.user_account.user_id"),
        nullable=True,
    )
    reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 상태 전이를 유발한 API 요청과의 상관관계 추적(예: Idempotency-Key 발급 요청).
    # integration 스키마의 멱등성 레코드 테이블은 다른 에이전트가 소유하므로 여기서는
    # FK를 걸지 않고 값만 저장한다.
    request_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    meeting: Mapped["MeetingRequest"] = relationship(
        "MeetingRequest", back_populates="status_history"
    )


class Lead(Base):
    """interaction.meeting_outcome — docs/db-erd-table-spec.md 14.5절.

    파이썬 클래스 이름은 작업 지시와 docs/2026-backju-ai-matching-service-design.md 5.1절
    표기(Lead)를 따르고, 물리 테이블명은 db-erd-table-spec.md 14.5절이 정의한
    "meeting_outcome"을 그대로 쓴다. 상담 1건당 결과는 하나이므로 meeting_id는 UNIQUE다.

    결과코드는 outcome_term_id 단일 컬럼이 아니라 taxonomy_version_id·concept_id 복합
    컬럼으로 두고, 위 모듈 docstring의 "taxonomy 참조에 대하여" 설명대로
    (taxonomy_version_id, concept_id) 복합 FK로 ontology.concept_revision을 참조한다
    (concept_code 네임스페이스 제안: MEETING_OUTCOME.*). 후보 값은
    docs/user-ia-wireframes.md 8절 E-04 화면 기준 유효 리드/추가 검토/정보 제공/조건
    불일치이며, 정확한 concept_code는 시드 데이터로 나중에 채운다.
    """

    __tablename__ = "meeting_outcome"
    __table_args__ = (
        CheckConstraint(
            "expected_probability_percent IS NULL OR "
            "(expected_probability_percent >= 0 AND expected_probability_percent <= 100)",
            name="probability_range",
        ),
        CheckConstraint(
            "(taxonomy_version_id IS NULL) = (concept_id IS NULL)",
            name="outcome_concept_pair",
        ),
        ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_meeting_outcome_ontology_revision",
        ),
        {"schema": SCHEMA_INTERACTION},
    )

    meeting_outcome_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interaction.meeting.meeting_id"),
        nullable=False,
        unique=True,
    )
    is_qualified_lead: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # TODO(6단계 온톨로지 시드 확정 후): concept_code가 'MEETING_OUTCOME.'로 시작하는
    # ontology.concept/concept_revision으로 시드한다.
    taxonomy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    expected_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str | None] = mapped_column(CHAR(3), nullable=True, default="KRW")
    expected_probability_percent: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    # 상담 결과 자유메모. message_enc와 동일하게 애플리케이션 계층에서 암호화 후 저장한다.
    memo_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    recorded_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.user_account.user_id"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    meeting: Mapped["MeetingRequest"] = relationship(
        "MeetingRequest", back_populates="outcome"
    )


class FollowUp(Base):
    """interaction.follow_up_action — docs/db-erd-table-spec.md 14.5절.

    파이썬 클래스 이름은 작업 지시와 docs/2026-backju-ai-matching-service-design.md 5.1절
    표기(FollowUp)를 따르고, 물리 테이블명은 db-erd-table-spec.md 14.5절이 정의한
    "follow_up_action"을 그대로 쓴다. docs/user-ia-wireframes.md 8절 E-04 화면(상담결과와
    같은 화면에서 저장)처럼 한 상담에 후속조치가 시간 흐름에 따라 여러 건 생길 수 있으므로
    meeting_id에 직접 연결하고(1:N), meeting_outcome에는 종속시키지 않는다.

    조치코드도 Lead와 동일한 이유로 action_term_id 단일 컬럼이 아니라 taxonomy_version_id·
    concept_id 복합 컬럼으로 두고 ontology.concept_revision을 복합 FK로 참조한다
    (concept_code 네임스페이스 제안: FOLLOW_UP_ACTION.*). 후보 값은 E-04 화면 기준
    샘플/견적/추가 미팅/연락 없음이며, 정확한 concept_code는 시드 데이터로 나중에 채운다.
    """

    __tablename__ = "follow_up_action"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_sql_in_list(FOLLOW_UP_ACTION_STATUSES)})",
            name="status_allowed",
        ),
        CheckConstraint(
            "(taxonomy_version_id IS NULL) = (concept_id IS NULL)",
            name="action_concept_pair",
        ),
        ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_follow_up_action_ontology_revision",
        ),
        Index("ix_follow_up_action_meeting_status", "meeting_id", "status"),
        {"schema": SCHEMA_INTERACTION},
    )

    follow_up_action_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    meeting_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("interaction.meeting.meeting_id"),
        nullable=False,
    )
    # TODO(6단계 온톨로지 시드 확정 후): concept_code가 'FOLLOW_UP_ACTION.'로 시작하는
    # ontology.concept/concept_revision으로 시드한다.
    taxonomy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    concept_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    assignee_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.user_account.user_id"),
        nullable=True,
    )
    # docs/user-ia-wireframes.md 8절 E-04 "다음 연락일 [날짜]" — 날짜 단위 필드.
    due_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # E-04 화면의 자유 메모. 민감정보 입력 금지 안내는 UI 책임이지만, 만일을 대비해
    # message_enc/memo_enc와 동일하게 암호화 저장 컬럼으로 둔다.
    note_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    meeting: Mapped["MeetingRequest"] = relationship(
        "MeetingRequest", back_populates="follow_ups"
    )
