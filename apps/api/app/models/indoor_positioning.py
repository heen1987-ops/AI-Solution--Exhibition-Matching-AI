"""실내 위치 체크포인트 스캔 모델 (interaction 스키마).

무엇이고 왜 있는가
-------------------
이 파일은 "카메라 기반 실내측위"(베스텔라랩 Watchmile류 제품이 하는 것)를 흉내내지 않는다 -
이 코드베이스에는 그런 카메라 인프라가 없다. 대신 이미 존재하는 QR 인프라
(``exhibition.booth_qr`` - app/models/exhibitor.py BoothQr)를 재사용해, 방문객이 부스의
QR을 스캔할 때마다 "이 시각, 이 부스 근처에 있었다"는 저정밀·이벤트 기반 위치 관측 하나를
기록한다. 부스 좌표(``exhibition.booth.map_x/map_y``)와 결합하면 방문 경로 재계산의 "현재
위치" 신호로 쓸 수 있다 - GPS도, 실시간 삼각측량도 아니지만 오늘 이 리포지토리에서 실제로
배포 가능한 유일한 실내 위치 신호다.

app/services/routing/positioning.py의 ``IndoorPositionSource`` 프로토콜과 이 테이블의 관계는
그 모듈의 docstring을 참고한다 - 이 테이블은 ``QrCheckpointProvider`` 하나만을 위한 원자료고,
향후 카메라/AI 기반 공급자가 추가돼도 이 테이블·이 provider는 그대로 둔 채 새 provider
클래스 하나만 추가하면 된다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, ForeignKeyConstraint, Index, func
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_INTERACTION, Base
from app.models.common import new_uuid7

_new_uuid = new_uuid7


class IndoorCheckpointScan(Base):
    """interaction.indoor_checkpoint_scan.

    db-erd-table-spec.md에 명시적으로 정의된 테이블은 아니다(16.4절은 route/route_item만
    다룬다) - 이 파일을 지시한 작업 범위(YOUR TRACK 3번 항목)가 새로 추가하라고 명시한
    테이블이며, 스키마·명명 관례는 이 리포지토리의 기존 append-only 관측 테이블
    (exhibition.booth_status_history)을 그대로 따른다: UPDATE/DELETE 없이 INSERT 전용,
    "누가·언제·어떤 근거로"를 남긴다.

    tenant/event/visit_session 경계는 profile.visit_session과 동일한 복합 FK 패턴으로
    강제한다(app/models/profile.py VisitSession, app/models/route.py Route와 동일한 관례) -
    다른 사용자의 방문 세션에 스캔을 붙일 수 없다.
    """

    __tablename__ = "indoor_checkpoint_scan"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                "exhibition.event.tenant_id",
                "exhibition.event.event_id",
            ],
            name="fk_indoor_checkpoint_scan_event_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "visit_session_id"],
            [
                "profile.visit_session.tenant_id",
                "profile.visit_session.event_id",
                "profile.visit_session.visit_session_id",
            ],
            name="fk_indoor_checkpoint_scan_visit_session_boundary",
        ),
        Index(
            "ix_indoor_checkpoint_scan_visit_session_scanned",
            "visit_session_id",
            "scanned_at",
        ),
        {"schema": SCHEMA_INTERACTION},
    )

    indoor_checkpoint_scan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("core.tenant.tenant_id"), nullable=False
    )
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    visit_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), nullable=False
    )
    booth_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exhibition.booth.booth_id"),
        nullable=False,
    )
    # 어떤 QR(키·회전판)이 이 관측을 만들었는지 감사 추적용으로 남긴다. booth_id로도 위치
    # 신호로는 충분하지만, QR 자체가 회전(key_version)되므로 어떤 발급본이 스캔됐는지는
    # booth_qr_id로만 알 수 있다.
    booth_qr_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("exhibition.booth_qr.booth_qr_id"),
        nullable=False,
    )
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


__all__ = ["IndoorCheckpointScan"]
