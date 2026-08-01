from __future__ import annotations

import time
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

import pytest
from app.api.v1.routers import recommendations
from app.core.config import Settings
from app.core.site_context import sign_site_context, verify_site_context
from app.db.session import get_db
from app.main import app
from app.models.matching import InteractionClientEventDedupe
from app.services.matching import candidate_generator, request_validator
from app.services.matching.errors import RecommendationError
from app.services.matching.types import (
    MatchCandidate,
    MatchReasonDraft,
    PipelineTrace,
    RecommendationOutcome,
    SubjectContext,
)
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError


def _subject_headers() -> dict[str, str]:
    return {
        "X-Tenant-Id": str(uuid.uuid4()),
        "X-Event-Id": str(uuid.uuid4()),
        "X-Profile-Id": str(uuid.uuid4()),
        "X-Guest-Session-Id": str(uuid.uuid4()),
        "X-Request-ID": "req-api-contract-001",
    }


def test_site_context_signature_detects_tampering_and_replay() -> None:
    now = int(time.time())
    headers = {key.lower(): value for key, value in _subject_headers().items()}
    headers["x-site-context-timestamp"] = str(now)
    headers["x-site-context-signature"] = sign_site_context(
        headers, timestamp=now, secret="test-adapter-secret"
    )

    assert verify_site_context(headers, secret="test-adapter-secret", now=now).valid

    tampered = {**headers, "x-profile-id": str(uuid.uuid4())}
    assert (
        verify_site_context(tampered, secret="test-adapter-secret", now=now).reason
        == "CONTEXT_SIGNATURE_MISMATCH"
    )
    assert (
        verify_site_context(
            headers,
            secret="test-adapter-secret",
            now=now + 301,
        ).reason
        == "STALE_CONTEXT_SIGNATURE"
    )


def test_production_configuration_rejects_the_local_default_secret() -> None:
    with pytest.raises(ValidationError):
        Settings(ENV="production")
    with pytest.raises(ValidationError):
        Settings(ENV="production", SECRET_KEY="configured-session-secret")

    settings = Settings(
        ENV="production",
        SECRET_KEY="configured-session-secret",
        SITE_CONTEXT_SECRET="configured-site-adapter-secret",
    )
    assert settings.site_context_secret == "configured-site-adapter-secret"


def test_interaction_context_uses_an_explicit_privacy_allowlist() -> None:
    sanitized = recommendations._sanitize_context(
        {
            "source": "recommendation-card",
            "email": "visitor@example.com",
            "free_note": "민감한 자유 메모",
            "nested": {"token": "never-store"},
        },
        zone="ENTRANCE_A",
    )

    assert sanitized == {
        "zone": "ENTRANCE_A",
        "source": "recommendation-card",
    }


def test_recommendation_routes_are_published_in_openapi() -> None:
    paths = app.openapi()["paths"]

    assert "/api/v1/recommendations" in paths
    assert "/api/v1/recommendation-sessions/{recommendation_session_id}/items" in paths
    assert "/api/v1/interactions/batch" in paths


def test_recommendation_rank_cursor_is_opaque_and_validated() -> None:
    cursor = recommendations._encode_rank_cursor(17)

    assert cursor != "17"
    assert recommendations._decode_rank_cursor(cursor) == 17
    with pytest.raises(RecommendationError):
        recommendations._decode_rank_cursor("17")


class _ScalarResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalar_one(self) -> Any:
        return self.value

    def scalar_one_or_none(self) -> Any:
        return self.value


@pytest.mark.asyncio
async def test_optional_vector_channel_never_rolls_back_pipeline_transaction() -> None:
    class SessionWithoutVectorTable:
        async def execute(self, statement: Any) -> _ScalarResult:
            assert "to_regclass" in str(statement)
            return _ScalarResult(False)

    ids, available = await candidate_generator._vector_search_candidates(
        SessionWithoutVectorTable(),  # type: ignore[arg-type]
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
    )

    assert ids == []
    assert available is False


@pytest.mark.asyncio
async def test_persisted_product_uses_public_product_id_not_event_product_id() -> None:
    product_id = uuid.uuid4()
    event_product_id = uuid.uuid4()
    exhibitor_id = uuid.uuid4()

    class ProductResult:
        def first(self) -> Any:
            return SimpleNamespace(product_id=product_id, exhibitor_id=exhibitor_id)

    class ProductLookupSession:
        async def execute(self, statement: Any) -> ProductResult:
            del statement
            return ProductResult()

    object_id, resolved_exhibitor_id = await recommendations._resolve_result_object_id(
        ProductLookupSession(),  # type: ignore[arg-type]
        SimpleNamespace(
            object_type="EVENT_PRODUCT",
            event_product_id=event_product_id,
            tenant_id=uuid.uuid4(),
            event_id=uuid.uuid4(),
        ),
    )

    assert object_id == str(product_id)
    assert object_id != str(event_product_id)
    assert resolved_exhibitor_id == exhibitor_id


@pytest.mark.asyncio
async def test_request_validator_rejects_profile_owner_mismatch() -> None:
    tenant_id = uuid.uuid4()
    event_id = uuid.uuid4()
    subject = SubjectContext(
        tenant_id=tenant_id,
        event_id=event_id,
        profile_id=uuid.uuid4(),
        visit_session_id=None,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        request_id="req-owner-boundary",
        idempotency_key=None,
        server_time=datetime.now(UTC),
    )

    class OwnerMismatchSession:
        async def get(self, entity: Any, key: uuid.UUID) -> Any:
            del entity, key
            return SimpleNamespace(tenant_id=tenant_id, event_status="OPEN")

        async def execute(self, statement: Any) -> _ScalarResult:
            del statement
            return _ScalarResult(
                SimpleNamespace(
                    user_id=uuid.uuid4(),
                    guest_session_id=None,
                    user_type="GENERAL_VISITOR",
                    completeness_score=100,
                )
            )

    with pytest.raises(RecommendationError) as raised:
        await request_validator.validate_request(
            OwnerMismatchSession(),  # type: ignore[arg-type]
            subject=subject,
            recommendation_type="PRODUCT",
            context_input={},
            limit=5,
        )

    assert raised.value.code == "RESOURCE_FORBIDDEN"


def test_create_recommendation_returns_versioned_envelope(monkeypatch) -> None:
    now = datetime.now(UTC)
    candidate = MatchCandidate(
        object_type="PRODUCT",
        object_id=uuid.uuid4(),
        recommendable_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        participation_id=uuid.uuid4(),
        public_object_id="event-product-public-001",
        final_score=0.91,
        rank=1,
        recommended_action="VISIT_NOW",
        availability={"tasting": True},
        reasons=[
            MatchReasonDraft(
                code="CATEGORY_MATCH",
                text="관심 있으신 주종과 일치합니다.",
                evidence_refs=["event_product:001:category"],
                contribution_score=0.8,
                generated_by="TEMPLATE",
            )
        ],
        match_result_id=uuid.uuid4(),
    )
    outcome = RecommendationOutcome(
        recommendation_session_id=uuid.uuid4(),
        generated_at=now,
        expires_at=now + timedelta(minutes=10),
        profile_version=3,
        ranking_version="match-v1.0-baseline",
        explanation_version="explain-v1.0-template",
        policy_version="consumer-score-v1.0",
        items=[candidate],
        trace=PipelineTrace(result_count=1),
    )

    async def fake_generate(db: Any, **kwargs: Any) -> RecommendationOutcome:
        del db
        assert kwargs["recommendation_type"] == "PRODUCT"
        return outcome

    async def fake_db():
        yield object()

    monkeypatch.setattr(
        recommendations.recommendation_orchestrator, "generate", fake_generate
    )
    app.dependency_overrides[get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/recommendations",
            headers=_subject_headers(),
            json={"recommendation_type": "PRODUCT", "limit": 5},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["meta"]["request_id"] == "req-api-contract-001"
    assert body["data"]["policy_version"] == "consumer-score-v1.0"
    assert body["data"]["ranking_version"] == "match-v1.0-baseline"
    assert body["data"]["items"][0]["match_level"] == "VERY_HIGH"


def test_recommendation_errors_use_the_public_error_envelope() -> None:
    headers = _subject_headers()
    headers.pop("X-Guest-Session-Id")

    async def fake_db():
        yield object()

    app.dependency_overrides[get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/recommendations",
            headers=headers,
            json={"recommendation_type": "PRODUCT"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 401
    assert response.json() == {
        "success": False,
        "error": {
            "code": "AUTH_REQUIRED",
            "message": "X-User-Id와 X-Guest-Session-Id 중 정확히 하나가 필요합니다.",
            "field_errors": [],
            "retryable": False,
            "retry_after_seconds": None,
        },
        "meta": {
            "request_id": "req-api-contract-001",
            "server_time": response.json()["meta"]["server_time"],
        },
    }


def test_database_failures_return_retryable_public_envelope(monkeypatch) -> None:
    async def fail_generate(db: Any, **kwargs: Any) -> RecommendationOutcome:
        del db, kwargs
        raise SQLAlchemyError("simulated database outage")

    async def fake_db():
        yield object()

    monkeypatch.setattr(
        recommendations.recommendation_orchestrator,
        "generate",
        fail_generate,
    )
    app.dependency_overrides[get_db] = fake_db
    try:
        response = TestClient(app, raise_server_exceptions=False).post(
            "/api/v1/recommendations",
            headers=_subject_headers(),
            json={"recommendation_type": "PRODUCT"},
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 503
    assert response.json()["success"] is False
    assert response.json()["error"]["code"] == "SERVICE_TEMPORARILY_UNAVAILABLE"
    assert response.json()["error"]["retryable"] is True


class _NestedTransaction:
    def __init__(self, session: _InteractionSession) -> None:
        self.session = session

    async def __aenter__(self) -> None:
        self.session.savepoint_count += 1

    async def __aexit__(self, exc_type, exc, traceback) -> bool:
        del exc, traceback
        if exc_type is not None:
            self.session.savepoint_rollback_count += 1
        return False


class _InteractionSession:
    def __init__(self, *, fail_at_flush: int | None = 2) -> None:
        self.rows: list[Any] = []
        self.claims: list[InteractionClientEventDedupe] = []
        self.flush_count = 0
        self.fail_at_flush = fail_at_flush
        self.commit_count = 0
        self.rollback_count = 0
        self.savepoint_count = 0
        self.savepoint_rollback_count = 0

    def begin_nested(self) -> _NestedTransaction:
        return _NestedTransaction(self)

    def add(self, row: Any) -> None:
        self.rows.append(row)
        if isinstance(row, InteractionClientEventDedupe):
            self.claims.append(row)

    async def execute(self, statement: Any) -> _ScalarQueryResult:
        entity = statement.column_descriptions[0].get("entity")
        if entity is InteractionClientEventDedupe:
            return _ScalarQueryResult(self.claims[-1] if self.claims else None)
        raise AssertionError(f"unexpected statement: {statement}")

    async def flush(self) -> None:
        self.flush_count += 1
        if self.fail_at_flush is not None and self.flush_count == self.fail_at_flush:
            raise SQLAlchemyError("simulated row failure")

    async def commit(self) -> None:
        self.commit_count += 1

    async def rollback(self) -> None:
        self.rollback_count += 1


class _ScalarQueryResult:
    def __init__(self, value: Any) -> None:
        self.value = value

    def scalar_one_or_none(self) -> Any:
        return self.value


def test_interaction_batch_isolates_failed_rows_with_savepoints() -> None:
    session = _InteractionSession()

    async def fake_db():
        yield session

    occurred_at = datetime.now(UTC).isoformat()
    app.dependency_overrides[get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/interactions/batch",
            headers=_subject_headers(),
            json={
                "events": [
                    {"event_type": "SERVICE_STARTED", "occurred_at": occurred_at},
                    {
                        "event_type": "MINIMUM_PROFILE_COMPLETED",
                        "occurred_at": occurred_at,
                    },
                ]
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    assert response.json()["data"]["accepted"] == 1
    assert response.json()["data"]["rejected"] == 1
    assert session.savepoint_count == 2
    assert session.savepoint_rollback_count == 1
    assert session.rollback_count == 0
    assert session.commit_count == 1


def test_interaction_client_event_dedupe_reuses_or_rejects_by_payload() -> None:
    session = _InteractionSession(fail_at_flush=None)

    async def fake_db():
        yield session

    client_event_id = str(uuid.uuid4())
    occurred_at = datetime.now(UTC).isoformat()
    app.dependency_overrides[get_db] = fake_db
    try:
        response = TestClient(app).post(
            "/api/v1/interactions/batch",
            headers=_subject_headers(),
            json={
                "events": [
                    {
                        "client_event_id": client_event_id,
                        "event_type": "SERVICE_STARTED",
                        "occurred_at": occurred_at,
                    },
                    {
                        "client_event_id": client_event_id,
                        "event_type": "SERVICE_STARTED",
                        "occurred_at": occurred_at,
                    },
                    {
                        "client_event_id": client_event_id,
                        "event_type": "MINIMUM_PROFILE_COMPLETED",
                        "occurred_at": occurred_at,
                    },
                ]
            },
        )
    finally:
        app.dependency_overrides.pop(get_db, None)

    assert response.status_code == 200
    data = response.json()["data"]
    assert data["accepted"] == 2
    assert data["rejected"] == 1
    assert data["results"][1]["reason"] == "DUPLICATE_IGNORED"
    assert data["results"][2]["reason"] == "IDEMPOTENCY_CONFLICT"
    assert session.flush_count == 1
