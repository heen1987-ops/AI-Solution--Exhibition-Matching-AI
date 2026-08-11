"""analytics_aggregation job.

Turns raw `interaction.interaction_event` rows (see
`apps/api/app/models/matching.py::InteractionEvent`) into the daily/funnel/search-no-result
data marts published in `apps/api/app/models/analytics.py` (schema `analytics`), using plain
PostgreSQL rather than Kafka or a separate data warehouse (PROJECT_SCOPE.md explicit
exclusion list).

Design: full recompute, not incremental
----------------------------------------
Every `aggregate_*` function in this module is pure and takes the *complete* set of raw events
for the target tenant/event/period on every call, then recomputes the period's metrics from
scratch. This is a deliberate simplicity choice over delta/incremental aggregation:

- **Idempotent re-aggregation** falls out for free: pure functions with no side effects,
  combined with `MetricSink.upsert_*` writing by natural key (see
  `app/models/analytics.py`'s UNIQUE constraints), mean re-running the job for the same period
  overwrites the same rows with the same values rather than accumulating duplicates.
- **Late-arriving events** are handled the same way: as long as the caller supplies the fuller,
  more complete event set on a later run (the normal case - a scheduled re-aggregation of
  "yesterday" a few hours after midnight to catch anything that arrived late), the recomputed
  totals are simply correct, not incrementally patched. There is no separate "late event
  delta" code path to get wrong.

Both properties are exercised directly in `apps/worker/tests/test_analytics_aggregation.py`.

Known gaps (documented per this track's own instructions - "check for one, else note as a
gap" - rather than silently assumed)
---------------------------------------------------------------------------------------------
1. **No dedicated test/staff-event flag.** `InteractionEvent` (app/models/matching.py) has no
   column for this; the only free-form field is `context_json`, and the *current* interaction-
   event API contract (`app/api/v1/routers/recommendations.py::_ALLOWED_CONTEXT_KEYS` - BACKEND-
   owned, confirmed by reading it, not guessed) does not include any test/staff key at all -
   an event's `context` is stripped down to `{source, component, variant, reason_code,
   network_state, offline_replay}` before it is ever persisted. This module still checks for a
   conventional set of flag keys (`_TEST_FLAG_KEYS` below) in whatever `context` mapping it is
   given, so it is forward-compatible the day that allow-list grows a flag - but as of this
   track's own review, **no interaction event currently written by this codebase can carry
   such a flag**, so `exclude_test_and_staff_events` is a no-op against real data today. This
   is a genuine shared-schema gap, not something this track can fix (the allow-list lives in
   BACKEND-owned `app/api/v1/routers/recommendations.py`, outside this track's OWNED PATHS).
2. **Most funnel/daily-metric step names have no confirmed canonical `event_type` string yet.**
   The 259-concept ontology's `ACTION.*` namespace (src/meet_ai/ontology/catalog.v1.json) only
   covers 9 recommendation-feedback signals (impression/click/favorite/dismiss/route-add/
   check-in/feedback/meeting-request/meeting-complete - see `event_mappings` in that file) and
   maps to `RECOMMENDATION_IMPRESSION`, `RECOMMENDATION_OPENED`, `RECOMMENDATION_SAVED`, etc.
   Those are used below. Everything else this track's funnel spec asks for - profile-confirm,
   the whole kiosk funnel (session-start/query-submit/results/map/QR-send), and most of the
   buyer funnel (verify/match-generate/compare/meeting-accept) - has **no event_type emitted
   anywhere in this repository as of this track's review** (grepped
   `apps/api/app/api/v1/routers/search.py` and `kiosk.py`: neither logs any interaction_event
   at all yet). Blocker-Score assessment: this is real ambiguity, but low-risk and fully
   reversible (an alias list that doesn't match reality just yields a legitimate zero count,
   never a fabricated one), so per this track's own escalation rule the safest default is
   applied and documented here rather than blocking: each step is defined as a tuple of
   *plausible* event_type aliases (`WEB_FUNNEL_STEPS` / `KIOSK_FUNNEL_STEPS` /
   `BUYER_FUNNEL_STEPS` below), matching the alias-tuple pattern already used elsewhere in this
   codebase (`app/services/matching/cold_start_runtime.py::_DETAIL_EVENTS` etc.). When
   USER_WEB/KIOSK/AI_SEARCH/BACKEND-BUYER-MATCH wire up real event emission, only these tuples
   need updating - the aggregation/suppression/idempotency machinery does not change.
3. **Search query text cannot be recovered from interaction_event today**, for the same
   `_ALLOWED_CONTEXT_KEYS` reason as gap 1 (no `query_text`/`query_norm` key is allowed
   through). `analytics.search_no_result_summary.query_norm` is schema-ready for it but will
   read back "UNKNOWN" against current data until that allow-list grows a query key.

Timezone bucketing ("행사 시간대" day boundary)
-------------------------------------------------
`occurred_at`/`received_at` are always stored UTC (`InteractionEvent.occurred_at` is
`DateTime(timezone=True)`, always populated tz-aware). The task requires bucketing daily
metrics by the *event's local* day boundary, not raw UTC. This module represents an event's
timezone as a **fixed UTC offset** (`utc_offset: timedelta`) rather than an IANA zone name
(`zoneinfo.ZoneInfo("Asia/Seoul")`): the shared venv this repository runs in has no `tzdata`
package installed and Windows has no system IANA tz database, so `zoneinfo` lookups fail here
(`ZoneInfoNotFoundError`) without adding a new dependency. A fixed offset is also *exactly*
correct for this project's actual venue (Korea does not observe DST), so nothing is lost in
practice; `KST_OFFSET = timedelta(hours=9)` is the default. If a future multi-region event
needs real DST-aware IANA rules, add `tzdata` as a dependency and swap `local_date`'s
implementation without changing any caller's signature.

Persistence boundary is async (unified-repo port note)
--------------------------------------------------------
`MetricSink` and `InMemoryMetricSink` are `async` here, unlike the standalone-worktree
original - this repo has no *synchronous* SQLAlchemy engine anywhere (`app/db/session.py`
only exposes an async engine/sessionmaker), so a sync Protocol would have no real
implementation to satisfy it. `worker/sinks/analytics_sink.py` is the Postgres-backed
implementation (`INSERT ... ON CONFLICT DO UPDATE` against this table's own UNIQUE
constraints), consuming `worker.sinks.analytics_sink.read_raw_events` to map
`interaction.interaction_event` rows into this module's `RawEvent` shape.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Protocol, runtime_checkable

AGGREGATION_VERSION = "analytics-aggregation/1.0.0"

#: Korea does not observe daylight saving time, so a fixed offset is exact (see module
#: docstring "Timezone bucketing" for why this is not `zoneinfo.ZoneInfo("Asia/Seoul")`).
KST_OFFSET = timedelta(hours=9)

#: AGENTS.md top-level rule: "Small-group / minority-group statistics: any aggregate with
#: fewer than 5 underlying users must be suppressed or shown as 'fewer than 5'."
SUPPRESSION_THRESHOLD = 5


# ---------------------------------------------------------------------------
# Raw input shape
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RawEvent:
    """Mirrors the subset of `interaction.interaction_event` columns this job needs.

    `worker/sinks/analytics_sink.py::read_raw_events` maps `InteractionEvent` ORM rows to
    this shape before calling into this module, keeping this module decoupled from any
    concrete persistence - the same pattern `document_parsing.py`'s `SegmentStore` Protocol
    uses.
    """

    interaction_event_id: str
    tenant_id: str
    event_id: str
    event_type: str
    occurred_at: datetime
    received_at: datetime
    user_id: str | None = None
    guest_session_id: str | None = None
    visit_session_id: str | None = None
    client_event_id: str | None = None
    context: Mapping[str, object] | None = None

    def __post_init__(self) -> None:
        if self.occurred_at.tzinfo is None or self.occurred_at.utcoffset() is None:
            raise ValueError("occurred_at must be timezone-aware")
        if self.received_at.tzinfo is None or self.received_at.utcoffset() is None:
            raise ValueError("received_at must be timezone-aware")


def actor_key(event: RawEvent) -> str | None:
    """A single de-duplicated identity for distinct-actor counting.

    `InteractionEvent`'s own CHECK constraint (`subject_at_most_one`) already guarantees
    `user_id`/`guest_session_id` are not both set; `visit_session_id` is a third, coarser
    subject axis used when neither identity is available. Prefixing keeps the three id spaces
    from colliding if a UUID were ever (extremely unlikely) reused across them.
    """

    if event.user_id:
        return f"user:{event.user_id}"
    if event.guest_session_id:
        return f"guest:{event.guest_session_id}"
    if event.visit_session_id:
        return f"visit:{event.visit_session_id}"
    return None


_TEST_FLAG_KEYS: tuple[str, ...] = ("is_test", "test_event", "staff", "is_staff")


def is_test_or_staff_event(event: RawEvent) -> bool:
    """Best-effort test/staff exclusion - see module docstring gap (1)."""

    if not event.context:
        return False
    return any(bool(event.context.get(key)) for key in _TEST_FLAG_KEYS)


def local_date(occurred_at: datetime, *, utc_offset: timedelta = KST_OFFSET) -> date:
    """Bucket a UTC instant into a local calendar date via a fixed offset (see module docstring)."""

    return (occurred_at.astimezone(UTC) + utc_offset).date()


def _suppress(distinct_actor_count: int) -> bool:
    """0 is never suppressed (nobody to identify); 1..4 is (see class docstring rationale)."""

    return 0 < distinct_actor_count < SUPPRESSION_THRESHOLD


def _bucketed(
    events: Sequence[RawEvent],
    *,
    tenant_id: str,
    event_id: str,
    metric_date: date,
    utc_offset: timedelta,
    exclude_test_and_staff: bool = True,
) -> list[RawEvent]:
    result = []
    for event in events:
        if event.tenant_id != tenant_id or event.event_id != event_id:
            continue
        if exclude_test_and_staff and is_test_or_staff_event(event):
            continue
        if local_date(event.occurred_at, utc_offset=utc_offset) != metric_date:
            continue
        result.append(event)
    return result


# ---------------------------------------------------------------------------
# Daily metrics
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DailyMetricRow:
    tenant_id: str
    event_id: str
    metric_date: date
    metric_code: str
    dimension_code: str
    event_count: int | None
    distinct_actor_count: int | None
    suppressed: bool


#: metric_code -> event_type aliases. "__ALL__" is a sentinel meaning "every bucketed event
#: regardless of type" (used for the total-interaction-volume metric). See module docstring
#: gap (2) for which of these have a confirmed canonical event_type vs. a forward-looking
#: best-effort alias.
DEFAULT_DAILY_METRIC_DEFINITIONS: dict[str, tuple[str, ...]] = {
    "TOTAL_INTERACTIONS": ("__ALL__",),
    "RECOMMENDATION_IMPRESSION": ("RECOMMENDATION_IMPRESSION",),
    "RECOMMENDATION_CLICK": ("RECOMMENDATION_OPENED", "RECOMMENDATION_CLICKED"),
    "FAVORITE_SAVE": ("RECOMMENDATION_SAVED", "FAVORITE_ADD"),
    "CHECK_IN": ("BOOTH_CHECKED_IN", "CHECK_IN", "FIELD.CHECK_IN"),
    "FEEDBACK_SUBMIT": ("FEEDBACK_SUBMITTED", "FEEDBACK_SUBMIT"),
    "MEETING_REQUEST": ("MEETING_REQUEST_SUBMITTED", "MEETING_REQUESTED"),
    "MEETING_ACCEPT": ("MEETING_ACCEPTED",),
    "MEETING_COMPLETE": ("MEETING_COMPLETED",),
    "ROUTE_ADD": ("ROUTE_ITEM_ADDED",),
    "QR_SEND": ("QR_HANDOFF_SENT", "QR_SEND", "QR_SCAN"),
}


def aggregate_daily_metrics(
    events: Sequence[RawEvent],
    *,
    tenant_id: str,
    event_id: str,
    metric_date: date,
    utc_offset: timedelta = KST_OFFSET,
    metric_definitions: Mapping[str, tuple[str, ...]] | None = None,
) -> list[DailyMetricRow]:
    definitions = dict(metric_definitions) if metric_definitions else DEFAULT_DAILY_METRIC_DEFINITIONS
    bucketed = _bucketed(
        events, tenant_id=tenant_id, event_id=event_id, metric_date=metric_date, utc_offset=utc_offset
    )

    rows: list[DailyMetricRow] = []
    for metric_code, aliases in definitions.items():
        matched = bucketed if aliases == ("__ALL__",) else [e for e in bucketed if e.event_type in aliases]
        distinct_actor_count = len({actor_key(e) for e in matched if actor_key(e) is not None})
        suppressed = _suppress(distinct_actor_count)
        rows.append(
            DailyMetricRow(
                tenant_id=tenant_id,
                event_id=event_id,
                metric_date=metric_date,
                metric_code=metric_code,
                dimension_code="ALL",
                event_count=None if suppressed else len(matched),
                distinct_actor_count=None if suppressed else distinct_actor_count,
                suppressed=suppressed,
            )
        )
    rows.sort(key=lambda r: (r.metric_code, r.dimension_code))
    return rows


# ---------------------------------------------------------------------------
# Funnels
# ---------------------------------------------------------------------------

#: (step_code, event_type aliases)
FunnelStep = tuple[str, tuple[str, ...]]

#: Web funnel: profile-confirm -> recommendation-impression -> recommendation-click ->
#: exhibitor-detail -> favorite-save.
WEB_FUNNEL_STEPS: tuple[FunnelStep, ...] = (
    ("PROFILE_CONFIRM", ("PROFILE_CONFIRMED", "PROFILE_CONFIRM")),
    ("RECOMMENDATION_IMPRESSION", ("RECOMMENDATION_IMPRESSION",)),
    ("RECOMMENDATION_CLICK", ("RECOMMENDATION_OPENED", "RECOMMENDATION_CLICKED")),
    ("EXHIBITOR_DETAIL", ("VIEW_DETAIL", "VIEW.DETAIL", "EXHIBITOR_DETAIL_VIEWED")),
    ("FAVORITE_SAVE", ("RECOMMENDATION_SAVED", "FAVORITE_ADD")),
)

#: Kiosk funnel: session-start -> query-submit -> results -> exhibitor-detail -> map ->
#: QR-send.
KIOSK_FUNNEL_STEPS: tuple[FunnelStep, ...] = (
    ("SESSION_START", ("KIOSK_SESSION_STARTED", "SESSION_START")),
    ("QUERY_SUBMIT", ("KIOSK_QUERY_SUBMITTED", "QUERY_SUBMIT")),
    ("RESULTS_VIEWED", ("KIOSK_RESULTS_VIEWED", "SEARCH_RESULTS_VIEWED")),
    ("EXHIBITOR_DETAIL", ("VIEW_DETAIL", "VIEW.DETAIL", "KIOSK_EXHIBITOR_DETAIL_VIEWED")),
    ("MAP_VIEW", ("MAP_VIEWED", "ROUTE_ITEM_ADDED")),
    ("QR_SEND", ("QR_HANDOFF_SENT", "QR_SEND", "QR_SCAN")),
)

#: Buyer funnel: verify -> match-generate -> compare -> meeting-request -> meeting-accept ->
#: meeting-complete. Deliberately does NOT include any deal-value/contract metric per this
#: track's explicit instruction and PROJECT_SCOPE.md's exclusion of quotes/contracts/
#: settlement.
BUYER_FUNNEL_STEPS: tuple[FunnelStep, ...] = (
    ("VERIFY", ("BUYER_VERIFIED", "VERIFY")),
    ("MATCH_GENERATE", ("MATCH_GENERATED", "RECOMMENDATION_GENERATED")),
    ("COMPARE", ("MATCH_COMPARED", "COMPARE_VIEWED")),
    ("MEETING_REQUEST", ("MEETING_REQUEST_SUBMITTED", "MEETING_REQUESTED")),
    ("MEETING_ACCEPT", ("MEETING_ACCEPTED",)),
    ("MEETING_COMPLETE", ("MEETING_COMPLETED",)),
)

FUNNEL_DEFINITIONS: dict[str, tuple[FunnelStep, ...]] = {
    "WEB": WEB_FUNNEL_STEPS,
    "KIOSK": KIOSK_FUNNEL_STEPS,
    "BUYER": BUYER_FUNNEL_STEPS,
}


@dataclass(frozen=True)
class FunnelMetricRow:
    tenant_id: str
    event_id: str
    metric_date: date
    funnel_code: str
    step_code: str
    step_order: int
    actor_count: int | None
    suppressed: bool
    conversion_from_previous: float | None


def aggregate_funnel_metrics(
    events: Sequence[RawEvent],
    *,
    tenant_id: str,
    event_id: str,
    metric_date: date,
    funnel_code: str,
    utc_offset: timedelta = KST_OFFSET,
    steps: tuple[FunnelStep, ...] | None = None,
) -> list[FunnelMetricRow]:
    step_defs = steps if steps is not None else FUNNEL_DEFINITIONS[funnel_code]
    bucketed = _bucketed(
        events, tenant_id=tenant_id, event_id=event_id, metric_date=metric_date, utc_offset=utc_offset
    )

    rows: list[FunnelMetricRow] = []
    previous_actor_count: int | None = None
    previous_suppressed = False
    for order, (step_code, aliases) in enumerate(step_defs, start=1):
        alias_set = set(aliases)
        distinct_actor_count = len(
            {actor_key(e) for e in bucketed if e.event_type in alias_set and actor_key(e) is not None}
        )
        suppressed = _suppress(distinct_actor_count)

        conversion: float | None = None
        if (
            order > 1
            and not suppressed
            and not previous_suppressed
            and previous_actor_count is not None
            and previous_actor_count > 0
        ):
            # Never derivable back into a suppressed count: both this step and the previous
            # step must be un-suppressed for a conversion ratio to be safe to publish (see
            # app/models/analytics.py's ck_funnel_metric_suppressed_hides_values comment).
            conversion = round(distinct_actor_count / previous_actor_count, 6)

        rows.append(
            FunnelMetricRow(
                tenant_id=tenant_id,
                event_id=event_id,
                metric_date=metric_date,
                funnel_code=funnel_code,
                step_code=step_code,
                step_order=order,
                actor_count=None if suppressed else distinct_actor_count,
                suppressed=suppressed,
                conversion_from_previous=conversion,
            )
        )
        previous_actor_count = distinct_actor_count
        previous_suppressed = suppressed
    return rows


# ---------------------------------------------------------------------------
# Search no-result summary
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SearchNoResultRow:
    tenant_id: str
    event_id: str
    summary_date: date
    channel_code: str
    query_norm: str
    occurrence_count: int | None
    distinct_actor_count: int | None
    suppressed: bool
    last_occurred_at: datetime | None


#: Forward-looking best-effort aliases - see module docstring gap (2)/(3): no such event is
#: emitted anywhere in this repository yet.
DEFAULT_ZERO_RESULT_EVENT_TYPES: tuple[str, ...] = (
    "SEARCH_NO_RESULT",
    "KIOSK_SEARCH_NO_RESULT",
    "QUERY_ZERO_RESULT",
)


def _normalize_query(value: object) -> str:
    if not isinstance(value, str):
        return "UNKNOWN"
    normalized = value.strip().lower()
    return normalized or "UNKNOWN"


def _channel_for(event: RawEvent) -> str:
    if isinstance(event.context, Mapping):
        channel = event.context.get("channel")
        if isinstance(channel, str) and channel.strip():
            return channel.strip().upper()
    if event.event_type.upper().startswith("KIOSK"):
        return "KIOSK"
    return "UNKNOWN"


def aggregate_search_no_result_summary(
    events: Sequence[RawEvent],
    *,
    tenant_id: str,
    event_id: str,
    summary_date: date,
    utc_offset: timedelta = KST_OFFSET,
    zero_result_event_types: tuple[str, ...] = DEFAULT_ZERO_RESULT_EVENT_TYPES,
) -> list[SearchNoResultRow]:
    bucketed = [
        e
        for e in _bucketed(
            events, tenant_id=tenant_id, event_id=event_id, metric_date=summary_date, utc_offset=utc_offset
        )
        if e.event_type in zero_result_event_types
    ]

    groups: dict[tuple[str, str], list[RawEvent]] = defaultdict(list)
    for event in bucketed:
        context = event.context or {}
        # "query_norm" is the forward-looking key name; "query_text" is normalized here too in
        # case a future contract only carries the raw text. See module docstring gap (3).
        raw_query = context.get("query_norm") if isinstance(context, Mapping) else None
        if raw_query is None and isinstance(context, Mapping):
            raw_query = context.get("query_text")
        groups[(_channel_for(event), _normalize_query(raw_query))].append(event)

    rows: list[SearchNoResultRow] = []
    for (channel_code, query_norm), grouped in groups.items():
        distinct_actor_count = len({actor_key(e) for e in grouped if actor_key(e) is not None})
        suppressed = _suppress(distinct_actor_count)
        rows.append(
            SearchNoResultRow(
                tenant_id=tenant_id,
                event_id=event_id,
                summary_date=summary_date,
                channel_code=channel_code,
                query_norm=query_norm,
                occurrence_count=None if suppressed else len(grouped),
                distinct_actor_count=None if suppressed else distinct_actor_count,
                suppressed=suppressed,
                last_occurred_at=None if suppressed else max(e.occurred_at for e in grouped),
            )
        )
    rows.sort(key=lambda r: (r.channel_code, r.query_norm))
    return rows


# ---------------------------------------------------------------------------
# Orchestration + idempotent persistence boundary
# ---------------------------------------------------------------------------


@runtime_checkable
class MetricSink(Protocol):
    """Persistence boundary, upsert-by-natural-key (idempotent by construction).

    `worker/sinks/analytics_sink.py::AnalyticsSink` is the Postgres-backed implementation:
    `INSERT ... ON CONFLICT (<natural key>) DO UPDATE` against the UNIQUE constraints
    `apps/api/app/models/analytics.py` already declares. `async` (not `def`, unlike the
    standalone-worktree original of this module) because this repo has no synchronous
    SQLAlchemy engine to implement a sync Protocol against - see module docstring.
    """

    async def upsert_daily_metrics(self, rows: Sequence[DailyMetricRow]) -> None: ...

    async def upsert_funnel_metrics(self, rows: Sequence[FunnelMetricRow]) -> None: ...

    async def upsert_search_no_result_summary(self, rows: Sequence[SearchNoResultRow]) -> None: ...


@dataclass
class InMemoryMetricSink:
    """Reference MetricSink for tests/local use - not safe to share across processes."""

    daily_metrics: dict[tuple, DailyMetricRow] = field(default_factory=dict)
    funnel_metrics: dict[tuple, FunnelMetricRow] = field(default_factory=dict)
    search_no_result_summaries: dict[tuple, SearchNoResultRow] = field(default_factory=dict)

    async def upsert_daily_metrics(self, rows: Sequence[DailyMetricRow]) -> None:
        for row in rows:
            key = (row.tenant_id, row.event_id, row.metric_date, row.metric_code, row.dimension_code)
            self.daily_metrics[key] = row

    async def upsert_funnel_metrics(self, rows: Sequence[FunnelMetricRow]) -> None:
        for row in rows:
            key = (row.tenant_id, row.event_id, row.metric_date, row.funnel_code, row.step_code)
            self.funnel_metrics[key] = row

    async def upsert_search_no_result_summary(self, rows: Sequence[SearchNoResultRow]) -> None:
        for row in rows:
            key = (row.tenant_id, row.event_id, row.summary_date, row.channel_code, row.query_norm)
            self.search_no_result_summaries[key] = row


@dataclass(frozen=True)
class AggregationResult:
    aggregation_run_id: str
    daily_metrics: tuple[DailyMetricRow, ...]
    funnel_metrics: tuple[FunnelMetricRow, ...]
    search_no_result_summaries: tuple[SearchNoResultRow, ...]


async def run_daily_aggregation(
    events: Sequence[RawEvent],
    sink: MetricSink,
    *,
    tenant_id: str,
    event_id: str,
    metric_date: date,
    utc_offset: timedelta = KST_OFFSET,
    daily_metric_definitions: Mapping[str, tuple[str, ...]] | None = None,
    funnels: Mapping[str, tuple[FunnelStep, ...]] | None = None,
    zero_result_event_types: tuple[str, ...] = DEFAULT_ZERO_RESULT_EVENT_TYPES,
    aggregation_run_id: str | None = None,
) -> AggregationResult:
    """Full-recompute aggregation for one (tenant, event, calendar day) - see module docstring.

    Safe to call repeatedly (idempotent re-aggregation) and safe to call with a fuller event
    set on a later run (late-arriving events) - both properties come from recomputing from
    scratch every time and upserting by natural key, not from any special-cased logic here.
    """

    run_id = aggregation_run_id or str(uuid.uuid4())
    funnel_defs = dict(funnels) if funnels is not None else FUNNEL_DEFINITIONS

    daily_rows = aggregate_daily_metrics(
        events,
        tenant_id=tenant_id,
        event_id=event_id,
        metric_date=metric_date,
        utc_offset=utc_offset,
        metric_definitions=daily_metric_definitions,
    )

    funnel_rows: list[FunnelMetricRow] = []
    for funnel_code, steps in funnel_defs.items():
        funnel_rows.extend(
            aggregate_funnel_metrics(
                events,
                tenant_id=tenant_id,
                event_id=event_id,
                metric_date=metric_date,
                funnel_code=funnel_code,
                utc_offset=utc_offset,
                steps=steps,
            )
        )

    search_rows = aggregate_search_no_result_summary(
        events,
        tenant_id=tenant_id,
        event_id=event_id,
        summary_date=metric_date,
        utc_offset=utc_offset,
        zero_result_event_types=zero_result_event_types,
    )

    await sink.upsert_daily_metrics(daily_rows)
    await sink.upsert_funnel_metrics(funnel_rows)
    await sink.upsert_search_no_result_summary(search_rows)

    return AggregationResult(
        aggregation_run_id=run_id,
        daily_metrics=tuple(daily_rows),
        funnel_metrics=tuple(funnel_rows),
        search_no_result_summaries=tuple(search_rows),
    )


# ---------------------------------------------------------------------------
# Job registration hook (for the integrator - see document_parsing.py precedent)
# ---------------------------------------------------------------------------


@runtime_checkable
class JobRegistry(Protocol):
    def register(self, name: str, handler: object) -> None: ...


async def handle_analytics_aggregation_job(
    payload: Mapping[str, object], *, sink: MetricSink
) -> AggregationResult:
    """Job-shaped entry point. `payload` carries `events` (list[RawEvent]), `tenant_id`,
    `event_id`, `metric_date` (date), and optional `utc_offset` (timedelta)."""

    events = payload["events"]
    if not isinstance(events, (list, tuple)) or not all(isinstance(e, RawEvent) for e in events):
        raise TypeError("payload['events'] must be a sequence of RawEvent")
    metric_date = payload["metric_date"]
    if not isinstance(metric_date, date):
        raise TypeError("payload['metric_date'] must be a date")
    tenant_id = payload["tenant_id"]
    event_id = payload["event_id"]
    if not isinstance(tenant_id, str) or not isinstance(event_id, str):
        raise TypeError("payload['tenant_id'] and payload['event_id'] must be str")
    utc_offset = payload.get("utc_offset", KST_OFFSET)
    if not isinstance(utc_offset, timedelta):
        utc_offset = KST_OFFSET
    return await run_daily_aggregation(
        events, sink, tenant_id=tenant_id, event_id=event_id, metric_date=metric_date, utc_offset=utc_offset
    )


def register_analytics_aggregation_job(registry: JobRegistry) -> None:
    """Registration hook for the integrator - wiring a real RQ/Celery registry and a
    Postgres-backed MetricSink is integration work outside this track's OWNED PATHS."""

    registry.register("analytics_aggregation", handle_analytics_aggregation_job)
