"""Read-only query layer for ``/admin/analytics/*`` (WAVE 2E / BACKEND-ANALYTICS).

Two data sources, deliberately kept separate
----------------------------------------------
1. **Behavioral/interaction-derived KPIs** (recommendation impressions/clicks, favorite
   saves, meeting requests/accepts, buyer-funnel steps, search volume, zero-result
   queries, pipeline data-quality) are read *only* from the ``analytics.*`` aggregate
   tables WORKER-ANALYTICS publishes (``app/models/analytics.py``:
   ``AnalyticsDailyMetric``, ``AnalyticsFunnelMetric``, ``AnalyticsSearchNoResultSummary``,
   ``AnalyticsDataQualitySnapshot``) - never ``interaction.interaction_event`` directly,
   per this track's prompt ("do NOT query raw interaction_events directly from this
   router, always go through the aggregate tables").
2. **Structural headcounts** (registered users, profile-confirm rate, kiosk session
   count/duration/QR-handoffs, published exhibitor/product counts) have **no
   representation at all** in the ``analytics.*`` aggregate tables - they are not
   interaction events, they are canonical business/account records. WORKER-ANALYTICS's
   pipeline only ever aggregates ``interaction.interaction_event`` rows (see
   ``apps/worker/app/jobs/analytics_aggregation.py``'s module docstring), so a
   "registered_users" or "published_exhibitor_count" KPI simply cannot exist in those
   tables under any reconciliation - there is nothing to reconcile, the source data
   lives in ``profile.user_account``/``profile.user_role``/``profile.user_profile``/
   ``kiosk.kiosk_session``/``kiosk.kiosk_qr_handoff``/``exhibition.exhibitor``/
   ``exhibition.exhibitor_participation``/``exhibition.event_product`` instead. This
   track's prompt forbids querying *interaction_events* directly; it does not (and could
   not, since the KPI list it hands this track requires them) forbid read-only queries
   against these other canonical operational tables. Blocker Score for this reading:
   low (reversible, no privacy/security risk, and the alternative - leaving half the
   mandated overview KPI list permanently at "0, never available" - is a worse outcome
   for a read-only reporting endpoint). Flagged here and in the final report rather than
   silently assumed.

Every function in this module takes an already-open ``AsyncSession`` and returns either
a plain aggregate (``int``/tuple of ints) or an already-built
``app.schemas.analytics.Metric`` - never a raw per-user/per-session row - so no caller
above this layer can accidentally leak row-level detail.

See ``app/schemas/analytics.py``'s module docstring ("Reconciliation note") for the two
gaps this module works around: no per-exhibitor dimension in the landed tables (buyer
breakdown), and reusing ``Metric.suppressed`` to mean "not available from any landed
table" in a few specific, explicitly-commented spots below (never for a value this
module could have shown but chose to hide for another reason).
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.analytics import (
    AnalyticsDailyMetric,
    AnalyticsDataQualitySnapshot,
    AnalyticsFunnelMetric,
    AnalyticsSearchNoResultSummary,
)
from app.models.exhibitor import EventProduct, Exhibitor, ExhibitorParticipation
from app.models.identity import Role, UserRole
from app.models.kiosk import KioskQrHandoff, KioskSession
from app.models.profile import UserProfile
from app.schemas.analytics import (
    AnalyticsRole,
    BuyerAnalyticsResponse,
    ChannelSearchPerformance,
    DailyCount,
    DataQualityAnalyticsResponse,
    DataQualityCheckSummary,
    KioskAnalyticsResponse,
    Metric,
    NoResultQueryItem,
    NoResultQueryResponse,
    OverviewAnalyticsResponse,
    SearchAnalyticsSummary,
    SearchInsightsResponse,
    TopQueryItem,
    WebAnalyticsResponse,
)
from app.services.analytics.suppression import (
    SMALL_GROUP_SUPPRESSION_THRESHOLD,
    combine_rate,
    drop_small_groups,
    redact_query_text,
    suppress_metric,
    suppress_rate,
)

#: A masked "not available from any landed table" Metric - see this module's docstring
#: point (2) and app/schemas/analytics.py's "Reconciliation note". Never used for a value
#: this module could compute but is hiding for privacy reasons (that path always goes
#: through suppress_metric/suppress_rate/combine_rate instead, which independently arrive
#: at the same suppressed=True shape when the underlying count is small).
_UNAVAILABLE = Metric(value=None, suppressed=True)

#: Masked exhibitor-scoped buyer response - see app/schemas/analytics.py gap (1).
_MASKED_EXHIBITOR_BUYER_METRICS: dict[str, Metric] = {
    "buyer_matches": _UNAVAILABLE,
    "meeting_requests": _UNAVAILABLE,
    "meeting_accepts": _UNAVAILABLE,
    "meeting_completions": _UNAVAILABLE,
    "valid_leads": _UNAVAILABLE,
    "meeting_accept_rate": _UNAVAILABLE,
    "meeting_completion_rate": _UNAVAILABLE,
    "valid_lead_rate": _UNAVAILABLE,
}


# ---------------------------------------------------------------------------
# analytics.daily_metric / analytics.funnel_metric period rollups
# ---------------------------------------------------------------------------


async def _daily_metric_rows(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    metric_code: str,
    period_start: date,
    period_end: date,
    dimension_code: str = "ALL",
) -> Sequence[object]:
    stmt = select(
        AnalyticsDailyMetric.event_count,
        AnalyticsDailyMetric.suppressed,
    ).where(
        AnalyticsDailyMetric.event_id == event_id,
        AnalyticsDailyMetric.metric_code == metric_code,
        AnalyticsDailyMetric.dimension_code == dimension_code,
        AnalyticsDailyMetric.metric_date >= period_start,
        AnalyticsDailyMetric.metric_date <= period_end,
    )
    return (await db.execute(stmt)).all()


def _metric_from_period_rows(rows: Sequence, value_attr: str) -> Metric:
    """Roll several already-suppressed daily/funnel rows up into one period
    ``Metric``. A day with no rows at all is a true, non-identifying zero. If
    *any* day/step in the period was suppressed, the whole period figure is
    suppressed too (a conservative choice - summing the un-suppressed days
    around a masked day could let a reader back the masked day's count out by
    subtraction, so this module never does that)."""

    if not rows:
        return Metric(value=0, suppressed=False)
    if any(row.suppressed for row in rows):
        return Metric(value=None, suppressed=True)
    total = sum(getattr(row, value_attr) or 0 for row in rows)
    return Metric(value=float(total), suppressed=False)


async def _daily_metric(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    metric_code: str,
    period_start: date,
    period_end: date,
) -> Metric:
    rows = await _daily_metric_rows(
        db,
        event_id=event_id,
        metric_code=metric_code,
        period_start=period_start,
        period_end=period_end,
    )
    return _metric_from_period_rows(rows, "event_count")


async def _funnel_step_rows(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    funnel_code: str,
    step_code: str,
    period_start: date,
    period_end: date,
) -> Sequence[object]:
    stmt = select(
        AnalyticsFunnelMetric.actor_count,
        AnalyticsFunnelMetric.suppressed,
    ).where(
        AnalyticsFunnelMetric.event_id == event_id,
        AnalyticsFunnelMetric.funnel_code == funnel_code,
        AnalyticsFunnelMetric.step_code == step_code,
        AnalyticsFunnelMetric.metric_date >= period_start,
        AnalyticsFunnelMetric.metric_date <= period_end,
    )
    return (await db.execute(stmt)).all()


async def _funnel_metric(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    funnel_code: str,
    step_code: str,
    period_start: date,
    period_end: date,
) -> Metric:
    rows = await _funnel_step_rows(
        db,
        event_id=event_id,
        funnel_code=funnel_code,
        step_code=step_code,
        period_start=period_start,
        period_end=period_end,
    )
    return _metric_from_period_rows(rows, "actor_count")


async def _daily_series(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    metric_code: str,
    period_start: date,
    period_end: date,
) -> list[DailyCount]:
    """Per-day trend for ``metric_code``, dropping (not zeroing) any day whose
    row is suppressed - see ``suppression.drop_small_groups``'s docstring for
    why a masked day is omitted rather than shown as 0 (0 would be a false,
    fabricated value; omission is the only non-identifying, non-fabricating
    option for a single day's row)."""

    stmt = (
        select(
            AnalyticsDailyMetric.metric_date,
            AnalyticsDailyMetric.event_count,
            AnalyticsDailyMetric.suppressed,
        )
        .where(
            AnalyticsDailyMetric.event_id == event_id,
            AnalyticsDailyMetric.metric_code == metric_code,
            AnalyticsDailyMetric.dimension_code == "ALL",
            AnalyticsDailyMetric.metric_date >= period_start,
            AnalyticsDailyMetric.metric_date <= period_end,
        )
        .order_by(AnalyticsDailyMetric.metric_date)
    )
    rows = (await db.execute(stmt)).all()
    return [
        DailyCount(activity_date=row.metric_date, count=int(row.event_count or 0))
        for row in rows
        if not row.suppressed
    ]


# ---------------------------------------------------------------------------
# Structural headcounts (see module docstring point 2 - not interaction events)
# ---------------------------------------------------------------------------


async def _count_registered_users(db: AsyncSession, *, event_id: uuid.UUID) -> int:
    stmt = (
        select(func.count(func.distinct(UserRole.user_id)))
        .select_from(UserRole)
        .join(Role, Role.role_id == UserRole.role_id)
        .where(
            UserRole.event_id == event_id,
            UserRole.valid_until.is_(None),
            Role.role_code.in_(("VISITOR", "BUYER")),
        )
    )
    return int((await db.execute(stmt)).scalar_one())


async def _profile_confirm_counts(
    db: AsyncSession, *, event_id: uuid.UUID
) -> tuple[int, int]:
    stmt = select(
        func.count(UserProfile.profile_id).filter(
            UserProfile.profile_status == "COMPLETE"
        ),
        func.count(UserProfile.profile_id),
    ).where(
        UserProfile.event_id == event_id,
        UserProfile.user_id.is_not(None),
        UserProfile.deleted_at.is_(None),
    )
    row = (await db.execute(stmt)).one()
    return int(row[0] or 0), int(row[1] or 0)


async def _published_exhibitor_count(db: AsyncSession, *, event_id: uuid.UUID) -> int:
    stmt = (
        select(func.count(func.distinct(Exhibitor.exhibitor_id)))
        .select_from(Exhibitor)
        .join(
            ExhibitorParticipation,
            ExhibitorParticipation.exhibitor_id == Exhibitor.exhibitor_id,
        )
        .where(
            ExhibitorParticipation.event_id == event_id,
            ExhibitorParticipation.participation_status == "APPROVED",
            Exhibitor.master_approval_status == "APPROVED",
            Exhibitor.deleted_at.is_(None),
        )
    )
    return int((await db.execute(stmt)).scalar_one())


async def _published_product_count(db: AsyncSession, *, event_id: uuid.UUID) -> int:
    stmt = select(func.count(EventProduct.event_product_id)).where(
        EventProduct.event_id == event_id,
        EventProduct.approval_status == "APPROVED",
    )
    return int((await db.execute(stmt)).scalar_one())


async def _kiosk_session_stats(
    db: AsyncSession, *, event_id: uuid.UUID, period_start: date, period_end: date
) -> tuple[int, float | None]:
    start = datetime.combine(period_start, time.min, tzinfo=UTC)
    end = datetime.combine(period_end, time.max, tzinfo=UTC)
    duration_seconds = func.extract(
        "epoch", func.coalesce(KioskSession.closed_at, KioskSession.last_activity_at) - KioskSession.created_at
    )
    stmt = select(
        func.count(KioskSession.session_id),
        func.avg(duration_seconds),
    ).where(
        KioskSession.event_id == event_id,
        KioskSession.created_at >= start,
        KioskSession.created_at <= end,
    )
    row = (await db.execute(stmt)).one()
    count = int(row[0] or 0)
    avg_duration = float(row[1]) if row[1] is not None else None
    return count, avg_duration


async def _daily_kiosk_sessions(
    db: AsyncSession, *, event_id: uuid.UUID, period_start: date, period_end: date
) -> list[DailyCount]:
    start = datetime.combine(period_start, time.min, tzinfo=UTC)
    end = datetime.combine(period_end, time.max, tzinfo=UTC)
    day_bucket = func.date(KioskSession.created_at).label("activity_date")
    stmt = (
        select(day_bucket, func.count(KioskSession.session_id))
        .where(
            KioskSession.event_id == event_id,
            KioskSession.created_at >= start,
            KioskSession.created_at <= end,
        )
        .group_by(day_bucket)
        .order_by(day_bucket)
    )
    rows = (await db.execute(stmt)).all()
    return [
        DailyCount(activity_date=activity_date, count=int(count))
        for activity_date, count in rows
        if int(count) >= SMALL_GROUP_SUPPRESSION_THRESHOLD
    ]


async def _qr_handoff_count(
    db: AsyncSession, *, event_id: uuid.UUID, period_start: date, period_end: date
) -> int:
    start = datetime.combine(period_start, time.min, tzinfo=UTC)
    end = datetime.combine(period_end, time.max, tzinfo=UTC)
    stmt = select(func.count(KioskQrHandoff.handoff_id)).where(
        KioskQrHandoff.event_id == event_id,
        KioskQrHandoff.created_at >= start,
        KioskQrHandoff.created_at <= end,
    )
    return int((await db.execute(stmt)).scalar_one())


# ---------------------------------------------------------------------------
# analytics.search_no_result_summary
# ---------------------------------------------------------------------------


async def _no_result_rows(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    period_start: date,
    period_end: date,
    channel_code: str | None = None,
) -> Sequence[object]:
    stmt = select(
        AnalyticsSearchNoResultSummary.channel_code,
        AnalyticsSearchNoResultSummary.query_norm,
        AnalyticsSearchNoResultSummary.occurrence_count,
        AnalyticsSearchNoResultSummary.distinct_actor_count,
        AnalyticsSearchNoResultSummary.suppressed,
        AnalyticsSearchNoResultSummary.last_occurred_at,
    ).where(
        AnalyticsSearchNoResultSummary.event_id == event_id,
        AnalyticsSearchNoResultSummary.summary_date >= period_start,
        AnalyticsSearchNoResultSummary.summary_date <= period_end,
    )
    if channel_code is not None:
        stmt = stmt.where(AnalyticsSearchNoResultSummary.channel_code == channel_code)
    return (await db.execute(stmt)).all()


def _no_result_total_metric(rows: Sequence) -> Metric:
    return _metric_from_period_rows(rows, "occurrence_count")


@dataclass(frozen=True)
class _QueryAggregate:
    channel_code: str
    query_norm: str
    occurrence_count: int
    distinct_actor_count: int
    last_occurred_at: datetime | None


def _aggregate_no_result_queries(rows: Sequence) -> list[_QueryAggregate]:
    """Group per-day ``search_no_result_summary`` rows by (channel, query) across
    the requested period. A group with *any* suppressed day is dropped entirely
    (not partially summed) - see ``suppression.drop_small_groups``'s rationale:
    for a list of query strings, the query text itself is the re-identifying
    signal, so there is no safe masked placeholder to show in its stead."""

    groups: dict[tuple[str, str], list] = defaultdict(list)
    for row in rows:
        groups[(row.channel_code, row.query_norm)].append(row)

    aggregated: list[_QueryAggregate] = []
    for (channel_code, query_norm), grouped in groups.items():
        if any(r.suppressed for r in grouped):
            continue
        occurrence_total = sum(r.occurrence_count or 0 for r in grouped)
        actor_total = sum(r.distinct_actor_count or 0 for r in grouped)
        last_seen = max(
            (r.last_occurred_at for r in grouped if r.last_occurred_at is not None),
            default=None,
        )
        aggregated.append(
            _QueryAggregate(
                channel_code=channel_code,
                query_norm=query_norm,
                occurrence_count=occurrence_total,
                distinct_actor_count=actor_total,
                last_occurred_at=last_seen,
            )
        )

    # Re-derived counts summed across days can still fall under the threshold
    # even when no single day was suppressed - apply the row-level rule again.
    return drop_small_groups(
        aggregated,
        underlying_count_of=lambda item: item.distinct_actor_count,
    )


# ---------------------------------------------------------------------------
# analytics.data_quality_snapshot
# ---------------------------------------------------------------------------


_STATUS_SEVERITY = {"OK": 0, "WARN": 1, "FAIL": 2}


async def get_data_quality(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    period_start: date,
    period_end: date,
    role: AnalyticsRole,
) -> DataQualityAnalyticsResponse:
    stmt = (
        select(
            AnalyticsDataQualitySnapshot.check_code,
            AnalyticsDataQualitySnapshot.status,
            AnalyticsDataQualitySnapshot.metric_value,
            AnalyticsDataQualitySnapshot.threshold_value,
            AnalyticsDataQualitySnapshot.affected_count,
        )
        .where(
            AnalyticsDataQualitySnapshot.event_id == event_id,
            AnalyticsDataQualitySnapshot.snapshot_date >= period_start,
            AnalyticsDataQualitySnapshot.snapshot_date <= period_end,
        )
        .order_by(AnalyticsDataQualitySnapshot.check_code)
    )
    rows = (await db.execute(stmt)).all()

    checks = [
        DataQualityCheckSummary(
            check_code=row.check_code,
            status=row.status,
            metric_value=float(row.metric_value) if row.metric_value is not None else None,
            threshold_value=float(row.threshold_value) if row.threshold_value is not None else None,
            affected_count=row.affected_count,
        )
        for row in rows
    ]
    overall_status = "OK"
    for check in checks:
        if _STATUS_SEVERITY[check.status] > _STATUS_SEVERITY[overall_status]:
            overall_status = check.status

    return DataQualityAnalyticsResponse(
        event_id=event_id,
        period_start=period_start,
        period_end=period_end,
        role=role,
        overall_status=overall_status,
        checks=checks,
    )


# ---------------------------------------------------------------------------
# GET /admin/analytics/overview
# ---------------------------------------------------------------------------


async def get_overview(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    period_start: date,
    period_end: date,
    role: AnalyticsRole,
) -> OverviewAnalyticsResponse:
    registered_users_count = await _count_registered_users(db, event_id=event_id)
    profile_complete, profile_total = await _profile_confirm_counts(db, event_id=event_id)
    published_exhibitors = await _published_exhibitor_count(db, event_id=event_id)
    published_products = await _published_product_count(db, event_id=event_id)
    kiosk_session_count, _ = await _kiosk_session_stats(
        db, event_id=event_id, period_start=period_start, period_end=period_end
    )

    # RECOMMENDATION_IMPRESSION is a web-personalization-only concept
    # (PROJECT_SCOPE.md: kiosk search is anonymous, not personalized) so the WEB
    # funnel's actor_count for it is used as the "web active users" proxy - the
    # closest available approximation to "distinct users who did anything on
    # the web module" given the landed tables (see module docstring point 2).
    web_active_users = await _funnel_metric(
        db,
        event_id=event_id,
        funnel_code="WEB",
        step_code="RECOMMENDATION_IMPRESSION",
        period_start=period_start,
        period_end=period_end,
    )
    recommendation_impression = await _daily_metric(
        db, event_id=event_id, metric_code="RECOMMENDATION_IMPRESSION",
        period_start=period_start, period_end=period_end,
    )
    recommendation_click = await _daily_metric(
        db, event_id=event_id, metric_code="RECOMMENDATION_CLICK",
        period_start=period_start, period_end=period_end,
    )
    favorites_saved = await _daily_metric(
        db, event_id=event_id, metric_code="FAVORITE_SAVE",
        period_start=period_start, period_end=period_end,
    )
    meeting_requests = await _daily_metric(
        db, event_id=event_id, metric_code="MEETING_REQUEST",
        period_start=period_start, period_end=period_end,
    )
    meeting_accepts = await _daily_metric(
        db, event_id=event_id, metric_code="MEETING_ACCEPT",
        period_start=period_start, period_end=period_end,
    )
    # KIOSK QUERY_SUBMIT is the only landed proxy for search volume - see
    # get_search_insights's docstring for why WEB search volume is unavailable.
    total_searches = await _funnel_metric(
        db, event_id=event_id, funnel_code="KIOSK", step_code="QUERY_SUBMIT",
        period_start=period_start, period_end=period_end,
    )
    no_result_rows = await _no_result_rows(
        db, event_id=event_id, period_start=period_start, period_end=period_end
    )
    buyer_matches = await _funnel_metric(
        db, event_id=event_id, funnel_code="BUYER", step_code="MATCH_GENERATE",
        period_start=period_start, period_end=period_end,
    )

    return OverviewAnalyticsResponse(
        event_id=event_id,
        period_start=period_start,
        period_end=period_end,
        role=role,
        registered_users=suppress_metric(registered_users_count, registered_users_count),
        profile_confirm_rate=suppress_rate(
            profile_complete, profile_complete, profile_total, profile_total
        ),
        web_active_users=web_active_users,
        kiosk_sessions=suppress_metric(kiosk_session_count, kiosk_session_count),
        total_searches=total_searches,
        no_result_rate=combine_rate(_no_result_total_metric(no_result_rows), total_searches),
        recommendation_click_rate=combine_rate(recommendation_click, recommendation_impression),
        favorites_saved=favorites_saved,
        buyer_matches=buyer_matches,
        meeting_requests=meeting_requests,
        meeting_accepts=meeting_accepts,
        # Counts of businesses/products, not people - the small-group
        # suppression rule (AGENTS.md: "fewer than 5 underlying users") does
        # not apply to these.
        published_exhibitor_count=Metric(value=float(published_exhibitors), suppressed=False),
        published_product_count=Metric(value=float(published_products), suppressed=False),
    )


# ---------------------------------------------------------------------------
# GET /admin/analytics/web
# ---------------------------------------------------------------------------


async def get_web_analytics(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    period_start: date,
    period_end: date,
    role: AnalyticsRole,
) -> WebAnalyticsResponse:
    active_users = await _funnel_metric(
        db, event_id=event_id, funnel_code="WEB", step_code="RECOMMENDATION_IMPRESSION",
        period_start=period_start, period_end=period_end,
    )
    impressions = await _daily_metric(
        db, event_id=event_id, metric_code="RECOMMENDATION_IMPRESSION",
        period_start=period_start, period_end=period_end,
    )
    clicks = await _daily_metric(
        db, event_id=event_id, metric_code="RECOMMENDATION_CLICK",
        period_start=period_start, period_end=period_end,
    )
    favorites = await _daily_metric(
        db, event_id=event_id, metric_code="FAVORITE_SAVE",
        period_start=period_start, period_end=period_end,
    )
    daily_active_users = await _daily_series(
        db, event_id=event_id, metric_code="RECOMMENDATION_IMPRESSION",
        period_start=period_start, period_end=period_end,
    )

    return WebAnalyticsResponse(
        event_id=event_id,
        period_start=period_start,
        period_end=period_end,
        role=role,
        active_users=active_users,
        # No session concept exists for the web module in the landed tables
        # (sessions are a kiosk.kiosk_session-only concept today) - reuse the
        # active-user figure rather than fabricate a distinct session count.
        sessions=active_users,
        avg_session_duration_seconds=_UNAVAILABLE,
        recommendation_impressions=impressions,
        recommendation_clicks=clicks,
        recommendation_click_rate=combine_rate(clicks, impressions),
        favorites_saved=favorites,
        daily_active_users=daily_active_users,
    )


# ---------------------------------------------------------------------------
# GET /admin/analytics/kiosk
# ---------------------------------------------------------------------------


async def get_kiosk_analytics(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    period_start: date,
    period_end: date,
    role: AnalyticsRole,
) -> KioskAnalyticsResponse:
    session_count, avg_duration = await _kiosk_session_stats(
        db, event_id=event_id, period_start=period_start, period_end=period_end
    )
    qr_handoffs = await _qr_handoff_count(
        db, event_id=event_id, period_start=period_start, period_end=period_end
    )
    searches = await _funnel_metric(
        db, event_id=event_id, funnel_code="KIOSK", step_code="QUERY_SUBMIT",
        period_start=period_start, period_end=period_end,
    )
    no_result_rows = await _no_result_rows(
        db, event_id=event_id, period_start=period_start, period_end=period_end,
        channel_code="KIOSK",
    )
    daily_sessions = await _daily_kiosk_sessions(
        db, event_id=event_id, period_start=period_start, period_end=period_end
    )

    return KioskAnalyticsResponse(
        event_id=event_id,
        period_start=period_start,
        period_end=period_end,
        role=role,
        sessions=suppress_metric(session_count, session_count),
        avg_session_duration_seconds=(
            Metric(value=avg_duration, suppressed=False)
            if session_count >= SMALL_GROUP_SUPPRESSION_THRESHOLD
            else Metric(value=None, suppressed=session_count > 0)
        ),
        qr_handoffs=suppress_metric(qr_handoffs, qr_handoffs),
        searches=searches,
        zero_result_rate=combine_rate(_no_result_total_metric(no_result_rows), searches),
        daily_sessions=daily_sessions,
    )


# ---------------------------------------------------------------------------
# GET /admin/analytics/buyer
# ---------------------------------------------------------------------------


async def get_buyer_analytics(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    period_start: date,
    period_end: date,
    role: AnalyticsRole,
    exhibitor_id: uuid.UUID | None,
) -> BuyerAnalyticsResponse:
    """``exhibitor_id`` must already be the server-resolved scope for
    EXHIBITOR_ADMIN (see ``app/services/analytics/access.py`` -
    ``AnalyticsAccessContext.exhibitor_id`` is never taken from client input
    for that role) or an EVENT_ADMIN-chosen filter. See this module's
    docstring / ``app/schemas/analytics.py`` gap (1): an exhibitor-scoped
    request cannot be computed from the landed tables today, so it is masked
    rather than silently widened to the event-wide total.
    """

    if exhibitor_id is not None:
        return BuyerAnalyticsResponse(
            event_id=event_id,
            period_start=period_start,
            period_end=period_end,
            role=role,
            exhibitor_id=exhibitor_id,
            breakdown=[],
            **_MASKED_EXHIBITOR_BUYER_METRICS,
        )

    buyer_matches = await _funnel_metric(
        db, event_id=event_id, funnel_code="BUYER", step_code="MATCH_GENERATE",
        period_start=period_start, period_end=period_end,
    )
    meeting_requests = await _daily_metric(
        db, event_id=event_id, metric_code="MEETING_REQUEST",
        period_start=period_start, period_end=period_end,
    )
    meeting_accepts = await _daily_metric(
        db, event_id=event_id, metric_code="MEETING_ACCEPT",
        period_start=period_start, period_end=period_end,
    )
    meeting_completions = await _daily_metric(
        db, event_id=event_id, metric_code="MEETING_COMPLETE",
        period_start=period_start, period_end=period_end,
    )

    return BuyerAnalyticsResponse(
        event_id=event_id,
        period_start=period_start,
        period_end=period_end,
        role=role,
        exhibitor_id=None,
        buyer_matches=buyer_matches,
        meeting_requests=meeting_requests,
        meeting_accepts=meeting_accepts,
        meeting_completions=meeting_completions,
        # No "valid lead" concept is emitted anywhere in the aggregate tables
        # (no LEAD/valid-lead metric_code exists in
        # analytics_aggregation.DEFAULT_DAILY_METRIC_DEFINITIONS) - masked
        # rather than fabricated, per this module's docstring point (2).
        valid_leads=_UNAVAILABLE,
        meeting_accept_rate=combine_rate(meeting_accepts, meeting_requests),
        meeting_completion_rate=combine_rate(meeting_completions, meeting_accepts),
        valid_lead_rate=_UNAVAILABLE,
        # See app/schemas/analytics.py gap (1) - no exhibitor dimension exists
        # in the landed tables yet, so a per-exhibitor breakdown can never be
        # populated today regardless of role.
        breakdown=[],
    )


# ---------------------------------------------------------------------------
# GET /admin/analytics/searches
# ---------------------------------------------------------------------------


async def get_search_analytics_summary(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    period_start: date,
    period_end: date,
    role: AnalyticsRole,
    top_queries_limit: int = 10,
) -> SearchAnalyticsSummary:
    total_searches = await _funnel_metric(
        db, event_id=event_id, funnel_code="KIOSK", step_code="QUERY_SUBMIT",
        period_start=period_start, period_end=period_end,
    )
    no_result_rows = await _no_result_rows(
        db, event_id=event_id, period_start=period_start, period_end=period_end
    )
    zero_result_rate = combine_rate(_no_result_total_metric(no_result_rows), total_searches)

    # Only zero-result queries are tracked anywhere in the landed tables (see
    # this function's docstring on SearchInsightsResponse for the full gap) -
    # "top_queries" here means "top no-result queries", the best available
    # proxy, not general query popularity.
    aggregated = _aggregate_no_result_queries(no_result_rows)
    aggregated.sort(key=lambda item: item.occurrence_count, reverse=True)
    top_queries = [
        TopQueryItem(query=redact_query_text(item.query_norm), count=item.occurrence_count)
        for item in aggregated[:top_queries_limit]
    ]

    period_start_dt = datetime.combine(period_start, time.min, tzinfo=UTC)
    period_end_dt = datetime.combine(period_end, time.max, tzinfo=UTC)

    return SearchAnalyticsSummary(
        event_id=event_id,
        period_start=period_start_dt,
        period_end=period_end_dt,
        total_searches=int(total_searches.value or 0) if not total_searches.suppressed else 0,
        zero_result_rate=zero_result_rate.value if not zero_result_rate.suppressed else 0.0,
        top_queries=top_queries,
        role=role,
    )


async def get_search_insights(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    period_start: date,
    period_end: date,
    role: AnalyticsRole,
) -> SearchInsightsResponse:
    """Extended search analytics. Two KPIs from this track's prompt have **no
    data source anywhere in the landed tables** and are always returned
    empty, not fabricated:

    - ``top_interest_codes``: no ontology concept-code dimension exists on
      ``analytics.search_no_result_summary`` or ``analytics.daily_metric``.
    - ``low_click_queries``: no click-through-by-query data exists anywhere
      (``search_no_result_summary`` only carries zero-result occurrence
      counts, never a click count for a query that *did* return results).

    ``daily_volume`` and the ``KIOSK`` row of ``channel_performance`` use the
    KIOSK funnel's ``QUERY_SUBMIT`` step as the search-volume source. There is
    no WEB-channel equivalent (``WEB_FUNNEL_STEPS`` has no search/query-submit
    step - the web module's NL search, if any, is not currently instrumented
    as an interaction event at all), so the ``WEB`` row's
    ``total_searches``/``zero_result_rate`` are masked
    (``suppressed=True``) rather than showing a false zero.
    """

    daily_volume = await _daily_kiosk_query_volume(
        db, event_id=event_id, period_start=period_start, period_end=period_end
    )

    kiosk_searches = await _funnel_metric(
        db, event_id=event_id, funnel_code="KIOSK", step_code="QUERY_SUBMIT",
        period_start=period_start, period_end=period_end,
    )
    kiosk_no_result_rows = await _no_result_rows(
        db, event_id=event_id, period_start=period_start, period_end=period_end,
        channel_code="KIOSK",
    )
    kiosk_zero_rate = combine_rate(_no_result_total_metric(kiosk_no_result_rows), kiosk_searches)

    web_clicks = await _daily_metric(
        db, event_id=event_id, metric_code="RECOMMENDATION_CLICK",
        period_start=period_start, period_end=period_end,
    )
    web_impressions = await _daily_metric(
        db, event_id=event_id, metric_code="RECOMMENDATION_IMPRESSION",
        period_start=period_start, period_end=period_end,
    )

    channel_performance = [
        ChannelSearchPerformance(
            channel="WEB",
            total_searches=_UNAVAILABLE,
            zero_result_rate=_UNAVAILABLE,
            recommendation_click_rate=combine_rate(web_clicks, web_impressions),
        ),
        ChannelSearchPerformance(
            channel="KIOSK",
            total_searches=kiosk_searches,
            zero_result_rate=kiosk_zero_rate,
            recommendation_click_rate=None,
        ),
    ]

    return SearchInsightsResponse(
        event_id=event_id,
        period_start=datetime.combine(period_start, time.min, tzinfo=UTC),
        period_end=datetime.combine(period_end, time.max, tzinfo=UTC),
        role=role,
        daily_volume=daily_volume,
        top_interest_codes=[],
        low_click_queries=[],
        channel_performance=channel_performance,
    )


async def _daily_kiosk_query_volume(
    db: AsyncSession, *, event_id: uuid.UUID, period_start: date, period_end: date
) -> list[DailyCount]:
    stmt = (
        select(
            AnalyticsFunnelMetric.metric_date,
            AnalyticsFunnelMetric.actor_count,
            AnalyticsFunnelMetric.suppressed,
        )
        .where(
            AnalyticsFunnelMetric.event_id == event_id,
            AnalyticsFunnelMetric.funnel_code == "KIOSK",
            AnalyticsFunnelMetric.step_code == "QUERY_SUBMIT",
            AnalyticsFunnelMetric.metric_date >= period_start,
            AnalyticsFunnelMetric.metric_date <= period_end,
        )
        .order_by(AnalyticsFunnelMetric.metric_date)
    )
    rows = (await db.execute(stmt)).all()
    return [
        DailyCount(activity_date=row.metric_date, count=int(row.actor_count or 0))
        for row in rows
        if not row.suppressed
    ]


# ---------------------------------------------------------------------------
# GET /admin/analytics/no-results
# ---------------------------------------------------------------------------


async def get_no_result_queries(
    db: AsyncSession,
    *,
    event_id: uuid.UUID,
    period_start: date,
    period_end: date,
    limit: int = 50,
) -> NoResultQueryResponse:
    rows = await _no_result_rows(
        db, event_id=event_id, period_start=period_start, period_end=period_end
    )
    aggregated = _aggregate_no_result_queries(rows)
    aggregated.sort(key=lambda item: item.occurrence_count, reverse=True)

    items = [
        NoResultQueryItem(
            query=redact_query_text(item.query_norm),
            count=item.occurrence_count,
            last_seen_at=item.last_occurred_at or datetime.now(UTC),
        )
        for item in aggregated[:limit]
    ]
    return NoResultQueryResponse(items=items)
