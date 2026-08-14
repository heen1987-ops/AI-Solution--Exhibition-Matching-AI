"""바이어 전용 매칭 세션/후보 도메인 SQLAlchemy 모델 (matching 스키마).

트랙: BACKEND-BUYER-MATCH (WAVE 2C).

기존 코드와의 관계에 대한 중요한 메모
--------------------------------------
``app/models/matching.py``의 ``MatchRun``/``MatchResult``/``MatchReason``가 이미
``profile.user_profile.user_type = 'BUYER'``를 포함한 모든 개인화 추천(연출/추천 위젯)을
처리하고, ``.harness/decisions.md`` DECISION-005는 재설계 문서의 ``/buyer/matches`` 경로를
새로 만들지 않고 기존 ``/recommendations``(user_type=BUYER로 처리)로 커버하기로 이미
결정했다.

그런데 이 워커(BACKEND-BUYER-MATCH, WAVE 2C)에게 주어진 작업 지시는 그 결정과 무관하게
``POST /buyer/matches``, ``GET /buyer/matches/{id}``, ``POST /buyer/compare`` 전용 엔드포인트와
전용 세션 저장소를 독립적으로 구현하도록 명시적으로 요구했다(바이어 자격조건 접근제어,
비교 API, unknown_fields 등 기존 추천 파이프라인에는 없는 바이어 전용 요구사항 포함).
그래서 이 파일은 기존 ``matching.recommendation_session``/``match_result``를 재사용하지 않고
별도 테이블(``matching.buyer_match_session``/``buyer_match_candidate``)로 새로 설계했다.

**통합 시 재정합 필요**: 두 경로(``/recommendations`` vs ``/buyer/matches``)가 당분간
병존한다. 통합 단계에서 다음 중 하나로 정리해야 한다.
  1) 이 테이블·라우터를 폐기하고 ``/buyer/matches``를 ``/recommendations``의 별칭으로 만든다
     (DECISION-005 원안), 또는
  2) DECISION-005를 뒤집고 이 전용 바이어 매칭 트랙을 정본으로 채택한다.
이 파일의 최종 보고서(작업 결과 요약)에 이 충돌을 명시적으로 남긴다.

컬럼 설계 근거
--------------
- ``filters_json``/``candidate_count``/``filtered_count``/``result_count``: 작업 지시가 명시한
  "filters, candidates, hard-filter 결과" 보존 요구사항. ``matching.recommendation_session``의
  candidate_count/filtered_count/result_count와 동일한 의도다.
- ``BuyerMatchCandidate.hard_filter_passed``: 이 테이블에는 하드필터를 통과한 후보만
  저장한다(탈락 후보는 세션 집계 카운트에만 반영되고 개별 행을 남기지 않는다 - db-erd의
  "hard_filter를 통과하지 못한 후보는 match_result에 넣지 않는다" 원칙을 그대로 따른다).
  컬럼 자체는 방어적으로 항상 True로 채워지며, 통합 후 탈락 후보 감사로그가 필요해지면
  별도 테이블로 분리한다.
- ``reason_codes``/``unknown_fields``: AGENTS.md 불변조건("AI는 원문에 없는 값을 단정하지
  않는다. UNKNOWN은 항상 UNKNOWN으로 유지된다")을 만족하기 위해, 점수에 기여한 근거 코드와
  "판단할 근거 데이터가 없어 unknown으로 남긴 항목" 코드를 분리해서 저장한다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SCHEMA_EXHIBITION, SCHEMA_MATCHING, Base
from app.models.common import new_uuid7

_new_uuid = new_uuid7

#: 세션 상태. matching.recommendation_session.status와 동일한 어휘 부분집합(INVALIDATED는
#: 이 트랙 범위 밖이라 제외).
BUYER_MATCH_SESSION_STATUSES: tuple[str, ...] = ("ACTIVE", "EXPIRED")

#: app.services.matching.types.score_to_match_level()과 동일한 4단계 등급 어휘를 그대로 쓴다
#: (중복 정의가 아니라 값 목록만 맞춘다 - 실제 계산은 그 함수를 재사용한다).
BUYER_MATCH_GRADES: tuple[str, ...] = ("VERY_HIGH", "HIGH", "MEDIUM", "LOW")

#: 이 트랙이 인정하는 바이어 자격 등급. 접근제어(app/services/buyer_match/access.py)가
#: 계산해서 세션에 스냅샷으로 남긴다 - 이후 정책이 바뀌어도 과거 세션이 어떤 등급으로
#: 생성됐는지 재현 가능해야 하기 때문이다(AGENTS.md 불변조건 5).
BUYER_VERIFICATION_TIERS: tuple[str, ...] = ("VERIFIED", "LIMITED")


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


class BuyerMatchSession(Base):
    """matching.buyer_match_session - 바이어 전용 매칭 실행 1건."""

    __tablename__ = "buyer_match_session"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_buyer_match_session_event_boundary",
        ),
        CheckConstraint(
            f"status IN ({_in_list(BUYER_MATCH_SESSION_STATUSES)})",
            name="status_allowed",
        ),
        CheckConstraint(
            f"verification_tier IN ({_in_list(BUYER_VERIFICATION_TIERS)})",
            name="verification_tier_allowed",
        ),
        CheckConstraint("candidate_count >= 0", name="candidate_count_nonneg"),
        CheckConstraint("filtered_count >= 0", name="filtered_count_nonneg"),
        CheckConstraint("result_count >= 0", name="result_count_nonneg"),
        CheckConstraint("profile_version >= 1", name="profile_version_positive"),
        Index("ix_buyer_match_session_buyer", "buyer_profile_id", "created_at"),
        Index("ix_buyer_match_session_tenant_event", "tenant_id", "event_id"),
        {"schema": SCHEMA_MATCHING},
    )

    buyer_match_session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    # profile 도메인 소유 테이블(app/models/profile.py). 지연 FK로만 존재한다.
    buyer_profile_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("profile.user_profile.profile_id"),
        nullable=False,
    )
    # 세션을 생성할 때의 profile.user_profile.current_version 스냅샷 (재현성).
    profile_version: Mapped[int] = mapped_column(Integer, nullable=False)
    # 이 트랙이 자체 정의한 개방형 정책 버전 문자열. matching.match_policy_version처럼
    # 정식 버전 테이블로 승격하기 전까지는 상수 문자열로 관리한다
    # (app/services/buyer_match/orchestrator.py의 POLICY_VERSION 참고).
    policy_version: Mapped[str] = mapped_column(String(100), nullable=False)
    # 세션 생성 시점에 계산한 바이어 자격 등급의 스냅샷 (app/services/buyer_match/access.py).
    verification_tier: Mapped[str] = mapped_column(String(20), nullable=False)
    filters_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, default=dict
    )
    candidate_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    filtered_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    generated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    candidates: Mapped[list[BuyerMatchCandidate]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
        order_by="BuyerMatchCandidate.rank",
    )


class BuyerMatchCandidate(Base):
    """matching.buyer_match_candidate - 세션 1건에 속한 하드필터 통과 후보 1건.

    하드필터에서 탈락한 후보는 이 테이블에 행을 남기지 않는다 (클래스 docstring 참고,
    matching.match_result와 동일한 append-only/필터 후 저장 원칙).
    """

    __tablename__ = "buyer_match_candidate"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "exhibitor_id"],
            [
                f"{SCHEMA_EXHIBITION}.exhibitor.tenant_id",
                f"{SCHEMA_EXHIBITION}.exhibitor.exhibitor_id",
            ],
            name="fk_buyer_match_candidate_exhibitor_boundary",
        ),
        UniqueConstraint(
            "buyer_match_session_id", "rank", name="uq_buyer_match_candidate_session_rank"
        ),
        UniqueConstraint(
            "buyer_match_session_id",
            "exhibitor_id",
            name="uq_buyer_match_candidate_session_exhibitor",
        ),
        CheckConstraint("rank > 0", name="rank_positive"),
        CheckConstraint("score >= 0 AND score <= 1", name="score_range"),
        CheckConstraint(
            f"grade IN ({_in_list(BUYER_MATCH_GRADES)})", name="grade_allowed"
        ),
        Index("ix_buyer_match_candidate_session_rank", "buyer_match_session_id", "rank"),
        {"schema": SCHEMA_MATCHING},
    )

    buyer_match_candidate_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    buyer_match_session_id: Mapped[uuid.UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.buyer_match_session.buyer_match_session_id"),
        nullable=False,
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    exhibitor_id: Mapped[uuid.UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    participation_id: Mapped[uuid.UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.exhibitor_participation.participation_id"),
        nullable=True,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    score: Mapped[float] = mapped_column(Numeric(5, 4), nullable=False)
    grade: Mapped[str] = mapped_column(String(20), nullable=False)
    hard_filter_passed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True
    )
    reason_codes: Mapped[list[str]] = mapped_column(JSONB, nullable=False, default=list)
    unknown_fields: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, default=list
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped[BuyerMatchSession] = relationship(back_populates="candidates")
