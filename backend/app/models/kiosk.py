"""키오스크 물리 단말기 프로비저닝·설정 (exhibition 스키마).

근거 문서와 우선순위
---------------------
- `.harness/contracts/domain-model.md` §15(CTR-008 WAVE-1 크로스워크)가 이 공백을 처음
  확인했다. `docs/redesign-v2/kiosk/K-1-service-scope.md` §4(자동 세션 초기화 - 유휴
  타임아웃 값이 실제로 저장될 곳이 필요), `K-6-i18n-accessibility.md` §1(다국어 시작화면)이
  요구하는 "단말별 설정"의 저장소.

왜 `profile.guest_session`과 다른가
------------------------------------
`profile.guest_session`(app/models/identity.py)은 "누가 방문해서 검색했는가"(방문자
관점, 익명 단기 세션)를 표현하고, 이 파일은 "어느 물리적 키오스크 단말기가 어느
부스/구역에 설치돼 있고 무엇으로 설정돼 있는가"(운영자 관점, 자산 관리)를 표현한다.
`GuestSession.device_type`은 자유문자열 메모(예: "MOBILE_WEB")일 뿐 단말 등록·설정
테이블이 아니다 - 두 개념을 하나의 테이블에 억지로 합치면 세션(짧은 수명, 대량 생성)과
단말(긴 수명, 소수 존재)의 라이프사이클이 뒤섞인다.

이 파일에서 구현하는 테이블
---------------------------
1. exhibition.kiosk_device - 물리 단말기 등록부. `exhibition.event_zone`(부스 위치)에
   선택적으로 연결한다(K-5 §2의 "구역 단위" 원칙 그대로 재사용 - 정밀 좌표 저장 없음).
2. exhibition.kiosk_config - 단말별 현재 설정(언어, 유휴 타임아웃 등). 단말 1개당
   설정 1행(UNIQUE)만 두는 최소 설계 - 설정 이력 버전관리는 이번 Wave 범위 밖.

개인정보 미포함 확인 (AGENTS.md §8)
--------------------------------------
이 파일의 모든 컬럼은 하드웨어 식별자·구역 위치·언어·타임아웃 설정뿐이며, 이름·전화·
이메일 등 개인 식별정보 컬럼은 전혀 없다. `infra/scripts/scope-violation-check`가
검사하는 개인정보 입력필드 패턴과 무관하다.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Integer,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SCHEMA_EXHIBITION, Base
from app.models.common import new_uuid7

_new_uuid = new_uuid7


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


KIOSK_DEVICE_STATUSES: tuple[str, ...] = (
    "PROVISIONED",
    "ACTIVE",
    "MAINTENANCE",
    "RETIRED",
)

#: K-1 §4 "자동 세션 초기화"의 두 트리거 - 유휴시간 경과, 또는 운영자 수동 초기화.
SESSION_RESET_POLICIES: tuple[str, ...] = ("IDLE_TIMEOUT", "MANUAL_ONLY")


class KioskDevice(Base):
    """exhibition.kiosk_device - 현장 키오스크 물리 단말기 등록부.

    `event_zone_id`는 K-5 §2의 "구역 단위" 원칙에 따라 선택적(nullable) - 등록 시점에
    아직 구역 배치가 확정되지 않은 단말도 있을 수 있다.
    """

    __tablename__ = "kiosk_device"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_kiosk_device_event_boundary",
        ),
        ForeignKeyConstraint(
            ["tenant_id", "event_id", "event_zone_id"],
            [
                f"{SCHEMA_EXHIBITION}.event_zone.tenant_id",
                f"{SCHEMA_EXHIBITION}.event_zone.event_id",
                f"{SCHEMA_EXHIBITION}.event_zone.event_zone_id",
            ],
            name="fk_kiosk_device_zone_boundary",
        ),
        UniqueConstraint(
            "tenant_id", "event_id", "device_code", name="uq_kiosk_device_event_code"
        ),
        CheckConstraint(
            f"device_status IN ({_in_list(KIOSK_DEVICE_STATUSES)})",
            name="device_status_allowed",
        ),
        {"schema": SCHEMA_EXHIBITION},
    )

    kiosk_device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_zone_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # 운영자가 현장에서 식별하는 사람이 읽을 수 있는 코드(예: "KIOSK-A-01") - 하드웨어
    # 일련번호와 별개로, 배치가 바뀌어도 안정적인 자체 코드를 둔다.
    device_code: Mapped[str] = mapped_column(String(50), nullable=False)
    hardware_model: Mapped[str | None] = mapped_column(String(100), nullable=True)
    device_status: Mapped[str] = mapped_column(
        String(20), nullable=False, default="PROVISIONED"
    )
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    registered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    config: Mapped[KioskConfig | None] = relationship(
        back_populates="device", uselist=False, cascade="all, delete-orphan"
    )


class KioskConfig(Base):
    """exhibition.kiosk_config - 단말별 현재 설정 1행.

    설정 이력(누가 언제 무엇을 바꿨는지)은 이번 Wave 범위 밖 - 필요해지면 별도
    `kiosk_config_history` 테이블을 추가하는 확장으로 다룬다(지금은 만들지 않음).
    """

    __tablename__ = "kiosk_config"
    __table_args__ = (
        UniqueConstraint("kiosk_device_id", name="uq_kiosk_config_device"),
        CheckConstraint(
            f"session_reset_policy IN ({_in_list(SESSION_RESET_POLICIES)})",
            name="session_reset_policy_allowed",
        ),
        CheckConstraint("idle_timeout_seconds > 0", name="idle_timeout_positive"),
        {"schema": SCHEMA_EXHIBITION},
    )

    kiosk_config_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    kiosk_device_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.kiosk_device.kiosk_device_id"),
        nullable=False,
    )
    default_locale: Mapped[str] = mapped_column(
        String(10), nullable=False, server_default="ko-KR"
    )
    # K-6 §1 다국어 지원 언어 목록 - concept_synonym.locale과 마찬가지로 자유 locale
    # 문자열 배열이라 CHECK로 폐쇄하지 않는다.
    supported_locales: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    idle_timeout_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="90"
    )
    session_reset_policy: Mapped[str] = mapped_column(
        String(20), nullable=False, default="IDLE_TIMEOUT"
    )
    feature_flags: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )

    device: Mapped[KioskDevice] = relationship(back_populates="config")
