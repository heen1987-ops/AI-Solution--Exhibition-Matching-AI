"""AI 추천 방문 동선(U-13) SQLAlchemy 모델 (interaction 스키마).

근거 문서
---------
- docs/db-erd-table-spec.md 16.4절: "route는 visit_session, 최적화 유형, 총·이동 시간, 상태,
  context snapshot을 가진다. route_item은 route, sequence, recommendable_id 또는 meeting_id,
  예정 도착·체류, 실제 도착, 상태를 가진다. CHECK num_nonnulls(recommendable_id, meeting_id) = 1."
  이 문서 문장이 이 파일의 유일한 1차 근거다 - 컬럼을 새로 설계하지 않고 이 문장을 그대로
  테이블로 옮긴다.
- apps/user-web/lib/types.ts ``RouteResponse``/``RouteItemView`` - 이미 프론트가 기대하는
  응답 계약. ``route_preference``/``total_minutes``/``walking_minutes``/``status`` 필드명을
  그대로 DB 컬럼명으로 써서 스키마 레이어(app/schemas/route.py)가 이름 변환 없이 1:1로
  직렬화할 수 있게 한다. profile.VisitSession.route_preference(07 8.4절)와도 같은 이름을
  써서 "최적화 유형"이라는 한 개념에 두 가지 컬럼명이 생기지 않도록 한다.

이 파일이 감독하는 두 테이블
-----------------------------
    1. interaction.route       - db-erd 16.4 앞부분
    2. interaction.route_item  - db-erd 16.4 뒷부분

다른 도메인 모델과의 관계
--------------------------
다른 스키마 테이블은 "스키마명.테이블명.컬럼명" 문자열 FK로만 참조하고, 다른 모델 모듈을
import하지 않는다 (app/models/exhibitor.py·meeting.py와 동일한 병렬 작업 관례).
route_item.recommendable_id는 exhibition.recommendable(다형 추천 대상 레지스트리, db-erd
13.3절)을 가리킨다 - 부스·행사제품·업체참가·프로그램 중 무엇을 가리키든 이 컬럼 하나로
충분하다(app/models/matching.py Recommendable 모듈 docstring 참고). route_item.meeting_id는
interaction.meeting(app/models/meeting.py MeetingRequest)을 가리킨다.
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
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SCHEMA_INTERACTION, Base
from app.models.common import new_uuid7

_new_uuid = new_uuid7

#: db-erd 16.4절과 apps/user-web/lib/types.ts RouteResponse.status(OpenEnum)가 공유하는
#: 3단계 경로 상태. 새 값이 추가돼도 프론트가 라벨 없이도 동작하도록 프론트는 OpenEnum으로
#: 두지만, DB는 다른 상태 컬럼들과 동일하게 CHECK로 고정한다.
ROUTE_STATUSES: tuple[str, ...] = ("ACTIVE", "COMPLETED", "CANCELLED")

#: db-erd 16.4절과 apps/user-web/lib/types.ts RouteItemView.status가 공유하는 4단계 상태.
ROUTE_ITEM_STATUSES: tuple[str, ...] = ("PENDING", "ARRIVED", "SKIPPED", "COMPLETED")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class Route(Base):
    """interaction.route - db-erd 16.4 앞부분.

    ``context_snapshot``은 이 경로를 계산할 때 사용한 입력을 그대로 보관한다(요청한
    ``start_location``/``constraints``, 실제로 채택된 위치 신호의 출처(``positioning_source``:
    "MANUAL_ZONE"|"QR_CHECKPOINT"), 생성 시각). recalculate가 매번 새 입력을 요구하지 않고
    "현재 상태로 다시 계산"만 하도록 프론트가 설계돼 있으므로(``recalculateRoute(routeId)``가
    바디 없이 POST한다 - apps/user-web/app/route/page.tsx), 원래 제약조건을 다시 조회하려면
    이 스냅샷이 필요하다.
    """

    __tablename__ = "route"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                "exhibition.event.tenant_id",
                "exhibition.event.event_id",
            ],
            name="fk_route_event_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "visit_session_id"],
            [
                "profile.visit_session.tenant_id",
                "profile.visit_session.event_id",
                "profile.visit_session.visit_session_id",
            ],
            name="fk_route_visit_session_boundary",
        ),
        CheckConstraint(
            f"status IN ({_in_list(ROUTE_STATUSES)})", name="status_allowed"
        ),
        CheckConstraint(
            "total_minutes IS NULL OR total_minutes >= 0", name="total_minutes_nonneg"
        ),
        CheckConstraint(
            "walking_minutes IS NULL OR walking_minutes >= 0",
            name="walking_minutes_nonneg",
        ),
        Index("ix_route_visit_session_status", "visit_session_id", "status"),
        {"schema": SCHEMA_INTERACTION},
    )

    route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    visit_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    # db-erd 16.4: "최적화 유형". apps/user-web/lib/types.ts RouteResponse.route_preference /
    # profile.VisitSession.route_preference(07 8.4절)와 동일 개념·동일 이름으로 맞춘다
    # (예: RECOMMENDED_FIRST, SHORTEST, LOW_CONGESTION - 07 문서 예시값, 개방형 코드라 CHECK를
    # 두지 않는다).
    route_preference: Mapped[str | None] = mapped_column(String(30), nullable=True)
    total_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    walking_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    context_snapshot: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    # 동시 recalculate 요청이 서로 덮어쓰지 않도록 두는 낙관적 동시성 컬럼. db-erd 16.4절에는
    # 명시돼 있지 않지만 이 저장소 전반의 관례(exhibition.booth.row_version 등)를 따른다 - API
    # 계약(RouteResponse)에는 노출하지 않는다.
    row_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)

    items: Mapped[list[RouteItem]] = relationship(
        back_populates="route",
        cascade="all, delete-orphan",
        order_by="RouteItem.sequence",
    )


class RouteItem(Base):
    """interaction.route_item - db-erd 16.4 뒷부분.

    "recommendable_id 또는 meeting_id, ... CHECK num_nonnulls(recommendable_id, meeting_id) = 1"
    을 그대로 구현한다. object_type/object_id 같은 공개 표현은 이 테이블에 두지 않는다 -
    exhibition.recommendable이 이미 그 다형 참조의 단일 진실 공급원이므로(모듈 docstring
    참고), 응답 시점에 recommendable을 한 번 더 읽어 공개 object_type/object_id로 변환한다
    (app/api/v1/routers/recommendations.py의 ``_resolve_result_object_id``와 동일한 패턴,
    app/services/routing/service.py 참고).
    """

    __tablename__ = "route_item"
    __table_args__ = (
        UniqueConstraint(
            "route_id", "sequence", name="uq_route_item_route_sequence"
        ),
        CheckConstraint(
            "num_nonnulls(recommendable_id, meeting_id) = 1",
            name="exactly_one_target",
        ),
        CheckConstraint(
            f"status IN ({_in_list(ROUTE_ITEM_STATUSES)})", name="status_allowed"
        ),
        CheckConstraint(
            "expected_stay_minutes IS NULL OR expected_stay_minutes >= 0",
            name="expected_stay_minutes_nonneg",
        ),
        CheckConstraint(
            "sequence >= 0", name="sequence_nonneg"
        ),
        Index("ix_route_item_route_sequence", "route_id", "sequence"),
        {"schema": SCHEMA_INTERACTION},
    )

    route_item_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    route_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_INTERACTION}.route.route_id"),
        nullable=False,
    )
    sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    recommendable_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exhibition.recommendable.recommendable_id"),
        nullable=True,
    )
    meeting_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_INTERACTION}.meeting.meeting_id"),
        nullable=True,
    )
    expected_arrival_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    expected_stay_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_arrival_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="PENDING")

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    route: Mapped[Route] = relationship(back_populates="items")


__all__ = [
    "ROUTE_ITEM_STATUSES",
    "ROUTE_STATUSES",
    "Route",
    "RouteItem",
]
