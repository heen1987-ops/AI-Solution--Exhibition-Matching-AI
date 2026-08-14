"""analytics 스키마 - PostgreSQL 기반 파생 데이터마트 (WAVE 2E / WORKER-ANALYTICS).

이 모듈은 `interaction.interaction_event`(app/models/matching.py의 InteractionEvent)
원시 이벤트 로그를 소스로 삼아 `apps/worker/app/jobs/analytics_aggregation.py`가
생성하는 일/퍼널/검색무응답/데이터품질 집계 결과를 담는 4개 테이블을 정의한다.
PROJECT_SCOPE.md의 명시적 제외 목록("Kafka 없음, 별도 데이터 웨어하우스 없음")에 따라
운영 PostgreSQL 안에서 원본 이벤트와 분리된 스키마(analytics)로 파생 집계를 저장하는
방식만 사용한다.

트랙 경계 (owned_paths) 관련 메모
--------------------------------
`.harness/locks.yaml`은 `apps/api/app/models/**`를 일반적으로 CONTRACTS 트랙 소유로
기록하지만, 이 파일을 작성하라는 WORKER-ANALYTICS(WAVE 2E) 작업 지시가 명시적으로
`apps/api/app/models/analytics.py`(신규)와 그에 대응하는 신규 Alembic 마이그레이션을
이 트랙의 owned_paths로 지정했다. 즉 "이 4개 테이블의 스키마/마이그레이션은
WORKER-ANALYTICS가 소유하고, 그 위의 읽기 API는 BACKEND-ANALYTICS가 소유한다"는 명시적
경계 조정이다. 다른 도메인 모델 파일은 건드리지 않았다.

테이블 이름 표기에 대하여
--------------------------
작업 지시는 테이블 이름을 "analytics_daily_metrics", "analytics_funnel_metrics",
"search_no_result_summaries", "data_quality_snapshots"(복수형, `analytics_` 접두어 포함)로
불렀다. 이 저장소의 기존 관례(스키마가 이미 네임스페이스를 제공하므로 테이블명은 단수·
접두어 없이 짓는다 - 예: `interaction.interaction_event`, `profile.buyer_profile`)를 따라
`analytics.daily_metric` / `analytics.funnel_metric` / `analytics.search_no_result_summary` /
`analytics.data_quality_snapshot`로 짓는다. BACKEND-ANALYTICS 읽기 API 트랙은 이 실제
이름을 참고해야 한다(최종 보고에도 명시).

멱등적 재집계(idempotent re-aggregation)
------------------------------------------
각 테이블은 (tenant_id, event_id, 날짜, 그리고 그 테이블의 분류 축) 조합에 UNIQUE 제약을
두어, 같은 기간을 다시 집계해도 새 행이 추가되지 않고 upsert(INSERT ... ON CONFLICT DO
UPDATE)로 값이 교체되도록 한다. 실제 upsert 실행부는
`apps/worker/app/jobs/analytics_aggregation.py`의 MetricSink 어댑터(스텁, 실제 Postgres
연동은 통합 담당 몫)가 이 UNIQUE 제약을 conflict target으로 사용한다.

소수 인원 억제(small-group suppression)
------------------------------------------
AGENTS.md 상위 규칙: "5명 미만 소수집단 통계는 정확한 숫자 대신 억제되거나 '5명 미만'으로
표시되어야 한다." 이 원칙을 표(rest) 단계에서부터 지킨다 - 즉 `suppressed=true`인 행은
`distinct_actor_count`뿐 아니라 그 행이 보고하는 수치 컬럼(`event_count`/`actor_count`/
`occurrence_count`)도 NULL로 저장한다(표시 시점에 숨기는 것이 아니라 저장 시점에 이미
정확한 소수 값이 존재하지 않도록 한다 - 읽기 API 버그로 인한 유출을 원천 차단).
`data_quality_snapshot`은 개인/소집단 통계가 아니라 파이프라인 자체의 운영 지표(수집
지연, 중복률 등 이벤트 전체 모집단 비율)이므로 이 억제 규칙 대상이 아니다(자세한 근거는
`analytics_aggregation.py`의 모듈 docstring 참고).
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKeyConstraint,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import SCHEMA_ANALYTICS, SCHEMA_EXHIBITION, Base
from app.models.common import new_uuid7

_EVENT_BOUNDARY_FK = ("tenant_id", "event_id")


def _event_boundary_fk(name: str) -> ForeignKeyConstraint:
    return ForeignKeyConstraint(
        list(_EVENT_BOUNDARY_FK),
        [
            f"{SCHEMA_EXHIBITION}.event.tenant_id",
            f"{SCHEMA_EXHIBITION}.event.event_id",
        ],
        name=name,
    )


class AnalyticsDailyMetric(Base):
    """analytics.daily_metric - 웹/키오스크/바이어 채널을 아우르는 일 단위 범용 지표.

    `metric_code`는 온톨로지 개념 코드가 아니라(6단계 ACTION.* 네임스페이스는 추천
    피드백 신호 10개뿐이라 이 지표 카탈로그를 감당하지 않는다) 애플리케이션 계층
    허용목록이다 - `interaction.interaction_event.event_type`과 동일한 설계 원칙
    (app/models/matching.py InteractionEvent 문서 참고: "허용 목록은 애플리케이션
    계층에서 관리한다"). 실제 후보값은 analytics_aggregation.py의
    DEFAULT_DAILY_METRIC_DEFINITIONS를 단일 진실 공급원으로 삼는다.
    """

    __tablename__ = "daily_metric"
    __table_args__ = (
        _event_boundary_fk("fk_daily_metric_event_boundary"),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "metric_date",
            "metric_code",
            "dimension_code",
            name="uq_daily_metric_natural_key",
        ),
        CheckConstraint(
            "(suppressed = false) OR (event_count IS NULL AND distinct_actor_count IS NULL)",
            name="ck_daily_metric_suppressed_hides_values",
        ),
        {"schema": SCHEMA_ANALYTICS},
    )

    daily_metric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    metric_code: Mapped[str] = mapped_column(String(60), nullable=False)
    # 채널/화면 등 부가 분류 축. 없으면 "ALL" (NULL을 쓰지 않는 이유: PostgreSQL UNIQUE
    # 제약은 NULL을 서로 다른 값으로 취급해 재집계 시 중복행을 만들 수 있다).
    dimension_code: Mapped[str] = mapped_column(String(40), nullable=False, default="ALL")
    event_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distinct_actor_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    # 재집계 실행을 추적하기 위한 디버그용 참조값(감사 목적, PII 아님).
    aggregation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class AnalyticsFunnelMetric(Base):
    """analytics.funnel_metric - 웹/키오스크/바이어 3개 퍼널의 단계별 도달·전환.

    `funnel_code` in ('WEB', 'KIOSK', 'BUYER'), `step_code`/`step_order`는
    analytics_aggregation.py의 WEB_FUNNEL_STEPS/KIOSK_FUNNEL_STEPS/BUYER_FUNNEL_STEPS를
    단일 진실 공급원으로 삼는다. `actor_count` 자체가 이미 "그 단계를 1회 이상 수행한
    서로 다른 사용자 수"이므로 별도 distinct_actor_count 컬럼을 두지 않는다.
    """

    __tablename__ = "funnel_metric"
    __table_args__ = (
        _event_boundary_fk("fk_funnel_metric_event_boundary"),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "metric_date",
            "funnel_code",
            "step_code",
            name="uq_funnel_metric_natural_key",
        ),
        CheckConstraint(
            "funnel_code IN ('WEB', 'KIOSK', 'BUYER')",
            name="ck_funnel_metric_funnel_code_allowed",
        ),
        CheckConstraint("step_order > 0", name="ck_funnel_metric_step_order_positive"),
        CheckConstraint(
            "(suppressed = false) OR (actor_count IS NULL AND conversion_from_previous IS NULL)",
            name="ck_funnel_metric_suppressed_hides_values",
        ),
        {"schema": SCHEMA_ANALYTICS},
    )

    funnel_metric_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    metric_date: Mapped[date] = mapped_column(Date, nullable=False)
    funnel_code: Mapped[str] = mapped_column(String(10), nullable=False)
    step_code: Mapped[str] = mapped_column(String(40), nullable=False)
    step_order: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    # 직전 단계 대비 전환율. 자신 또는 직전 단계가 억제된 경우 반드시 NULL이어야 한다
    # (그렇지 않으면 conversion * 직전단계count로 억제된 소수 값을 역산할 수 있다).
    conversion_from_previous: Mapped[float | None] = mapped_column(Numeric(9, 6), nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    aggregation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class AnalyticsSearchNoResultSummary(Base):
    """analytics.search_no_result_summary - 무응답(0건) 검색 질의 일 단위 집계.

    알려진 데이터 공백(최종 보고에도 기록): 현재 `interaction.interaction_event`에
    검색어 원문을 실을 수 있는 허용 컨텍스트 키가 없다(app/api/v1/routers/recommendations.py
    `_ALLOWED_CONTEXT_KEYS`에 query 관련 키 부재를 확인함). 따라서 `query_norm`은 스키마
    상으로는 준비해 두되(향후 검색 트랙이 허용 키를 추가하면 바로 채워짐), 현재 소스
    데이터로는 대부분 "UNKNOWN"으로 채워질 것으로 예상한다.
    """

    __tablename__ = "search_no_result_summary"
    __table_args__ = (
        _event_boundary_fk("fk_search_no_result_summary_event_boundary"),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "summary_date",
            "channel_code",
            "query_norm",
            name="uq_search_no_result_summary_natural_key",
        ),
        CheckConstraint(
            "(suppressed = false) OR "
            "(occurrence_count IS NULL AND distinct_actor_count IS NULL AND last_occurred_at IS NULL)",
            name="ck_search_no_result_summary_suppressed_hides_values",
        ),
        {"schema": SCHEMA_ANALYTICS},
    )

    search_no_result_summary_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    summary_date: Mapped[date] = mapped_column(Date, nullable=False)
    channel_code: Mapped[str] = mapped_column(String(20), nullable=False, default="UNKNOWN")
    query_norm: Mapped[str] = mapped_column(String(200), nullable=False, default="UNKNOWN")
    occurrence_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    distinct_actor_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    suppressed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    last_occurred_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    aggregation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )


class AnalyticsDataQualitySnapshot(Base):
    """analytics.data_quality_snapshot - 집계 파이프라인 자체의 운영 상태 스냅샷.

    개인/소수집단 통계가 아니라 그날 처리된 이벤트 전체 모집단에 대한 비율/지연 지표
    (수집 지연, 지각 도착률, client_event_id 중복률, 주체 미상 이벤트 비율, 억제된
    지표 비율)이므로 5명 미만 억제 규칙 대상이 아니다.
    """

    __tablename__ = "data_quality_snapshot"
    __table_args__ = (
        _event_boundary_fk("fk_data_quality_snapshot_event_boundary"),
        UniqueConstraint(
            "tenant_id",
            "event_id",
            "snapshot_date",
            "check_code",
            name="uq_data_quality_snapshot_natural_key",
        ),
        CheckConstraint(
            "status IN ('OK', 'WARN', 'FAIL')",
            name="ck_data_quality_snapshot_status_allowed",
        ),
        {"schema": SCHEMA_ANALYTICS},
    )

    data_quality_snapshot_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, default=new_uuid7
    )
    tenant_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    event_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    snapshot_date: Mapped[date] = mapped_column(Date, nullable=False)
    check_code: Mapped[str] = mapped_column(String(60), nullable=False)
    status: Mapped[str] = mapped_column(String(10), nullable=False)
    metric_value: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    threshold_value: Mapped[float | None] = mapped_column(Numeric(12, 6), nullable=True)
    affected_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    details_json: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    computed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    aggregation_run_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
