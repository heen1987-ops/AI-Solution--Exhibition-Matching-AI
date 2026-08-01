"""SQLAlchemy 선언적 베이스와 스키마 사용 규약.

이 모듈은 아직 도메인 모델을 정의하지 않는다 (그건 이후 단계 에이전트들의 책임이다).
여기서는 모든 도메인 모델이 상속해야 하는 공통 Base 클래스와, PostgreSQL 스키마를
어떻게 지정해야 하는지에 대한 규약만 정의한다.

--------------------------------------------------------------------------
스키마 규약 (docs/db-erd-table-spec.md 4절 기준)
--------------------------------------------------------------------------

이 프로젝트의 PostgreSQL 데이터베이스는 아래 스키마로 논리 분리된다:

    core        - 테넌트와 공통 주체
    identity    - 암호화 식별정보와 인증수단
    profile     - 계정, 역할, 세션, 동의, 사용자 프로파일
    ontology    - 버전형 개념, 계층, 동의어, 관계와 원천 매핑
    exhibition  - 행사, 업체, 제품, 부스, 프로그램
    matching    - 추천정책, 실행, 결과, 근거
    interaction - 저장, 경로, 방문, 피드백, 상담
    ai          - 모델, 실행, 추출속성, 임베딩
    integration - 원천연계, import, 멱등성, outbox
    privacy     - 보유정책, 권리요청, 삭제작업
    audit       - 관리자·민감정보 접근 감사
    quality     - 데이터 품질 이슈
    analytics   - 운영 DB에서 파생한 데이터마트

이 스키마들은 backend/alembic/versions의 최초 마이그레이션에서 CREATE SCHEMA IF NOT EXISTS로
생성된다 (모델이 없어도 스키마 자체는 먼저 존재해야 alembic autogenerate와 FK가 동작한다).

각 도메인 모델은 아래처럼 __table_args__에 schema를 명시해야 한다:

    from app.db.base import Base, SCHEMA_PROFILE

    class UserAccount(Base):
        __tablename__ = "user_account"
        __table_args__ = {"schema": SCHEMA_PROFILE}
        ...

    # 다른 제약조건(UniqueConstraint 등)과 함께 쓸 때는 튜플의 마지막 요소로 dict를 둔다:
    __table_args__ = (
        UniqueConstraint("tenant_id", "event_code", name="uq_event_tenant_code"),
        {"schema": SCHEMA_EXHIBITION},
    )

FK로 다른 스키마 테이블을 참조할 때는 ForeignKey("profile.user_account.user_id")처럼
"스키마명.테이블명.컬럼명" 전체 경로를 사용한다.

identity와 audit 스키마는 일반 서비스 역할의 직접 조회를 금지한다 (db-erd-table-spec.md 4절).
DB 역할·권한(GRANT) 설정은 이 리포지토리의 인프라/운영 작업 범위이며, alembic 마이그레이션에서
스키마 생성과 별도로 다뤄야 한다.
"""

from __future__ import annotations

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# db-erd-table-spec.md 4절의 스키마 목록. 새 스키마가 필요하면 여기와 최초 마이그레이션을 함께 갱신한다.
SCHEMA_CORE = "core"
SCHEMA_IDENTITY = "identity"
SCHEMA_PROFILE = "profile"
SCHEMA_ONTOLOGY = "ontology"
SCHEMA_EXHIBITION = "exhibition"
SCHEMA_MATCHING = "matching"
SCHEMA_INTERACTION = "interaction"
SCHEMA_AI = "ai"
SCHEMA_INTEGRATION = "integration"
SCHEMA_PRIVACY = "privacy"
SCHEMA_AUDIT = "audit"
SCHEMA_QUALITY = "quality"
SCHEMA_ANALYTICS = "analytics"

ALL_SCHEMAS: tuple[str, ...] = (
    SCHEMA_CORE,
    SCHEMA_IDENTITY,
    SCHEMA_PROFILE,
    SCHEMA_ONTOLOGY,
    SCHEMA_EXHIBITION,
    SCHEMA_MATCHING,
    SCHEMA_INTERACTION,
    SCHEMA_AI,
    SCHEMA_INTEGRATION,
    SCHEMA_PRIVACY,
    SCHEMA_AUDIT,
    SCHEMA_QUALITY,
    SCHEMA_ANALYTICS,
)

# alembic autogenerate가 제약조건에 예측 가능한 이름을 붙이도록 하는 표준 네이밍 컨벤션.
# 이게 없으면 일부 DB 변경(예: 제약조건 삭제)에서 자동생성 마이그레이션이 실패하거나 이름이
# 매번 달라질 수 있다.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """모든 도메인 모델의 공통 베이스.

    이후 단계 에이전트가 정의하는 모든 ORM 모델은 이 클래스를 상속해야 alembic env.py의
    target_metadata(=Base.metadata)에 잡히고 autogenerate 대상이 된다.
    """

    metadata = MetaData(naming_convention=NAMING_CONVENTION)
