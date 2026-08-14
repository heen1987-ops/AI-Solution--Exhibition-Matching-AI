"""BACKEND-ANALYTICS (WAVE 2E) coverage.

No live Postgres is assumed to be reachable in this environment (repo convention - see
test_search_api.py / test_buyer_match_api.py), so this file:

1. Exercises the pure logic (``app/services/analytics/suppression.py``, the row-assembly
   helpers in ``app/services/analytics/queries.py``) directly with plain Python inputs.
2. Verifies the SQL a query builder produces by capturing the compiled statement through a
   minimal fake ``AsyncSession`` (mirrors ``test_search_api.py``'s
   ``_candidate_pool_stmt``-compiling convention) rather than executing it.
3. Drives ``app/services/analytics/access.py``'s role resolution with a fake DB whose
   ``execute`` returns canned ``profile.user_role``/``profile.role`` join rows.
4. Drives the router end-to-end through ``TestClient`` with ``resolve_analytics_access`` and
   the ``app/services/analytics/queries.py`` functions monkeypatched, the same fake/monkeypatch
   pattern ``test_buyer_match_api.py`` and ``test_recommendation_api.py`` use for DB-backed
   routers.

Authentication in these tests (merge plan STEP 23)
----------------------------------------------------
The router no longer accepts an ``X-Actor-User-Id`` header, so the caller is established by
overriding ``app.core.auth.get_verified_principal`` - the same dependency-override precedent
``tests/test_recommendation_api.py`` uses. A request with no override at all exercises the
real 401 path.

Covers this track's required test list:
    - role-based access per the 3 roles (EVENT_ADMIN/DATA_REVIEWER/EXHIBITOR_ADMIN; WAVE 2E's
      ANALYST was collapsed onto DATA_REVIEWER at integration)
    - small-group suppression enforced
    - EXHIBITOR_ADMIN cannot see competitor data (server ignores a client-supplied
      ``exhibitor_id`` and always uses its own server-resolved one)
    - overview/web/kiosk/buyer/searches/no-results/data-quality all return well-formed
      responses against synthetic aggregate rows
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routers import analytics as analytics_router
from app.core.auth import (
    AuthException,
    VerifiedPrincipal,
    auth_exception_handler,
    get_verified_principal,
)
from app.db.session import get_db
from app.schemas.analytics import (
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
from app.schemas.auth import AuthPrincipal, AuthRoleGrant
from app.services.analytics import queries as analytics_queries
from app.services.analytics.access import (
    ENDPOINT_ALLOWED_ROLES,
    AnalyticsAccessContext,
    AnalyticsAccessDenied,
    normalize_claimed_role,
    require_endpoint_access,
    resolve_analytics_access,
)
from app.services.analytics.suppression import (
    SMALL_GROUP_SUPPRESSION_THRESHOLD,
    combine_rate,
    drop_small_groups,
    redact_query_text,
    suppress_metric,
    suppress_rate,
)

# apps/api/pyproject.toml sets asyncio_mode = "auto" - async def test_* functions run without
# an explicit @pytest.mark.asyncio marker (see test_buyer_match_api.py).

EVENT_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# app/services/analytics/suppression.py — pure, no DB
# ---------------------------------------------------------------------------


def test_suppress_metric_masks_a_small_nonzero_count() -> None:
    for count in range(1, SMALL_GROUP_SUPPRESSION_THRESHOLD):
        metric = suppress_metric(count, count)
        assert metric.suppressed is True
        assert metric.value is None


def test_suppress_metric_never_masks_a_true_zero() -> None:
    assert suppress_metric(0, 0) == Metric(value=0, suppressed=False)
    assert suppress_metric(None, None) == Metric(value=0, suppressed=False)


def test_suppress_metric_keeps_counts_at_or_above_the_threshold() -> None:
    metric = suppress_metric(SMALL_GROUP_SUPPRESSION_THRESHOLD, SMALL_GROUP_SUPPRESSION_THRESHOLD)
    assert metric == Metric(value=float(SMALL_GROUP_SUPPRESSION_THRESHOLD), suppressed=False)


def test_suppress_rate_masks_when_either_side_is_a_small_group() -> None:
    # denominator small
    assert suppress_rate(1, 1, 2, 2).suppressed is True
    # numerator small, denominator large
    assert suppress_rate(1, 1, 100, 100).suppressed is True
    # both large -> real rate
    rate = suppress_rate(10, 10, 20, 20)
    assert rate == Metric(value=0.5, suppressed=False)


def test_combine_rate_masks_when_either_input_metric_is_suppressed() -> None:
    masked = Metric(value=None, suppressed=True)
    real = Metric(value=10, suppressed=False)
    assert combine_rate(masked, real).suppressed is True
    assert combine_rate(real, masked).suppressed is True


def test_combine_rate_zero_denominator_is_a_real_unsuppressed_zero() -> None:
    zero = Metric(value=0, suppressed=False)
    ten = Metric(value=10, suppressed=False)
    assert combine_rate(ten, zero) == Metric(value=0, suppressed=False)


def test_drop_small_groups_filters_out_rows_under_the_threshold() -> None:
    rows = [
        SimpleNamespace(name="rare", count=1),
        SimpleNamespace(name="common", count=SMALL_GROUP_SUPPRESSION_THRESHOLD),
    ]
    kept = drop_small_groups(rows, underlying_count_of=lambda row: row.count)
    assert [row.name for row in kept] == ["common"]


def test_redact_query_text_masks_email_phone_and_rrn_patterns() -> None:
    text = "문의: person@example.com 010-1234-5678 901231-1234567"
    redacted = redact_query_text(text)
    assert "@" not in redacted
    assert "010-1234-5678" not in redacted
    assert "901231-1234567" not in redacted
    assert "[masked]" in redacted


def test_redact_query_text_passes_through_clean_text_unchanged() -> None:
    assert redact_query_text("막걸리 선물세트") == "막걸리 선물세트"


# ---------------------------------------------------------------------------
# app/services/analytics/access.py — role resolution (fake profile.user_role rows)
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    def all(self) -> list:
        return self._rows

    def one(self):
        return self._rows[0] if self._rows else (0, None)

    def scalar_one(self):
        return self._rows[0] if self._rows else 0


class _FakeAccessDb:
    def __init__(self, rows: list) -> None:
        self._rows = rows

    async def execute(self, stmt: object) -> _FakeResult:
        return _FakeResult(self._rows)


def _role_row(role_code: str, *, event_id: uuid.UUID | None, exhibitor_id: uuid.UUID | None = None):
    return SimpleNamespace(role_code=role_code, event_id=event_id, exhibitor_id=exhibitor_id)


async def test_admin_role_defaults_to_event_admin_and_permits_narrowing() -> None:
    db = _FakeAccessDb([_role_row("ADMIN", event_id=None)])

    context = await resolve_analytics_access(
        db, actor_user_id=uuid.uuid4(), event_id=EVENT_ID, claimed_role=None
    )
    assert context.role == "EVENT_ADMIN"
    assert context.exhibitor_id is None

    narrowed = await resolve_analytics_access(
        db, actor_user_id=uuid.uuid4(), event_id=EVENT_ID, claimed_role="DATA_REVIEWER"
    )
    assert narrowed.role == "DATA_REVIEWER"


async def test_operator_role_requires_a_matching_event_scope() -> None:
    other_event = uuid.uuid4()
    db = _FakeAccessDb([_role_row("OPERATOR", event_id=other_event)])

    with pytest.raises(AnalyticsAccessDenied) as excinfo:
        await resolve_analytics_access(
            db, actor_user_id=uuid.uuid4(), event_id=EVENT_ID, claimed_role=None
        )
    assert excinfo.value.reason == "INSUFFICIENT_ROLE"


async def test_exhibitor_role_is_scoped_server_side_to_its_own_exhibitor_id() -> None:
    own_exhibitor_id = uuid.uuid4()
    db = _FakeAccessDb([_role_row("EXHIBITOR", event_id=EVENT_ID, exhibitor_id=own_exhibitor_id)])

    context = await resolve_analytics_access(
        db, actor_user_id=uuid.uuid4(), event_id=EVENT_ID, claimed_role=None
    )
    assert context.role == "EXHIBITOR_ADMIN"
    assert context.exhibitor_id == own_exhibitor_id


async def test_no_role_rows_at_all_is_denied() -> None:
    db = _FakeAccessDb([])
    with pytest.raises(AnalyticsAccessDenied) as excinfo:
        await resolve_analytics_access(
            db, actor_user_id=uuid.uuid4(), event_id=EVENT_ID, claimed_role=None
        )
    assert excinfo.value.reason == "NO_ROLE_ASSIGNED"


async def test_visitor_role_alone_has_no_analytics_access() -> None:
    db = _FakeAccessDb([_role_row("VISITOR", event_id=EVENT_ID)])
    with pytest.raises(AnalyticsAccessDenied) as excinfo:
        await resolve_analytics_access(
            db, actor_user_id=uuid.uuid4(), event_id=EVENT_ID, claimed_role=None
        )
    assert excinfo.value.reason == "INSUFFICIENT_ROLE"


async def test_exhibitor_actor_cannot_claim_event_admin() -> None:
    db = _FakeAccessDb(
        [_role_row("EXHIBITOR", event_id=EVENT_ID, exhibitor_id=uuid.uuid4())]
    )
    with pytest.raises(AnalyticsAccessDenied) as excinfo:
        await resolve_analytics_access(
            db, actor_user_id=uuid.uuid4(), event_id=EVENT_ID, claimed_role="EVENT_ADMIN"
        )
    assert excinfo.value.reason == "ROLE_NOT_PERMITTED"


def test_require_endpoint_access_data_reviewer_is_limited_to_search_and_quality() -> None:
    context = AnalyticsAccessContext(role="DATA_REVIEWER", event_id=EVENT_ID)
    require_endpoint_access(context, "searches")
    require_endpoint_access(context, "no_results")
    require_endpoint_access(context, "data_quality")
    for denied_endpoint in ("overview", "web", "kiosk", "buyer"):
        with pytest.raises(AnalyticsAccessDenied):
            require_endpoint_access(context, denied_endpoint)  # type: ignore[arg-type]


def test_require_endpoint_access_exhibitor_admin_is_limited_to_buyer() -> None:
    context = AnalyticsAccessContext(role="EXHIBITOR_ADMIN", event_id=EVENT_ID, exhibitor_id=uuid.uuid4())
    require_endpoint_access(context, "buyer")
    for denied_endpoint in ("overview", "web", "kiosk", "searches", "no_results", "data_quality"):
        with pytest.raises(AnalyticsAccessDenied):
            require_endpoint_access(context, denied_endpoint)  # type: ignore[arg-type]


def test_analyst_is_collapsed_onto_data_reviewer_and_is_not_a_role_of_its_own() -> None:
    """WAVE 2E's ANALYST is not in ``auth.role_grant``'s CHECK, so it was collapsed onto
    DATA_REVIEWER at integration (merge plan STEP 23). An older client still sending
    ``X-Analytics-Role: ANALYST`` is narrowed, never widened, and ANALYST itself is no
    longer a value any endpoint's allowed set will accept."""

    assert normalize_claimed_role("ANALYST") == "DATA_REVIEWER"
    assert normalize_claimed_role("EVENT_ADMIN") == "EVENT_ADMIN"
    assert normalize_claimed_role("SUPER_ADMIN") is None

    for allowed in ENDPOINT_ALLOWED_ROLES.values():
        assert "ANALYST" not in allowed

    # Nothing ANALYST could reach became unreachable: EVENT_ADMIN still covers all seven.
    event_admin = AnalyticsAccessContext(role="EVENT_ADMIN", event_id=EVENT_ID)
    for endpoint in ("overview", "web", "kiosk", "buyer", "searches", "no_results", "data_quality"):
        require_endpoint_access(event_admin, endpoint)  # type: ignore[arg-type]


async def test_an_analyst_claim_narrows_a_staff_actor_to_data_reviewer() -> None:
    db = _FakeAccessDb([_role_row("ADMIN", event_id=None)])

    context = await resolve_analytics_access(
        db,
        actor_user_id=uuid.uuid4(),
        event_id=EVENT_ID,
        claimed_role=normalize_claimed_role("ANALYST"),
    )
    assert context.role == "DATA_REVIEWER"
    # ...and DATA_REVIEWER genuinely reaches less than ANALYST used to.
    with pytest.raises(AnalyticsAccessDenied):
        require_endpoint_access(context, "overview")


async def test_an_exhibitor_actor_cannot_reach_staff_views_via_the_analyst_alias() -> None:
    db = _FakeAccessDb(
        [_role_row("EXHIBITOR", event_id=EVENT_ID, exhibitor_id=uuid.uuid4())]
    )
    with pytest.raises(AnalyticsAccessDenied) as excinfo:
        await resolve_analytics_access(
            db,
            actor_user_id=uuid.uuid4(),
            event_id=EVENT_ID,
            claimed_role=normalize_claimed_role("ANALYST"),
        )
    assert excinfo.value.reason == "ROLE_NOT_PERMITTED"


# ---------------------------------------------------------------------------
# app/services/analytics/queries.py — pure row-assembly helpers
# ---------------------------------------------------------------------------


def test_metric_from_period_rows_with_no_rows_is_a_true_unsuppressed_zero() -> None:
    metric = analytics_queries._metric_from_period_rows([], "event_count")
    assert metric == Metric(value=0, suppressed=False)


def test_metric_from_period_rows_sums_unsuppressed_days() -> None:
    rows = [
        SimpleNamespace(event_count=3, suppressed=False),
        SimpleNamespace(event_count=4, suppressed=False),
    ]
    metric = analytics_queries._metric_from_period_rows(rows, "event_count")
    assert metric == Metric(value=7.0, suppressed=False)


def test_metric_from_period_rows_any_suppressed_day_masks_the_whole_period() -> None:
    rows = [
        SimpleNamespace(event_count=100, suppressed=False),
        SimpleNamespace(event_count=None, suppressed=True),
    ]
    metric = analytics_queries._metric_from_period_rows(rows, "event_count")
    assert metric.suppressed is True
    assert metric.value is None


def test_aggregate_no_result_queries_drops_a_group_with_any_suppressed_day() -> None:
    now = datetime.now(UTC)
    rows = [
        SimpleNamespace(
            channel_code="KIOSK", query_norm="rare term", occurrence_count=1,
            distinct_actor_count=1, suppressed=True, last_occurred_at=now,
        ),
        SimpleNamespace(
            channel_code="KIOSK", query_norm="common term", occurrence_count=10,
            distinct_actor_count=6, suppressed=False, last_occurred_at=now,
        ),
    ]
    aggregated = analytics_queries._aggregate_no_result_queries(rows)
    assert [item.query_norm for item in aggregated] == ["common term"]


def test_aggregate_no_result_queries_drops_groups_under_threshold_after_summing() -> None:
    now = datetime.now(UTC)
    rows = [
        SimpleNamespace(
            channel_code="KIOSK", query_norm="edge term", occurrence_count=2,
            distinct_actor_count=1, suppressed=False, last_occurred_at=now,
        ),
        SimpleNamespace(
            channel_code="KIOSK", query_norm="edge term", occurrence_count=2,
            distinct_actor_count=1, suppressed=False, last_occurred_at=now,
        ),
    ]
    # summed distinct_actor_count == 2, still below SMALL_GROUP_SUPPRESSION_THRESHOLD
    aggregated = analytics_queries._aggregate_no_result_queries(rows)
    assert aggregated == []


# ---------------------------------------------------------------------------
# app/services/analytics/queries.py — statement filter clauses (compiled, no live DB)
# ---------------------------------------------------------------------------


class _CapturingDb:
    """Captures the statement a query-builder function passes to ``execute`` so the
    test can compile and inspect its WHERE clause, without needing a live database
    (same convention ``test_search_api.py`` uses for ``catalog_search._candidate_pool_stmt``,
    adapted here since these builders execute inline rather than returning the statement)."""

    def __init__(self) -> None:
        self.captured: list = []

    async def execute(self, stmt: object) -> _FakeResult:
        self.captured.append(stmt)
        return _FakeResult([])

    def _compiled(self) -> str:
        return str(self.captured[-1].compile(compile_kwargs={"literal_binds": True}))


async def test_daily_metric_rows_scopes_event_metric_dimension_and_period() -> None:
    db = _CapturingDb()
    await analytics_queries._daily_metric_rows(
        db,
        event_id=EVENT_ID,
        metric_code="FAVORITE_SAVE",
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 3),
    )
    sql = db._compiled()
    assert "analytics.daily_metric.event_id" in sql
    assert EVENT_ID.hex in sql.replace("-", "")
    assert "'FAVORITE_SAVE'" in sql
    assert "'ALL'" in sql
    assert "2026-08-01" in sql
    assert "2026-08-03" in sql


async def test_no_result_rows_can_be_scoped_to_a_single_channel() -> None:
    db = _CapturingDb()
    await analytics_queries._no_result_rows(
        db,
        event_id=EVENT_ID,
        period_start=date(2026, 8, 1),
        period_end=date(2026, 8, 3),
        channel_code="KIOSK",
    )
    sql = db._compiled()
    assert "analytics.search_no_result_summary.channel_code" in sql
    assert "'KIOSK'" in sql


async def test_no_result_rows_omits_channel_filter_when_not_requested() -> None:
    db = _CapturingDb()
    await analytics_queries._no_result_rows(
        db, event_id=EVENT_ID, period_start=date(2026, 8, 1), period_end=date(2026, 8, 3)
    )
    sql = db._compiled()
    assert "channel_code = " not in sql


async def test_count_registered_users_only_counts_visitor_and_buyer_roles() -> None:
    db = _CapturingDb()
    await analytics_queries._count_registered_users(db, event_id=EVENT_ID)
    sql = db._compiled()
    assert "'VISITOR'" in sql and "'BUYER'" in sql
    assert "profile.user_role.event_id" in sql
    assert "profile.user_role.valid_until IS NULL" in sql


async def test_published_exhibitor_count_requires_approval_on_both_sides() -> None:
    db = _CapturingDb()
    await analytics_queries._published_exhibitor_count(db, event_id=EVENT_ID)
    sql = db._compiled()
    assert "exhibition.exhibitor_participation.participation_status = 'APPROVED'" in sql
    assert "'APPROVED'" in sql
    assert "exhibition.exhibitor.deleted_at IS NULL" in sql


async def test_kiosk_session_stats_scopes_to_event_and_created_at_window() -> None:
    db = _CapturingDb()
    await analytics_queries._kiosk_session_stats(
        db, event_id=EVENT_ID, period_start=date(2026, 8, 1), period_end=date(2026, 8, 1)
    )
    sql = db._compiled()
    assert "kiosk.kiosk_session.event_id" in sql
    assert EVENT_ID.hex in sql.replace("-", "")


# ---------------------------------------------------------------------------
# Router — role-based access + well-formed responses (TestClient, fakes)
# ---------------------------------------------------------------------------


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(analytics_router.build_analytics_router())
    return app


def _verified_principal(
    *,
    roles: tuple[str, ...] = ("EVENT_ADMIN",),
    authn_level: str = "AAL2",
    user_id: uuid.UUID | None = None,
) -> VerifiedPrincipal:
    """A verified session principal, the only way a caller is identified now.

    ``authn_level='AAL2'`` because EVENT_ADMIN and DATA_REVIEWER are in
    ``PRIVILEGED_ADMIN_ROLES``: ``require_roles`` demands MFA for them.
    """

    tenant_id = uuid.uuid4()
    return VerifiedPrincipal(
        principal=AuthPrincipal(
            subject_type="USER",
            subject_id=user_id or uuid.uuid4(),
            tenant_id=tenant_id,
            event_id=EVENT_ID,
            role_grants=[
                AuthRoleGrant(
                    role=role, tenant_id=tenant_id, event_id=EVENT_ID, exhibitor_id=None
                )
                for role in roles
            ],
            authn_level=authn_level,  # type: ignore[arg-type]
            amr={"magic_link"},
            authenticated_at=datetime.now(UTC),
            mfa_at=datetime.now(UTC),
        ),
        session=None,
    )


def _fixed_access(role: str, *, exhibitor_id: uuid.UUID | None = None):
    async def fake(db, *, actor_user_id, event_id, claimed_role):
        return AnalyticsAccessContext(role=role, event_id=event_id, exhibitor_id=exhibitor_id)

    return fake


def _client(
    app: FastAPI, *, principal: VerifiedPrincipal | None = None
) -> TestClient:
    """Authenticated client. Pass ``principal=None`` explicitly via
    ``_anonymous_client`` to exercise the unauthenticated path."""

    app.dependency_overrides[get_db] = lambda: iter([object()])
    resolved = principal if principal is not None else _verified_principal()
    app.dependency_overrides[get_verified_principal] = lambda: resolved
    return TestClient(app, raise_server_exceptions=False)


def _anonymous_client(app: FastAPI) -> TestClient:
    app.dependency_overrides[get_db] = lambda: iter([object()])
    return TestClient(app, raise_server_exceptions=False)


PERIOD_PARAMS = {"period_start": "2026-08-01", "period_end": "2026-08-03"}


async def test_overview_endpoint_returns_a_well_formed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analytics_router, "resolve_analytics_access", _fixed_access("EVENT_ADMIN"))

    async def fake_get_overview(db, *, event_id, period_start, period_end, role):
        metric = Metric(value=10, suppressed=False)
        masked = Metric(value=None, suppressed=True)
        return OverviewAnalyticsResponse(
            event_id=event_id, period_start=period_start, period_end=period_end, role=role,
            registered_users=metric, profile_confirm_rate=Metric(value=0.5, suppressed=False),
            web_active_users=metric, kiosk_sessions=metric, total_searches=metric,
            no_result_rate=Metric(value=0.1, suppressed=False),
            recommendation_click_rate=Metric(value=0.2, suppressed=False),
            favorites_saved=masked, buyer_matches=masked, meeting_requests=metric,
            meeting_accepts=masked, published_exhibitor_count=Metric(value=12, suppressed=False),
            published_product_count=Metric(value=40, suppressed=False),
        )

    monkeypatch.setattr(analytics_queries, "get_overview", fake_get_overview)

    app = _build_app()
    with _client(app) as client:
        response = client.get(
            "/admin/analytics/overview",
            params={"event_id": str(EVENT_ID), **PERIOD_PARAMS},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "EVENT_ADMIN"
    assert body["registered_users"] == {"value": 10.0, "suppressed": False}
    assert body["favorites_saved"] == {"value": None, "suppressed": True}


async def test_web_endpoint_returns_a_well_formed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analytics_router, "resolve_analytics_access", _fixed_access("EVENT_ADMIN"))

    async def fake_get_web(db, *, event_id, period_start, period_end, role):
        metric = Metric(value=5, suppressed=False)
        return WebAnalyticsResponse(
            event_id=event_id, period_start=period_start, period_end=period_end, role=role,
            active_users=metric, sessions=metric, avg_session_duration_seconds=Metric(value=None, suppressed=True),
            recommendation_impressions=metric, recommendation_clicks=metric,
            recommendation_click_rate=Metric(value=0.4, suppressed=False), favorites_saved=metric,
            daily_active_users=[DailyCount(activity_date=date(2026, 8, 1), count=5)],
        )

    monkeypatch.setattr(analytics_queries, "get_web_analytics", fake_get_web)

    app = _build_app()
    with _client(app) as client:
        response = client.get(
            "/admin/analytics/web",
            params={"event_id": str(EVENT_ID), **PERIOD_PARAMS},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["role"] == "EVENT_ADMIN"
    assert body["daily_active_users"] == [{"activity_date": "2026-08-01", "count": 5}]


async def test_kiosk_endpoint_returns_a_well_formed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analytics_router, "resolve_analytics_access", _fixed_access("EVENT_ADMIN"))

    async def fake_get_kiosk(db, *, event_id, period_start, period_end, role):
        metric = Metric(value=30, suppressed=False)
        return KioskAnalyticsResponse(
            event_id=event_id, period_start=period_start, period_end=period_end, role=role,
            sessions=metric, avg_session_duration_seconds=Metric(value=120.0, suppressed=False),
            qr_handoffs=Metric(value=None, suppressed=True), searches=metric,
            zero_result_rate=Metric(value=0.05, suppressed=False), daily_sessions=[],
        )

    monkeypatch.setattr(analytics_queries, "get_kiosk_analytics", fake_get_kiosk)

    app = _build_app()
    with _client(app) as client:
        response = client.get(
            "/admin/analytics/kiosk",
            params={"event_id": str(EVENT_ID), **PERIOD_PARAMS},
        )
    assert response.status_code == 200
    assert response.json()["qr_handoffs"] == {"value": None, "suppressed": True}


async def test_data_quality_endpoint_returns_a_well_formed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analytics_router, "resolve_analytics_access", _fixed_access("DATA_REVIEWER"))

    async def fake_get_data_quality(db, *, event_id, period_start, period_end, role):
        return DataQualityAnalyticsResponse(
            event_id=event_id, period_start=period_start, period_end=period_end, role=role,
            overall_status="WARN",
            checks=[
                DataQualityCheckSummary(
                    check_code="LATE_ARRIVAL_RATE", status="WARN", metric_value=0.12,
                    threshold_value=0.1, affected_count=42,
                )
            ],
        )

    monkeypatch.setattr(analytics_queries, "get_data_quality", fake_get_data_quality)

    app = _build_app()
    with _client(app) as client:
        response = client.get(
            "/admin/analytics/data-quality",
            params={"event_id": str(EVENT_ID), **PERIOD_PARAMS},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["overall_status"] == "WARN"
    assert body["checks"][0]["check_code"] == "LATE_ARRIVAL_RATE"


async def test_no_results_endpoint_returns_a_well_formed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analytics_router, "resolve_analytics_access", _fixed_access("DATA_REVIEWER"))

    async def fake_get_no_results(db, *, event_id, period_start, period_end):
        return NoResultQueryResponse(
            items=[
                NoResultQueryItem(
                    query="[masked] 관련 문의", count=7, last_seen_at=datetime.now(UTC)
                )
            ]
        )

    monkeypatch.setattr(analytics_queries, "get_no_result_queries", fake_get_no_results)

    app = _build_app()
    with _client(app) as client:
        response = client.get(
            "/admin/analytics/no-results",
            params={"event_id": str(EVENT_ID), **PERIOD_PARAMS},
        )
    assert response.status_code == 200
    assert response.json()["items"][0]["count"] == 7


async def test_searches_endpoint_default_and_detail_full(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analytics_router, "resolve_analytics_access", _fixed_access("EVENT_ADMIN"))

    async def fake_summary(db, *, event_id, period_start, period_end, role):
        return SearchAnalyticsSummary(
            event_id=event_id,
            period_start=datetime.now(UTC),
            period_end=datetime.now(UTC),
            total_searches=100,
            zero_result_rate=0.1,
            top_queries=[TopQueryItem(query="막걸리", count=9)],
            role=role,
        )

    async def fake_insights(db, *, event_id, period_start, period_end, role):
        return SearchInsightsResponse(
            event_id=event_id,
            period_start=datetime.now(UTC),
            period_end=datetime.now(UTC),
            role=role,
            daily_volume=[DailyCount(activity_date=date(2026, 8, 1), count=10)],
            top_interest_codes=[],
            low_click_queries=[],
            channel_performance=[
                ChannelSearchPerformance(
                    channel="KIOSK",
                    total_searches=Metric(value=100, suppressed=False),
                    zero_result_rate=Metric(value=0.1, suppressed=False),
                )
            ],
        )

    monkeypatch.setattr(analytics_queries, "get_search_analytics_summary", fake_summary)
    monkeypatch.setattr(analytics_queries, "get_search_insights", fake_insights)

    app = _build_app()
    with _client(app) as client:
        default_response = client.get(
            "/admin/analytics/searches",
            params={"event_id": str(EVENT_ID), **PERIOD_PARAMS},
        )
        full_response = client.get(
            "/admin/analytics/searches",
            params={"event_id": str(EVENT_ID), "detail": "full", **PERIOD_PARAMS},
        )
    assert default_response.status_code == 200
    assert default_response.json()["top_queries"] == [{"query": "막걸리", "count": 9}]
    assert full_response.status_code == 200
    assert full_response.json()["daily_volume"] == [{"activity_date": "2026-08-01", "count": 10}]


async def test_buyer_endpoint_event_admin_sees_event_wide_totals(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(analytics_router, "resolve_analytics_access", _fixed_access("EVENT_ADMIN"))
    captured: dict = {}

    async def fake_get_buyer(db, *, event_id, period_start, period_end, role, exhibitor_id):
        captured["exhibitor_id"] = exhibitor_id
        metric = Metric(value=8, suppressed=False)
        return BuyerAnalyticsResponse(
            event_id=event_id, period_start=period_start, period_end=period_end, role=role,
            exhibitor_id=exhibitor_id, buyer_matches=metric, meeting_requests=metric,
            meeting_accepts=metric, meeting_completions=metric,
            valid_leads=Metric(value=None, suppressed=True),
            meeting_accept_rate=Metric(value=0.5, suppressed=False),
            meeting_completion_rate=Metric(value=0.5, suppressed=False),
            valid_lead_rate=Metric(value=None, suppressed=True), breakdown=[],
        )

    monkeypatch.setattr(analytics_queries, "get_buyer_analytics", fake_get_buyer)

    app = _build_app()
    with _client(app) as client:
        response = client.get(
            "/admin/analytics/buyer",
            params={"event_id": str(EVENT_ID), **PERIOD_PARAMS},
        )
    assert response.status_code == 200
    assert captured["exhibitor_id"] is None


async def test_buyer_endpoint_exhibitor_admin_cannot_see_competitor_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The core exhibitor-isolation guarantee: an EXHIBITOR_ADMIN's own
    server-resolved ``exhibitor_id`` is always used, even when the request tries
    to ask for a *different* (competitor's) ``exhibitor_id`` via the query
    string. If this ever regressed to trusting the client-supplied value, an
    exhibitor could read another exhibitor's buyer-match figures."""

    own_exhibitor_id = uuid.uuid4()
    competitor_exhibitor_id = uuid.uuid4()
    monkeypatch.setattr(
        analytics_router,
        "resolve_analytics_access",
        _fixed_access("EXHIBITOR_ADMIN", exhibitor_id=own_exhibitor_id),
    )
    captured: dict = {}

    async def fake_get_buyer(db, *, event_id, period_start, period_end, role, exhibitor_id):
        captured["exhibitor_id"] = exhibitor_id
        return BuyerAnalyticsResponse(
            event_id=event_id, period_start=period_start, period_end=period_end, role=role,
            exhibitor_id=exhibitor_id,
            buyer_matches=Metric(value=None, suppressed=True),
            meeting_requests=Metric(value=None, suppressed=True),
            meeting_accepts=Metric(value=None, suppressed=True),
            meeting_completions=Metric(value=None, suppressed=True),
            valid_leads=Metric(value=None, suppressed=True),
            meeting_accept_rate=Metric(value=None, suppressed=True),
            meeting_completion_rate=Metric(value=None, suppressed=True),
            valid_lead_rate=Metric(value=None, suppressed=True), breakdown=[],
        )

    monkeypatch.setattr(analytics_queries, "get_buyer_analytics", fake_get_buyer)

    app = _build_app()
    with _client(app) as client:
        response = client.get(
            "/admin/analytics/buyer",
            params={
                "event_id": str(EVENT_ID),
                "exhibitor_id": str(competitor_exhibitor_id),
                **PERIOD_PARAMS,
            },
        )
    assert response.status_code == 200
    # The query layer was invoked with the exhibitor's OWN id, never the
    # competitor id supplied on the query string.
    assert captured["exhibitor_id"] == own_exhibitor_id
    assert captured["exhibitor_id"] != competitor_exhibitor_id
    assert response.json()["exhibitor_id"] == str(own_exhibitor_id)


# ---------------------------------------------------------------------------
# Router — role denial (403), bad role header (400), bad period (422)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("role", "path"),
    [
        ("DATA_REVIEWER", "/admin/analytics/overview"),
        ("DATA_REVIEWER", "/admin/analytics/web"),
        ("DATA_REVIEWER", "/admin/analytics/kiosk"),
        ("EXHIBITOR_ADMIN", "/admin/analytics/overview"),
        ("EXHIBITOR_ADMIN", "/admin/analytics/searches"),
        ("EXHIBITOR_ADMIN", "/admin/analytics/data-quality"),
    ],
)
async def test_role_not_permitted_for_endpoint_is_rejected_with_403(
    monkeypatch: pytest.MonkeyPatch, role: str, path: str
) -> None:
    monkeypatch.setattr(analytics_router, "resolve_analytics_access", _fixed_access(role))

    app = _build_app()
    with _client(app) as client:
        response = client.get(
            path, params={"event_id": str(EVENT_ID), **PERIOD_PARAMS}
        )
    assert response.status_code == 403


async def test_unassigned_actor_is_rejected_with_403(monkeypatch: pytest.MonkeyPatch) -> None:
    async def deny(db, *, actor_user_id, event_id, claimed_role):
        raise AnalyticsAccessDenied("NO_ROLE_ASSIGNED")

    monkeypatch.setattr(analytics_router, "resolve_analytics_access", deny)

    app = _build_app()
    with _client(app) as client:
        response = client.get(
            "/admin/analytics/overview",
            params={"event_id": str(EVENT_ID), **PERIOD_PARAMS},
        )
    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "NO_ROLE_ASSIGNED"


async def test_invalid_x_analytics_role_header_is_rejected_with_400() -> None:
    app = _build_app()
    with _client(app) as client:
        response = client.get(
            "/admin/analytics/overview",
            params={"event_id": str(EVENT_ID), **PERIOD_PARAMS},
            headers={"X-Analytics-Role": "SUPER_ADMIN"},
        )
    assert response.status_code == 400


async def test_period_start_after_period_end_is_rejected_with_422(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(analytics_router, "resolve_analytics_access", _fixed_access("EVENT_ADMIN"))

    app = _build_app()
    with _client(app) as client:
        response = client.get(
            "/admin/analytics/overview",
            params={
                "event_id": str(EVENT_ID),
                "period_start": "2026-08-03",
                "period_end": "2026-08-01",
            },
        )
    assert response.status_code == 422


# ---------------------------------------------------------------------------
# Router — authentication gate (merge plan STEP 23)
# ---------------------------------------------------------------------------


ANALYTICS_PATHS = (
    "/admin/analytics/overview",
    "/admin/analytics/web",
    "/admin/analytics/kiosk",
    "/admin/analytics/buyer",
    "/admin/analytics/searches",
    "/admin/analytics/no-results",
    "/admin/analytics/data-quality",
)


@pytest.mark.parametrize("path", ANALYTICS_PATHS)
def test_every_analytics_route_is_401_without_a_session(path: str) -> None:
    """There is no header that can identify a caller any more. All seven routes sit behind
    a router-level ``require_roles`` dependency, so an anonymous request never reaches a
    handler body - it cannot even provoke a 422 for a missing query param."""

    app = _build_app()
    with _anonymous_client(app) as client:
        response = client.get(path, params={"event_id": str(EVENT_ID), **PERIOD_PARAMS})
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize("path", ANALYTICS_PATHS)
def test_an_authenticated_caller_with_no_analytics_grant_is_403(path: str) -> None:
    app = _build_app()
    principal = _verified_principal(roles=())
    with _client(app, principal=principal) as client:
        response = client.get(path, params={"event_id": str(EVENT_ID), **PERIOD_PARAMS})
    assert response.status_code == 403
    assert response.json()["code"] == "RESOURCE_FORBIDDEN"


def test_an_aal1_operator_session_cannot_reach_an_analytics_view() -> None:
    """EVENT_ADMIN/DATA_REVIEWER are ``PRIVILEGED_ADMIN_ROLES``: reaching an operator
    analytics view demands MFA, not merely a logged-in session."""

    app = _build_app()
    principal = _verified_principal(roles=("EVENT_ADMIN",), authn_level="AAL1")
    with _client(app, principal=principal) as client:
        response = client.get(
            "/admin/analytics/overview", params={"event_id": str(EVENT_ID), **PERIOD_PARAMS}
        )
    assert response.status_code == 403
    assert response.json()["code"] == "MFA_REQUIRED"


async def test_the_actor_id_comes_from_the_principal_not_from_any_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Regression guard for the ported ``X-Actor-User-Id`` stub: a forged header must have
    no effect at all on which actor the authorization layer is asked about."""

    session_user_id = uuid.uuid4()
    forged_user_id = uuid.uuid4()
    captured: dict = {}

    async def capture(db, *, actor_user_id, event_id, claimed_role):
        captured["actor_user_id"] = actor_user_id
        return AnalyticsAccessContext(role="EVENT_ADMIN", event_id=event_id)

    async def fake_get_no_results(db, *, event_id, period_start, period_end):
        return NoResultQueryResponse(items=[])

    monkeypatch.setattr(analytics_router, "resolve_analytics_access", capture)
    monkeypatch.setattr(analytics_queries, "get_no_result_queries", fake_get_no_results)

    app = _build_app()
    principal = _verified_principal(user_id=session_user_id)
    with _client(app, principal=principal) as client:
        response = client.get(
            "/admin/analytics/no-results",
            params={"event_id": str(EVENT_ID), **PERIOD_PARAMS},
            headers={"X-Actor-User-Id": str(forged_user_id)},
        )
    assert response.status_code == 200
    assert captured["actor_user_id"] == session_user_id
    assert captured["actor_user_id"] != forged_user_id


async def test_an_analytics_role_header_of_analyst_is_accepted_and_collapsed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict = {}

    async def capture(db, *, actor_user_id, event_id, claimed_role):
        captured["claimed_role"] = claimed_role
        return AnalyticsAccessContext(role="DATA_REVIEWER", event_id=event_id)

    async def fake_get_no_results(db, *, event_id, period_start, period_end):
        return NoResultQueryResponse(items=[])

    monkeypatch.setattr(analytics_router, "resolve_analytics_access", capture)
    monkeypatch.setattr(analytics_queries, "get_no_result_queries", fake_get_no_results)

    app = _build_app()
    with _client(app) as client:
        response = client.get(
            "/admin/analytics/no-results",
            params={"event_id": str(EVENT_ID), **PERIOD_PARAMS},
            headers={"X-Analytics-Role": "ANALYST"},
        )
    assert response.status_code == 200
    assert captured["claimed_role"] == "DATA_REVIEWER"
