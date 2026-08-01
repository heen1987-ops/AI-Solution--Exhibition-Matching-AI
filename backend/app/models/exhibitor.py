"""참가업체·제품·부스 도메인 SQLAlchemy 모델 (exhibition 스키마).

근거 문서와 우선순위
---------------------
- docs/08-exhibitor-product-profile-model.md 27절(공급 프로파일 DB 구조) - exhibition 도메인
  최우선 근거. exhibitor_profile/product_profile/supply_capability/buyer_preference/
  profile_attribute 5개 테이블의 1차 근거다 (작업 지시 원칙: 07·08 문서는 각자 도메인에서
  db-erd-table-spec.md보다 우선).
- docs/db-erd-table-spec.md 11절(분류체계), 12절(행사·업체·제품), 13절(부스·프로그램·추천
  대상), 21절(핵심 인덱스) - 08 문서에 없는 기본 엔터티(Exhibitor, ExhibitorStaff, Product
  마스터, EventProduct, TradeCondition, Booth, Program)의 1차 근거다.

이 파일에서 구현하는 테이블
---------------------------
기본 엔터티 (db-erd 12·13절):
    1.  exhibition.exhibitor              - db-erd 12.2 (업체 마스터)
    2.  exhibition.exhibitor_business_type - db-erd에 명시된 테이블은 아니다. 08 4.2절
        "한 업체는 복수 유형을 가질 수 있다"를 만족하려면 exhibitor 테이블의 단일
        business_type 컬럼만으로는 부족해, participation_category/staff_topic과 동일한
        (개체, taxonomy_version_id, concept_id) 정규화 패턴을 그대로 적용해 새로 추가했다.
        exhibitor 테이블 자체의 business_type_taxonomy_version_id/concept_id는 db-erd 12.2가
        명시한 "대표 유형" 단일 컬럼으로 유지한다.
    3.  exhibition.exhibitor_participation - db-erd 12.3
    4.  exhibition.participation_category  - db-erd 12.3 본문 ("전시분야는
        participation_category(participation_id, taxonomy_version_id, concept_id)로 정규화")
    5.  exhibition.exhibitor_staff         - db-erd 12.4 (지시사항의 "ExhibitorContact")
    6.  exhibition.staff_topic             - db-erd 12.4 본문 ("상담주제는 staff_topic으로 관리")
    7.  exhibition.product                 - db-erd 12.5 (제품 마스터, 상시정보)
    8.  exhibition.event_product           - db-erd 12.6 (행사별 가격·재고·시음·판매 상태,
        08 2.2절 "상시정보와 행사정보 분리" 원칙의 핵심 구현)
    9.  exhibition.product_attribute       - db-erd 12.7
    10. exhibition.product_image           - db-erd 12.7
    11. exhibition.trade_condition         - db-erd 12.8
    12. exhibition.trade_condition_term    - db-erd 12.8 본문 ("지역·채널·국가는
        trade_condition_term으로 정규화")
    13. exhibition.booth                   - db-erd 13.1
    14. exhibition.booth_status_history    - db-erd 13.1 본문
    15. exhibition.booth_qr                - db-erd 13.1 본문
    16. exhibition.program                 - db-erd 13.2

08번 문서 27절 공급 프로파일 확장 테이블 (exhibition 도메인에서 08 문서가 최우선):
    17. exhibition.exhibitor_profile  - 08 27.1
    18. exhibition.product_profile    - 08 27.2
    19. exhibition.supply_capability  - 08 27.3
    20. exhibition.buyer_preference   - 08 27.4 (PK 필드명은 exhibitor_buyer_preference_id)
    21. exhibition.profile_attribute  - 08 27.5 (파이썬 클래스명은 SupplyProfileAttribute로
        지었다. profile.py가 이미 동일 테이블명 "profile_attribute"를 profile 스키마에 쓰고
        있어 클래스 이름이 겹치면 나중에 두 모듈을 함께 import할 때 헷갈리기 쉽기 때문이다 -
        스키마가 달라 실제 DB 충돌은 없다.)

의도적으로 이 파일에서 다시 만들지 않은 것 (다른 에이전트가 이미 구현)
------------------------------------------------------------------------
- exhibition.recommendable   : db-erd 13.3. app/models/matching.py가 이미 정의했다. 같은
  (schema, tablename)으로 다시 선언하면 Base.metadata 등록 시 충돌하므로 여기서는 만들지
  않는다. Booth/EventProduct/ExhibitorParticipation/Program 각각을 recommendable에 연결하는
  것은 그 파일의 책임이다.
- interaction.availability_slot : db-erd 14.1. app/models/meeting.py가 이미 정의했다(스키마도
  exhibition이 아니라 interaction). 지시사항에 "기본 엔터티" 예시로 언급되어 있었지만 이미
  다른 에이전트가 구현했으므로 중복 정의하지 않는다.

taxonomy_term 참조 불일치에 대한 통합 메모
--------------------------------------------
app/models/meeting.py는 topic_term_id/outcome_term_id/action_term_id가 "exhibition.taxonomy_term"
이라는 테이블을 참조한다고 가정하는데, 이 테이블은 db-erd-table-spec.md 어디에도 정의되어 있지
않다. 이 문서의 정본 분류체계 저장소는 ontology.taxonomy_version + ontology.concept +
ontology.concept_revision이며(11절, db/migrations/0001_ontology.sql), "모든 업무 테이블은 개념을
참조할 때 concept_id만 저장하지 않고 (taxonomy_version_id, concept_id)를 함께 FK로 둔다"(11절
마지막 문단)가 정본 규칙이다. 이 파일의 모든 개념 참조(business_type, region, category,
participation_category, staff_topic, trade_condition_term, buyer_preference의 buyer_type·
channel·region, profile_attribute)는 전부 이 규칙대로 (taxonomy_version_id, concept_id) 복합
FK로 ontology.concept_revision을 참조한다. meeting.py 쪽의 "exhibition.taxonomy_term" 가정은
이 파일의 책임 범위가 아니지만, 통합 단계에서 반드시 ontology.concept_revision 참조로
재정합해야 한다는 점을 여기 남긴다.

거래조건 가용성 필드를 boolean이 아니라 상태코드로 설계한 이유
------------------------------------------------------------------
db-erd 12.8절은 trade_condition.oem_available/private_label_available/export_available을
"BOOLEAN"으로 표기한다. 그런데 08 문서 2.4절("미등록과 불가능 분리")은 이 프로젝트 전체의
확정 설계원칙(38절 확정사항 4번)으로 YES/NO/CONDITIONAL/NEGOTIABLE/UNKNOWN 5단계 상태를
요구하고, 실제로 5단계 AI 매칭엔진 입력 예시(08 문서 29절)도 "oem_status": "NEGOTIABLE",
"private_label_status": "NO"처럼 상태코드 문자열을 그대로 쓴다. exhibition 도메인은 08 문서가
db-erd보다 우선하므로, 이 파일은 db-erd의 표기를 오탈자/단순화로 보고 oem_status/
private_label_status/export_status 3개 컬럼을 TRADE_AVAILABILITY_STATUSES CHECK 제약을 가진
문자열 컬럼으로 구현한다(컬럼명도 08 29절 JSON 필드명과 그대로 맞췄다). exclusive_distribution_
considered("독점유통 검토 여부", 08 9.3절)는 참/거짓 그 자체를 묻는 질문이라 boolean으로 유지한다.

pgvector 관련 메모
-------------------
backend/pyproject.toml에는 pgvector 파이썬 패키지가 없다(직접 추가하지 않았다 - 작업 지시).
다만 이 파일이 구현하는 08 문서 27절의 5개 테이블(exhibitor_profile, product_profile,
supply_capability, buyer_preference, profile_attribute)에는 임베딩 컬럼이 정의되어 있지 않다.
08 문서 26절의 임베딩(PRODUCT_CONSUMER, PRODUCT_TRADE, EXHIBITOR_CAPABILITY 등)은
db-erd 18.4절 ai.object_embedding(ai 스키마, recommendable_id FK)에 저장되도록 설계되어 있어
AI 도메인 에이전트의 책임 범위다. 따라서 이 파일에는 pgvector Vector 컬럼을 추가하지 않았다.
향후 exhibitor/product 도메인 자체에 임베딩 컬럼을 직접 두어야 하는 요구가 생기면 그때
pyproject.toml에 pgvector를 추가해야 한다.

다른 도메인 모델과의 관계
--------------------------
이 모듈은 다른 스키마의 테이블(core.tenant, profile.user_account, ai.ai_run 등)을
"스키마명.테이블명.컬럼명" 문자열 ForeignKey로만 참조하고 다른 모델 모듈을 import하지 않는다
(meeting.py 상단 메모와 동일한 이유 - 여러 에이전트 동시 작업). relationship()은 이 파일
안에서 함께 정의되는 클래스 사이에만 사용한다.
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
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SCHEMA_EXHIBITION, Base
from app.models.common import new_uuid7

_new_uuid = new_uuid7

# --------------------------------------------------------------------------
# 공용 상수. CHECK 제약과 애플리케이션 코드가 같은 값을 참조하도록 단일 진실 공급원으로 둔다
# (app/models/meeting.py의 MEETING_STATUSES 패턴을 그대로 따른다).
# --------------------------------------------------------------------------

#: db-erd 12.2/12.5/12.6/12.8절의 "DRAFT, APPROVED, REJECTED" 3단계 검수상태.
#: 업체·제품 "마스터" 기본정보와 행사별 상태·거래조건의 검수에 쓴다.
MASTER_APPROVAL_STATUSES: tuple[str, ...] = ("DRAFT", "APPROVED", "REJECTED")

#: 08 문서 4.1절 "승인상태: 작성중, 제출, 승인, 반려" - 공급 프로파일(exhibitor_profile/
#: product_profile) 전용 4단계 검수상태. master_approval_status보다 한 단계 더 세분화된다.
PROFILE_APPROVAL_STATUSES: tuple[str, ...] = (
    "DRAFT",
    "SUBMITTED",
    "APPROVED",
    "REJECTED",
)

#: db-erd 12.7절 product_attribute.review_status, product_image.approval_status.
REVIEW_STATUSES: tuple[str, ...] = ("PENDING", "APPROVED", "REJECTED")

#: 08 문서 10.3절 "검증상태" 6단계.
VERIFICATION_STATUSES: tuple[str, ...] = (
    "SELF_DECLARED",
    "DOCUMENT_SUBMITTED",
    "OPERATOR_REVIEWED",
    "VERIFIED",
    "EXPIRED",
    "REJECTED",
)

#: 08 문서 2.4절 "미등록과 불가능 분리" - 거래 가능 여부를 boolean이 아니라 5단계로 저장한다
#: (모듈 docstring "거래조건 가용성 필드..." 절 참고).
TRADE_AVAILABILITY_STATUSES: tuple[str, ...] = (
    "YES",
    "NO",
    "CONDITIONAL",
    "NEGOTIABLE",
    "UNKNOWN",
)

#: db-erd 6.3절 가격 공개범위. 08 문서 27.5절 profile_attribute.visibility에도 재사용한다
#: (14절 "공급 프로파일 속성 공통 구조"의 visibility가 6.3절과 동일 개념이라고 보는 것이
#: 문서 전체에서 가장 구체적인 코드 목록이기 때문).
VISIBILITY_LEVELS: tuple[str, ...] = (
    "PUBLIC",
    "BUYER_ONLY",
    "MATCHED_BUYER_ONLY",
    "MEETING_ACCEPTED",
    "PRIVATE",
)

#: 08 문서 15절 "데이터 출처" 10개 코드. profile_attribute.source_type에 사용한다.
SUPPLY_SOURCE_TYPES: tuple[str, ...] = (
    "EXHIBITOR_ENTERED",
    "EXHIBITOR_CONFIRMED",
    "OPERATOR_ENTERED",
    "OPERATOR_VERIFIED",
    "AI_EXTRACTED",
    "EXTERNAL_SYNC",
    "DOCUMENT_VERIFIED",
    "SYSTEM_CALCULATED",
    "REALTIME_OPERATION",
    "USER_FEEDBACK",
)

#: db-erd 12.7절 product_attribute.source (08 문서 15절보다 좁은, 3자 출처 구분).
PRODUCT_ATTRIBUTE_SOURCES: tuple[str, ...] = ("EXHIBITOR", "AI", "OPERATOR")

#: 08 문서 27.4절 "필수·선호·제외" 3단계.
BUYER_PREFERENCE_LEVELS: tuple[str, ...] = ("REQUIRED", "PREFERRED", "EXCLUDED")

#: db-erd 12.6절 event_product 상태 3종.
TASTING_STATUSES: tuple[str, ...] = ("AVAILABLE", "PAUSED", "ENDED")
PURCHASE_STATUSES: tuple[str, ...] = ("AVAILABLE", "LIMITED", "ENDED")
INVENTORY_STATUSES: tuple[str, ...] = ("AVAILABLE", "LOW", "SOLD_OUT", "UNKNOWN")

#: db-erd 12.3/12.4절.
PARTICIPATION_STATUSES: tuple[str, ...] = ("APPLIED", "APPROVED", "CANCELLED")

#: db-erd 13.1절 부스 운영상태 3종 (08 12.3절의 CONGESTED/SOLD_OUT은 congestion_level·
#: event_product.inventory_status 등 별도 컬럼으로 이미 표현되므로 이 컬럼 자체는 db-erd대로
#: 3종만 CHECK한다).
BOOTH_OPERATING_STATUSES: tuple[str, ...] = ("OPEN", "PAUSED", "CLOSED")
BOOTH_CONGESTION_LEVELS: tuple[str, ...] = ("LOW", "MEDIUM", "HIGH", "UNKNOWN")

#: 문서에 값 목록이 없어 잠정 정의 (모듈 docstring에서 명시하지 않은 세부값).
#: TODO(6단계 온톨로지 또는 운영 화면 상세설계 확정 후 재검토).
BOOTH_QR_STATUSES: tuple[str, ...] = ("ACTIVE", "REVOKED", "EXPIRED")
PROGRAM_STATUSES: tuple[str, ...] = ("PLANNED", "OPEN", "CLOSED", "CANCELLED")

#: db-erd 12.8절 "지역·채널·국가는 trade_condition_term으로 정규화한다".
TRADE_CONDITION_TERM_TYPES: tuple[str, ...] = ("REGION", "CHANNEL", "COUNTRY")

#: 08 27.5절 object_type: "업체·제품·거래조건".
SUPPLY_ATTRIBUTE_OBJECT_TYPES: tuple[str, ...] = (
    "EXHIBITOR",
    "PRODUCT",
    "TRADE_CONDITION",
)


def _in_list(values: tuple[str, ...]) -> str:
    """CHECK 제약의 'col IN (...)' 리터럴 목록 문자열을 상수 튜플에서 생성한다."""

    return ", ".join(f"'{value}'" for value in values)


def _ontology_fk(
    version_col: str, concept_col: str, *, name: str
) -> ForeignKeyConstraint:
    """ontology.concept_revision을 향한 (taxonomy_version_id, concept_id) 복합 FK 헬퍼.

    db-erd 11절 마지막 문단: "모든 업무 테이블은 개념을 참조할 때 concept_id만 저장하지 않고
    (taxonomy_version_id, concept_id)를 함께 FK로 둔다". 이 파일은 개념 참조가 매우 많아
    (업체 유형, 지역, 상담주제, 전시분야, 주종, 거래조건 지역/채널/국가, 바이어 선호 등)
    다른 도메인 파일들처럼 매번 인라인으로 쓰지 않고 헬퍼로 뺐다.
    """

    return ForeignKeyConstraint(
        [version_col, concept_col],
        [
            "ontology.concept_revision.taxonomy_version_id",
            "ontology.concept_revision.concept_id",
        ],
        name=name,
    )


# ============================================================================
# 1. 참가업체 마스터 (db-erd 12.2)
# ============================================================================


class Exhibitor(Base):
    """exhibition.exhibitor - db-erd 12.2.

    업체 마스터. 08 문서 2.2절 "상시정보와 행사정보 분리" 원칙에 따라 회사명·소재지·사업유형
    등 갱신주기가 낮은 상시정보만 담고, 행사별 참가정보는 ExhibitorParticipation으로,
    공급역량·희망 바이어 등 매칭용 프로파일은 ExhibitorProfile(08 27.1)로 분리한다.

    master_approval_status는 "업체 마스터 버전"(08 19.1절)의 검수상태이며, 공급 프로파일
    자체의 검수상태(ExhibitorProfile.approval_status)와는 별개다.
    """

    __tablename__ = "exhibitor"
    __table_args__ = (
        _ontology_fk(
            "business_type_taxonomy_version_id",
            "business_type_concept_id",
            name="fk_exhibitor_business_type_ontology_revision",
        ),
        _ontology_fk(
            "region_taxonomy_version_id",
            "region_concept_id",
            name="fk_exhibitor_region_ontology_revision",
        ),
        CheckConstraint(
            f"master_approval_status IN ({_in_list(MASTER_APPROVAL_STATUSES)})",
            name="master_approval_status_allowed",
        ),
        CheckConstraint(
            "data_completeness_percent >= 0 AND data_completeness_percent <= 100",
            name="data_completeness_percent_range",
        ),
        CheckConstraint(
            "num_nonnulls(business_type_taxonomy_version_id, business_type_concept_id) IN (0, 2)",
            name="business_type_pair_complete",
        ),
        CheckConstraint(
            "num_nonnulls(region_taxonomy_version_id, region_concept_id) IN (0, 2)",
            name="region_pair_complete",
        ),
        UniqueConstraint("tenant_id", "exhibitor_id", name="uq_exhibitor_tenant_id"),
        Index("ix_exhibitor_tenant", "tenant_id"),
        {"schema": SCHEMA_EXHIBITION},
    )

    exhibitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False
    )
    company_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # db-erd 12.2: "중복검사" - 사업자등록번호 원문 대신 HMAC만 저장한다 (identity.user_identity와
    # 동일한 암호화·해시 분리 패턴). 원문·복호화는 이 모델의 책임이 아니다.
    business_registration_hmac: Mapped[bytes | None] = mapped_column(
        LargeBinary, nullable=True
    )
    company_summary: Mapped[str | None] = mapped_column(Text, nullable=True)

    # 08 4.2절: "한 업체는 복수 유형을 가질 수 있다" - 이 컬럼은 db-erd 12.2가 명시한 대표
    # 단일 유형이고, 전체 유형 목록은 ExhibitorBusinessType 정규화 테이블에 별도로 둔다.
    business_type_taxonomy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    business_type_concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    region_taxonomy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    region_concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )

    website_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    master_approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DRAFT"
    )
    data_completeness_percent: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )
    current_profile_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
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

    business_types: Mapped[list[ExhibitorBusinessType]] = relationship(
        back_populates="exhibitor", cascade="all, delete-orphan"
    )
    participations: Mapped[list[ExhibitorParticipation]] = relationship(
        back_populates="exhibitor", cascade="all, delete-orphan"
    )
    products: Mapped[list[Product]] = relationship(
        back_populates="exhibitor", cascade="all, delete-orphan"
    )
    profile: Mapped[ExhibitorProfile | None] = relationship(
        back_populates="exhibitor", cascade="all, delete-orphan", uselist=False
    )
    supply_capabilities: Mapped[list[SupplyCapability]] = relationship(
        back_populates="exhibitor", cascade="all, delete-orphan"
    )
    buyer_preferences: Mapped[list[ExhibitorBuyerPreference]] = relationship(
        back_populates="exhibitor", cascade="all, delete-orphan"
    )


class ExhibitorBusinessType(Base):
    """exhibition.exhibitor_business_type - db-erd에 없는 정규화 테이블(모듈 docstring 참고).

    08 문서 4.2절 "업체 유형 코드" 표(EXHIBITOR.BREWERY 등)와 "한 업체는 복수 유형을 가질 수
    있다"를 만족한다. 코드값 자체는 6단계 온톨로지 시드 데이터로 채운다 - 이 테이블은 하드코딩
    enum 없이 ontology.concept_revision 참조 구조만 제공한다.
    """

    __tablename__ = "exhibitor_business_type"
    __table_args__ = (
        _ontology_fk(
            "taxonomy_version_id",
            "concept_id",
            name="fk_exhibitor_business_type_ontology_revision",
        ),
        UniqueConstraint(
            "exhibitor_id",
            "taxonomy_version_id",
            "concept_id",
            name="uq_exhibitor_business_type_concept",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    exhibitor_business_type_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    exhibitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id"),
        nullable=False,
    )
    taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    exhibitor: Mapped[Exhibitor] = relationship(back_populates="business_types")


# ============================================================================
# 2. 행사 참가 (db-erd 12.3)
# ============================================================================


class ExhibitorParticipation(Base):
    """exhibition.exhibitor_participation - db-erd 12.3."""

    __tablename__ = "exhibitor_participation"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_exhibitor_participation_event_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            [
                f"{SCHEMA_EXHIBITION}.exhibitor.tenant_id",
                f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id",
            ],
            name="fk_exhibitor_participation_exhibitor_boundary",
        ),
        UniqueConstraint(
            "event_id", "exhibitor_id", name="uq_exhibitor_participation_event"
        ),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "participation_id",
            name="uq_exhibitor_participation_boundary_id",
        ),
        CheckConstraint(
            f"participation_status IN ({_in_list(PARTICIPATION_STATUSES)})",
            name="participation_status_allowed",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    participation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    exhibitor_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    participation_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="APPLIED"
    )
    promotion_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    consultation_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    approved_at: Mapped[datetime | None] = mapped_column(
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

    exhibitor: Mapped[Exhibitor] = relationship(back_populates="participations")
    categories: Mapped[list[ParticipationCategory]] = relationship(
        back_populates="participation", cascade="all, delete-orphan"
    )
    staff_members: Mapped[list[ExhibitorStaff]] = relationship(
        back_populates="participation", cascade="all, delete-orphan"
    )
    event_products: Mapped[list[EventProduct]] = relationship(
        back_populates="participation", cascade="all, delete-orphan"
    )
    trade_conditions: Mapped[list[TradeCondition]] = relationship(
        back_populates="participation", cascade="all, delete-orphan"
    )
    booths: Mapped[list[Booth]] = relationship(
        back_populates="participation", cascade="all, delete-orphan"
    )


class ParticipationCategory(Base):
    """exhibition.participation_category - db-erd 12.3 본문.

    "전시분야는 participation_category(participation_id, taxonomy_version_id, concept_id)로
    정규화한다"를 그대로 구현한다. 문서가 나열한 3개 컬럼을 그대로 복합 PK로 삼는다(대리키를
    추가하지 않는다) - 한 참가가 같은 전시분야 개념을 중복으로 가질 이유가 없기 때문이다.
    """

    __tablename__ = "participation_category"
    __table_args__ = (
        _ontology_fk(
            "taxonomy_version_id",
            "concept_id",
            name="fk_participation_category_ontology_revision",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    participation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor_participation.participation_id"),
        primary_key=True,
    )
    taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    participation: Mapped[ExhibitorParticipation] = relationship(
        back_populates="categories"
    )


# ============================================================================
# 3. 담당자 (db-erd 12.4, 지시사항의 "ExhibitorContact")
# ============================================================================


class ExhibitorStaff(Base):
    """exhibition.exhibitor_staff - db-erd 12.4.

    08 13절 "상담 담당자 프로파일"의 DB 대응 테이블. 담당자는 업체가 아니라 "행사 참가" 단위에
    연결된다(db-erd 12.4: "담당자는 참여 단위에 연결한다") - 같은 업체라도 행사마다 다른
    담당자를 배정할 수 있기 때문이다.
    """

    __tablename__ = "exhibitor_staff"
    __table_args__ = ({"schema": SCHEMA_EXHIBITION},)

    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    participation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor_participation.participation_id"),
        nullable=False,
    )
    # db-erd 12.4: "user_id | UUID FK | 파트너 계정". 초대는 했지만 아직 파트너 계정을 만들지
    # 않은 담당자도 등록할 수 있도록 nullable로 둔다 (문서에 필수 여부가 명시되어 있지 않음).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profile.user_account.user_id"), nullable=True
    )
    display_name: Mapped[str] = mapped_column(String(100), nullable=False)
    position_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    participation: Mapped[ExhibitorParticipation] = relationship(
        back_populates="staff_members"
    )
    topics: Mapped[list[StaffTopic]] = relationship(
        back_populates="staff", cascade="all, delete-orphan"
    )


class StaffTopic(Base):
    """exhibition.staff_topic - db-erd 12.4 본문 ("상담주제는 staff_topic으로 관리한다").

    08 13.2절 "상담 전문분야"(제품소개, 가격·견적, OEM 등) 코드값을 담는다. 적합 업체라도
    해당 상담주제를 처리할 담당자가 없으면 추천 순위를 낮춘다는 08 13.1절 규칙은 매칭엔진
    책임이며, 이 테이블은 그 판단에 필요한 원자료만 제공한다.
    """

    __tablename__ = "staff_topic"
    __table_args__ = (
        _ontology_fk(
            "taxonomy_version_id", "concept_id", name="fk_staff_topic_ontology_revision"
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    staff_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor_staff.staff_id"),
        primary_key=True,
    )
    taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    staff: Mapped[ExhibitorStaff] = relationship(back_populates="topics")


# ============================================================================
# 4. 제품 마스터 (db-erd 12.5) + 행사별 상태 (db-erd 12.6)
# ============================================================================


class Product(Base):
    """exhibition.product - db-erd 12.5.

    제품 "마스터" (상시정보). 08 2.2절 원칙에 따라 행사별 가격·재고·시음·판매 상태는 절대
    이 테이블에 두지 않고 EventProduct로 분리한다(db-erd 12.6 본문: "가격·재고·시음 상태는
    제품 마스터에 두지 않는다").
    """

    __tablename__ = "product"
    __table_args__ = (
        _ontology_fk(
            "category_taxonomy_version_id",
            "category_concept_id",
            name="fk_product_category_ontology_revision",
        ),
        CheckConstraint(
            "alcohol_percentage IS NULL "
            "OR (alcohol_percentage >= 0 AND alcohol_percentage <= 100)",
            name="alcohol_percentage_range",
        ),
        CheckConstraint(
            f"master_approval_status IN ({_in_list(MASTER_APPROVAL_STATUSES)})",
            name="master_approval_status_allowed",
        ),
        CheckConstraint(
            "num_nonnulls(category_taxonomy_version_id, category_concept_id) IN (0, 2)",
            name="category_pair_complete",
        ),
        # db-erd 21절 idx_product_category를 그대로 반영한다.
        Index(
            "idx_product_category",
            "category_taxonomy_version_id",
            "category_concept_id",
            postgresql_where=text(
                "deleted_at IS NULL AND master_approval_status = 'APPROVED'"
            ),
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    exhibitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id"),
        nullable=False,
    )
    product_name: Mapped[str] = mapped_column(String(200), nullable=False)
    category_taxonomy_version_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    category_concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    product_summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    alcohol_percentage: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    # db-erd 12.5: "초기 원료" - AI 구조화 이전의 자유 입력을 담는 잠정 컬럼. 정규화된 원료
    # 속성(예: INGREDIENT.RICE)은 ProductAttribute(concept 참조)로 별도 저장한다.
    main_ingredients_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    production_method: Mapped[str | None] = mapped_column(Text, nullable=True)
    master_approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DRAFT"
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

    exhibitor: Mapped[Exhibitor] = relationship(back_populates="products")
    event_products: Mapped[list[EventProduct]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    attributes: Mapped[list[ProductAttribute]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    images: Mapped[list[ProductImage]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    profile: Mapped[ProductProfile | None] = relationship(
        back_populates="product", cascade="all, delete-orphan", uselist=False
    )
    supply_capabilities: Mapped[list[SupplyCapability]] = relationship(
        back_populates="product"
    )


class EventProduct(Base):
    """exhibition.event_product - db-erd 12.6.

    "제품 마스터와 행사별 가격·재고·시음·판매 상태를 분리"(08 2.2절, db-erd 1절)의 핵심
    테이블. 동일 제품이 여러 행사에 출품되면 행사마다 독립된 행이 생긴다.
    """

    __tablename__ = "event_product"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_event_product_event_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "participation_id"],
            [
                f"{SCHEMA_EXHIBITION}.exhibitor_participation.tenant_id",
                f"{SCHEMA_EXHIBITION}.exhibitor_participation.event_id",
                f"{SCHEMA_EXHIBITION}.exhibitor_participation.participation_id",
            ],
            name="fk_event_product_participation_boundary",
        ),
        UniqueConstraint(
            "event_id", "product_id", name="uq_event_product_event_product"
        ),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "event_product_id",
            name="uq_event_product_boundary_id",
        ),
        CheckConstraint(
            "retail_price_amount IS NULL OR retail_price_amount >= 0",
            name="retail_price_amount_nonneg",
        ),
        CheckConstraint(
            "event_price_amount IS NULL OR event_price_amount >= 0",
            name="event_price_amount_nonneg",
        ),
        CheckConstraint(
            f"tasting_status IN ({_in_list(TASTING_STATUSES)})",
            name="tasting_status_allowed",
        ),
        CheckConstraint(
            f"purchase_status IN ({_in_list(PURCHASE_STATUSES)})",
            name="purchase_status_allowed",
        ),
        CheckConstraint(
            f"inventory_status IN ({_in_list(INVENTORY_STATUSES)})",
            name="inventory_status_allowed",
        ),
        CheckConstraint(
            f"approval_status IN ({_in_list(MASTER_APPROVAL_STATUSES)})",
            name="approval_status_allowed",
        ),
        # db-erd 21절 idx_event_product_filter를 그대로 반영한다.
        Index(
            "idx_event_product_filter",
            "event_id",
            "approval_status",
            "inventory_status",
            "tasting_status",
            "purchase_status",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    event_product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    participation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.product.product_id"),
        nullable=False,
    )
    retail_price_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    event_price_amount: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, default="KRW")
    tasting_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="AVAILABLE"
    )
    purchase_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="AVAILABLE"
    )
    inventory_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNKNOWN"
    )
    status_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DRAFT"
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

    participation: Mapped[ExhibitorParticipation] = relationship(
        back_populates="event_products"
    )
    product: Mapped[Product] = relationship(back_populates="event_products")
    trade_conditions: Mapped[list[TradeCondition]] = relationship(
        back_populates="event_product"
    )


class ProductAttribute(Base):
    """exhibition.product_attribute - db-erd 12.7.

    AI가 추출했거나 업체·운영자가 입력한 제품 속성(맛·향·원료 등)을 개념 단위로 저장한다.
    08 24절 "AI 추출 금지·제한사항" 원칙에 따라 review_status가 APPROVED가 되기 전에는
    매칭 하드필터·검색근거로 쓰지 않아야 한다 - 그 강제는 애플리케이션/매칭 계층 책임이다.
    """

    __tablename__ = "product_attribute"
    __table_args__ = (
        _ontology_fk(
            "taxonomy_version_id",
            "concept_id",
            name="fk_product_attribute_ontology_revision",
        ),
        # db-erd 12.7: "numeric_value 또는 text_value" - 정확히 하나만 채운다.
        CheckConstraint(
            "num_nonnulls(numeric_value, text_value) = 1",
            name="exactly_one_value",
        ),
        CheckConstraint(
            f"source IN ({_in_list(PRODUCT_ATTRIBUTE_SOURCES)})",
            name="source_allowed",
        ),
        CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="confidence_range",
        ),
        CheckConstraint(
            f"review_status IN ({_in_list(REVIEW_STATUSES)})",
            name="review_status_allowed",
        ),
        Index(
            "ix_product_attribute_lookup",
            "product_id",
            "taxonomy_version_id",
            "concept_id",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    product_attribute_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.product.product_id"),
        nullable=False,
    )
    taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    numeric_value: Mapped[float | None] = mapped_column(Numeric(), nullable=True)
    text_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    confidence: Mapped[float | None] = mapped_column(Numeric(4, 3), nullable=True)
    review_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )
    # ai.ai_run 도메인이 게시되기 전까지 추적 식별자만 저장한다. 해당 테이블이 도입되는
    # 마이그레이션에서 FK를 추가한다.
    ai_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # db-erd: "evidence reference" - matching.match_reason.evidence_refs와 동일하게 승인된
    # 근거 참조 목록을 JSON으로 담는다 (예: 원문 근거문장 위치, ai_run 입력 해시 등).
    evidence_ref: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    product: Mapped[Product] = relationship(back_populates="attributes")


class ProductImage(Base):
    """exhibition.product_image - db-erd 12.7."""

    __tablename__ = "product_image"
    __table_args__ = (
        CheckConstraint(
            f"approval_status IN ({_in_list(REVIEW_STATUSES)})",
            name="approval_status_allowed",
        ),
        CheckConstraint("display_order >= 0", name="display_order_nonneg"),
        {"schema": SCHEMA_EXHIBITION},
    )

    product_image_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.product.product_id"),
        nullable=False,
    )
    storage_key: Mapped[str] = mapped_column(String(500), nullable=False)
    # db-erd에 값 목록이 없어 개방형 문자열로 둔다 (예: MAIN, DETAIL, LABEL, CERTIFICATE 등).
    image_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    display_order: Mapped[int] = mapped_column(SmallInteger, nullable=False, default=0)
    alt_text: Mapped[str | None] = mapped_column(String(300), nullable=True)
    approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PENDING"
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    product: Mapped[Product] = relationship(back_populates="images")


# ============================================================================
# 5. 거래조건 (db-erd 12.8)
# ============================================================================


class TradeCondition(Base):
    """exhibition.trade_condition - db-erd 12.8.

    08 7.2절 "거래조건 적용 단위"(업체 공통 -> 제품별 -> 바이어별 확정) 중 앞의 두 단계를
    담당한다. event_product_id가 NULL이면 업체 공통조건, 채워지면 제품별 조건이다(db-erd 12.8
    본문: "제품별, 업체 공통이면 NULL"). 바이어별 확정조건(세 번째 단계)은 상담(interaction.
    meeting) 도메인의 책임이라 이 테이블에 포함하지 않는다.

    oem_status/private_label_status/export_status 설계 근거는 모듈 docstring
    "거래조건 가용성 필드를 boolean이 아니라 상태코드로 설계한 이유" 절을 참고한다.
    """

    __tablename__ = "trade_condition"
    __table_args__ = (
        CheckConstraint(
            "min_order_quantity IS NULL OR min_order_quantity >= 0",
            name="min_order_quantity_nonneg",
        ),
        CheckConstraint(
            "max_order_quantity IS NULL OR max_order_quantity >= 0",
            name="max_order_quantity_nonneg",
        ),
        CheckConstraint(
            "min_order_quantity IS NULL OR max_order_quantity IS NULL "
            "OR min_order_quantity <= max_order_quantity",
            name="order_quantity_order",
        ),
        CheckConstraint(
            "monthly_capacity IS NULL OR monthly_capacity >= 0",
            name="monthly_capacity_nonneg",
        ),
        CheckConstraint(
            "wholesale_price_min_amount IS NULL OR wholesale_price_min_amount >= 0",
            name="wholesale_price_min_nonneg",
        ),
        CheckConstraint(
            "wholesale_price_max_amount IS NULL OR wholesale_price_max_amount >= 0",
            name="wholesale_price_max_nonneg",
        ),
        CheckConstraint(
            "wholesale_price_min_amount IS NULL OR wholesale_price_max_amount IS NULL "
            "OR wholesale_price_min_amount <= wholesale_price_max_amount",
            name="wholesale_price_order",
        ),
        CheckConstraint(
            f"oem_status IN ({_in_list(TRADE_AVAILABILITY_STATUSES)})",
            name="oem_status_allowed",
        ),
        CheckConstraint(
            f"private_label_status IN ({_in_list(TRADE_AVAILABILITY_STATUSES)})",
            name="private_label_status_allowed",
        ),
        CheckConstraint(
            f"export_status IN ({_in_list(TRADE_AVAILABILITY_STATUSES)})",
            name="export_status_allowed",
        ),
        CheckConstraint(
            "lead_time_days IS NULL OR lead_time_days >= 0",
            name="lead_time_days_nonneg",
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until",
            name="valid_period_order",
        ),
        CheckConstraint(
            f"approval_status IN ({_in_list(MASTER_APPROVAL_STATUSES)})",
            name="approval_status_allowed",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    trade_condition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    participation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor_participation.participation_id"),
        nullable=False,
    )
    event_product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.event_product.event_product_id"),
        nullable=True,
    )
    min_order_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    max_order_quantity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    monthly_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    wholesale_price_min_amount: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    wholesale_price_max_amount: Mapped[int | None] = mapped_column(
        BigInteger, nullable=True
    )
    currency: Mapped[str] = mapped_column(CHAR(3), nullable=False, default="KRW")
    oem_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNKNOWN"
    )
    private_label_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNKNOWN"
    )
    # 08 9.3절 "독점유통 검토 여부" - 거래 가능 여부가 아니라 검토 착수 여부를 묻는 참/거짓
    # 질문이라 boolean으로 유지한다 (모듈 docstring 참고).
    exclusive_distribution_considered: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    export_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNKNOWN"
    )
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DRAFT"
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

    participation: Mapped[ExhibitorParticipation] = relationship(
        back_populates="trade_conditions"
    )
    event_product: Mapped[EventProduct | None] = relationship(
        back_populates="trade_conditions"
    )
    terms: Mapped[list[TradeConditionTerm]] = relationship(
        back_populates="trade_condition", cascade="all, delete-orphan"
    )


class TradeConditionTerm(Base):
    """exhibition.trade_condition_term - db-erd 12.8 본문
    ("지역·채널·국가는 trade_condition_term으로 정규화한다").
    """

    __tablename__ = "trade_condition_term"
    __table_args__ = (
        _ontology_fk(
            "taxonomy_version_id",
            "concept_id",
            name="fk_trade_condition_term_ontology_revision",
        ),
        CheckConstraint(
            f"term_type IN ({_in_list(TRADE_CONDITION_TERM_TYPES)})",
            name="term_type_allowed",
        ),
        UniqueConstraint(
            "trade_condition_id",
            "term_type",
            "taxonomy_version_id",
            "concept_id",
            name="uq_trade_condition_term",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    trade_condition_term_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    trade_condition_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.trade_condition.trade_condition_id"),
        nullable=False,
    )
    term_type: Mapped[str] = mapped_column(String(20), nullable=False)
    taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    trade_condition: Mapped[TradeCondition] = relationship(back_populates="terms")


# ============================================================================
# 6. 부스 (db-erd 13.1)
# ============================================================================


class Booth(Base):
    """exhibition.booth - db-erd 13.1.

    08 12.3절 "실시간 운영상태" 갱신 대상. congestion_level·operating_status는 08 12.3절
    "상태 우선순위"(CLOSED > PAUSED > SOLD_OUT > CONGESTED > OPEN)에 따라 매칭엔진이
    재정렬·제외에 사용하는 실시간 필드이며, row_version으로 낙관적 동시성을 제어한다(db-erd
    13.1 본문: "row_version | BIGINT | 동시 수정").
    """

    __tablename__ = "booth"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_booth_event_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "zone_id"],
            [
                f"{SCHEMA_EXHIBITION}.event_zone.tenant_id",
                f"{SCHEMA_EXHIBITION}.event_zone.event_id",
                f"{SCHEMA_EXHIBITION}.event_zone.event_zone_id",
            ],
            name="fk_booth_zone_same_event",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "participation_id"],
            [
                f"{SCHEMA_EXHIBITION}.exhibitor_participation.tenant_id",
                f"{SCHEMA_EXHIBITION}.exhibitor_participation.event_id",
                f"{SCHEMA_EXHIBITION}.exhibitor_participation.participation_id",
            ],
            name="fk_booth_participation_boundary",
        ),
        UniqueConstraint("event_id", "booth_number", name="uq_booth_event_number"),
        CheckConstraint(
            f"operating_status IN ({_in_list(BOOTH_OPERATING_STATUSES)})",
            name="operating_status_allowed",
        ),
        CheckConstraint(
            f"congestion_level IN ({_in_list(BOOTH_CONGESTION_LEVELS)})",
            name="congestion_level_allowed",
        ),
        CheckConstraint(
            "estimated_wait_minutes IS NULL OR estimated_wait_minutes >= 0",
            name="estimated_wait_minutes_nonneg",
        ),
        # db-erd 21절 idx_booth_live를 그대로 반영한다.
        Index("idx_booth_live", "event_id", "operating_status", "congestion_level"),
        {"schema": SCHEMA_EXHIBITION},
    )

    booth_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    participation_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    zone_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    booth_number: Mapped[str] = mapped_column(String(30), nullable=False)
    map_x: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    map_y: Mapped[float | None] = mapped_column(Numeric(10, 3), nullable=True)
    operating_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="CLOSED"
    )
    congestion_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNKNOWN"
    )
    estimated_wait_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status_observed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # db-erd 6.2절: "row_version | BIGINT | NOT NULL, 기본 1".
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

    participation: Mapped[ExhibitorParticipation] = relationship(
        back_populates="booths"
    )
    status_history: Mapped[list[BoothStatusHistory]] = relationship(
        back_populates="booth", cascade="all, delete-orphan"
    )
    qr_codes: Mapped[list[BoothQr]] = relationship(
        back_populates="booth", cascade="all, delete-orphan"
    )


class BoothStatusHistory(Base):
    """exhibition.booth_status_history - db-erd 13.1 본문.

    "변경 전후 상태, 행위자, 사유, request_id, created_at을 append-only로 저장한다". 이
    클래스는 UPDATE·DELETE를 막는 DB 트리거를 만들지 않는다(권한·트리거는 인프라 작업
    범위); 리포지토리 계층에서 INSERT 전용으로 다뤄야 한다 (interaction.meeting_status_history
    와 동일한 패턴, app/models/meeting.py 참고).
    """

    __tablename__ = "booth_status_history"
    __table_args__ = (
        CheckConstraint(
            f"previous_status IS NULL OR previous_status IN ({_in_list(BOOTH_OPERATING_STATUSES)})",
            name="previous_status_allowed",
        ),
        CheckConstraint(
            f"new_status IN ({_in_list(BOOTH_OPERATING_STATUSES)})",
            name="new_status_allowed",
        ),
        Index("ix_booth_status_history_booth_created", "booth_id", "created_at"),
        {"schema": SCHEMA_EXHIBITION},
    )

    booth_status_history_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    booth_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.booth.booth_id"),
        nullable=False,
    )
    previous_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    new_status: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("profile.user_account.user_id"), nullable=True
    )
    reason_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    # 상태 전이를 유발한 API 요청과의 상관관계 추적. integration.idempotency_record는 다른
    # 에이전트 소유라 FK를 걸지 않고 값만 저장한다 (meeting.py MeetingStatusHistory와 동일).
    request_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    booth: Mapped[Booth] = relationship(back_populates="status_history")


class BoothQr(Base):
    """exhibition.booth_qr - db-erd 13.1 본문.

    "토큰 원문 대신 HMAC, valid_from/until, status, key_version을 저장한다". QR 스캔의
    5분 중복 방지 자체는 integration.idempotency_record + 방문·부스 잠금(db-erd 22.2절)의
    책임이며, 이 테이블은 QR 토큰 자체의 발급·회전만 관리한다.
    """

    __tablename__ = "booth_qr"
    __table_args__ = (
        CheckConstraint(
            f"status IN ({_in_list(BOOTH_QR_STATUSES)})", name="status_allowed"
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from < valid_until",
            name="valid_period_order",
        ),
        CheckConstraint("key_version >= 1", name="key_version_positive"),
        {"schema": SCHEMA_EXHIBITION},
    )

    booth_qr_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    booth_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.booth.booth_id"),
        nullable=False,
    )
    token_hmac: Mapped[bytes] = mapped_column(LargeBinary, nullable=False, unique=True)
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    key_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    booth: Mapped[Booth] = relationship(back_populates="qr_codes")


# ============================================================================
# 7. 프로그램 (db-erd 13.2)
# ============================================================================


class Program(Base):
    """exhibition.program - db-erd 13.2.

    db-erd 13.2절 본문은 "행사·구역, 프로그램명·유형, 시작·종료, 정원, 예약필요, 상태를
    저장한다"는 한 문장뿐이라, 컬럼별 정확한 타입·제약(특히 program_type·status 허용값)은
    이 파일에서 합리적으로 확정했다. TODO(운영 화면 상세설계 확정 후 재검토): program_type·
    status 실제 허용값 목록.
    """

    __tablename__ = "program"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_program_event_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "zone_id"],
            [
                f"{SCHEMA_EXHIBITION}.event_zone.tenant_id",
                f"{SCHEMA_EXHIBITION}.event_zone.event_id",
                f"{SCHEMA_EXHIBITION}.event_zone.event_zone_id",
            ],
            name="fk_program_zone_same_event",
        ),
        CheckConstraint(
            "start_at IS NULL OR end_at IS NULL OR start_at < end_at",
            name="time_range",
        ),
        CheckConstraint("capacity IS NULL OR capacity >= 0", name="capacity_nonneg"),
        CheckConstraint(
            f"status IN ({_in_list(PROGRAM_STATUSES)})", name="status_allowed"
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    program_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    zone_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), nullable=True)
    program_name: Mapped[str] = mapped_column(String(200), nullable=False)
    # db-erd에 값 목록이 없어 개방형 문자열로 둔다 (예: TALK, TASTING_CLASS, PERFORMANCE 등).
    program_type: Mapped[str | None] = mapped_column(String(30), nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    end_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    reservation_required: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PLANNED")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


# ============================================================================
# 8. 공급 프로파일 확장 테이블 (08 문서 27절 - exhibition 도메인 최우선 근거)
# ============================================================================


class ExhibitorProfile(Base):
    """exhibition.exhibitor_profile - 08 문서 27.1절.

    Exhibitor(상시 마스터 정보)에 덧붙는 1:1 확장 테이블로, 매칭엔진이 바로 소비할 수 있는
    사업역량·희망 바이어·완성도·거래 준비도를 담는다(08 3절 "공급 프로파일 전체 구조" 1·3·8
    항목의 DB 반영). business_type은 08 4.2절이 "복수 유형 가능"이라 규정하고 08 29절 매칭엔진
    입력 예시가 "business_types": [...] 배열로 요구하므로, 정규화 원본은
    ExhibitorBusinessType에 두고 여기서는 그 배열을 그대로 캐시한 JSONB로 저장한다(모듈
    docstring 참고). capability_json/preferred_buyer_json도 08 4.3절·8.3절 JSON 예시를 그대로
    담는 캐시 컬럼이다.
    """

    __tablename__ = "exhibitor_profile"
    __table_args__ = (
        CheckConstraint(
            "trade_readiness_score IS NULL "
            "OR (trade_readiness_score >= 0 AND trade_readiness_score <= 100)",
            name="trade_readiness_score_range",
        ),
        CheckConstraint(
            "consumer_completeness >= 0 AND consumer_completeness <= 100",
            name="consumer_completeness_range",
        ),
        CheckConstraint(
            "buyer_completeness >= 0 AND buyer_completeness <= 100",
            name="buyer_completeness_range",
        ),
        CheckConstraint(
            f"approval_status IN ({_in_list(PROFILE_APPROVAL_STATUSES)})",
            name="approval_status_allowed",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    exhibitor_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    exhibitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id"),
        nullable=False,
        unique=True,
    )
    # 08 27.1: "business_type | 업체 유형" - 단수형 필드명이지만 08 4.2절의 "복수 유형 가능"과
    # 29절 매칭엔진 입력 예시("business_types": [...])를 만족하려면 코드 배열이어야 한다.
    # 정규화된 원본은 ExhibitorBusinessType이며 이 컬럼은 그 스냅샷 캐시다.
    business_type: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 08 4.3절 제조·유통·사업화역량 체크리스트 JSON.
    capability_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 08 8.3절 "업체 희망 바이어 프로파일" JSON 예시 구조.
    preferred_buyer_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 08 18절 "거래 준비도" 산식(가중합)의 결과 점수. 등급(READY 등)은 애플리케이션 계층에서
    # 이 점수로부터 계산한다 - 27.1절 필드 목록에 별도 등급 컬럼이 없기 때문이다.
    trade_readiness_score: Mapped[float | None] = mapped_column(
        Numeric(5, 2), nullable=True
    )
    consumer_completeness: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )
    buyer_completeness: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DRAFT"
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    exhibitor: Mapped[Exhibitor] = relationship(back_populates="profile")


class ProductProfile(Base):
    """exhibition.product_profile - 08 문서 27.2절.

    Product(상시 마스터)에 덧붙는 1:1 확장 테이블로, 08 5절 "제품 프로파일"의 맛·향·용도·
    차별성 구조를 담는다. category_code는 product.category_concept_id의 표시용 코드 캐시다
    (product 마스터가 이미 category_taxonomy_version_id/category_concept_id로 주종 개념을
    정규화 참조하므로, 여기서는 27.5절과 동일하게 "조회·API용" attribute_code 문자열만 둔다).
    """

    __tablename__ = "product_profile"
    __table_args__ = (
        CheckConstraint(
            "consumer_score >= 0 AND consumer_score <= 100", name="consumer_score_range"
        ),
        CheckConstraint(
            "buyer_score >= 0 AND buyer_score <= 100", name="buyer_score_range"
        ),
        CheckConstraint(
            f"approval_status IN ({_in_list(PROFILE_APPROVAL_STATUSES)})",
            name="approval_status_allowed",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    product_profile_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    product_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.product.product_id"),
        nullable=False,
        unique=True,
    )
    # product.category_concept_id의 표시용 코드 캐시. 정본은 product 테이블 쪽 복합 FK다.
    category_code: Mapped[str | None] = mapped_column(String(100), nullable=True)
    # 08 5.2절 JSON 예시 구조: {"TASTE.DRY": 4, "TASTE.SMOOTH": 3, ...} (0~5 강도).
    taste_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    aroma_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    # 08 5.3절 USE.* 코드 배열.
    usage_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # 08 5.4절 차별성 코드 배열. "수상·인증·친환경 표현은 증빙자료가 있을 때만 공개"(5.4절
    # 본문)라는 제약은 애플리케이션/승인 계층에서 강제해야 한다.
    feature_json: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    consumer_score: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=0
    )
    buyer_score: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False, default=0)
    current_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DRAFT"
    )
    # 27.2절 필드 목록에는 없지만, db-erd 6.2절 공통 변경 컬럼 규칙에 따라 변경시각을 남긴다.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    product: Mapped[Product] = relationship(back_populates="profile")


class SupplyCapability(Base):
    """exhibition.supply_capability - 08 문서 27.3절.

    08 7.4절 "생산역량 구조"(current_monthly_capacity, expandable_capacity 등)를
    27.3절이 정의한 실제 컬럼명(monthly_capacity, available_capacity 등)으로 구현한다.
    product_id는 27.3절 표에는 있지만 08 7.4절 본문은 업체 단위 생산역량만 설명하므로,
    trade_condition.event_product_id와 동일하게 "제품별이면 채우고 업체 공통이면 NULL"
    패턴으로 nullable 처리한다.
    """

    __tablename__ = "supply_capability"
    __table_args__ = (
        CheckConstraint(
            "monthly_capacity IS NULL OR monthly_capacity >= 0",
            name="monthly_capacity_nonneg",
        ),
        CheckConstraint(
            "available_capacity IS NULL OR available_capacity >= 0",
            name="available_capacity_nonneg",
        ),
        CheckConstraint(
            "lead_time_days IS NULL OR lead_time_days >= 0",
            name="lead_time_days_nonneg",
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until",
            name="valid_period_order",
        ),
        CheckConstraint(
            f"verification_status IN ({_in_list(VERIFICATION_STATUSES)})",
            name="verification_status_allowed",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    supply_capability_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    exhibitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id"),
        nullable=False,
    )
    product_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.product.product_id"),
        nullable=True,
    )
    monthly_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    available_capacity: Mapped[int | None] = mapped_column(Integer, nullable=True)
    lead_time_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 08 8.1절 유통채널 코드 배열의 지역/배송 버전. 정규화 원본이 필요해지면
    # trade_condition_term과 동일한 패턴으로 별도 정규화 테이블을 추가할 수 있다. 현재는
    # 27.3절이 이 필드를 단일 컬럼으로만 정의하고 있어 코드 배열 캐시(JSONB)로 둔다.
    supply_regions: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    logistics_methods: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    valid_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    valid_until: Mapped[date | None] = mapped_column(Date, nullable=True)
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="SELF_DECLARED"
    )
    # 27.3절 필드 목록에는 없지만 db-erd 6.2절 공통 변경 컬럼 규칙을 따른다.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    exhibitor: Mapped[Exhibitor] = relationship(back_populates="supply_capabilities")
    product: Mapped[Product | None] = relationship(back_populates="supply_capabilities")


class ExhibitorBuyerPreference(Base):
    """exhibition.buyer_preference - 08 문서 27.4절 (PK 필드명은 exhibitor_buyer_preference_id).

    08 8.3절 "업체 희망 바이어 프로파일" JSON 예시를 정규화한 테이블. buyer_type/channel/
    region 3개 차원 중 최소 하나는 채워야 의미가 있는 선호 규칙이 되므로 CHECK로 강제한다.
    코드값은 하드코딩 enum이 아니라 ontology.concept_revision 참조로 받는다(작업 지시 원칙).
    """

    __tablename__ = "buyer_preference"
    __table_args__ = (
        _ontology_fk(
            "taxonomy_version_id",
            "buyer_type_concept_id",
            name="fk_buyer_preference_buyer_type_ontology_revision",
        ),
        _ontology_fk(
            "taxonomy_version_id",
            "channel_concept_id",
            name="fk_buyer_preference_channel_ontology_revision",
        ),
        _ontology_fk(
            "taxonomy_version_id",
            "region_concept_id",
            name="fk_buyer_preference_region_ontology_revision",
        ),
        CheckConstraint(
            "num_nonnulls(buyer_type_concept_id, channel_concept_id, region_concept_id) >= 1",
            name="at_least_one_dimension",
        ),
        CheckConstraint(
            "volume_min IS NULL OR volume_min >= 0", name="volume_min_nonneg"
        ),
        CheckConstraint(
            "volume_max IS NULL OR volume_max >= 0", name="volume_max_nonneg"
        ),
        CheckConstraint(
            "volume_min IS NULL OR volume_max IS NULL OR volume_min <= volume_max",
            name="volume_order",
        ),
        CheckConstraint(
            f"preference_level IN ({_in_list(BUYER_PREFERENCE_LEVELS)})",
            name="preference_level_allowed",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    exhibitor_buyer_preference_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    exhibitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id"),
        nullable=False,
    )
    # buyer_type/channel/region 3개 개념이 통상 같은 활성 분류체계 버전을 공유한다고 보고
    # taxonomy_version_id 하나를 공유 컬럼으로 둔다(각 concept_id별로 버전을 따로 저장하지
    # 않는다) - 27.4절이 각 코드를 별도 버전 컬럼 없이 buyer_type_code/channel_code/
    # region_code로만 나열하는 것과 가장 가까운 절충이다.
    taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    buyer_type_concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    channel_concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    region_concept_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    volume_min: Mapped[int | None] = mapped_column(Integer, nullable=True)
    volume_max: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preference_level: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PREFERRED"
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    exhibitor: Mapped[Exhibitor] = relationship(back_populates="buyer_preferences")


class SupplyProfileAttribute(Base):
    """exhibition.profile_attribute - 08 문서 27.5절.

    08 14절 "공급 프로파일 속성 공통 구조"의 DB 구현이다. object_type + object_id로 업체·
    제품·거래조건 중 무엇의 속성인지 표시하는 다형 참조이며, db-erd 2절이 일반적으로는
    다형 참조를 recommendable 패턴으로 대체하라고 권고하지만 이 속성 저장소는 "추천 대상"이
    아니라 "속성 원자료"이므로 그 권고 대상이 아니다(recommendable은 exhibitor_participation/
    event_product/booth/program처럼 추천 결과가 직접 가리키는 대상에만 적용된다). object_id는
    object_type에 따라 대상 테이블이 달라지므로 단일 FK를 걸지 않는다.

    클래스 이름을 SupplyProfileAttribute로 지은 이유는 모듈 docstring을 참고한다(profile.py의
    ProfileAttribute와 이름 충돌을 피하기 위함이며, 실제 테이블은 스키마가 달라 충돌하지 않는다).
    """

    __tablename__ = "profile_attribute"
    __table_args__ = (
        _ontology_fk(
            "taxonomy_version_id",
            "concept_id",
            name="fk_supply_profile_attribute_ontology_revision",
        ),
        # attribute_code(비정규화 캐시)가 concept_id의 실제 concept_code와 어긋나지 않도록
        # DB에서 강제한다. ontology.concept은 PRIMARY KEY(concept_id)와 별개로
        # UNIQUE(concept_id, concept_code)도 가지고 있어(0003_foundation.py upgrade() 첫
        # 문장: op.create_unique_constraint("uq_ontology_concept_id_code", "concept",
        # ["concept_id", "concept_code"], schema="ontology")) 이 복합 FK가 유효하다.
        ForeignKeyConstraint(
            ["concept_id", "attribute_code"],
            ["ontology.concept.concept_id", "ontology.concept.concept_code"],
            name="fk_supply_profile_attribute_concept_code",
        ),
        CheckConstraint(
            f"object_type IN ({_in_list(SUPPLY_ATTRIBUTE_OBJECT_TYPES)})",
            name="object_type_allowed",
        ),
        CheckConstraint(
            f"source_type IN ({_in_list(SUPPLY_SOURCE_TYPES)})",
            name="source_type_allowed",
        ),
        CheckConstraint(
            f"verification_status IN ({_in_list(VERIFICATION_STATUSES)})",
            name="verification_status_allowed",
        ),
        CheckConstraint("confidence >= 0 AND confidence <= 1", name="confidence_range"),
        CheckConstraint(
            f"visibility IN ({_in_list(VISIBILITY_LEVELS)})", name="visibility_allowed"
        ),
        CheckConstraint(
            "valid_from IS NULL OR valid_until IS NULL OR valid_from <= valid_until",
            name="valid_period_order",
        ),
        Index(
            "ix_supply_profile_attribute_lookup",
            "object_type",
            "object_id",
            "taxonomy_version_id",
            "concept_id",
            "active",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    supply_attribute_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    object_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 다형 참조 대상 ID. object_type에 따라 exhibitor_id/product_id/trade_condition_id 중
    # 하나를 가리키며, 대상 테이블이 가변적이라 단일 FK를 걸지 않는다 (클래스 docstring 참고).
    object_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    taxonomy_version_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    concept_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    # 08 27.5절: "조회·API용 개념 코드(비정규화 시 정본과 일치 검증)". 위 복합 FK
    # (fk_supply_profile_attribute_concept_code)가 concept_id에 해당하는 실제 concept_code와의
    # 일치를 DB에서 강제한다.
    attribute_code: Mapped[str] = mapped_column(String(100), nullable=False)
    value_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    source_type: Mapped[str] = mapped_column(String(30), nullable=False)
    verification_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="SELF_DECLARED"
    )
    confidence: Mapped[float] = mapped_column(Numeric(4, 3), nullable=False, default=1)
    visibility: Mapped[str] = mapped_column(
        String(30), nullable=False, default="PUBLIC"
    )
    valid_from: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    valid_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # 27.5절 필드 목록에는 없지만 db-erd 6.2절 공통 규칙에 따라 생성시각을 남긴다.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
