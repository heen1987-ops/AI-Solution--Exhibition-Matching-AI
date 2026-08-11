"""Tests for apps/worker/app/jobs/analytics_aggregation.py and data_quality.py
(WAVE 2E / WORKER-ANALYTICS).

Covers the five explicitly-required behaviors:
1. aggregation correctness on a synthetic event set,
2. idempotent re-aggregation (running the same period twice never double-counts),
3. late-arriving event handling (a fuller later run corrects, never inflates),
4. small-group suppression (<5 distinct users -> values nulled at the output row),
5. timezone handling (UTC storage, "행사 시간대" local-day bucketing),
plus the data-quality snapshot job and the test/staff-flag exclusion path.

All events are synthetic and in-memory; no identifiers here are real personal data
(uuid4-style opaque strings only), per the no-PII-in-fixtures rule.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from worker.jobs.analytics_aggregation import (
    KST_OFFSET,
    SUPPRESSION_THRESHOLD,
    InMemoryMetricSink,
    RawEvent,
    actor_key,
    aggregate_daily_metrics,
    aggregate_funnel_metrics,
    aggregate_search_no_result_summary,
    handle_analytics_aggregation_job,
    is_test_or_staff_event,
    local_date,
    register_analytics_aggregation_job,
    run_daily_aggregation,
)
from worker.jobs.data_quality import (
    CHECK_DUPLICATE_CLIENT_EVENT_RATE,
    CHECK_INGESTION_LATENCY_P95,
    CHECK_LATE_ARRIVAL_RATE,
    CHECK_SUBJECT_UNKNOWN_RATE,
    CHECK_SUPPRESSED_METRIC_RATIO,
    STATUS_FAIL,
    STATUS_OK,
    STATUS_WARN,
    CheckThresholds,
    InMemoryDataQualitySink,
    compute_data_quality_snapshots,
    register_data_quality_job,
    run_data_quality_job,
)

TENANT = "tenant-0001"
EVENT = "event-0001"
OTHER_EVENT = "event-9999"
DAY = date(2026, 8, 2)

_UTC = UTC
_seq = 0


def _utc(hour: int, minute: int = 0, *, day: int = 2) -> datetime:
    return datetime(2026, 8, day, hour, minute, tzinfo=_UTC)


def _kst_morning_utc() -> datetime:
    """2026-08-02 10:00 KST == 2026-08-02 01:00 UTC (same local/UTC day)."""

    return _utc(1)


def make_event(
    event_type: str,
    *,
    user: str | None = None,
    guest: str | None = None,
    visit: str | None = None,
    occurred_at: datetime | None = None,
    received_at: datetime | None = None,
    client_event_id: str | None = None,
    context: dict | None = None,
    tenant_id: str = TENANT,
    event_id: str = EVENT,
) -> RawEvent:
    global _seq
    _seq += 1
    occurred = occurred_at or _kst_morning_utc()
    return RawEvent(
        interaction_event_id=f"ie-{_seq:05d}",
        tenant_id=tenant_id,
        event_id=event_id,
        event_type=event_type,
        occurred_at=occurred,
        received_at=received_at or (occurred + timedelta(seconds=2)),
        user_id=user,
        guest_session_id=guest,
        visit_session_id=visit,
        client_event_id=client_event_id,
        context=context,
    )


def _users(prefix: str, n: int) -> list[str]:
    return [f"{prefix}-{i:03d}" for i in range(n)]


def _daily_row(rows, metric_code):
    return next(r for r in rows if r.metric_code == metric_code)


def _funnel_row(rows, step_code):
    return next(r for r in rows if r.step_code == step_code)


# ---------------------------------------------------------------------------
# 1. Aggregation correctness on a synthetic event set
# ---------------------------------------------------------------------------


class TestDailyMetricCorrectness:
    def test_counts_events_and_distinct_actors(self):
        events = [
            make_event("RECOMMENDATION_IMPRESSION", user=u) for u in _users("u", 6)
        ]
        # one user repeats -> 7 events, still 6 distinct actors
        events.append(make_event("RECOMMENDATION_IMPRESSION", user="u-000"))
        rows = aggregate_daily_metrics(
            events, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        row = _daily_row(rows, "RECOMMENDATION_IMPRESSION")
        assert row.event_count == 7
        assert row.distinct_actor_count == 6
        assert row.suppressed is False

    def test_alias_event_types_roll_into_one_metric(self):
        events = [make_event("RECOMMENDATION_OPENED", user=u) for u in _users("a", 3)]
        events += [make_event("RECOMMENDATION_CLICKED", user=u) for u in _users("b", 3)]
        rows = aggregate_daily_metrics(
            events, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        row = _daily_row(rows, "RECOMMENDATION_CLICK")
        assert row.event_count == 6
        assert row.distinct_actor_count == 6

    def test_total_interactions_counts_everything_bucketed(self):
        events = [make_event("RECOMMENDATION_IMPRESSION", user=u) for u in _users("u", 5)]
        events += [make_event("SOME_UNMAPPED_TYPE", user=u) for u in _users("v", 5)]
        rows = aggregate_daily_metrics(
            events, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        assert _daily_row(rows, "TOTAL_INTERACTIONS").event_count == 10

    def test_other_tenant_or_event_rows_are_excluded(self):
        events = [make_event("RECOMMENDATION_IMPRESSION", user=u) for u in _users("u", 6)]
        events.append(
            make_event("RECOMMENDATION_IMPRESSION", user="x-1", event_id=OTHER_EVENT)
        )
        events.append(
            make_event(
                "RECOMMENDATION_IMPRESSION", user="x-2", tenant_id="tenant-else"
            )
        )
        rows = aggregate_daily_metrics(
            events, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        assert _daily_row(rows, "RECOMMENDATION_IMPRESSION").event_count == 6

    def test_actor_key_prefers_user_then_guest_then_visit(self):
        assert actor_key(make_event("X", user="u1", visit="v1")) == "user:u1"
        assert actor_key(make_event("X", guest="g1", visit="v1")) == "guest:g1"
        assert actor_key(make_event("X", visit="v1")) == "visit:v1"
        assert actor_key(make_event("X")) is None

    def test_test_and_staff_flagged_events_are_excluded(self):
        events = [make_event("RECOMMENDATION_IMPRESSION", user=u) for u in _users("u", 6)]
        events.append(
            make_event(
                "RECOMMENDATION_IMPRESSION", user="staff-1", context={"is_staff": True}
            )
        )
        events.append(
            make_event(
                "RECOMMENDATION_IMPRESSION", user="test-1", context={"is_test": True}
            )
        )
        assert is_test_or_staff_event(events[-1]) is True
        rows = aggregate_daily_metrics(
            events, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        row = _daily_row(rows, "RECOMMENDATION_IMPRESSION")
        assert row.event_count == 6
        assert row.distinct_actor_count == 6


class TestFunnelCorrectness:
    def test_web_funnel_step_counts_and_conversion(self):
        events: list[RawEvent] = []
        confirm_users = _users("w", 10)
        for u in confirm_users:
            events.append(make_event("PROFILE_CONFIRMED", user=u))
        for u in confirm_users[:8]:
            events.append(make_event("RECOMMENDATION_IMPRESSION", user=u))
        for u in confirm_users[:6]:
            events.append(make_event("RECOMMENDATION_OPENED", user=u))
        for u in confirm_users[:5]:
            events.append(make_event("VIEW_DETAIL", user=u))
        rows = aggregate_funnel_metrics(
            events, tenant_id=TENANT, event_id=EVENT, metric_date=DAY, funnel_code="WEB"
        )
        assert [r.step_order for r in rows] == [1, 2, 3, 4, 5]
        assert _funnel_row(rows, "PROFILE_CONFIRM").actor_count == 10
        assert _funnel_row(rows, "RECOMMENDATION_IMPRESSION").actor_count == 8
        assert _funnel_row(rows, "RECOMMENDATION_CLICK").actor_count == 6
        assert _funnel_row(rows, "EXHIBITOR_DETAIL").actor_count == 5
        assert _funnel_row(rows, "RECOMMENDATION_IMPRESSION").conversion_from_previous == pytest.approx(0.8)
        assert _funnel_row(rows, "RECOMMENDATION_CLICK").conversion_from_previous == pytest.approx(0.75)
        # first step never has a conversion-from-previous
        assert _funnel_row(rows, "PROFILE_CONFIRM").conversion_from_previous is None

    def test_kiosk_funnel_counts_guest_sessions_as_actors(self):
        events: list[RawEvent] = []
        guests = _users("g", 7)
        for g in guests:
            events.append(make_event("KIOSK_SESSION_STARTED", guest=g))
        for g in guests[:5]:
            events.append(make_event("KIOSK_QUERY_SUBMITTED", guest=g))
        rows = aggregate_funnel_metrics(
            events, tenant_id=TENANT, event_id=EVENT, metric_date=DAY, funnel_code="KIOSK"
        )
        assert _funnel_row(rows, "SESSION_START").actor_count == 7
        assert _funnel_row(rows, "QUERY_SUBMIT").actor_count == 5
        # steps with no events at all: zero, unsuppressed (nothing to protect)
        assert _funnel_row(rows, "QR_SEND").actor_count == 0
        assert _funnel_row(rows, "QR_SEND").suppressed is False

    def test_buyer_funnel_has_no_deal_value_step(self):
        rows = aggregate_funnel_metrics(
            [], tenant_id=TENANT, event_id=EVENT, metric_date=DAY, funnel_code="BUYER"
        )
        step_codes = {r.step_code for r in rows}
        assert step_codes == {
            "VERIFY",
            "MATCH_GENERATE",
            "COMPARE",
            "MEETING_REQUEST",
            "MEETING_ACCEPT",
            "MEETING_COMPLETE",
        }
        assert not any("DEAL" in s or "CONTRACT" in s or "VALUE" in s for s in step_codes)


class TestSearchNoResultCorrectness:
    def test_groups_by_channel_and_normalized_query(self):
        events = [
            make_event(
                "KIOSK_SEARCH_NO_RESULT",
                guest=g,
                context={"channel": "KIOSK", "query_text": "  Omija Wine  "},
            )
            for g in _users("g", 5)
        ]
        events.append(
            make_event(
                "SEARCH_NO_RESULT",
                user="u-1",
                context={"channel": "WEB", "query_text": "takju"},
            )
        )
        rows = aggregate_search_no_result_summary(
            events, tenant_id=TENANT, event_id=EVENT, summary_date=DAY
        )
        kiosk = next(r for r in rows if r.channel_code == "KIOSK")
        assert kiosk.query_norm == "omija wine"
        assert kiosk.occurrence_count == 5
        assert kiosk.distinct_actor_count == 5
        assert kiosk.suppressed is False
        web = next(r for r in rows if r.channel_code == "WEB")
        assert web.suppressed is True  # single user -> suppressed

    def test_missing_query_text_stays_unknown_never_fabricated(self):
        events = [
            make_event("SEARCH_NO_RESULT", user=u, context={"channel": "WEB"})
            for u in _users("u", 6)
        ]
        rows = aggregate_search_no_result_summary(
            events, tenant_id=TENANT, event_id=EVENT, summary_date=DAY
        )
        assert rows[0].query_norm == "UNKNOWN"


# ---------------------------------------------------------------------------
# 2. Idempotent re-aggregation
# ---------------------------------------------------------------------------


class TestIdempotentReaggregation:
    @pytest.mark.asyncio
    async def test_running_twice_produces_identical_sink_state_no_double_count(self):
        events = [make_event("RECOMMENDATION_IMPRESSION", user=u) for u in _users("u", 8)]
        events += [make_event("PROFILE_CONFIRMED", user=u) for u in _users("u", 8)]
        sink = InMemoryMetricSink()

        await run_daily_aggregation(
            events, sink, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        first_daily = dict(sink.daily_metrics)
        first_funnel = dict(sink.funnel_metrics)
        first_search = dict(sink.search_no_result_summaries)

        await run_daily_aggregation(
            events, sink, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )

        assert sink.daily_metrics == first_daily
        assert sink.funnel_metrics == first_funnel
        assert sink.search_no_result_summaries == first_search
        # explicitly: the impression count did not double
        key = (TENANT, EVENT, DAY, "RECOMMENDATION_IMPRESSION", "ALL")
        assert sink.daily_metrics[key].event_count == 8

    @pytest.mark.asyncio
    async def test_row_count_stable_across_reruns(self):
        events = [make_event("RECOMMENDATION_IMPRESSION", user=u) for u in _users("u", 8)]
        sink = InMemoryMetricSink()
        for _ in range(3):
            await run_daily_aggregation(
                events, sink, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
            )
        # one row per (metric_code) and per (funnel, step) - never 3x
        assert len({k for k in sink.daily_metrics}) == len(sink.daily_metrics)
        daily_keys = [k for k in sink.daily_metrics if k[3] == "RECOMMENDATION_IMPRESSION"]
        assert len(daily_keys) == 1


# ---------------------------------------------------------------------------
# 3. Late-arriving events
# ---------------------------------------------------------------------------


class TestLateArrivingEvents:
    @pytest.mark.asyncio
    async def test_reaggregation_with_fuller_set_corrects_without_inflating(self):
        on_time = [
            make_event("RECOMMENDATION_IMPRESSION", user=u) for u in _users("u", 6)
        ]
        sink = InMemoryMetricSink()
        await run_daily_aggregation(
            on_time, sink, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        key = (TENANT, EVENT, DAY, "RECOMMENDATION_IMPRESSION", "ALL")
        assert sink.daily_metrics[key].event_count == 6

        # two events occurred on DAY but were only received the next day (late arrivals)
        late = [
            make_event(
                "RECOMMENDATION_IMPRESSION",
                user=f"late-{i}",
                occurred_at=_utc(14),
                received_at=_utc(3, day=3),
            )
            for i in range(2)
        ]
        await run_daily_aggregation(
            on_time + late, sink, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        row = sink.daily_metrics[key]
        assert row.event_count == 8  # 6 + 2, not 6 + 6 + 2
        assert row.distinct_actor_count == 8

    def test_late_event_lands_in_its_occurrence_day_not_receipt_day(self):
        late = [
            make_event(
                "RECOMMENDATION_IMPRESSION",
                user=f"late-{i}",
                occurred_at=_utc(14),  # 2026-08-02 23:00 KST -> local day 08-02
                received_at=_utc(9, day=3),  # received the next day
            )
            for i in range(5)  # 5 users so the row is published, not suppressed
        ]
        rows_occurrence_day = aggregate_daily_metrics(
            late, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        rows_receipt_day = aggregate_daily_metrics(
            late, tenant_id=TENANT, event_id=EVENT, metric_date=date(2026, 8, 3)
        )
        assert _daily_row(rows_occurrence_day, "RECOMMENDATION_IMPRESSION").event_count == 5
        assert _daily_row(rows_receipt_day, "RECOMMENDATION_IMPRESSION").event_count == 0


# ---------------------------------------------------------------------------
# 4. Small-group suppression
# ---------------------------------------------------------------------------


class TestSmallGroupSuppression:
    @pytest.mark.parametrize("n", [1, 2, 3, 4])
    def test_fewer_than_threshold_distinct_users_is_suppressed(self, n):
        assert n < SUPPRESSION_THRESHOLD
        events = [make_event("RECOMMENDATION_IMPRESSION", user=u) for u in _users("u", n)]
        rows = aggregate_daily_metrics(
            events, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        row = _daily_row(rows, "RECOMMENDATION_IMPRESSION")
        assert row.suppressed is True
        assert row.event_count is None
        assert row.distinct_actor_count is None

    def test_exactly_threshold_users_is_published(self):
        events = [
            make_event("RECOMMENDATION_IMPRESSION", user=u)
            for u in _users("u", SUPPRESSION_THRESHOLD)
        ]
        rows = aggregate_daily_metrics(
            events, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        row = _daily_row(rows, "RECOMMENDATION_IMPRESSION")
        assert row.suppressed is False
        assert row.distinct_actor_count == SUPPRESSION_THRESHOLD

    def test_zero_users_is_not_suppressed(self):
        rows = aggregate_daily_metrics(
            [], tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        row = _daily_row(rows, "RECOMMENDATION_IMPRESSION")
        assert row.suppressed is False
        assert row.event_count == 0

    def test_many_events_from_few_users_still_suppressed(self):
        # 40 events but only 2 distinct users -> still a small group
        events = [
            make_event("RECOMMENDATION_IMPRESSION", user=f"u-{i % 2}") for i in range(40)
        ]
        rows = aggregate_daily_metrics(
            events, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        assert _daily_row(rows, "RECOMMENDATION_IMPRESSION").suppressed is True

    def test_funnel_conversion_nulled_when_either_side_suppressed(self):
        events: list[RawEvent] = []
        for u in _users("w", 10):
            events.append(make_event("PROFILE_CONFIRMED", user=u))
        for u in _users("w", 3):  # suppressed step (3 < 5)
            events.append(make_event("RECOMMENDATION_IMPRESSION", user=u))
        for u in _users("w", 6):  # next step un-suppressed again
            events.append(make_event("RECOMMENDATION_OPENED", user=u))
        rows = aggregate_funnel_metrics(
            events, tenant_id=TENANT, event_id=EVENT, metric_date=DAY, funnel_code="WEB"
        )
        suppressed_step = _funnel_row(rows, "RECOMMENDATION_IMPRESSION")
        assert suppressed_step.suppressed is True
        assert suppressed_step.actor_count is None
        assert suppressed_step.conversion_from_previous is None
        # step after a suppressed step must not leak a ratio either
        after = _funnel_row(rows, "RECOMMENDATION_CLICK")
        assert after.suppressed is False
        assert after.conversion_from_previous is None


# ---------------------------------------------------------------------------
# 5. Timezone handling (store UTC, bucket by event-local "행사 시간대" day)
# ---------------------------------------------------------------------------


class TestTimezoneBucketing:
    def test_utc_evening_is_next_kst_day(self):
        # 2026-08-01 16:30 UTC == 2026-08-02 01:30 KST
        assert local_date(_utc(16, 30, day=1)) == date(2026, 8, 2)

    def test_utc_midday_is_same_kst_day(self):
        assert local_date(_utc(3, day=2)) == date(2026, 8, 2)

    def test_naive_datetime_is_rejected(self):
        with pytest.raises(ValueError):
            make_event(
                "X",
                user="u",
                # deliberately naive - the whole point of this test
                occurred_at=datetime(2026, 8, 2, 10, 0),  # noqa: DTZ001
            )

    def test_events_straddling_utc_midnight_bucket_into_one_kst_day(self):
        # Both instants are 2026-08-02 in KST although they differ in UTC date
        late_utc_aug1 = [
            make_event("RECOMMENDATION_IMPRESSION", user=u, occurred_at=_utc(20, day=1))
            for u in _users("a", 3)
        ]
        early_utc_aug2 = [
            make_event("RECOMMENDATION_IMPRESSION", user=u, occurred_at=_utc(2, day=2))
            for u in _users("b", 3)
        ]
        rows = aggregate_daily_metrics(
            late_utc_aug1 + early_utc_aug2,
            tenant_id=TENANT,
            event_id=EVENT,
            metric_date=date(2026, 8, 2),
        )
        row = _daily_row(rows, "RECOMMENDATION_IMPRESSION")
        assert row.event_count == 6
        assert row.distinct_actor_count == 6

    def test_non_default_offset_changes_bucketing(self):
        instant = _utc(20, day=1)  # 08-02 05:00 KST, but 08-01 20:00 UTC+0
        assert local_date(instant, utc_offset=KST_OFFSET) == date(2026, 8, 2)
        assert local_date(instant, utc_offset=timedelta(0)) == date(2026, 8, 1)
        events = [
            make_event("RECOMMENDATION_IMPRESSION", user=u, occurred_at=instant)
            for u in _users("u", 5)
        ]
        rows_utc = aggregate_daily_metrics(
            events,
            tenant_id=TENANT,
            event_id=EVENT,
            metric_date=date(2026, 8, 1),
            utc_offset=timedelta(0),
        )
        assert _daily_row(rows_utc, "RECOMMENDATION_IMPRESSION").event_count == 5


# ---------------------------------------------------------------------------
# Orchestration entry points
# ---------------------------------------------------------------------------


class TestJobEntryPoints:
    @pytest.mark.asyncio
    async def test_run_daily_aggregation_writes_all_three_marts(self):
        events = [make_event("RECOMMENDATION_IMPRESSION", user=u) for u in _users("u", 6)]
        events += [
            make_event(
                "SEARCH_NO_RESULT", user=u, context={"channel": "WEB", "query_text": "q"}
            )
            for u in _users("u", 6)
        ]
        sink = InMemoryMetricSink()
        result = await run_daily_aggregation(
            events, sink, tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        assert result.daily_metrics and result.funnel_metrics
        assert result.search_no_result_summaries
        assert sink.daily_metrics and sink.funnel_metrics and sink.search_no_result_summaries
        funnel_codes = {r.funnel_code for r in result.funnel_metrics}
        assert funnel_codes == {"WEB", "KIOSK", "BUYER"}

    @pytest.mark.asyncio
    async def test_handle_job_validates_payload(self):
        sink = InMemoryMetricSink()
        with pytest.raises(TypeError):
            await handle_analytics_aggregation_job(
                {"events": "nope", "metric_date": DAY, "tenant_id": TENANT, "event_id": EVENT},
                sink=sink,
            )
        with pytest.raises(TypeError):
            await handle_analytics_aggregation_job(
                {"events": [], "metric_date": "2026-08-02", "tenant_id": TENANT, "event_id": EVENT},
                sink=sink,
            )

    def test_registration_hooks_do_not_touch_shared_modules(self):
        registered: dict[str, object] = {}

        class Registry:
            def register(self, name, handler):
                registered[name] = handler

        register_analytics_aggregation_job(Registry())
        register_data_quality_job(Registry())
        assert set(registered) == {"analytics_aggregation", "data_quality"}


# ---------------------------------------------------------------------------
# Data quality snapshots
# ---------------------------------------------------------------------------


class TestDataQuality:
    def test_latency_p95_and_status(self):
        events = [
            make_event(
                "X",
                user=f"u-{i}",
                occurred_at=_utc(1),
                received_at=_utc(1) + timedelta(seconds=1),
            )
            for i in range(19)
        ]
        events.append(
            make_event(
                "X", user="slow", occurred_at=_utc(1), received_at=_utc(1) + timedelta(seconds=700)
            )
        )
        rows = compute_data_quality_snapshots(
            events, tenant_id=TENANT, event_id=EVENT, snapshot_date=DAY
        )
        latency = next(r for r in rows if r.check_code == CHECK_INGESTION_LATENCY_P95)
        # nearest-rank p95 of 20 values -> 19th smallest == 1s -> OK
        assert latency.metric_value == pytest.approx(1.0)
        assert latency.status == STATUS_OK

    def test_late_arrival_rate_warn(self):
        on_time = [make_event("X", user=f"u-{i}") for i in range(9)]
        late = [
            make_event(
                "X",
                user="late",
                occurred_at=_utc(14),
                received_at=_utc(5, day=3),
            )
        ]
        rows = compute_data_quality_snapshots(
            on_time + late, tenant_id=TENANT, event_id=EVENT, snapshot_date=DAY
        )
        rate = next(r for r in rows if r.check_code == CHECK_LATE_ARRIVAL_RATE)
        assert rate.metric_value == pytest.approx(0.1)
        assert rate.status == STATUS_WARN
        assert rate.affected_count == 1

    def test_duplicate_client_event_id_rate(self):
        events = [
            make_event("X", user=f"u-{i}", client_event_id=f"c-{i}") for i in range(8)
        ]
        events.append(make_event("X", user="u-0", client_event_id="c-0"))  # duplicate
        events.append(make_event("X", user="u-9"))  # no client id -> excluded from denom
        rows = compute_data_quality_snapshots(
            events, tenant_id=TENANT, event_id=EVENT, snapshot_date=DAY
        )
        dup = next(r for r in rows if r.check_code == CHECK_DUPLICATE_CLIENT_EVENT_RATE)
        assert dup.affected_count == 1
        assert dup.metric_value == pytest.approx(1 / 9)
        assert dup.status == STATUS_FAIL  # > 0.05 default fail threshold

    def test_subject_unknown_rate(self):
        events = [make_event("X", user=f"u-{i}") for i in range(3)]
        events.append(make_event("X"))  # no subject at all
        rows = compute_data_quality_snapshots(
            events, tenant_id=TENANT, event_id=EVENT, snapshot_date=DAY
        )
        unknown = next(r for r in rows if r.check_code == CHECK_SUBJECT_UNKNOWN_RATE)
        assert unknown.metric_value == pytest.approx(0.25)
        assert unknown.affected_count == 1

    @pytest.mark.asyncio
    async def test_suppressed_metric_ratio_requires_aggregation_result(self):
        events = [make_event("RECOMMENDATION_IMPRESSION", user="u-1")]  # 1 user -> suppressed
        rows_without = compute_data_quality_snapshots(
            events, tenant_id=TENANT, event_id=EVENT, snapshot_date=DAY
        )
        assert not any(
            r.check_code == CHECK_SUPPRESSED_METRIC_RATIO for r in rows_without
        )
        agg = await run_daily_aggregation(
            events, InMemoryMetricSink(), tenant_id=TENANT, event_id=EVENT, metric_date=DAY
        )
        rows_with = compute_data_quality_snapshots(
            events,
            tenant_id=TENANT,
            event_id=EVENT,
            snapshot_date=DAY,
            aggregation_result=agg,
        )
        ratio = next(
            r for r in rows_with if r.check_code == CHECK_SUPPRESSED_METRIC_RATIO
        )
        assert 0.0 < ratio.metric_value <= 1.0
        assert ratio.affected_count >= 1

    def test_no_events_yields_no_rows_never_fabricated_zeroes(self):
        rows = compute_data_quality_snapshots(
            [], tenant_id=TENANT, event_id=EVENT, snapshot_date=DAY
        )
        assert rows == []

    def test_snapshot_details_carry_no_identifiers(self):
        events = [
            make_event("X", user=f"u-{i}", client_event_id=f"c-{i}") for i in range(6)
        ]
        rows = compute_data_quality_snapshots(
            events, tenant_id=TENANT, event_id=EVENT, snapshot_date=DAY
        )
        for row in rows:
            for value in (row.details_json or {}).values():
                assert isinstance(value, (int, float))

    @pytest.mark.asyncio
    async def test_data_quality_job_is_idempotent(self):
        events = [make_event("X", user=f"u-{i}") for i in range(6)]
        sink = InMemoryDataQualitySink()
        await run_data_quality_job(
            events, sink, tenant_id=TENANT, event_id=EVENT, snapshot_date=DAY
        )
        first = dict(sink.snapshots)
        await run_data_quality_job(
            events, sink, tenant_id=TENANT, event_id=EVENT, snapshot_date=DAY
        )
        assert sink.snapshots == first

    def test_threshold_override_and_validation(self):
        with pytest.raises(ValueError):
            CheckThresholds(warn_at=0.5, fail_at=0.1)
        events = [make_event("X", user=f"u-{i}") for i in range(4)] + [make_event("X")]
        rows = compute_data_quality_snapshots(
            events,
            tenant_id=TENANT,
            event_id=EVENT,
            snapshot_date=DAY,
            thresholds={CHECK_SUBJECT_UNKNOWN_RATE: CheckThresholds(0.0, 0.05)},
        )
        unknown = next(r for r in rows if r.check_code == CHECK_SUBJECT_UNKNOWN_RATE)
        assert unknown.status == STATUS_FAIL  # 0.2 > 0.05 overridden fail threshold
