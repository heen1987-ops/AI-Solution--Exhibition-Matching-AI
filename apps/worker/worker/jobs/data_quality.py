"""data_quality job.

Computes operational data-quality snapshots over the same raw
`interaction.interaction_event` feed that `analytics_aggregation.py` consumes, and
publishes them into `analytics.data_quality_snapshot`
(`apps/api/app/models/analytics.py::AnalyticsDataQualitySnapshot`).

Relationship to small-group suppression
----------------------------------------
These checks are pipeline-health ratios over the *entire* event population of a day
(ingestion latency, late-arrival rate, duplicate rate, subject-unknown rate, suppressed-
metric ratio) - not statistics about any person or small group - so the "<5 distinct
users" suppression rule deliberately does not apply here (see
`AnalyticsDataQualitySnapshot`'s docstring for the same rationale on the schema side).
No check below ever writes an identifier, query text, or any other per-user value into
`details_json`; only counts, rates, and seconds.

Idempotency
------------
Same contract as analytics_aggregation.py: every check is a pure full recompute over the
supplied event set, keyed by the natural key (tenant_id, event_id, snapshot_date,
check_code) that `uq_data_quality_snapshot_natural_key` enforces. Re-running the job for
the same day upserts the same rows; a later run over a fuller (late-arrival-inclusive)
event set simply recomputes the correct values.

Persistence boundary is async - see analytics_aggregation.py's module docstring "Persistence
boundary is async" for why (no synchronous SQLAlchemy engine exists anywhere in this repo).
"""

from __future__ import annotations

import math
import uuid
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Protocol, runtime_checkable

from worker.jobs.analytics_aggregation import (
    KST_OFFSET,
    AggregationResult,
    JobRegistry,
    RawEvent,
    actor_key,
    local_date,
)

DATA_QUALITY_VERSION = "data-quality/1.0.0"

STATUS_OK = "OK"
STATUS_WARN = "WARN"
STATUS_FAIL = "FAIL"

CHECK_INGESTION_LATENCY_P95 = "INGESTION_LATENCY_P95_SECONDS"
CHECK_LATE_ARRIVAL_RATE = "LATE_ARRIVAL_RATE"
CHECK_DUPLICATE_CLIENT_EVENT_RATE = "DUPLICATE_CLIENT_EVENT_RATE"
CHECK_SUBJECT_UNKNOWN_RATE = "SUBJECT_UNKNOWN_RATE"
CHECK_SUPPRESSED_METRIC_RATIO = "SUPPRESSED_METRIC_RATIO"


@dataclass(frozen=True)
class CheckThresholds:
    """`value <= warn_at` -> OK, `value <= fail_at` -> WARN, else FAIL.

    All checks in this module are "lower is better" metrics (seconds of latency or a
    0..1 rate), so a single monotonic threshold pair suffices.
    """

    warn_at: float
    fail_at: float

    def __post_init__(self) -> None:
        if self.fail_at < self.warn_at:
            raise ValueError("fail_at must be >= warn_at")

    def status_for(self, value: float) -> str:
        if value <= self.warn_at:
            return STATUS_OK
        if value <= self.fail_at:
            return STATUS_WARN
        return STATUS_FAIL


#: Conservative MVP defaults; the integrator can override per deployment via
#: `run_data_quality_job(..., thresholds={...})` without touching this module.
DEFAULT_THRESHOLDS: dict[str, CheckThresholds] = {
    CHECK_INGESTION_LATENCY_P95: CheckThresholds(warn_at=60.0, fail_at=600.0),
    CHECK_LATE_ARRIVAL_RATE: CheckThresholds(warn_at=0.05, fail_at=0.20),
    CHECK_DUPLICATE_CLIENT_EVENT_RATE: CheckThresholds(warn_at=0.01, fail_at=0.05),
    CHECK_SUBJECT_UNKNOWN_RATE: CheckThresholds(warn_at=0.10, fail_at=0.50),
    CHECK_SUPPRESSED_METRIC_RATIO: CheckThresholds(warn_at=0.50, fail_at=0.90),
}


@dataclass(frozen=True)
class DataQualitySnapshotRow:
    tenant_id: str
    event_id: str
    snapshot_date: date
    check_code: str
    status: str
    metric_value: float | None
    threshold_value: float | None
    affected_count: int | None
    details_json: Mapping[str, object] | None


def _percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile on an already-sorted, non-empty sequence."""

    if not sorted_values:
        raise ValueError("percentile of empty sequence")
    rank = max(1, math.ceil(pct / 100.0 * len(sorted_values)))
    return sorted_values[rank - 1]


def _bucketed_for_day(
    events: Sequence[RawEvent],
    *,
    tenant_id: str,
    event_id: str,
    snapshot_date: date,
    utc_offset: timedelta,
) -> list[RawEvent]:
    return [
        e
        for e in events
        if e.tenant_id == tenant_id
        and e.event_id == event_id
        and local_date(e.occurred_at, utc_offset=utc_offset) == snapshot_date
    ]


def compute_data_quality_snapshots(
    events: Sequence[RawEvent],
    *,
    tenant_id: str,
    event_id: str,
    snapshot_date: date,
    utc_offset: timedelta = KST_OFFSET,
    aggregation_result: AggregationResult | None = None,
    thresholds: Mapping[str, CheckThresholds] | None = None,
) -> list[DataQualitySnapshotRow]:
    """Pure full recompute of all checks for one (tenant, event, local calendar day).

    `aggregation_result` (optional) enables the SUPPRESSED_METRIC_RATIO check, which is a
    property of the published metric rows rather than of the raw events; when omitted,
    that check is simply skipped rather than guessed at (unknown stays unknown).
    """

    limits = dict(DEFAULT_THRESHOLDS)
    if thresholds:
        limits.update(thresholds)

    day_events = _bucketed_for_day(
        events,
        tenant_id=tenant_id,
        event_id=event_id,
        snapshot_date=snapshot_date,
        utc_offset=utc_offset,
    )
    total = len(day_events)
    rows: list[DataQualitySnapshotRow] = []

    def _add(
        check_code: str,
        value: float,
        *,
        affected_count: int | None,
        details: Mapping[str, object] | None = None,
    ) -> None:
        limit = limits[check_code]
        rows.append(
            DataQualitySnapshotRow(
                tenant_id=tenant_id,
                event_id=event_id,
                snapshot_date=snapshot_date,
                check_code=check_code,
                status=limit.status_for(value),
                metric_value=round(value, 6),
                threshold_value=limit.warn_at,
                affected_count=affected_count,
                details_json=details,
            )
        )

    # 1) Ingestion latency p95 (seconds between the client-side occurrence and server
    #    receipt). Negative deltas (client clock skew) are floored at 0 for the latency
    #    metric itself but surfaced in details for observability.
    if total:
        deltas = [
            (e.received_at - e.occurred_at).total_seconds() for e in day_events
        ]
        negative_clock_skew = sum(1 for d in deltas if d < 0)
        latencies = sorted(max(0.0, d) for d in deltas)
        _add(
            CHECK_INGESTION_LATENCY_P95,
            _percentile(latencies, 95.0),
            affected_count=total,
            details={"negative_clock_skew_events": negative_clock_skew},
        )

    # 2) Late-arrival rate: events whose server receipt fell on a *later* local calendar
    #    day than their occurrence day. These are exactly the events a same-night
    #    aggregation run would have missed - the scheduled re-aggregation (full recompute,
    #    see analytics_aggregation.py) is what makes them safe, and this check is what
    #    makes their volume visible.
    if total:
        late = sum(
            1
            for e in day_events
            if local_date(e.received_at, utc_offset=utc_offset)
            > local_date(e.occurred_at, utc_offset=utc_offset)
        )
        _add(CHECK_LATE_ARRIVAL_RATE, late / total, affected_count=late)

    # 3) Duplicate client_event_id rate among events that carry one (client retries /
    #    offline replays that slipped past API-level idempotency).
    if total:
        with_client_id = [e for e in day_events if e.client_event_id]
        duplicate_extras = 0
        if with_client_id:
            counts = Counter(e.client_event_id for e in with_client_id)
            duplicate_extras = sum(c - 1 for c in counts.values() if c > 1)
        rate = duplicate_extras / len(with_client_id) if with_client_id else 0.0
        _add(
            CHECK_DUPLICATE_CLIENT_EVENT_RATE,
            rate,
            affected_count=duplicate_extras,
            details={"events_with_client_event_id": len(with_client_id)},
        )

    # 4) Subject-unknown rate: events with no user/guest/visit subject at all cannot
    #    participate in distinct-actor counting, silently deflating funnel steps.
    if total:
        unknown = sum(1 for e in day_events if actor_key(e) is None)
        _add(CHECK_SUBJECT_UNKNOWN_RATE, unknown / total, affected_count=unknown)

    # 5) Suppressed-metric ratio over the published daily+funnel rows (a high ratio means
    #    the day's traffic was so thin that most published metrics are hidden by the
    #    small-group rule - a signal to widen the reporting window, never to lower the
    #    suppression threshold).
    if aggregation_result is not None:
        metric_rows = list(aggregation_result.daily_metrics) + list(
            aggregation_result.funnel_metrics
        )
        if metric_rows:
            suppressed = sum(1 for r in metric_rows if r.suppressed)
            _add(
                CHECK_SUPPRESSED_METRIC_RATIO,
                suppressed / len(metric_rows),
                affected_count=suppressed,
                details={"metric_rows_total": len(metric_rows)},
            )

    rows.sort(key=lambda r: r.check_code)
    return rows


# ---------------------------------------------------------------------------
# Idempotent persistence boundary + job registration (same pattern as
# analytics_aggregation.MetricSink / document_parsing.SegmentStore)
# ---------------------------------------------------------------------------


@runtime_checkable
class DataQualitySink(Protocol):
    async def upsert_data_quality_snapshots(
        self, rows: Sequence[DataQualitySnapshotRow]
    ) -> None: ...


@dataclass
class InMemoryDataQualitySink:
    snapshots: dict[tuple, DataQualitySnapshotRow] = field(default_factory=dict)

    async def upsert_data_quality_snapshots(
        self, rows: Sequence[DataQualitySnapshotRow]
    ) -> None:
        for row in rows:
            key = (row.tenant_id, row.event_id, row.snapshot_date, row.check_code)
            self.snapshots[key] = row


@dataclass(frozen=True)
class DataQualityResult:
    run_id: str
    snapshots: tuple[DataQualitySnapshotRow, ...]


async def run_data_quality_job(
    events: Sequence[RawEvent],
    sink: DataQualitySink,
    *,
    tenant_id: str,
    event_id: str,
    snapshot_date: date,
    utc_offset: timedelta = KST_OFFSET,
    aggregation_result: AggregationResult | None = None,
    thresholds: Mapping[str, CheckThresholds] | None = None,
    run_id: str | None = None,
) -> DataQualityResult:
    rows = compute_data_quality_snapshots(
        events,
        tenant_id=tenant_id,
        event_id=event_id,
        snapshot_date=snapshot_date,
        utc_offset=utc_offset,
        aggregation_result=aggregation_result,
        thresholds=thresholds,
    )
    await sink.upsert_data_quality_snapshots(rows)
    return DataQualityResult(run_id=run_id or str(uuid.uuid4()), snapshots=tuple(rows))


async def handle_data_quality_job(
    payload: Mapping[str, object], *, sink: DataQualitySink
) -> DataQualityResult:
    events = payload["events"]
    if not isinstance(events, (list, tuple)) or not all(
        isinstance(e, RawEvent) for e in events
    ):
        raise TypeError("payload['events'] must be a sequence of RawEvent")
    snapshot_date = payload["snapshot_date"]
    if not isinstance(snapshot_date, date):
        raise TypeError("payload['snapshot_date'] must be a date")
    tenant_id = payload["tenant_id"]
    event_id = payload["event_id"]
    if not isinstance(tenant_id, str) or not isinstance(event_id, str):
        raise TypeError("payload['tenant_id'] and payload['event_id'] must be str")
    utc_offset = payload.get("utc_offset", KST_OFFSET)
    if not isinstance(utc_offset, timedelta):
        utc_offset = KST_OFFSET
    aggregation_result = payload.get("aggregation_result")
    if aggregation_result is not None and not isinstance(
        aggregation_result, AggregationResult
    ):
        raise TypeError(
            "payload['aggregation_result'] must be an AggregationResult when provided"
        )
    return await run_data_quality_job(
        events,
        sink,
        tenant_id=tenant_id,
        event_id=event_id,
        snapshot_date=snapshot_date,
        utc_offset=utc_offset,
        aggregation_result=aggregation_result,
    )


def register_data_quality_job(registry: JobRegistry) -> None:
    """Registration hook for the integrator (never wires itself into shared modules)."""

    registry.register("data_quality", handle_data_quality_job)
