"""자연어·카테고리 검색 세션·질의·결과 (matching 스키마).

근거 문서와 우선순위
---------------------
- `.harness/contracts/domain-model.md` §15(CTR-008 WAVE-1 크로스워크) - 이 파일이 채우는
  공백을 처음 확인한 문서. `docs/redesign-v2/web/W-2-user-journey.md` §1-6(웹 자연어
  추가검색), `docs/redesign-v2/common/C-4-search-recommendation-engine.md`(구조화+키워드+
  벡터 RRF), CR-001 WEB_ONLY 전환이 기능 요구의 1차 근거다. 기존 키오스크 검색 근거는
  deprecated cleanup 참고자료로만 남는다.

왜 `matching.recommendation_session`/`matching.match_result`(app/models/matching.py)를
재사용하지 않는가
-------------------------------------------------------------------------------------
`RecommendationSession.profile_id`는 NOT NULL이다(개인화 추천은 항상 프로파일이 있다는
전제). 그런데 GUEST_WEB 검색(W-1 §3 "지속 프로파일 없음")은 프로파일 자체가 없는 상태에서
성립해야 한다 - 이 채널을 표현하려면 프로파일을 필수로 요구하지 않는 별도 세션 개념이
필요하다. 결과 대상은 기존
`exhibition.recommendable`(matching.py) 레지스트리를 그대로 재사용하므로 다형 FK나
신규 레지스트리는 만들지 않는다.

이 파일에서 구현하는 테이블
---------------------------
1. matching.search_session - 검색 1회 방문 단위(사람이 아니라 "검색을 시작한 사건").
   인증 사용자(user_id) 또는 익명 게스트(guest_session_id) 중 정확히 하나에 귀속된다.
2. matching.search_query   - 세션 내 개별 질의(자유텍스트 또는 카테고리 선택).
   `ai/schemas`(AIS-005, 이번 Wave에 별도 태스크로 정의됨)의 의도추출 출력을
   `intent_json`에 참조로만 남긴다(원문 없는 조건 생성 금지 원칙과 무관 - 이 테이블은
   그 출력을 검증 없이 그대로 저장하는 감사 로그 역할일 뿐, 판단 로직은 서비스 계층 책임).
3. matching.search_result  - 질의별 순위 결과. AIS-006(하이브리드 검색 Provider
   인터페이스)이 정의하는 점수 DTO(structured_score/keyword_score/semantic_score/
   final_score/reason_codes)와 컬럼명을 맞춰, Wave 2 구현이 매핑 없이 그대로 저장할
   수 있게 한다 - 실제 점수 계산 로직은 이 파일의 책임이 아니다(Wave 2, AIS-GROUP-001).

의도적으로 이 파일에서 만들지 않은 것
--------------------------------------
- 신규 recommendable 레지스트리: `exhibition.recommendable`(app/models/matching.py)을
  FK로 그대로 참조한다.
- AI 의도추출 원본 로그: `ai.ai_execution_log`(CTR-007, 아직 미구현)가 담당할 영역이라
  FK 없이 값만 저장한다(다른 스키마 테이블을 문자열 ForeignKey로만 참조하는 기존 관례와
  동일한 이유로, 아직 없는 테이블은 FK를 걸 수 없다).
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
    Numeric,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import SCHEMA_EXHIBITION, SCHEMA_MATCHING, SCHEMA_PROFILE, Base
from app.models.common import new_uuid7

_new_uuid = new_uuid7


def _in_list(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


#: 검색을 시작한 채널. CR-001 이후 전용 KIOSK 채널은 신규 persistence 대상이 아니며,
#: legacy WEB/KIOSK 값은 0013 migration에서 REGISTERED_WEB/GUEST_WEB로 backfill한다.
SEARCH_CHANNELS: tuple[str, ...] = (
    "REGISTERED_WEB",
    "GUEST_WEB",
    "BUYER_WEB",
    "ADMIN_PREVIEW",
)

SEARCH_SESSION_STATUSES: tuple[str, ...] = ("ACTIVE", "EXPIRED", "COMPLETED")

#: K-4/W-2 §1-6 공통: 자유텍스트 또는 카테고리 선택 중 하나.
SEARCH_QUERY_TYPES: tuple[str, ...] = ("FREE_TEXT", "CATEGORY")

#: CTR-004(오류코드)의 SEARCH_NO_RESULT/AI_SERVICE_UNAVAILABLE과 대응하는 폴백 사유.
#: 신규 값이 필요하면 CTR-004와 함께 갱신한다.
SEARCH_FALLBACK_REASONS: tuple[str, ...] = (
    "NO_RESULT",
    "AI_SERVICE_UNAVAILABLE",
    "INVALID_QUERY",
)


class SearchSession(Base):
    """matching.search_session - 프로파일 유무와 무관하게 성립하는 검색 세션.

    인증 사용자(user_id)와 익명 게스트(guest_session_id) 중 정확히 하나에만 귀속된다
    (profile.guest_session의 num_nonnulls 관례와 동일한 상호배타 원칙).
    """

    __tablename__ = "search_session"
    __table_args__ = (
        ForeignKeyConstraint(
            ["tenant_id", "event_id"],
            [
                f"{SCHEMA_EXHIBITION}.event.tenant_id",
                f"{SCHEMA_EXHIBITION}.event.event_id",
            ],
            name="fk_search_session_event_boundary",
        ),
        CheckConstraint(
            f"channel IN ({_in_list(SEARCH_CHANNELS)})", name="channel_allowed"
        ),
        CheckConstraint(
            f"status IN ({_in_list(SEARCH_SESSION_STATUSES)})", name="status_allowed"
        ),
        CheckConstraint(
            "num_nonnulls(user_id, guest_session_id) = 1",
            name="exactly_one_actor",
        ),
        Index("idx_search_session_guest", "guest_session_id", "started_at"),
        Index("idx_search_session_user", "user_id", "started_at"),
        {"schema": SCHEMA_MATCHING},
    )

    search_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    channel: Mapped[str] = mapped_column(String(30), nullable=False)
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
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="ACTIVE")
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    ended_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    queries: Mapped[list[SearchQuery]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class SearchQuery(Base):
    """matching.search_query - 세션 내 개별 질의 1건.

    `sequence_no`로 세션 내 순서를 고정해, 자연어 추가검색이 여러 차례 반복되는 흐름
    (W-2 §1-6)을 재현 가능하게 한다.
    """

    __tablename__ = "search_query"
    __table_args__ = (
        UniqueConstraint(
            "search_session_id", "sequence_no", name="uq_search_query_session_sequence"
        ),
        CheckConstraint(
            f"query_type IN ({_in_list(SEARCH_QUERY_TYPES)})",
            name="query_type_allowed",
        ),
        CheckConstraint(
            f"fallback_reason IS NULL OR fallback_reason IN "
            f"({_in_list(SEARCH_FALLBACK_REASONS)})",
            name="fallback_reason_allowed",
        ),
        CheckConstraint("result_count >= 0", name="result_count_nonneg"),
        CheckConstraint("sequence_no >= 1", name="sequence_no_positive"),
        {"schema": SCHEMA_MATCHING},
    )

    search_query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    search_session_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.search_session.search_session_id"),
        nullable=False,
    )
    sequence_no: Mapped[int] = mapped_column(Integer, nullable=False)
    query_type: Mapped[str] = mapped_column(String(20), nullable=False)
    # 자유텍스트 질의 원문. CATEGORY 질의는 NULL일 수 있다(카테고리 선택은
    # concept_codes만으로 충분).
    query_text: Mapped[str | None] = mapped_column(String(500), nullable=True)
    # AIS-005(자연어 질의 출력 Schema)가 정의하는 concept_codes 목록을 검증 없이 그대로
    # 참조로만 저장한다 - 온톨로지 코드 유효성 검증은 AIS-005 Pydantic validator의 책임이지
    # 이 테이블의 책임이 아니다.
    concept_codes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    # AIS-005 출력 전체(디버깅·재현용 원문 스냅샷) - AI 실행 자체의 로그는
    # ai.ai_execution_log(CTR-007)가 담당하므로 FK는 걸지 않는다.
    intent_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    result_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    fallback_reason: Mapped[str | None] = mapped_column(String(30), nullable=True)
    submitted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    session: Mapped[SearchSession] = relationship(back_populates="queries")
    results: Mapped[list[SearchResult]] = relationship(
        back_populates="query", cascade="all, delete-orphan"
    )


class SearchResult(Base):
    """matching.search_result - 질의별 순위 결과.

    컬럼명은 AIS-006(하이브리드 검색 Provider 인터페이스)의 점수 DTO
    (structured_score/keyword_score/semantic_score/final_score/reason_codes)와
    맞춘다 - 실제 채널별 점수 계산은 Wave 2(AIS-GROUP-001) 구현 책임이며, 이 테이블은
    저장 형태만 미리 확정한다.
    """

    __tablename__ = "search_result"
    __table_args__ = (
        UniqueConstraint(
            "search_query_id", "rank", name="uq_search_result_query_rank"
        ),
        UniqueConstraint(
            "search_query_id",
            "recommendable_id",
            name="uq_search_result_query_recommendable",
        ),
        CheckConstraint("rank >= 1", name="rank_positive"),
        Index("idx_search_result_query_rank", "search_query_id", "rank"),
        Index("idx_search_result_target", "recommendable_id", text("created_at DESC")),
        {"schema": SCHEMA_MATCHING},
    )

    search_result_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=_new_uuid
    )
    search_query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_MATCHING}.search_query.search_query_id"),
        nullable=False,
    )
    recommendable_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey(f"{SCHEMA_EXHIBITION}.recommendable.recommendable_id"),
        nullable=False,
    )
    rank: Mapped[int] = mapped_column(Integer, nullable=False)
    structured_score: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    keyword_score: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    semantic_score: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    data_quality_score: Mapped[float | None] = mapped_column(
        Numeric(8, 5), nullable=True
    )
    availability_score: Mapped[float | None] = mapped_column(
        Numeric(8, 5), nullable=True
    )
    final_score: Mapped[float | None] = mapped_column(Numeric(8, 5), nullable=True)
    reason_codes: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    query: Mapped[SearchQuery] = relationship(back_populates="results")
