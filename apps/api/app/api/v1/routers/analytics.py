"""Role-scoped analytics read API. Track: BACKEND-ANALYTICS (WAVE 2E).

Exposes ``GET /admin/analytics/{overview,web,kiosk,buyer,searches,no-results,
data-quality}``. This file does not touch ``app/api/v1/api.py`` (the shared
router aggregator); it exposes ``build_analytics_router()`` so the integrator
can::

    from app.api.v1.routers.analytics import build_analytics_router
    api_router.include_router(build_analytics_router(), tags=["analytics"])

This router owns no persistence logic itself - every endpoint is a thin
composition of ``app/services/analytics/access.py`` (role resolution/
authorization) and ``app/services/analytics/queries.py`` (the read-only query
layer against the ``analytics.*`` aggregate tables + a small set of read-only
operational headcount tables - see that module's docstring for exactly which
tables and why).

Authentication and authorization (integration, merge plan STEP 23)
--------------------------------------------------------------------
The WAVE 2E original identified the caller from a client-supplied actor-id header. That is
gone, and no header on this router may ever identify anybody again. Two independent gates
now apply to every route here:

1. ``require_roles("EVENT_ADMIN", "DATA_REVIEWER", "EXHIBITOR_ADMIN")`` is a
   router-level dependency, so an unauthenticated call fails 401 before any
   handler body runs, and an authenticated caller holding none of those
   ``auth.role_grant`` rows fails 403. EVENT_ADMIN and DATA_REVIEWER are in
   ``PRIVILEGED_ADMIN_ROLES``, so reaching an operator analytics view over a
   browser session additionally requires AAL2 (MFA) - see
   ``app/core/auth.py``.
2. ``app/services/analytics/access.py`` then answers the domain question
   against the legacy ``profile.user_role``/``profile.role`` tables: which
   analytics role may this actor act as for this event, and may that role
   call this endpoint. Its optional ``X-Analytics-Role`` header can only ever
   *narrow* the DB-derived permitted set.

The actor id itself comes from ``app/core/router_auth.py``'s
``get_actor_user_id``, i.e. from a verified session/JWT principal only.

k-anonymity: every number these endpoints return has already been passed
through ``app/services/analytics/suppression.py``; any aggregate covering
fewer than ``SMALL_GROUP_SUPPRESSION_THRESHOLD`` (5) users is returned as
``Metric(value=None, suppressed=True)`` or dropped from a breakdown list
entirely. This router must never reconstruct or bypass that.
"""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import require_roles
from app.core.router_auth import get_actor_user_id
from app.db.session import get_db
from app.schemas.analytics import (
    AnalyticsRole,
    BuyerAnalyticsResponse,
    DataQualityAnalyticsResponse,
    KioskAnalyticsResponse,
    NoResultQueryResponse,
    OverviewAnalyticsResponse,
    SearchAnalyticsSummary,
    SearchInsightsResponse,
    WebAnalyticsResponse,
)
from app.services.analytics import queries as analytics_queries
from app.services.analytics.access import (
    AnalyticsAccessContext,
    AnalyticsAccessDenied,
    EndpointName,
    normalize_claimed_role,
    require_endpoint_access,
    resolve_analytics_access,
)

#: Router-level authentication gate - see the module docstring. Declared once
#: here so no route can be added later without it.
ANALYTICS_ROLE_DEPENDENCY = Depends(
    require_roles("EVENT_ADMIN", "DATA_REVIEWER", "EXHIBITOR_ADMIN")
)

router = APIRouter(prefix="/admin/analytics", dependencies=[ANALYTICS_ROLE_DEPENDENCY])
DbSession = Annotated[AsyncSession, Depends(get_db)]


def build_analytics_router() -> APIRouter:
    """Exposed for the integrator - see module docstring."""

    return router


# ---------------------------------------------------------------------------
# Shared request plumbing
# ---------------------------------------------------------------------------


def _default_period() -> tuple[date, date]:
    """Last 7 calendar days (inclusive of today) when no explicit period is
    supplied - a reasonable default window for an admin dashboard landing
    view, matching how the pre-existing ``getSearchAnalytics`` admin call
    (``apps/admin/lib/types.ts``) expects a response with no query params."""

    today = date.today()
    return today - timedelta(days=6), today


def _period_params(
    period_start: Annotated[date | None, Query()] = None,
    period_end: Annotated[date | None, Query()] = None,
) -> tuple[date, date]:
    default_start, default_end = _default_period()
    start = period_start or default_start
    end = period_end or default_end
    if start > end:
        raise HTTPException(
            status_code=422,
            detail={"code": "INVALID_PERIOD", "message": "period_start must be <= period_end"},
        )
    return start, end


PeriodParams = Annotated[tuple[date, date], Depends(_period_params)]


async def _access_context(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    event_id: uuid.UUID,
    endpoint: EndpointName,
    x_analytics_role: str | None,
) -> AnalyticsAccessContext:
    claimed: AnalyticsRole | None = None
    if x_analytics_role is not None:
        claimed = normalize_claimed_role(x_analytics_role)
        if claimed is None:
            raise HTTPException(
                status_code=400,
                detail={"code": "INVALID_ANALYTICS_ROLE", "message": "unknown X-Analytics-Role"},
            )

    try:
        context = await resolve_analytics_access(
            db, actor_user_id=actor_user_id, event_id=event_id, claimed_role=claimed
        )
        require_endpoint_access(context, endpoint)
    except AnalyticsAccessDenied as error:
        raise HTTPException(
            status_code=403, detail={"code": error.reason, "message": "analytics access denied"}
        ) from error
    return context


AnalyticsRoleHeader = Annotated[str | None, Header(alias="X-Analytics-Role")]
ActorUserId = Annotated[uuid.UUID, Depends(get_actor_user_id)]


# ---------------------------------------------------------------------------
# GET /admin/analytics/overview
# ---------------------------------------------------------------------------


@router.get("/overview", response_model=OverviewAnalyticsResponse)
async def get_overview(
    event_id: uuid.UUID,
    db: DbSession,
    actor_user_id: ActorUserId,
    period: PeriodParams,
    x_analytics_role: AnalyticsRoleHeader = None,
) -> OverviewAnalyticsResponse:
    context = await _access_context(
        db, actor_user_id=actor_user_id, event_id=event_id, endpoint="overview",
        x_analytics_role=x_analytics_role,
    )
    period_start, period_end = period
    return await analytics_queries.get_overview(
        db, event_id=event_id, period_start=period_start, period_end=period_end, role=context.role
    )


# ---------------------------------------------------------------------------
# GET /admin/analytics/web
# ---------------------------------------------------------------------------


@router.get("/web", response_model=WebAnalyticsResponse)
async def get_web(
    event_id: uuid.UUID,
    db: DbSession,
    actor_user_id: ActorUserId,
    period: PeriodParams,
    x_analytics_role: AnalyticsRoleHeader = None,
) -> WebAnalyticsResponse:
    context = await _access_context(
        db, actor_user_id=actor_user_id, event_id=event_id, endpoint="web",
        x_analytics_role=x_analytics_role,
    )
    period_start, period_end = period
    return await analytics_queries.get_web_analytics(
        db, event_id=event_id, period_start=period_start, period_end=period_end, role=context.role
    )


# ---------------------------------------------------------------------------
# GET /admin/analytics/kiosk
# ---------------------------------------------------------------------------


@router.get("/kiosk", response_model=KioskAnalyticsResponse)
async def get_kiosk(
    event_id: uuid.UUID,
    db: DbSession,
    actor_user_id: ActorUserId,
    period: PeriodParams,
    x_analytics_role: AnalyticsRoleHeader = None,
) -> KioskAnalyticsResponse:
    context = await _access_context(
        db, actor_user_id=actor_user_id, event_id=event_id, endpoint="kiosk",
        x_analytics_role=x_analytics_role,
    )
    period_start, period_end = period
    return await analytics_queries.get_kiosk_analytics(
        db, event_id=event_id, period_start=period_start, period_end=period_end, role=context.role
    )


# ---------------------------------------------------------------------------
# GET /admin/analytics/buyer
# ---------------------------------------------------------------------------


@router.get("/buyer", response_model=BuyerAnalyticsResponse)
async def get_buyer(
    event_id: uuid.UUID,
    db: DbSession,
    actor_user_id: ActorUserId,
    period: PeriodParams,
    exhibitor_id: Annotated[uuid.UUID | None, Query()] = None,
    x_analytics_role: AnalyticsRoleHeader = None,
) -> BuyerAnalyticsResponse:
    context = await _access_context(
        db, actor_user_id=actor_user_id, event_id=event_id, endpoint="buyer",
        x_analytics_role=x_analytics_role,
    )
    period_start, period_end = period

    # EXHIBITOR_ADMIN is always scoped to their own server-resolved
    # exhibitor_id (app/services/analytics/access.py never derives this from
    # client input) - a client-supplied exhibitor_id is ignored entirely for
    # this role, never merged/overridden-by, so there is no path by which an
    # EXHIBITOR_ADMIN can see another exhibitor's scoped figures.
    if context.role == "EXHIBITOR_ADMIN":
        effective_exhibitor_id = context.exhibitor_id
    else:
        effective_exhibitor_id = exhibitor_id

    return await analytics_queries.get_buyer_analytics(
        db,
        event_id=event_id,
        period_start=period_start,
        period_end=period_end,
        role=context.role,
        exhibitor_id=effective_exhibitor_id,
    )


# ---------------------------------------------------------------------------
# GET /admin/analytics/searches
# ---------------------------------------------------------------------------


@router.get("/searches", response_model=None)
async def get_searches(
    event_id: uuid.UUID,
    db: DbSession,
    actor_user_id: ActorUserId,
    period: PeriodParams,
    detail: Annotated[str | None, Query()] = None,
    x_analytics_role: AnalyticsRoleHeader = None,
) -> SearchAnalyticsSummary | SearchInsightsResponse:
    context = await _access_context(
        db, actor_user_id=actor_user_id, event_id=event_id, endpoint="searches",
        x_analytics_role=x_analytics_role,
    )
    period_start, period_end = period
    if detail == "full":
        return await analytics_queries.get_search_insights(
            db, event_id=event_id, period_start=period_start, period_end=period_end, role=context.role
        )
    return await analytics_queries.get_search_analytics_summary(
        db, event_id=event_id, period_start=period_start, period_end=period_end, role=context.role
    )


# ---------------------------------------------------------------------------
# GET /admin/analytics/no-results
# ---------------------------------------------------------------------------


@router.get("/no-results", response_model=NoResultQueryResponse)
async def get_no_results(
    event_id: uuid.UUID,
    db: DbSession,
    actor_user_id: ActorUserId,
    period: PeriodParams,
    x_analytics_role: AnalyticsRoleHeader = None,
) -> NoResultQueryResponse:
    await _access_context(
        db, actor_user_id=actor_user_id, event_id=event_id, endpoint="no_results",
        x_analytics_role=x_analytics_role,
    )
    period_start, period_end = period
    return await analytics_queries.get_no_result_queries(
        db, event_id=event_id, period_start=period_start, period_end=period_end
    )


# ---------------------------------------------------------------------------
# GET /admin/analytics/data-quality
# ---------------------------------------------------------------------------


@router.get("/data-quality", response_model=DataQualityAnalyticsResponse)
async def get_data_quality(
    event_id: uuid.UUID,
    db: DbSession,
    actor_user_id: ActorUserId,
    period: PeriodParams,
    x_analytics_role: AnalyticsRoleHeader = None,
) -> DataQualityAnalyticsResponse:
    context = await _access_context(
        db, actor_user_id=actor_user_id, event_id=event_id, endpoint="data_quality",
        x_analytics_role=x_analytics_role,
    )
    period_start, period_end = period
    return await analytics_queries.get_data_quality(
        db, event_id=event_id, period_start=period_start, period_end=period_end, role=context.role
    )
