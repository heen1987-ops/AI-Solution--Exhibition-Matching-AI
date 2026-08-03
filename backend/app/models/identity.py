"""identity/profile 도메인 - 계정, 식별정보, 인증수단, 역할, 게스트 세션 SQLAlchemy 모델.

근거 문서:
    - docs/db-erd-table-spec.md 7.2~7.4절(계정·식별정보·인증수단), 8.1~8.3절(역할·세션) - 1차 근거.
    - docs/frontend-backend-ai-interface-spec.md 2.2절(인증 상태·역할 enum), 2.3절(식별자
      정의) - authentication_state/actor_role 개념 정의는 이 문서를 최우선으로 따른다.

이 파일에서 구현하는 테이블:
    1. profile.user_account          - db-erd 7.2 (authentication_state 보유)
    2. identity.user_identity        - db-erd 7.3 (성명·연락처 등 직접식별정보, HMAC 포함)
    3. identity.authentication_method - db-erd 7.4
    4. profile.role                  - db-erd 8.1 (actor_role 코드값)
    5. profile.user_role             - db-erd 8.2
    6. profile.guest_session         - db-erd 8.3

authentication_state / actor_role에 대한 메모 (인터페이스 명세 2.2절 최우선 원칙):
    인터페이스 명세는 `authentication_state: GUEST | PHONE_VERIFIED | ACCOUNT_AUTHENTICATED`로
    3가지 값을 정의하지만, db-erd 7.2절은 user_account.authentication_state 컬럼 자체에는
    PHONE_VERIFIED/ACCOUNT_AUTHENTICATED 2가지만 명시한다. 이는 서로 충돌이 아니라 스코프가
    다르다: db-erd 7.2절이 명시하듯 "GUEST는 계정 상태가 아니라 guest_session으로 표현한다"
    - 즉 GUEST인 행위자는애초에 profile.user_account 행을 갖지 않는다(guest_session만 있음).
    API가 노출하는 3분류 authentication_state는 "user_account 행이 없으면 GUEST, 있으면 그
    행의 authentication_state 값" 형태로 BFF가 계산하는 합성값이다. 따라서 이 파일의
    user_account.authentication_state 컬럼은 db-erd 7.2절 그대로 2값 CHECK 제약을 둔다.

    actor_role(VISITOR/BUYER/EXHIBITOR/OPERATOR/ADMIN)은 두 문서가 완전히 일치하므로
    profile.role.role_code에 동일한 5값 CHECK 제약을 둔다.

식별정보 스키마 접근 제한에 대한 메모:
    app/db/base.py 안내대로 identity 스키마는 일반 서비스 역할의 직접 조회를 금지해야 한다.
    이 파일은 ORM 모델 정의만 다루며, 실제 DB 역할(GRANT/REVOKE)·RLS 설정은 인프라/운영
    작업 범위로 남겨 둔다.

profile.role / profile.user_role에 대한 메모:
    db-erd 8.1절은 표 없이 "role_code: VISITOR, BUYER, EXHIBITOR, OPERATOR, ADMIN" 한 줄만
    있고, 8.2절 user_role 표에는 필수 여부(Y/N) 표시가 없다. 이 파일의 NOT NULL/기본값
    선택은 8.2절 산문("EXHIBITOR 역할은 exhibitor_id 필수, OPERATOR는 event_id 필수")과
    상식적인 업무 규칙에 따른 합리적 추정이며, exhibitor_id/event_id 필수 여부를 역할별로
    강제하는 조건부 제약은 role_code가 별 테이블(profile.role)에 있어 순수 CHECK로 표현할
    수 없으므로 애플리케이션 계층(서비스 레이어) 검증으로 남겨 둔다 - 아래 TODO 참고.

    [갱신] user_role.exhibitor_id는 exhibition.exhibitor(업체 마스터)를 가리킨다. 이 문단을
    처음 쓴 시점에는 exhibition 도메인이 아직 없어 FK를 걸지 않았지만, app/models/exhibitor.py가
    나온 뒤 __table_args__의 fk_user_role_exhibitor_boundary 복합 FK
    (tenant_id, exhibitor_id) -> exhibition.exhibitor(tenant_id, exhibitor_id)로 이미
    연결되어 있다. exhibitor_id가 NULL인 행(전역/이벤트 스코프 역할)은 FK가 자동으로
    통과하므로 이 컬럼을 nullable로 유지하는 것과 충돌하지 않는다.
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
    LargeBinary,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import (
    SCHEMA_CORE,
    SCHEMA_EXHIBITION,
    SCHEMA_IDENTITY,
    SCHEMA_PROFILE,
    Base,
)
from app.models.common import new_uuid7

_new_uuid = new_uuid7


class UserAccount(Base):
    """profile.user_account - db-erd 7.2.

    가명(pseudonymous) 사용자 계정. GUEST는 이 테이블에 행을 만들지 않는다 (모듈 docstring
    "authentication_state / actor_role에 대한 메모" 참고).
    """

    __tablename__ = "user_account"
    __table_args__ = (
        CheckConstraint(
            "authentication_state IN ('PHONE_VERIFIED', 'ACCOUNT_AUTHENTICATED')",
            name="authentication_state_allowed",
        ),
        CheckConstraint(
            "account_status IN ('ACTIVE', 'SUSPENDED', 'WITHDRAWN')",
            name="account_status_allowed",
        ),
        {"schema": SCHEMA_PROFILE},
    )

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    authentication_state: Mapped[str] = mapped_column(String(30), nullable=False)
    account_status: Mapped[str] = mapped_column(
        String(20), nullable=False, server_default="ACTIVE"
    )
    default_language: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="ko-KR"
    )
    timezone: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="Asia/Seoul"
    )
    last_authenticated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    identity: Mapped[UserIdentity | None] = relationship(
        back_populates="user_account", uselist=False, cascade="all, delete-orphan"
    )
    authentication_methods: Mapped[list[AuthenticationMethod]] = relationship(
        back_populates="user_account", cascade="all, delete-orphan"
    )
    roles: Mapped[list[UserRole]] = relationship(
        back_populates="user_account", cascade="all, delete-orphan"
    )


class UserIdentity(Base):
    """identity.user_identity - db-erd 7.3.

    성명·전화번호·이메일 등 직접식별정보를 봉투 암호화(enc)와 조회용 HMAC으로 나눠 저장한다.
    실제 암호화/HMAC 키 관리(KMS/Vault)는 애플리케이션 서비스 계층의 책임이며 이 모델은
    저장 스키마만 정의한다.
    """

    __tablename__ = "user_identity"
    __table_args__ = (
        Index(
            "uq_user_identity_phone_hmac",
            "phone_hmac",
            unique=True,
            postgresql_where=text("phone_hmac IS NOT NULL"),
        ),
        Index("ix_user_identity_retention_expires_at", "retention_expires_at"),
        {"schema": SCHEMA_IDENTITY},
    )

    identity_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
        unique=True,
    )
    name_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    phone_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    phone_hmac: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    email_enc: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    email_hmac: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    phone_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    email_verified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 목적별 보유기간 계산 결과 (privacy.retention_policy 기준). db-erd 7.3절: "연령확인은
    # identity 속성이 아니라 동의·자격 이력에 저장한다" - 그래서 연령 관련 컬럼은 두지 않는다.
    retention_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
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

    user_account: Mapped[UserAccount] = relationship(back_populates="identity")


class AuthenticationMethod(Base):
    """identity.authentication_method - db-erd 7.4.

    OTP challenge/실패횟수 등 단명 상태는 이 마스터 테이블에 누적하지 않는다 (db-erd 7.4절
    "OTP challenge·실패횟수는 짧은 수명의 Redis 또는 별도 보안 테이블에서 관리").
    """

    __tablename__ = "authentication_method"
    __table_args__ = (
        CheckConstraint(
            "method_type IN ('PHONE_OTP', 'EMAIL', 'SOCIAL')",
            name="method_type_allowed",
        ),
        Index("ix_authentication_method_user_id", "user_id"),
        {"schema": SCHEMA_IDENTITY},
    )

    authentication_method_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
    )
    method_type: Mapped[str] = mapped_column(String(30), nullable=False)
    provider: Mapped[str | None] = mapped_column(String(100), nullable=True)
    provider_subject_hmac: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    last_authenticated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    revoked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user_account: Mapped[UserAccount] = relationship(
        back_populates="authentication_methods"
    )


class Role(Base):
    """profile.role - db-erd 8.1.

    db-erd 8.1절은 "role_code: VISITOR, BUYER, EXHIBITOR, OPERATOR, ADMIN" 한 줄뿐이라
    role_id/role_name/created_at 등 나머지 컬럼은 합리적 기본 설계다 (모듈 docstring 참고).
    이 값은 frontend-backend-ai-interface-spec.md 2.2절의 actor_role과 정확히 일치한다.
    """

    __tablename__ = "role"
    __table_args__ = (
        CheckConstraint(
            "role_code IN ('VISITOR', 'BUYER', 'EXHIBITOR', 'OPERATOR', 'ADMIN')",
            name="role_code_allowed",
        ),
        {"schema": SCHEMA_PROFILE},
    )

    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    role_code: Mapped[str] = mapped_column(String(30), nullable=False, unique=True)
    role_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user_roles: Mapped[list[UserRole]] = relationship(back_populates="role")


class UserRole(Base):
    """profile.user_role - db-erd 8.2.

    "부분 유일성으로 동일 활성 역할 중복을 방지한다"(db-erd 8.2절)는 요구를 partial unique
    index로 구현한다. 단, PostgreSQL의 부분 유니크 인덱스는 NULL을 서로 다른 값으로 취급하므로
    event_id 또는 exhibitor_id가 NULL인 전역 역할끼리는 이 인덱스만으로 완전한 중복 방지가
    되지 않는다 - 그런 경우의 중복 방지는 애플리케이션 계층에서 추가로 검증해야 한다.

    TODO(서비스 계층): "EXHIBITOR 역할은 exhibitor_id 필수, OPERATOR는 event_id 필수"(db-erd
    8.2절) 규칙은 role_code가 다른 테이블(profile.role)에 있어 순수 CHECK 제약으로 표현할 수
    없다. 역할 배정 서비스 로직에서 role_code를 조회해 검증해야 한다.
    """

    __tablename__ = "user_role"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_user_role_event_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            [
                f"{SCHEMA_EXHIBITION}.exhibitor.tenant_id",
                f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id",
            ],
            name="fk_user_role_exhibitor_boundary",
        ),
        Index(
            "uq_user_role_active_assignment",
            "tenant_id",
            "event_id",
            "user_id",
            "role_id",
            "exhibitor_id",
            unique=True,
            postgresql_where=text("valid_until IS NULL"),
            postgresql_nulls_not_distinct=True,
        ),
        {"schema": SCHEMA_PROFILE},
    )

    user_role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_CORE}.tenant.tenant_id"),
        nullable=False,
    )
    # "이벤트 스코프, 전역 역할은 NULL" (db-erd 8.2절).
    event_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=False,
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA_PROFILE}.role.role_id"), nullable=False
    )
    # 단일 컬럼 FK는 없지만 __table_args__의 fk_user_role_exhibitor_boundary 복합 FK가
    # (tenant_id, exhibitor_id) -> exhibition.exhibitor(tenant_id, exhibitor_id)를
    # 강제한다 (모듈 docstring "[갱신]" 메모 참고).
    exhibitor_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 부여자는 사람 사용자일 수도, 서비스 주체일 수도 있어 FK를 걸지 않는다 (db-erd 6.2절
    # created_by/updated_by와 동일한 "서비스 주체 가능" 성격).
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user_account: Mapped[UserAccount] = relationship(back_populates="roles")
    role: Mapped[Role] = relationship(back_populates="user_roles")


class GuestSession(Base):
    """profile.guest_session - db-erd 8.3.

    익명(GUEST) 행위자의 세션 단위. 인증 성공 시 converted_user_id/converted_at으로 전환
    이력을 남긴다 (db-erd 7.2절 "GUEST는 계정 상태가 아니라 guest_session으로 표현한다").
    """

    __tablename__ = "guest_session"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_guest_session_event_boundary",
        ),
        CheckConstraint(
            "entry_channel IN ('QR', 'WEB', 'KIOSK')", name="entry_channel_allowed"
        ),
        {"schema": SCHEMA_PROFILE},
    )

    guest_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # 원문 세션 토큰은 저장하지 않는다 (db-erd 8.3절 "원문 토큰 미저장").
    session_token_hmac: Mapped[bytes] = mapped_column(
        LargeBinary, nullable=False, unique=True
    )
    entry_channel: Mapped[str] = mapped_column(String(20), nullable=False)
    entry_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 예: MOBILE_WEB 등 - db-erd 8.3절이 "등"으로 예시만 들어 하드코딩 enum을 두지 않는다.
    device_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    language: Mapped[str | None] = mapped_column(
        String(10), nullable=True, server_default="ko-KR"
    )
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    converted_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_PROFILE}.user_account.user_id"),
        nullable=True,
    )
    converted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
