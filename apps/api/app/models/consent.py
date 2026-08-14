"""동의·개인정보 권리·감사(신뢰) 도메인 SQLAlchemy 모델.

근거 문서:
    - docs/db-erd-table-spec.md 9.1~9.4절(동의·개인정보 권리), 20.1절(감사로그) - 1차 근거.
    - docs/frontend-backend-ai-interface-spec.md 7.4절(자격·동의 API) - purpose 값 예시와
      동의 갱신 시 현재상태+불변이력 병행 원칙의 API 표면 근거.

이 파일에서 구현하는 테이블:
    1. profile.consent_policy   - db-erd 9.1
    2. profile.user_consent     - db-erd 9.2
    3. privacy.privacy_request  - db-erd 9.3
    4. privacy.retention_policy - db-erd 9.4 (표 없음, 산문 기반 추정 구조)
    5. privacy.deletion_job     - db-erd 9.4 (표 없음, 산문 기반 추정 구조)
    6. audit.audit_log          - db-erd 20.1

consent_policy.purpose / required_for에 대한 메모:
    db-erd 9.2절은 목적 목록을 "목적 예시:"라는 표제 아래 5개(AGE_CONFIRMATION 등)를 든다.
    "예시"라고 명시했으므로 이 값들로 CHECK 제약을 걸지 않고 자유 문자열로 둔다 - 새 목적이
    추가될 때마다 스키마 마이그레이션이 필요해지는 것을 막기 위함이다. required_for도
    "AGE_SERVICE, PERSONALIZATION 등"으로 "등"이 붙어 있어 동일하게 자유 문자열로 둔다.
    반대로 privacy_request.request_type/status, audit_log.action_type처럼 "등" 표시 없이
    확정적으로 나열된 값은 CHECK 제약으로 강제한다.

retention_policy / deletion_job에 대한 메모:
    db-erd 9.4절은 표가 없고 다음 산문 설명만 있다:
      - retention_policy: "데이터분류, 목적, 시작점, 기간, 파기방법, 법적 보존 예외, 정책버전"
      - deletion_job: "privacy_request 또는 만료정책을 원인으로 생성하며 테이블별 처리상태,
        재시도, 비식별화 결과, 완료시각을 기록"
    아래 컬럼 설계는 이 설명을 그대로 컬럼화한 합리적 추정이다. 정확한 기산점 코드값,
    파기방법 코드값 등은 6단계류 세부설계가 없어 자유 문자열로 두었다.

audit_log에 대한 메모:
    db-erd 6.2절 규칙대로 이 테이블에는 updated_at/row_version을 두지 않는다(append-only).
    actor_role은 profile.role을 FK로 참조하지 않고 행위 시점의 값을 그대로 스냅샷 저장한다
    - 감사로그는 나중에 역할이 바뀌거나 삭제되어도 당시 사실을 보존해야 하기 때문이다.
    DB 역할의 UPDATE/DELETE 금지 및 WORM/해시체인 보강(db-erd 20.1절)은 인프라 작업 범위다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    SCHEMA_AUDIT,
    SCHEMA_CORE,
    SCHEMA_EXHIBITION,
    SCHEMA_PRIVACY,
    SCHEMA_PROFILE,
    Base,
)
from app.models.common import new_uuid7

_new_uuid = new_uuid7


class ConsentPolicy(Base):
    """profile.consent_policy - db-erd 9.1."""

    __tablename__ = "consent_policy"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_consent_policy_event_boundary",
        ),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "purpose",
            "document_version",
            name="uq_consent_policy_tenant_event_purpose_version",
            postgresql_nulls_not_distinct=True,
        ),
        CheckConstraint(
            "effective_until IS NULL OR effective_from <= effective_until",
            name="effective_period_order",
        ),
        {"schema": SCHEMA_PROFILE},
    )

    consent_policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"),
        nullable=False,
    )
    # "행사별 정책, 공통이면 NULL" (db-erd 9.1절).
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # 예: AGE_CONFIRMATION, PERSONALIZED_RECOMMENDATION 등 - "예시"이므로 자유 문자열.
    purpose: Mapped[str] = mapped_column(String(50), nullable=False)
    document_version: Mapped[str] = mapped_column(String(50), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    # 예: AGE_SERVICE, PERSONALIZATION 등 - "등"이 붙어 있어 자유 문자열.
    required_for: Mapped[str | None] = mapped_column(String(50), nullable=True)
    effective_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    effective_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    content_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user_consents: Mapped[list[UserConsent]] = relationship(
        back_populates="consent_policy"
    )


class UserConsent(Base):
    """profile.user_consent - db-erd 9.2.

    선택 이력은 불변으로 쌓는다 - "과거 행을 update하여 철회를 덮어쓰지 않는다"(db-erd 9.2절).
    """

    __tablename__ = "user_consent"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_user_consent_event_boundary",
        ),
        CheckConstraint(
            "num_nonnulls(user_id, guest_session_id) = 1", name="exactly_one_owner"
        ),
        CheckConstraint(
            "source_channel IS NULL OR source_channel IN ('WEB', 'QR', 'KIOSK')",
            name="source_channel_allowed",
        ),
        Index("ix_user_consent_policy_id", "consent_policy_id"),
        {"schema": SCHEMA_PROFILE},
    )

    consent_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"),
        nullable=False,
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=True,
    )
    guest_session_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.guest_session.guest_session_id"),
        nullable=True,
    )
    consent_policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.consent_policy.consent_policy_id"),
        nullable=False,
    )
    accepted: Mapped[bool] = mapped_column(nullable=False)
    source_channel: Mapped[str | None] = mapped_column(String(20), nullable=True)
    ip_hmac: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    consent_policy: Mapped[ConsentPolicy] = relationship(back_populates="user_consents")


class PrivacyRequest(Base):
    """privacy.privacy_request - db-erd 9.3."""

    __tablename__ = "privacy_request"
    __table_args__ = (
        CheckConstraint(
            "request_type IN ('ACCESS', 'EXPORT', 'CORRECT', 'DELETE', 'WITHDRAW')",
            name="request_type_allowed",
        ),
        CheckConstraint(
            "status IN ('RECEIVED', 'VERIFYING', 'PROCESSING', 'COMPLETED', 'REJECTED')",
            name="status_allowed",
        ),
        {"schema": SCHEMA_PRIVACY},
    )

    privacy_request_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
    )
    request_type: Mapped[str] = mapped_column(String(30), nullable=False)
    scope_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    status: Mapped[str] = mapped_column(
        String(30), nullable=False, server_default="RECEIVED"
    )
    rejection_reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    requested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    due_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    deletion_jobs: Mapped[list[DeletionJob]] = relationship(
        back_populates="privacy_request"
    )


class RetentionPolicy(Base):
    """privacy.retention_policy - db-erd 9.4 (표 없음, 모듈 docstring의 추정 구조 참고)."""

    __tablename__ = "retention_policy"
    __table_args__ = (
        UniqueConstraint(
            "tenant_id",
            "data_category",
            "purpose",
            "policy_version",
            name="uq_retention_policy_tenant_category_purpose_version",
        ),
        CheckConstraint(
            "retention_period_days >= 0", name="retention_period_days_nonneg"
        ),
        {"schema": SCHEMA_PRIVACY},
    )

    retention_policy_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"),
        nullable=False,
    )
    # 데이터분류 (예: IDENTITY_DIRECT, BEHAVIOR_EVENT 등) - 6단계류 코드값 미확정, 자유 문자열.
    data_category: Mapped[str] = mapped_column(String(100), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    # 기산점 (예: COLLECTED_AT, CONSENT_WITHDRAWN_AT, EVENT_ENDED_AT) - 자유 문자열.
    start_point_code: Mapped[str] = mapped_column(String(50), nullable=False)
    retention_period_days: Mapped[int] = mapped_column(Integer, nullable=False)
    # 파기방법 (예: HARD_DELETE, ANONYMIZE, KEY_DESTRUCTION) - 자유 문자열.
    disposal_method: Mapped[str] = mapped_column(String(50), nullable=False)
    legal_hold_exception: Mapped[str | None] = mapped_column(Text, nullable=True)
    policy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    deletion_jobs: Mapped[list[DeletionJob]] = relationship(
        back_populates="retention_policy"
    )


class DeletionJob(Base):
    """privacy.deletion_job - db-erd 9.4 (표 없음, 모듈 docstring의 추정 구조 참고).

    privacy_request 또는 retention_policy(만료) 중 최소 하나를 원인으로 가진다.
    """

    __tablename__ = "deletion_job"
    __table_args__ = (
        CheckConstraint(
            "num_nonnulls(privacy_request_id, retention_policy_id) >= 1",
            name="at_least_one_cause",
        ),
        CheckConstraint(
            "status IN ('PENDING', 'IN_PROGRESS', 'COMPLETED', 'FAILED')",
            name="status_allowed",
        ),
        CheckConstraint("retry_count >= 0", name="retry_count_nonneg"),
        {"schema": SCHEMA_PRIVACY},
    )

    deletion_job_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"),
        nullable=False,
    )
    privacy_request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PRIVACY}.privacy_request.privacy_request_id"),
        nullable=True,
    )
    retention_policy_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PRIVACY}.retention_policy.retention_policy_id"),
        nullable=True,
    )
    # "테이블별 처리상태"(db-erd 9.4절) - 삭제 대상 테이블/객체 단위로 한 행씩 기록한다.
    target_table: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="PENDING"
    )
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    anonymization_result: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    privacy_request: Mapped[PrivacyRequest | None] = relationship(
        back_populates="deletion_jobs"
    )
    retention_policy: Mapped[RetentionPolicy | None] = relationship(
        back_populates="deletion_jobs"
    )


class AuditLog(Base):
    """audit.audit_log - db-erd 20.1.

    append-only. updated_at/row_version을 두지 않는다 (모듈 docstring 참고).
    """

    __tablename__ = "audit_log"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_audit_log_event_boundary",
        ),
        CheckConstraint(
            "action_type IN ('VIEW', 'CREATE', 'UPDATE', 'DELETE', 'EXPORT', 'APPROVE')",
            name="action_type_allowed",
        ),
        CheckConstraint(
            "actor_role IS NULL OR actor_role IN "
            "('VISITOR', 'BUYER', 'EXHIBITOR', 'OPERATOR', 'ADMIN')",
            name="actor_role_allowed",
        ),
        Index(
            "ix_audit_log_tenant_event_occurred_at",
            "tenant_id",
            "event_id",
            "occurred_at",
        ),
        Index("ix_audit_log_resource", "resource_type", "resource_id"),
        {"schema": SCHEMA_AUDIT},
    )

    audit_log_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"), nullable=True
    )
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=True,
    )
    # 행위 시점의 역할 스냅샷 (FK 아님 - 모듈 docstring 참고).
    actor_role: Mapped[str | None] = mapped_column(String(30), nullable=True)
    action_type: Mapped[str] = mapped_column(String(20), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(100), nullable=False)
    # 다형 참조 대상 id (FK 아님 - resource_type에 따라 가리키는 테이블이 달라진다).
    resource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    before_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    after_hash: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    request_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    ip_hmac: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
