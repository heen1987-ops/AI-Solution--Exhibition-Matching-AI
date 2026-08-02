"""Tests for the anonymous web/kiosk catalog search endpoints (BACKEND-008).

No live Postgres/Redis is assumed to be reachable in this environment, so
these tests follow the project's established convention (see
test_recommendation_api.py) of faking the AsyncSession/Redis-store
dependencies at the router boundary, plus compiling SQLAlchemy statements to
verify the mandatory approval/status filters without a live database.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from typing import Any

import pytest
from app.api.v1.routers import search as search_router
from app.db.session import get_db
from app.main import app
from app.schemas.search import SearchResult
from app.services import catalog_search
from app.services.search_query_interpreter import interpret_query
from app.services.search_sessions import (
    SearchSessionRecord,
    SearchSessionStore,
    get_search_session_store,
)
from fastapi.testclient import TestClient
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

EVENT_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# app.services.search_query_interpreter — pure, no DB
# ---------------------------------------------------------------------------


def test_interpret_query_matches_a_curated_synonym() -> None:
    result = interpret_query("막걸리 파는 업체를 찾아줘")

    assert "ALCOHOL.TAKJU" in result.concept_codes
    assert "막걸리" in result.matched_terms


def test_interpret_query_returns_nothing_for_an_unrecognizable_query() -> None:
    result = interpret_query("zzqxvv 관련없는 아무 말")

    assert result.concept_codes == ()
    assert result.matched_terms == ()


def test_interpret_query_handles_an_empty_string() -> None:
    assert interpret_query("").concept_codes == ()


# ---------------------------------------------------------------------------
# app.services.catalog_search — pure helpers
# ---------------------------------------------------------------------------


def test_score_text_ranks_more_matched_tokens_higher() -> None:
    tokens = catalog_search._tokens("막걸리 선물")
    score_full, matched_full = catalog_search._score_text(
        tokens, "선물하기 좋은 막걸리 세트"
    )
    score_partial, _ = catalog_search._score_text(tokens, "막걸리만 팝니다")

    assert score_full == 1.0
    assert set(matched_full) == {"막걸리", "선물"}
    assert 0 < score_partial < score_full


# ---------------------------------------------------------------------------
# app.services.catalog_search._candidate_pool_stmt — mandatory exposure rules
# (verified by compiling the statement; a live Postgres is not required to
# prove the WHERE clause enforces approval/status filters)
# ---------------------------------------------------------------------------


def _compiled_where(event_id: uuid.UUID) -> str:
    stmt = catalog_search._candidate_pool_stmt(event_id)
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def test_candidate_pool_excludes_unapproved_exhibitors_and_products() -> None:
    sql = _compiled_where(EVENT_ID)

    assert "exhibition.exhibitor.master_approval_status = 'APPROVED'" in sql
    assert "exhibition.exhibitor_participation.participation_status = 'APPROVED'" in sql
    assert "exhibition.event_product.approval_status = 'APPROVED'" in sql
    assert "master_approval_status_1 = 'APPROVED'" in sql or (
        "exhibition.product.master_approval_status" in sql and "'APPROVED'" in sql
    )
    assert "exhibition.exhibitor.deleted_at IS NULL" in sql


def test_candidate_pool_excludes_closed_booths() -> None:
    sql = _compiled_where(EVENT_ID)

    assert "exhibition.booth.operating_status IN ('OPEN', 'PAUSED')" in sql
    assert "'CLOSED'" not in sql


def test_candidate_pool_scopes_to_the_requested_event() -> None:
    sql = _compiled_where(EVENT_ID)

    assert "exhibition.exhibitor_participation.event_id = " in sql
    assert EVENT_ID.hex in sql.replace("-", "")


def test_candidate_pool_uses_postgres_full_text_rank_for_a_query() -> None:
    sql = str(
        catalog_search._candidate_pool_stmt(EVENT_ID, "막걸리")
        .compile(compile_kwargs={"literal_binds": True})
    )

    assert "to_tsvector" in sql
    assert "plainto_tsquery" in sql
    assert "ts_rank_cd" in sql


# ---------------------------------------------------------------------------
# app.services.catalog_search.search_approved_catalog — ranking/grouping logic
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def all(self) -> list[Any]:
        return self._rows


class _FakeCatalogSession:
    """Fakes just enough of AsyncSession for search_approved_catalog when
    category_codes is empty (skips the ontology-resolution queries entirely,
    exercising exactly one execute() call — the candidate pool query)."""

    def __init__(self, *, event: Any, rows: list[Any]) -> None:
        self._event = event
        self._rows = rows

    async def get(self, entity: Any, key: Any) -> Any:
        del entity, key
        return self._event

    async def execute(self, statement: Any) -> _FakeResult:
        del statement
        return _FakeResult(self._rows)


def _open_event() -> SimpleNamespace:
    return SimpleNamespace(event_status="OPEN", current_taxonomy_version_id=None)


def _catalog_row(
    *,
    exhibitor_id: uuid.UUID | None = None,
    booth_id: uuid.UUID | None = None,
    company_name: str = "풍년 막걸리 양조장",
    company_summary: str = "전통 방식으로 빚은 막걸리를 소개합니다",
    completeness: float = 80.0,
    booth_number: str = "A-01",
    operating_status: str = "OPEN",
    product_name: str = "풍년 생막걸리",
) -> tuple[Any, Any, Any, Any, Any]:
    exhibitor = SimpleNamespace(
        exhibitor_id=exhibitor_id or uuid.uuid4(),
        company_name=company_name,
        company_summary=company_summary,
        data_completeness_percent=completeness,
    )
    participation = SimpleNamespace(
        participation_id=uuid.uuid4(), promotion_summary="현장 시음 행사 진행 중"
    )
    booth = SimpleNamespace(
        booth_id=booth_id or uuid.uuid4(),
        booth_number=booth_number,
        operating_status=operating_status,
        estimated_wait_minutes=None,
        map_x=None,
        map_y=None,
    )
    product = SimpleNamespace(product_id=uuid.uuid4(), product_name=product_name)
    zone = SimpleNamespace(zone_name="A홀")
    return exhibitor, participation, booth, product, zone


@pytest.mark.asyncio
async def test_search_matches_a_korean_natural_language_query() -> None:
    session = _FakeCatalogSession(event=_open_event(), rows=[_catalog_row()])

    results = await catalog_search.search_approved_catalog(
        session,  # type: ignore[arg-type]
        event_id=EVENT_ID,
        query="막걸리 파는 곳 찾아줘",
        category_codes=[],
        limit=12,
    )

    assert len(results) == 1
    assert results[0].name == "풍년 막걸리 양조장"
    assert results[0].rank == 1
    assert "막걸리" in results[0].reason


@pytest.mark.asyncio
async def test_search_returns_no_results_when_nothing_matches() -> None:
    session = _FakeCatalogSession(
        event=_open_event(),
        rows=[_catalog_row(company_name="산들 와이너리", product_name="레드 와인")],
    )

    results = await catalog_search.search_approved_catalog(
        session,  # type: ignore[arg-type]
        event_id=EVENT_ID,
        query="완전히 무관한 검색어 zzzqxvv",
        category_codes=[],
        limit=12,
    )

    assert results == []


@pytest.mark.asyncio
async def test_search_dedupes_multiple_products_from_the_same_exhibitor() -> None:
    exhibitor_id = uuid.uuid4()
    booth_id = uuid.uuid4()
    rows = [
        _catalog_row(
            exhibitor_id=exhibitor_id, booth_id=booth_id, product_name="생막걸리"
        ),
        _catalog_row(
            exhibitor_id=exhibitor_id, booth_id=booth_id, product_name="탁주 스페셜"
        ),
    ]
    session = _FakeCatalogSession(event=_open_event(), rows=rows)

    results = await catalog_search.search_approved_catalog(
        session,  # type: ignore[arg-type]
        event_id=EVENT_ID,
        query="막걸리",
        category_codes=[],
        limit=12,
    )

    assert len(results) == 1
    assert set(results[0].product_names) == {"생막걸리", "탁주 스페셜"}


@pytest.mark.asyncio
async def test_search_returns_nothing_when_the_event_is_not_open() -> None:
    for event in (
        None,
        SimpleNamespace(event_status="PREPARING", current_taxonomy_version_id=None),
        SimpleNamespace(event_status="CLOSED", current_taxonomy_version_id=None),
    ):
        session = _FakeCatalogSession(event=event, rows=[_catalog_row()])

        results = await catalog_search.search_approved_catalog(
            session,  # type: ignore[arg-type]
            event_id=EVENT_ID,
            query="막걸리",
            category_codes=[],
            limit=12,
        )

        assert results == []


# ---------------------------------------------------------------------------
# Router: POST /search, GET /search/{id} — envelope, session round-trip,
# validation, and graceful-degradation error handling
# ---------------------------------------------------------------------------


class _FakeSearchSessionStore:
    def __init__(self, *, fail_save: bool = False, fail_get: bool = False) -> None:
        self._data: dict[uuid.UUID, SearchSessionRecord] = {}
        self._fail_save = fail_save
        self._fail_get = fail_get

    async def save(self, record: SearchSessionRecord, ttl_seconds: int) -> None:
        del ttl_seconds
        if self._fail_save:
            raise RedisError("simulated redis outage")
        self._data[record.response.search_session_id] = record

    async def get(self, search_session_id: uuid.UUID) -> SearchSessionRecord | None:
        if self._fail_get:
            raise RedisError("simulated redis outage")
        return self._data.get(search_session_id)


async def _fake_db() -> Any:
    yield object()


def _override(store: SearchSessionStore) -> None:
    app.dependency_overrides[get_db] = _fake_db
    app.dependency_overrides[get_search_session_store] = lambda: store


def _clear_overrides() -> None:
    app.dependency_overrides.pop(get_db, None)
    app.dependency_overrides.pop(get_search_session_store, None)


def _one_result() -> SearchResult:
    return SearchResult(
        result_id="exhibitor:00000000-0000-0000-0000-000000000001:booth:1",
        rank=1,
        exhibitor_id=uuid.uuid4(),
        booth_id=uuid.uuid4(),
        name="풍년 막걸리 양조장",
        booth_number="A-01",
        summary="전통 막걸리 양조장",
        product_names=["생막걸리"],
        reason="검색하신 '막걸리'와 관련된 승인 업체예요.",
        concepts=["ALCOHOL.TAKJU"],
        operating_status="OPEN",
    )


def test_create_search_returns_versioned_envelope_and_interprets_korean_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(db: Any, **kwargs: Any) -> list[SearchResult]:
        del db
        assert kwargs["event_id"] == EVENT_ID
        assert "ALCOHOL.TAKJU" in kwargs["category_codes"]
        return [_one_result()]

    monkeypatch.setattr(search_router, "search_approved_catalog", fake_search)
    store = _FakeSearchSessionStore()
    _override(store)
    try:
        response = TestClient(app).post(
            "/api/v1/search",
            headers={"X-Request-ID": "req-search-001"},
            json={
                "event_id": str(EVENT_ID),
                "query": "막걸리 파는 업체를 찾아줘",
                "channel": "KIOSK",
            },
        )
    finally:
        _clear_overrides()

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["meta"]["request_id"] == "req-search-001"
    data = body["data"]
    assert data["channel"] == "KIOSK"
    assert "ALCOHOL.TAKJU" in data["interpreted_query"]["concepts"]
    assert data["results"][0]["name"] == "풍년 막걸리 양조장"
    assert data["clarification"] is None
    assert uuid.UUID(data["search_session_id"])


def test_get_search_round_trips_a_saved_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(db: Any, **kwargs: Any) -> list[SearchResult]:
        del db, kwargs
        return [_one_result()]

    monkeypatch.setattr(search_router, "search_approved_catalog", fake_search)
    store = _FakeSearchSessionStore()
    _override(store)
    try:
        client = TestClient(app)
        created = client.post(
            "/api/v1/search",
            json={"event_id": str(EVENT_ID), "query": "막걸리"},
        ).json()["data"]

        fetched = client.get(f"/api/v1/search/{created['search_session_id']}")
    finally:
        _clear_overrides()

    assert fetched.status_code == 200
    assert fetched.json()["data"]["search_session_id"] == created["search_session_id"]
    assert fetched.json()["data"]["results"][0]["name"] == "풍년 막걸리 양조장"


def test_no_results_search_returns_a_helpful_clarification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(db: Any, **kwargs: Any) -> list[SearchResult]:
        del db, kwargs
        return []

    monkeypatch.setattr(search_router, "search_approved_catalog", fake_search)
    store = _FakeSearchSessionStore()
    _override(store)
    try:
        response = TestClient(app).post(
            "/api/v1/search",
            json={"event_id": str(EVENT_ID), "query": "완전히 무관한 검색어 zzzqxvv"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["results"] == []
    assert data["clarification"] is not None
    assert data["clarification"]["options"]


def test_get_search_returns_404_for_a_missing_or_expired_session() -> None:
    store = _FakeSearchSessionStore()
    _override(store)
    try:
        response = TestClient(app).get(f"/api/v1/search/{uuid.uuid4()}")
    finally:
        _clear_overrides()

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "SEARCH_SESSION_NOT_FOUND"


def test_search_request_requires_query_or_category_codes() -> None:
    store = _FakeSearchSessionStore()
    _override(store)
    try:
        response = TestClient(app).post(
            "/api/v1/search",
            json={"event_id": str(EVENT_ID), "query": "", "category_codes": []},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 422


def test_search_unavailable_when_the_catalog_query_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def failing_search(db: Any, **kwargs: Any) -> list[SearchResult]:
        del db, kwargs
        raise SQLAlchemyError("simulated database outage")

    monkeypatch.setattr(search_router, "search_approved_catalog", failing_search)
    store = _FakeSearchSessionStore()
    _override(store)
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            "/api/v1/search",
            json={"event_id": str(EVENT_ID), "query": "막걸리"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 503
    detail = response.json()["detail"]
    assert detail["code"] == "SEARCH_UNAVAILABLE"
    assert detail["retryable"] is True


def test_search_session_store_outage_is_reported_as_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_search(db: Any, **kwargs: Any) -> list[SearchResult]:
        del db, kwargs
        return [_one_result()]

    monkeypatch.setattr(search_router, "search_approved_catalog", fake_search)
    store = _FakeSearchSessionStore(fail_save=True)
    _override(store)
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            "/api/v1/search",
            json={"event_id": str(EVENT_ID), "query": "막걸리"},
        )
    finally:
        _clear_overrides()

    assert response.status_code == 503
    assert response.json()["detail"]["code"] == "SEARCH_SESSION_STORE_UNAVAILABLE"


def test_search_routes_are_published_in_openapi() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/search" in paths
    assert "/api/v1/search/{search_session_id}" in paths
