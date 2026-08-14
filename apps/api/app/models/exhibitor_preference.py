"""업체 공개 거래조건 요약 + 협력유형 선호 (exhibition 스키마 확장).

WAVE2C BACKEND-EXHIBITOR-PREFERENCE 트랙 산출물.

이 파일을 새로 만들기 전에 확인한 선행 구현 (중복 방지)
-----------------------------------------------------------
``app/models/exhibitor.py``가 이미 이 트랙 GOAL의 상당 부분을 구현하고 있다:

- ``TradeCondition``(exhibition.trade_condition) - oem_status/private_label_status/
  export_status(5단계 YES/NO/CONDITIONAL/NEGOTIABLE/UNKNOWN), min_order_quantity,
  lead_time_days. ``TradeConditionTerm``이 REGION/CHANNEL/COUNTRY 코드를 정규화 보관한다.
- ``ExhibitorBuyerPreference``(exhibition.buyer_preference) - buyer_type/channel/region
  3차원 + volume_min/max + preference_level(REQUIRED/PREFERRED/EXCLUDED). 이미
  ``app/api/v1/routers/partner.py``의 ``PUT /partner/exhibitors/{id}/buyer-preferences``가
  전체 CRUD를 제공한다.

작업 지시가 요구한 필드 중 위 두 테이블이 이미 충분히 커버하는
(oem_available/pb_available/export_available/moq/expected_lead_time/
distribution_channel_codes/supply_region_codes, preferred_buyer_types/preferred_channels/
preferred_regions/min_order_scale) 것을 이 파일에서 다시 저장소로 만들면 동일 사실에 대한
두 개의 진실 공급원이 생겨 정합성 위험을 낳는다(작업 지시의 "동일 목적 파일을 처음부터 새로
만들지 말라" 원칙과 직접 충돌). 그래서 이 파일은 **진짜로 비어 있는 두 조각만** 새 테이블로
추가하고, 나머지는 ``app/services/exhibitor_preference/service.py``가 기존 테이블을 조회해
합성한 읽기 전용 뷰로 제공한다(그 서비스 모듈 docstring에 전체 매핑표가 있다).

이 파일이 새로 추가하는 것
---------------------------
1. ``ExhibitorTradeAvailability``(exhibition.exhibitor_trade_availability) - 업체 단위
   1:1 확장. ``new_trade_available``(신규 거래처 개시 자체에 대한 개방도)과
   ``meeting_available``(상담 수용 일반 의향)은 기존 스키마 어디에도 없다.
   ``ExhibitorParticipation.consultation_enabled``가 의미상 가장 가깝지만 그것은
   (a) 참가 단위 boolean이라 "선언 안 함"과 "명시적으로 거부"를 구분하지 못하고
   (b) NOT NULL DEFAULT FALSE라 08 2.4절 "미등록과 불가능 분리" 원칙(=이 프로젝트 전체가
   따르는 5단계 상태값 규칙, TRADE_AVAILABILITY_STATUSES)을 만족하지 못한다. 그래서 업체가
   명시적으로 선언할 때까지 UNKNOWN으로 남는 별도 5단계 필드를 둔다.
2. ``ExhibitorPreferredCooperationType``(exhibition.exhibitor_cooperation_type) - 업체가
   선호하는 협력유형(신규공급/정기공급/도매/위탁/OEM/PB/독점/공동마케팅/공동개발 등)의
   다대다 목록. 온톨로지 TRADE.* 그룹(concept_type=TRADE_TYPE)에 대응한다.
   ``ExhibitorBuyerPreference``는 buyer_type/channel/region 3차원만 다루고 거래유형
   차원이 없어 여기서 새로 추가한다.

다른 도메인 모델과의 관계
--------------------------
exhibitor.py 모듈 docstring과 동일한 원칙을 따른다: 이 파일은 다른 모델 모듈을 import하지
않는다(여러 에이전트가 동시에 exhibitor.py를 건드릴 수 있어 그 파일에 대한 직접 의존은
충돌 위험을 키운다). ``exhibition.exhibitor``는 문자열 FK("schema.table.column")로만
참조하고, relationship()도 이 파일 안에서 정의된 클래스 사이에만 사용한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_EXHIBITION, Base
from app.models.common import new_uuid7

_new_uuid = new_uuid7

#: 08 문서 2.4절 "미등록과 불가능 분리" 5단계 - exhibitor.py의 TRADE_AVAILABILITY_STATUSES와
#: 동일한 값 목록이다. 값을 여기서 다시 정의하는 이유는 모듈 docstring "다른 도메인 모델과의
#: 관계" 절 참고 (다른 모델 모듈을 import하지 않는 멀티에이전트 안전 관행).
TRADE_AVAILABILITY_STATUSES: tuple[str, ...] = (
    "YES",
    "NO",
    "CONDITIONAL",
    "NEGOTIABLE",
    "UNKNOWN",
)

#: exhibitor.py MASTER_APPROVAL_STATUSES와 동일한 3단계. 공개 노출 전 검수를 강제한다
#: (지시사항의 절대 금지사항: "미승인/미공개 업체 데이터는 공개 검색/추천/키오스크 결과에
#: 절대 노출되지 않는다").
PREFERENCE_APPROVAL_STATUSES: tuple[str, ...] = ("DRAFT", "APPROVED", "REJECTED")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def _ontology_fk(
    version_col: str, concept_col: str, *, name: str
) -> ForeignKeyConstraint:
    """exhibitor.py의 동명 헬퍼와 동일한 (taxonomy_version_id, concept_id) 복합 FK 패턴."""

    return ForeignKeyConstraint(
        [version_col, concept_col],
        [
            "ontology.concept_revision.taxonomy_version_id",
            "ontology.concept_revision.concept_id",
        ],
        name=name,
    )


class ExhibitorTradeAvailability(Base):
    """exhibition.exhibitor_trade_availability - 업체 단위 1:1 공개 거래 개방도 선언.

    ``exhibitor_id`` 자체가 unique라 참가(event)나 제품에 묶이지 않는, 업체 전체에 대한
    단일 공개 선언이다. approval_status가 APPROVED가 되기 전에는 공개 검색/추천/키오스크
    결과에 노출하면 안 된다 - 그 강제는 소비 측(공개 카탈로그/매칭) 책임이며 이 테이블은
    선언 원자료만 보관한다.
    """

    __tablename__ = "exhibitor_trade_availability"
    __table_args__ = (
        CheckConstraint(
            f"new_trade_available IN ({_in_list(TRADE_AVAILABILITY_STATUSES)})",
            name="new_trade_available_allowed",
        ),
        CheckConstraint(
            f"meeting_available IN ({_in_list(TRADE_AVAILABILITY_STATUSES)})",
            name="meeting_available_allowed",
        ),
        CheckConstraint(
            f"approval_status IN ({_in_list(PREFERENCE_APPROVAL_STATUSES)})",
            name="approval_status_allowed",
        ),
        UniqueConstraint("exhibitor_id", name="uq_exhibitor_trade_availability_exhibitor"),
        {"schema": SCHEMA_EXHIBITION},
    )

    exhibitor_trade_availability_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    exhibitor_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id"),
        nullable=False,
    )
    # 신규 거래처를 새로 받을 의향이 있는지 - 어떤 기존 테이블에도 없는 신규 필드.
    # 명시 선언 전까지는 절대 NO로 간주하지 않는다(기본값 UNKNOWN, 애플리케이션 계층에서도
    # 이 필드를 부분수정(PATCH-like)으로만 갱신해 미입력을 NO로 오치환하지 않는다).
    new_trade_available: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNKNOWN", server_default="UNKNOWN"
    )
    # 상담(meeting) 수용에 대한 일반 의향 - ExhibitorParticipation.consultation_enabled(boolean,
    # 참가 단위, 미선언과 거부를 구분 못함)와 구분되는 업체 단위 5단계 선언. 모듈 docstring
    # "이 파일이 새로 추가하는 것" 1번 참고.
    meeting_available: Mapped[str] = mapped_column(
        String(20), nullable=False, default="UNKNOWN", server_default="UNKNOWN"
    )
    approval_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="DRAFT", server_default="DRAFT"
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


class ExhibitorPreferredCooperationType(Base):
    """exhibition.exhibitor_cooperation_type - 업체가 선호하는 협력유형 목록.

    온톨로지 TRADE.* 그룹(concept_type=TRADE_TYPE, 예: TRADE.OEM, TRADE.PRIVATE_LABEL,
    TRADE.EXCLUSIVE, TRADE.CONSIGNMENT, TRADE.JOINT_MARKETING)을 참조한다.
    ``ExhibitorBuyerPreference``(buyer_type/channel/region 3차원)에는 이 차원이 없어
    새로 추가했다 - 모듈 docstring "이 파일이 새로 추가하는 것" 2번 참고.

    선호(preference)는 없음(row 미존재)이 "선호 없음"이지 "거부"가 아니다. PROJECT_SCOPE의
    "누락된 업체 희망 바이어 조건을 감점으로 취급하지 않는다" 원칙을 그대로 이 차원에도
    적용한다 - 다운스트림 매칭은 row가 없으면 이 차원을 그냥 스코어링에서 제외해야 한다
    (``services/exhibitor_preference/service.py``의 ``has_buyer_preference`` 참고).
    """

    __tablename__ = "exhibitor_cooperation_type"
    __table_args__ = (
        _ontology_fk(
            "taxonomy_version_id",
            "concept_id",
            name="fk_exhibitor_cooperation_type_ontology_revision",
        ),
        UniqueConstraint(
            "exhibitor_id",
            "taxonomy_version_id",
            "concept_id",
            name="uq_exhibitor_cooperation_type_concept",
        ),
        Index(
            "ix_exhibitor_cooperation_type_lookup",
            "exhibitor_id",
            "active",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    exhibitor_cooperation_type_id: Mapped[uuid.UUID] = mapped_column(
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
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
