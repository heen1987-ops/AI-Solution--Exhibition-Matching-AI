"""BACKEND-ANALYTICS (WAVE 2E) response/query schemas for ``/admin/analytics/*``.

Reconciliation note (read before editing) - UPDATED after WORKER-ANALYTICS landed
-----------------------------------------------------------------------------------
An earlier draft of this module was written before WORKER-ANALYTICS's tables existed
and queried a *provisional* shape (``app/services/analytics/tables.py``, now removed)
modelled after ``docs/db-erd-table-spec.md`` §20.3 (fact_recommendation/fact_meeting/
dim_exhibitor). WORKER-ANALYTICS has since landed the real tables in
``app/models/analytics.py`` + ``apps/api/alembic/versions/20260802_0017_analytics_aggregation.py``:
``analytics.daily_metric``, ``analytics.funnel_metric``,
``analytics.search_no_result_summary``, ``analytics.data_quality_snapshot`` - a
materially different shape (interaction-event-derived metric/funnel rows, not the
fact/dim star schema the provisional draft assumed). ``app/services/analytics/queries.py``
now queries these real tables directly (imported as ORM classes from
``app.models.analytics`` - this track does not own that file or its migration per
``.harness/locks.yaml``/the WAVE 2E prompt, but importing an already-landed model for a
read-only ``SELECT`` is not "owning" it).

Two genuine, documented gaps fell out of this reconciliation (Blocker Score: real but
reversible, no privilege-escalation risk, and the safe default is to mask/omit rather
than fabricate - see AGENTS.md "AI must never assert a value the source text does not
contain"):

1. **No per-exhibitor breakdown dimension exists in the landed tables.**
   ``analytics.daily_metric.dimension_code`` exists as a column but WORKER-ANALYTICS's
   actual ``aggregate_daily_metrics``/``aggregate_funnel_metrics`` implementation
   (``apps/worker/app/jobs/analytics_aggregation.py``) never populates it with an
   exhibitor id - every row is written with ``dimension_code="ALL"``. So an
   exhibitor-scoped buyer-analytics request (``EXHIBITOR_ADMIN``, or ``EVENT_ADMIN``
   with an ``exhibitor_id`` filter) has **no real per-exhibitor number to
   return** from these tables today. Silently substituting the *event-wide* total under
   an exhibitor's name would be worse than not implementing this at all (it would look
   exhibitor-specific while actually leaking/misrepresenting the whole event's
   aggregate, and would violate this track's own "EXHIBITOR_ADMIN must not see
   competitor detail" requirement in spirit even though no single competitor's number
   is named). ``app/services/analytics/queries.py`` therefore returns every ``Metric``
   in an exhibitor-scoped ``BuyerAnalyticsResponse`` as masked (``value=None,
   suppressed=True``) and ``breakdown`` always empty, regardless of role. This is a
   real product gap for WORKER-ANALYTICS to close (add an exhibitor dimension to the
   daily/funnel tables or a dedicated per-exhibitor table), not a bug in this router.
2. **``Metric.suppressed`` is reused for "not available from any landed table"**, not
   only for the small-group-suppression rule it was originally documented for. The
   response schema has no third "unavailable" state, and inventing one now would be a
   breaking contract change outside a single track's authority mid-wave. Reusing the
   existing masked representation is the safer of the two options available (never
   fabricate a number) and is called out explicitly at every call site in
   ``queries.py`` that does this (``valid_leads``, ``low_click_queries``,
   ``top_interest_codes``, the ``WEB`` row's ``total_searches``/``zero_result_rate`` in
   ``channel_performance``, etc. - see that module's docstring for the full list).

``DataQualityAnalyticsResponse``/``DataQualityIssueSummary`` below were also reshaped
in this pass: the earlier draft assumed a ``quality.data_quality_issue`` rollup table
that does not exist anywhere in this repository (no ``SCHEMA_QUALITY``-scoped ORM model
was ever created by any track). The only landed data-quality source is
``analytics.data_quality_snapshot`` (WORKER-ANALYTICS's pipeline-health checks -
ingestion latency, late-arrival rate, duplicate rate, subject-unknown rate, suppressed-
metric ratio), so the response now mirrors that table's actual shape instead.

Role model reconciliation note
-------------------------------
WAVE 2E specified four analytics roles: EVENT_ADMIN, ANALYST, DATA_REVIEWER,
EXHIBITOR_ADMIN. Two role vocabularies exist in the unified repo and neither
of them has an ANALYST:

* ``profile.role.role_code`` (``app/models/identity.py``) - the legacy
  operational vocabulary, five values: VISITOR, BUYER, EXHIBITOR, OPERATOR,
  ADMIN. ``app/services/analytics/access.py`` derives the analytics roles
  from it (ADMIN/OPERATOR => may act as EVENT_ADMIN or DATA_REVIEWER;
  EXHIBITOR => may only act as EXHIBITOR_ADMIN, scoped server-side to their
  own ``exhibitor_id`` from ``profile.user_role`` - never from client input).
* ``auth.role_grant.role`` (``app/models/auth.py``) - the authenticated
  authorization vocabulary that ``require_roles`` reads, whose
  ``auth_role_grant_role_allowed`` CHECK admits exactly EVENT_ADMIN,
  DATA_REVIEWER and EXHIBITOR_ADMIN.

At integration (merge plan STEP 23) ANALYST was therefore collapsed onto
DATA_REVIEWER rather than widening that CHECK: ANALYST's only reach beyond
DATA_REVIEWER (overview/web/kiosk) is already covered by EVENT_ADMIN, so
nothing an operator could see before is unreachable now.

An optional ``X-Analytics-Role`` header lets a staff caller request a
narrower view than their DB role would allow (defense in depth / least
privilege by choice); it can never grant a view the DB role does not already
permit. See ``app/services/analytics/access.py``'s module docstring for the
full mapping table.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, Field

#: The analytics-facing role vocabulary. Deliberately identical to
#: ``auth.role_grant.role``'s ``auth_role_grant_role_allowed`` CHECK
#: (``app/models/auth.py``) so no analytics view can name a role the real
#: authorization substrate cannot grant. WAVE 2E's fourth role, ANALYST, was
#: collapsed onto DATA_REVIEWER at integration - see
#: ``app/services/analytics/access.py``'s module docstring for why that loses
#: no reach.
AnalyticsRole = Literal["EVENT_ADMIN", "DATA_REVIEWER", "EXHIBITOR_ADMIN"]

ANALYTICS_ROLES: tuple[AnalyticsRole, ...] = (
    "EVENT_ADMIN",
    "DATA_REVIEWER",
    "EXHIBITOR_ADMIN",
)

#: docs/db-erd-table-spec.md's small-group/minority-group suppression rule,
#: enforced server-side (never trusted to the client) in
#: app/services/analytics/suppression.py.
SMALL_GROUP_SUPPRESSION_THRESHOLD = 5


class Metric(BaseModel):
    """A single suppressible aggregate figure.

    ``value`` is ``None`` and ``suppressed`` is ``True`` when the underlying
    distinct-user (or distinct-session) count backing this figure is below
    ``SMALL_GROUP_SUPPRESSION_THRESHOLD`` - the figure is masked rather than
    shown as an exact (re-identifying) number. A true zero (no underlying
    activity at all) is never suppressed; suppression only hides *small but
    nonzero* groups.
    """

    value: float | None
    suppressed: bool = False


class TopQueryItem(BaseModel):
    """Matches ``apps/admin/lib/types.ts``' ``SearchAnalyticsSummary.top_queries``
    item shape exactly (``{query, count}``) so the already-written admin
    dashboard call (``getSearchAnalytics``) works without a frontend change."""

    query: str
    count: int


class SearchAnalyticsSummary(BaseModel):
    """``GET /admin/analytics/searches`` response.

    Field-for-field match of ``apps/admin/lib/types.ts``'
    ``SearchAnalyticsSummary`` (the admin dashboard already calls this
    endpoint and expects exactly this shape - see
    ``apps/admin/app/dashboard/page.tsx``).
    """

    event_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    total_searches: int
    zero_result_rate: float
    top_queries: list[TopQueryItem] = Field(default_factory=list)
    role: AnalyticsRole


class NoResultQueryItem(BaseModel):
    """Matches ``apps/admin/lib/types.ts``' ``NoResultQueryItem`` exactly."""

    query: str
    count: int
    last_seen_at: datetime


class NoResultQueryResponse(BaseModel):
    """``GET /admin/analytics/no-results`` response - matches
    ``apps/admin/lib/types.ts``' ``NoResultQueryResponse`` exactly."""

    items: list[NoResultQueryItem] = Field(default_factory=list)


class LowClickQueryItem(BaseModel):
    """A search term that returns results but is rarely clicked through -
    distinct from a zero-result query, useful for ranking/UX review."""

    query: str
    search_count: int
    click_count: int
    click_through_rate: float
    last_seen_at: datetime


class ChannelSearchPerformance(BaseModel):
    channel: Literal["WEB", "KIOSK"]
    total_searches: Metric
    zero_result_rate: Metric
    recommendation_click_rate: Metric | None = None


class TopInterestCodeItem(BaseModel):
    concept_code: str
    search_count: int


class DailyCount(BaseModel):
    activity_date: date
    count: int


class SearchInsightsResponse(BaseModel):
    """Extended search analytics beyond the admin dashboard's minimal
    ``SearchAnalyticsSummary`` card: volume trend, top interest codes,
    low-click queries, per-channel performance. Returned by the same
    ``GET /admin/analytics/searches`` call via the ``detail=full`` query
    flag so the existing minimal contract stays the default/backward
    compatible response.
    """

    event_id: uuid.UUID
    period_start: datetime
    period_end: datetime
    role: AnalyticsRole
    daily_volume: list[DailyCount] = Field(default_factory=list)
    top_interest_codes: list[TopInterestCodeItem] = Field(default_factory=list)
    low_click_queries: list[LowClickQueryItem] = Field(default_factory=list)
    channel_performance: list[ChannelSearchPerformance] = Field(default_factory=list)


class OverviewAnalyticsResponse(BaseModel):
    """``GET /admin/analytics/overview`` - the KPI list from this track's
    prompt: registered users, profile-confirm rate, web active users, kiosk
    sessions, total searches, no-result rate, recommendation click rate,
    favorites saved, buyer matches, meeting requests/accepts, published
    exhibitor/product counts."""

    event_id: uuid.UUID
    period_start: date
    period_end: date
    role: AnalyticsRole

    registered_users: Metric
    profile_confirm_rate: Metric
    web_active_users: Metric
    kiosk_sessions: Metric
    total_searches: Metric
    no_result_rate: Metric
    recommendation_click_rate: Metric
    favorites_saved: Metric
    buyer_matches: Metric
    meeting_requests: Metric
    meeting_accepts: Metric
    published_exhibitor_count: Metric
    published_product_count: Metric


class WebAnalyticsResponse(BaseModel):
    """``GET /admin/analytics/web`` - pre-registered web personalization
    module engagement."""

    event_id: uuid.UUID
    period_start: date
    period_end: date
    role: AnalyticsRole

    active_users: Metric
    sessions: Metric
    avg_session_duration_seconds: Metric
    recommendation_impressions: Metric
    recommendation_clicks: Metric
    recommendation_click_rate: Metric
    favorites_saved: Metric
    daily_active_users: list[DailyCount] = Field(default_factory=list)


class KioskAnalyticsResponse(BaseModel):
    """``GET /admin/analytics/kiosk`` - anonymous kiosk module usage."""

    event_id: uuid.UUID
    period_start: date
    period_end: date
    role: AnalyticsRole

    sessions: Metric
    avg_session_duration_seconds: Metric
    qr_handoffs: Metric
    searches: Metric
    zero_result_rate: Metric
    daily_sessions: list[DailyCount] = Field(default_factory=list)


class ExhibitorBuyerMatchRow(BaseModel):
    """One exhibitor's row in the buyer-match breakdown. Only ever returned
    to EVENT_ADMIN (never DATA_REVIEWER/EXHIBITOR_ADMIN - see
    ``app/services/analytics/access.py``), and each row is independently
    small-group-suppressed so a single exhibitor with <5 underlying buyers
    never has its exact count exposed even inside an event-wide list."""

    exhibitor_id: uuid.UUID
    buyer_matches: Metric
    meeting_requests: Metric
    meeting_accepts: Metric


class BuyerAnalyticsResponse(BaseModel):
    """``GET /admin/analytics/buyer``.

    - EVENT_ADMIN with no ``exhibitor_id`` filter: event-wide totals plus a
      per-exhibitor ``breakdown`` (each row suppressed independently).
    - EVENT_ADMIN with an ``exhibitor_id`` filter, or EXHIBITOR_ADMIN
      (always, using their own server-resolved exhibitor_id - see
      ``app/services/analytics/access.py`` for why a client-supplied
      exhibitor_id can never widen an EXHIBITOR_ADMIN's own scope): totals
      scoped to that one exhibitor, ``breakdown`` always empty. Per this
      module's "Reconciliation note" gap (1), the landed aggregate tables
      have no per-exhibitor dimension at all yet, so every ``Metric`` here is
      currently returned masked (``suppressed=True``) rather than showing the
      event-wide total under one exhibitor's name.
    (DATA_REVIEWER never reaches this endpoint at all - see
    ``ENDPOINT_ALLOWED_ROLES``.)

    Never includes anything at per-buyer granularity - see this track's
    prompt: "must never expose an individual buyer's specific
    match/order-scale data in a general analytics response".
    """

    event_id: uuid.UUID
    period_start: date
    period_end: date
    role: AnalyticsRole
    exhibitor_id: uuid.UUID | None = None

    buyer_matches: Metric
    meeting_requests: Metric
    meeting_accepts: Metric
    meeting_completions: Metric
    valid_leads: Metric
    meeting_accept_rate: Metric
    meeting_completion_rate: Metric
    valid_lead_rate: Metric
    breakdown: list[ExhibitorBuyerMatchRow] = Field(default_factory=list)


DataQualityStatus = Literal["OK", "WARN", "FAIL"]


class DataQualityCheckSummary(BaseModel):
    """One row of ``analytics.data_quality_snapshot`` (see
    ``apps/worker/app/jobs/data_quality.py`` for the check catalog -
    ``INGESTION_LATENCY_P95_SECONDS``, ``LATE_ARRIVAL_RATE``,
    ``DUPLICATE_CLIENT_EVENT_RATE``, ``SUBJECT_UNKNOWN_RATE``,
    ``SUPPRESSED_METRIC_RATIO``). Never subject to small-group suppression -
    these are pipeline-wide ratios, not per-person/small-group statistics
    (see that table's ORM docstring)."""

    check_code: str
    status: DataQualityStatus
    metric_value: float | None
    threshold_value: float | None
    affected_count: int | None


class DataQualityAnalyticsResponse(BaseModel):
    """``GET /admin/analytics/data-quality`` - rollup of
    ``analytics.data_quality_snapshot`` (the only data-quality source that has
    actually landed in this repo - see this module's "Reconciliation note" for
    why this replaced an earlier draft that assumed a nonexistent
    ``quality.data_quality_issue`` table)."""

    event_id: uuid.UUID
    period_start: date
    period_end: date
    role: AnalyticsRole

    #: Worst status across all checks in the period (FAIL > WARN > OK), or
    #: "OK" when no snapshot rows exist yet for the period (nothing observed
    #: is not evidence of a problem).
    overall_status: DataQualityStatus
    checks: list[DataQualityCheckSummary] = Field(default_factory=list)
