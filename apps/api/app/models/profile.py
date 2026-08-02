"""profile 도메인 SQLAlchemy 모델.

근거 문서:
    - docs/07-user-profile-model.md 22절(프로파일 DB 구조) - 1차 근거. 이 문서가 db-erd-table-spec.md
      보다 최신·상세하므로 필드명이 다르면 이 문서를 우선한다 (작업 지시 원칙).
    - docs/db-erd-table-spec.md 8.4절, 10절 - 07번 문서에 없는 필드(tenant_id, event_id FK,
      guest_session_id, row_version, deleted_at 등)를 보충하거나, 07번 문서에 아예 없는
      VisitSession·BuyerNeed 테이블의 1차 근거로 사용한다.

이 파일에서 구현하는 테이블:
    1. profile.user_profile        - 07 22.1 + db-erd 10.1 보강
    2. profile.profile_attribute   - 07 22.2 (범용 속성 저장소, 6단계 온톨로지 참조)
    3. profile.inferred_preference - 07 22.3 (행동추론 선호 점수)
    4. profile.profile_version     - 07 22.5 + db-erd 10.7 보강
    5. profile.visit_session       - db-erd 8.4 (07 4.3절은 설명뿐이라 db-erd 필드를 그대로 따름)
    6. profile.context_profile     - 07 22.4 (visit_session에 딸린 상황 스냅샷)
    7. profile.buyer_need          - db-erd 10.5

의도적으로 이번 작업 범위에서 제외한 것:
    - profile.profile_goal, profile.consumer_preference, profile.preference_item,
      profile.buyer_need_item (db-erd 10.2~10.4, 10.6) : 이번 지시에서 명시적으로 요청된
      5개 07-문서 테이블 + VisitSession + BuyerNeed에 포함되지 않는다. preference_item과
      buyer_need_item은 ontology.concept_revision에 대한 FK가 필요하므로 후속 작업에서
      별도로 추가한다.

크로스 스키마 참조에 대한 메모:
    이 파일의 여러 컬럼은 core.tenant, profile.user_account, profile.guest_session,
    exhibition.event, exhibition.event_zone 등 다른 도메인 에이전트가 만드는 테이블을
    ForeignKey 문자열("스키마.테이블.컬럼")로 참조한다. SQLAlchemy는 이런 FK를 지연 결합
    (lazy resolve)하므로 이 모듈을 import하는 것 자체는 항상 문제 없지만, 실제 DB에
    CREATE TABLE을 적용하려면 참조 대상 테이블이 먼저 존재해야 한다.

    2026-08-01 기준 backend/alembic/versions/20260801_0002_0003_foundation.py("0003_foundation")가
    core.tenant, exhibition.event/event_day/event_zone, profile.user_account/role/user_role/
    guest_session/consent_policy/user_consent, identity.user_identity/authentication_method,
    privacy.*, audit.audit_log를 이미 생성하므로, 이 파일이 참조하는 대상 테이블은 모두
    존재한다. 이 도메인의 마이그레이션은 down_revision="0003_foundation"으로 그 뒤에 연결한다
    (profile_attribute/inferred_preference가 참조하는 ontology.concept_revision은
    0003_foundation이 의존하는 0002_ontology에서 생성됨).

    exhibition.event_zone의 PK 컬럼명은 db-erd-table-spec.md 12.1절에 명시되어 있지 않아
    "event_zone_id"로 가정했으나, 0003_foundation이 실제로 이 이름을 사용하는 것으로 확인했다.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    CHAR,
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    Numeric,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SCHEMA_EXHIBITION, SCHEMA_PROFILE, Base
from app.models.common import new_uuid7

_new_uuid = new_uuid7


class UserProfile(Base):
    """profile.user_profile - 07 22.1 + db-erd 10.1.

    행사 단위로 생성되는 추천용 사용자 프로파일의 루트 테이블이다. 회원 식별정보
    (이름·연락처·이메일 등)는 identity 스키마에 분리되어 있으며 이 테이블은 참조하지 않는다
    (07 2.1절 "식별정보와 추천정보 분리" 원칙).
    """

    __tablename__ = "user_profile"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_user_profile_event_boundary",
        ),
        # db-erd 2절: 게스트 프로파일은 user_id 또는 guest_session_id 중 정확히 하나만 소유자로 갖는다.
        CheckConstraint(
            "num_nonnulls(user_id, guest_session_id) = 1",
            name="exactly_one_owner",
        ),
        CheckConstraint(
            "completeness_score >= 0 AND completeness_score <= 100",
            name="completeness_score_range",
        ),
        CheckConstraint(
            "user_type IN ('GENERAL_VISITOR', 'BUYER')",
            name="user_type_allowed",
        ),
        CheckConstraint(
            "profile_status IN ('DRAFT', 'COMPLETE', 'INACTIVE')",
            name="profile_status_allowed",
        ),
        # db-erd 10.1 부분 유일성 (1/2): 인증 사용자는 (tenant, event, user, user_type) 단위로 하나.
        Index(
            "uq_user_profile_user_event_type",
            "tenant_id",
            "event_id",
            "user_id",
            "user_type",
            unique=True,
            postgresql_where=text("deleted_at IS NULL AND user_id IS NOT NULL"),
        ),
        # db-erd 10.1 부분 유일성 (2/2): 익명 사용자는 (tenant, event, guest_session, user_type) 단위로 하나.
        Index(
            "uq_user_profile_guest_event_type",
            "tenant_id",
            "event_id",
            "guest_session_id",
            "user_type",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND guest_session_id IS NOT NULL"
            ),
        ),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "profile_id",
            name="uq_user_profile_boundary_id",
        ),
        {"schema": SCHEMA_PROFILE},
    )

    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )

    # db-erd 10.1 보강: 07 문서는 event_id만 명시하지만, 멀티테넌시 원칙(db-erd 6.4)상
    # 업무 테이블은 tenant_id를 함께 가져야 한다.
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False
    )
    # 07 22.1: event_id (필수)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # 07 22.1: user_id. db-erd 10.1처럼 익명 사용자를 지원하기 위해 nullable로 두고
    # guest_session_id와 상호배타 CHECK를 건다.
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profile.user_account.user_id"), nullable=True
    )
    # db-erd 10.1 보강: 07 문서에는 없지만 db-erd 2절 "게스트 프로파일" 요구사항을 만족하려면
    # 필수인 컬럼이다.
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.guest_session.guest_session_id"),
        nullable=True,
    )

    user_type: Mapped[str] = mapped_column(String(30), nullable=False)
    profile_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DRAFT"
    )
    primary_goal_code: Mapped[str | None] = mapped_column(String(50), nullable=True)

    # 07 22.1 필드명은 completeness_score, db-erd 10.1은 completeness_percent - 07 우선.
    completeness_score: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    # db-erd 6.2/22.3절 보강: "프로파일 수정" 트랜잭션 경계에서 If-Match row_version 검사를
    # 요구하므로 낙관적 동시성 제어용 컬럼을 추가한다. 07 문서에는 없는 필드다.
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
    # db-erd 10.1 보강: 28.1절 "프로파일 초기화"/"전체 프로파일 삭제 요청" 사용자 통제기능을
    # 논리삭제로 구현하기 위한 컬럼. 07 문서에는 없다.
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    attributes: Mapped[list[ProfileAttribute]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    inferred_preferences: Mapped[list[InferredPreference]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    versions: Mapped[list[ProfileVersion]] = relationship(
        back_populates="profile", cascade="all, delete-orphan"
    )
    buyer_need: Mapped[BuyerNeed | None] = relationship(
        back_populates="profile", cascade="all, delete-orphan", uselist=False
    )


class ProfileAttribute(Base):
    """profile.profile_attribute - 07 22.2.

    명시적/암묵적 프로파일 속성을 범용 구조로 저장한다 (07 10절 "프로파일 속성 공통 구조").
    개념 ID만 저장하면 과거 의미를 재현할 수 없으므로 taxonomy_version_id와 concept_id를
    함께 ontology.concept_revision에 연결한다.

    attribute_code는 07 22.2 필드 목록에 명시된 비정규화 컬럼이다("조회·API용 개념 코드
    (비정규화 시 정본과 일치 검증)") - taxonomy_version_id/concept_id로 ontology를 매번
    조인하지 않고도 API 응답에서 코드값을 바로 노출하기 위함이다. 정본은 어디까지나
    ontology.concept.concept_code이며, (concept_id, attribute_code) 복합 FK가 일치를 강제한다.
    """

    __tablename__ = "profile_attribute"
    __table_args__ = (
        CheckConstraint(
            "requirement_level IN ('REQUIRED', 'PREFERRED', 'ACCEPTABLE', 'EXCLUDED')",
            name="requirement_level_allowed",
        ),
        # 07 11.1절 출처 코드 전체 목록.
        CheckConstraint(
            "source_type IN ("
            "'USER_SELECTED', 'USER_TYPED', 'USER_EDITED', 'REGISTRATION', "
            "'BEHAVIOR_SINGLE', 'BEHAVIOR_AGGREGATED', 'FEEDBACK', 'AI_EXTRACTED', "
            "'OPERATOR_CONFIRMED', 'DEFAULT', 'EXTERNAL_SYNC'"
            ")",
            name="source_type_allowed",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "freshness_score IS NULL OR (freshness_score >= 0 AND freshness_score <= 1)",
            name="freshness_score_range",
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until",
            name="valid_period_order",
        ),
        ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_profile_attribute_ontology_revision",
        ),
        ForeignKeyConstraint(
            ["concept_id", "attribute_code"],
            ["ontology.concept.concept_id", "ontology.concept.concept_code"],
            name="fk_profile_attribute_concept_code",
        ),
        Index(
            "ix_profile_attribute_lookup",
            "profile_id",
            "taxonomy_version_id",
            "concept_id",
            "active",
        ),
        {"schema": SCHEMA_PROFILE},
    )

    profile_attribute_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_profile.profile_id"),
        nullable=False,
    )

    taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # 07 22.2: attribute_code (비정규화 컬럼, 클래스 docstring 참고).
    attribute_code: Mapped[str] = mapped_column(String(100), nullable=False)

    value_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    requirement_level: Mapped[str] = mapped_column(String(20), nullable=False)
    priority: Mapped[int | None] = mapped_column(SmallInteger, nullable=True)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    source_reference_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=1)
    freshness_score: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    profile: Mapped[UserProfile] = relationship(back_populates="attributes")


class InferredPreference(Base):
    """profile.inferred_preference - 07 22.3.

    행동에서 추론한 속성별 선호 점수. 07 8절 "행동 기반 추론 규칙"에 따라 반복성·신뢰도가
    쌓이며 갱신되므로 (profile_id, taxonomy_version_id, concept_id) 조합을 유일하게 유지하고 재계산 시
    upsert하는 것을 전제로 한다 (07 문서에 명시적 제약은 없으나 합리적 구현 선택).

    attribute_code는 07 22.3 필드 목록의 비정규화 컬럼이다. profile_attribute와 동일한 근거로
    ontology 조인 없이 조회·API 응답에 코드값을 노출하기 위함이다 (ProfileAttribute docstring 참고).
    """

    __tablename__ = "inferred_preference"
    __table_args__ = (
        UniqueConstraint(
            "profile_id",
            "taxonomy_version_id",
            "concept_id",
            name="uq_inferred_preference_concept",
        ),
        ForeignKeyConstraint(
            ["taxonomy_version_id", "concept_id"],
            [
                "ontology.concept_revision.taxonomy_version_id",
                "ontology.concept_revision.concept_id",
            ],
            name="fk_inferred_preference_ontology_revision",
        ),
        ForeignKeyConstraint(
            ["concept_id", "attribute_code"],
            ["ontology.concept.concept_id", "ontology.concept.concept_code"],
            name="fk_inferred_preference_concept_code",
        ),
        CheckConstraint(
            "inferred_score >= -1 AND inferred_score <= 1", name="inferred_score_range"
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            "positive_evidence_count >= 0", name="positive_evidence_count_nonneg"
        ),
        CheckConstraint(
            "negative_evidence_count >= 0", name="negative_evidence_count_nonneg"
        ),
        {"schema": SCHEMA_PROFILE},
    )

    inferred_preference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_profile.profile_id"),
        nullable=False,
    )
    taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # 07 22.3: attribute_code (비정규화 컬럼, 클래스 docstring 참고).
    attribute_code: Mapped[str] = mapped_column(String(100), nullable=False)

    # 07 8.3절 예시상 0~1 사이 값으로 보이지만, 8.2절(긍정/부정 행동 분리)에 따라 부정적
    # 선호(비선호)를 함께 표현할 수 있도록 -1~1 범위로 잡는다.
    inferred_score: Mapped[float] = mapped_column(
        Numeric(5, 4), nullable=False, default=0
    )
    positive_evidence_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    negative_evidence_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0
    )
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=0)
    first_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    profile: Mapped[UserProfile] = relationship(back_populates="inferred_preferences")


class ProfileVersion(Base):
    """profile.profile_version - 07 22.5 + db-erd 10.7.

    프로파일 변경 시점의 전체 스냅샷을 불변 기록으로 저장한다 (07 4.4절 "추천 세션 스냅샷",
    22.3 트랜잭션 경계: 프로파일 수정 시 version_number 증가 + 스냅샷 생성).
    """

    __tablename__ = "profile_version"
    __table_args__ = (
        UniqueConstraint(
            "profile_id", "version_number", name="uq_profile_version_number"
        ),
        UniqueConstraint(
            "profile_id",
            "profile_version_id",
            name="uq_profile_version_profile_id_version_id",
        ),
        CheckConstraint("version_number >= 1", name="version_number_positive"),
        {"schema": SCHEMA_PROFILE},
    )

    profile_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_profile.profile_id"),
        nullable=False,
    )
    version_number: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_json: Mapped[dict] = mapped_column(JSONB, nullable=False)

    # db-erd 10.7 보강: 07 문서에는 없지만 스냅샷 무결성·중복탐지에 유용한 컬럼이다.
    snapshot_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    # db-erd 10.7은 change_reason 값으로 USER_UPDATE/FEEDBACK/AI_CONFIRMATION 3개만 예시하지만,
    # 07 25절(즉시/준실시간/배치 갱신 트리거)에는 이보다 훨씬 다양한 트리거가 나열되어 있어
    # 3개로 하드 CHECK 제약을 걸면 실제 트리거를 표현하지 못할 수 있다. 그래서 CHECK 없이
    # 자유 문자열로 두고 주석으로만 예시를 남긴다.
    change_reason: Mapped[str] = mapped_column(String(30), nullable=False)

    # 07 필드명은 source_event_id. db-erd 10.7은 source_interaction_event_id로 부르며
    # interaction.interaction_event(파티션 테이블, 복합 PK)를 가리킨다. 파티션 테이블은
    # 표준 FK 대상으로 쓰기 어려우므로 FK 없이 값만 저장한다.
    source_event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    profile: Mapped[UserProfile] = relationship(back_populates="versions")


class VisitSession(Base):
    """profile.visit_session - db-erd 8.4.

    07 문서에는 4.3절(방문 세션 프로파일)에 설명만 있고 DB 구조가 없으므로, 이미 상세 컬럼
    정의가 있는 db-erd-table-spec.md 8.4절을 그대로 따른다 (작업 지시사항).
    """

    __tablename__ = "visit_session"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_visit_session_event_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "current_zone_id"],
            [
                f"{SCHEMA_EXHIBITION}.event_zone.tenant_id",
                f"{SCHEMA_EXHIBITION}.event_zone.event_id",
                f"{SCHEMA_EXHIBITION}.event_zone.event_zone_id",
            ],
            name="fk_visit_session_zone_same_event",
        ),
        CheckConstraint(
            "num_nonnulls(user_id, guest_session_id) = 1", name="exactly_one_owner"
        ),
        CheckConstraint(
            "session_status IN ('PLANNED', 'ACTIVE', 'COMPLETED', 'CANCELLED')",
            name="session_status_allowed",
        ),
        CheckConstraint(
            "entry_at IS NULL OR exit_at IS NULL OR entry_at <= exit_at",
            name="entry_exit_order",
        ),
        CheckConstraint(
            "available_minutes IS NULL OR available_minutes >= 0",
            name="available_minutes_nonneg",
        ),
        Index("ix_visit_session_event_date", "tenant_id", "event_id", "visit_date"),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "visit_session_id",
            name="uq_visit_session_boundary_id",
        ),
        {"schema": SCHEMA_PROFILE},
    )

    visit_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profile.user_account.user_id"), nullable=True
    )
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("profile.guest_session.guest_session_id"),
        nullable=True,
    )
    profile_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_profile.profile_id"),
        nullable=True,
    )

    visit_date: Mapped[date] = mapped_column(Date, nullable=False)
    entry_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    exit_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    available_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # exhibition.event_zone의 PK 컬럼명은 db-erd에 명시되지 않아 관례상 event_zone_id로 가정함
    # (모듈 docstring 참고).
    current_zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    current_zone_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    route_preference: Mapped[str | None] = mapped_column(String(30), nullable=True)
    session_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PLANNED"
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

    context_profiles: Mapped[list[ContextProfile]] = relationship(
        back_populates="visit_session", cascade="all, delete-orphan"
    )


class ContextProfile(Base):
    """profile.context_profile - 07 22.4.

    추천 요청 시점에만 유효한 상황정보 스냅샷이다 (07 9절 "상황 프로파일"). 하나의 방문
    세션 동안 위치·잔여시간이 계속 바뀔 수 있으므로 visit_session_id 당 여러 행이 쌓일 수
    있다고 보고 유일 제약을 걸지 않았다.
    """

    __tablename__ = "context_profile"
    __table_args__ = (
        CheckConstraint(
            "remaining_minutes IS NULL OR remaining_minutes >= 0",
            name="remaining_minutes_nonneg",
        ),
        CheckConstraint(
            "max_walk_minutes IS NULL OR max_walk_minutes >= 0",
            name="max_walk_minutes_nonneg",
        ),
        Index("ix_context_profile_session_captured", "visit_session_id", "captured_at"),
        {"schema": SCHEMA_PROFILE},
    )

    context_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    visit_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.visit_session.visit_session_id"),
        nullable=False,
    )
    current_zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exhibition.event_zone.event_zone_id"),
        nullable=True,
    )
    remaining_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_walk_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    avoid_congestion: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    next_schedule_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    context_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    captured_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    visit_session: Mapped[VisitSession] = relationship(
        back_populates="context_profiles"
    )


class BuyerNeed(Base):
    """profile.buyer_need - db-erd 10.5.

    바이어 프로파일의 1:1 확장 테이블 (USER_PROFILE ||--o| BUYER_NEED : specializes, db-erd
    5절 논리 ERD). 07 문서 5.2/6.1절의 바이어 명시적 속성 항목과 대응한다.
    """

    __tablename__ = "buyer_need"
    __table_args__ = (
        CheckConstraint(
            "target_price_min_amount IS NULL OR target_price_min_amount >= 0",
            name="target_price_min_nonneg",
        ),
        CheckConstraint(
            "target_price_max_amount IS NULL OR target_price_max_amount >= 0",
            name="target_price_max_nonneg",
        ),
        CheckConstraint(
            "target_price_min_amount IS NULL OR target_price_max_amount IS NULL "
            "OR target_price_min_amount <= target_price_max_amount",
            name="target_price_order",
        ),
        CheckConstraint(
            "monthly_units_min IS NULL OR monthly_units_min >= 0",
            name="monthly_units_min_nonneg",
        ),
        CheckConstraint(
            "monthly_units_max IS NULL OR monthly_units_max >= 0",
            name="monthly_units_max_nonneg",
        ),
        CheckConstraint(
            "monthly_units_min IS NULL OR monthly_units_max IS NULL "
            "OR monthly_units_min <= monthly_units_max",
            name="monthly_units_order",
        ),
        CheckConstraint(
            "price_basis IS NULL OR price_basis IN ('RETAIL_PRICE', 'WHOLESALE_PRICE')",
            name="price_basis_allowed",
        ),
        {"schema": SCHEMA_PROFILE},
    )

    # 1:1 확장이므로 profile_id 자체가 PK이자 FK다.
    profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_profile.profile_id"),
        primary_key=True,
    )

    # 프로파일 유형이 아니라 조직 분류값이며 6단계 BUYER.* 코드 또는 별도 항목으로 정규화한다.
    organization_type: Mapped[str | None] = mapped_column(String(50), nullable=True)

    target_price_min_amount: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    target_price_max_amount: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, default="KRW")
    price_basis: Mapped[str | None] = mapped_column(String(30), nullable=True)

    monthly_units_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_units_max: Mapped[int | None] = mapped_column(Integer, nullable=True)

    decision_timeline: Mapped[str | None] = mapped_column(String(30), nullable=True)
    business_email_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    company_verified: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    profile: Mapped[UserProfile] = relationship(back_populates="buyer_need")
