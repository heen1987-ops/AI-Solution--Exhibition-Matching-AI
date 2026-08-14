"""Postgres-backed `MetricSink` / `DataQualitySink` + `interaction_event` reader.

Implements `worker.jobs.analytics_aggregation.MetricSink` and
`worker.jobs.data_quality.DataQualitySink` against the real `analytics.*` tables
(`apps/api/app/models/analytics.py`), using `INSERT ... ON CONFLICT (<natural key>) DO
UPDATE` against each table's own `UniqueConstraint` - the idempotent-upsert boundary those
two job modules' own docstrings described as "integration work" when the tables had no
adapter yet. `read_raw_events` is the read-side counterpart: it maps
`interaction.interaction_event` rows (`apps/api/app/models/matching.py::InteractionEvent`)
into `worker.jobs.analytics_aggregation.RawEvent`, the shape the pure `aggregate_*`
functions consume - this reader does no bucketing/filtering itself, callers pass a date
window wide enough to cover late-arriving events (see that module's "Late-arriving events"
docstring section) and the pure functions do the rest.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import date

from app.models.analytics import (
    AnalyticsDailyMetric,
    AnalyticsDataQualitySnapshot,
    AnalyticsFunnelMetric,
    AnalyticsSearchNoResultSummary,
)
from app.models.matching import InteractionEvent
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from worker.jobs.analytics_aggregation import (
    DailyMetricRow,
    FunnelMetricRow,
    RawEvent,
    SearchNoResultRow,
)
from worker.jobs.data_quality import DataQualitySnapshotRow


async def read_raw_events(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> list[RawEvent]:
    """Load one event's `interaction_event` rows for `[start_date, end_date]` (inclusive,
    filtered on the partition key `event_date`) and map them to `RawEvent`."""

    rows = (
        await db.scalars(
            select(InteractionEvent).where(
                InteractionEvent.tenant_id == tenant_id,
                InteractionEvent.event_id == event_id,
                InteractionEvent.event_date >= start_date,
                InteractionEvent.event_date <= end_date,
            )
        )
    ).all()
    return [
        RawEvent(
            interaction_event_id=str(row.interaction_event_id),
            tenant_id=str(row.tenant_id),
            event_id=str(row.event_id),
            event_type=row.event_type,
            occurred_at=row.occurred_at,
            received_at=row.received_at,
            user_id=str(row.user_id) if row.user_id else None,
            guest_session_id=str(row.guest_session_id) if row.guest_session_id else None,
            visit_session_id=str(row.visit_session_id) if row.visit_session_id else None,
            client_event_id=str(row.client_event_id) if row.client_event_id else None,
            context=row.context_json,
        )
        for row in rows
    ]


class AnalyticsSink:
    """Implements both `MetricSink` and `DataQualitySink` against `analytics.*` tables.

    One statement per row rather than a single multi-row upsert: the four `analytics.*`
    tables together publish at most a few dozen rows per (tenant, event, day) aggregation
    run (10 daily metrics + ~17 funnel steps + a handful of search/quality rows), so the
    simplicity of "one execute per row, same conflict target as the table's own
    UniqueConstraint" outweighs any batching complexity at this scale.
    """

    def __init__(self, db: AsyncSession) -> None:
        self._db = db

    async def upsert_daily_metrics(self, rows: Sequence[DailyMetricRow]) -> None:
        for row in rows:
            stmt = pg_insert(AnalyticsDailyMetric).values(
                tenant_id=row.tenant_id,
                event_id=row.event_id,
                metric_date=row.metric_date,
                metric_code=row.metric_code,
                dimension_code=row.dimension_code,
                event_count=row.event_count,
                distinct_actor_count=row.distinct_actor_count,
                suppressed=row.suppressed,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "tenant_id",
                    "event_id",
                    "metric_date",
                    "metric_code",
                    "dimension_code",
                ],
                set_={
                    "event_count": stmt.excluded.event_count,
                    "distinct_actor_count": stmt.excluded.distinct_actor_count,
                    "suppressed": stmt.excluded.suppressed,
                },
            )
            await self._db.execute(stmt)

    async def upsert_funnel_metrics(self, rows: Sequence[FunnelMetricRow]) -> None:
        for row in rows:
            stmt = pg_insert(AnalyticsFunnelMetric).values(
                tenant_id=row.tenant_id,
                event_id=row.event_id,
                metric_date=row.metric_date,
                funnel_code=row.funnel_code,
                step_code=row.step_code,
                step_order=row.step_order,
                actor_count=row.actor_count,
                suppressed=row.suppressed,
                conversion_from_previous=row.conversion_from_previous,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "tenant_id",
                    "event_id",
                    "metric_date",
                    "funnel_code",
                    "step_code",
                ],
                set_={
                    "step_order": stmt.excluded.step_order,
                    "actor_count": stmt.excluded.actor_count,
                    "suppressed": stmt.excluded.suppressed,
                    "conversion_from_previous": stmt.excluded.conversion_from_previous,
                },
            )
            await self._db.execute(stmt)

    async def upsert_search_no_result_summary(self, rows: Sequence[SearchNoResultRow]) -> None:
        for row in rows:
            stmt = pg_insert(AnalyticsSearchNoResultSummary).values(
                tenant_id=row.tenant_id,
                event_id=row.event_id,
                summary_date=row.summary_date,
                channel_code=row.channel_code,
                query_norm=row.query_norm,
                occurrence_count=row.occurrence_count,
                distinct_actor_count=row.distinct_actor_count,
                suppressed=row.suppressed,
                last_occurred_at=row.last_occurred_at,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=[
                    "tenant_id",
                    "event_id",
                    "summary_date",
                    "channel_code",
                    "query_norm",
                ],
                set_={
                    "occurrence_count": stmt.excluded.occurrence_count,
                    "distinct_actor_count": stmt.excluded.distinct_actor_count,
                    "suppressed": stmt.excluded.suppressed,
                    "last_occurred_at": stmt.excluded.last_occurred_at,
                },
            )
            await self._db.execute(stmt)

    async def upsert_data_quality_snapshots(
        self, rows: Sequence[DataQualitySnapshotRow]
    ) -> None:
        for row in rows:
            stmt = pg_insert(AnalyticsDataQualitySnapshot).values(
                tenant_id=row.tenant_id,
                event_id=row.event_id,
                snapshot_date=row.snapshot_date,
                check_code=row.check_code,
                status=row.status,
                metric_value=row.metric_value,
                threshold_value=row.threshold_value,
                affected_count=row.affected_count,
                details_json=dict(row.details_json) if row.details_json else None,
            )
            stmt = stmt.on_conflict_do_update(
                index_elements=["tenant_id", "event_id", "snapshot_date", "check_code"],
                set_={
                    "status": stmt.excluded.status,
                    "metric_value": stmt.excluded.metric_value,
                    "threshold_value": stmt.excluded.threshold_value,
                    "affected_count": stmt.excluded.affected_count,
                    "details_json": stmt.excluded.details_json,
                },
            )
            await self._db.execute(stmt)
