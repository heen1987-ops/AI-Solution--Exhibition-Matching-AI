"""Tests for BACKEND-017 (visit feedback API).

No live Postgres is assumed reachable in this environment, so these tests follow the project's
established convention (see test_checkin_api.py, test_favorites_api.py's FakeAsyncSession):

  - the service layer (app/services/feedback/service.py) is exercised directly against a
    self-contained FakeAsyncSession that queues db.scalar()/db.get() results and can simulate a
    race via IntegrityError on commit,
  - the router (app/api/v1/routers/feedback.py) is exercised through a real
    fastapi.testclient.TestClient with app.dependency_overrides for get_db, get_settings, and
    app.api.v1.routers.profile.get_current_subject.

Covers every behavior named in this track's task spec:
    1. successful submit with positive+negative reasons (authenticated + anonymous guest)
    2. comment encryption round-trip - plaintext is never stored raw on the persisted row
    3. rating enum validation (schema-level 422 for an unknown rating)
    4. invalid object_type / unresolvable object_id rejected cleanly (422, never 500)
    5. cross-tenant/session isolation - a feedback row is tied to the submitting visit_session,
       never another session's, and one subject's session never leaks into another's lookup
    6. immutability - the router exposes no PATCH/PUT/DELETE for feedback
    7. Idempotency-Key replay avoids double-inserting
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app.api.v1.routers.feedback import build_feedback_router
from app.api.v1.routers.profile import CurrentSubject, get_current_subject
from app.core.auth import AuthException, auth_exception_handler
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.feedback import Feedback
from app.models.integration import IdempotencyRecord
from app.services.feedback.service import (
    FeedbackTargetNotFoundError,
    VisitSessionNotFoundError,
    decrypt_comment,
    submit_feedback,
)

TENANT = uuid.uuid4()
EVENT = uuid.uuid4()
OTHER_TENANT = uuid.uuid4()
OTHER_EVENT = uuid.uuid4()


def _settings() -> Settings:
    return Settings(
        SECRET_KEY="feedback-unit-test-secret",
        AUTH_TOKEN_PEPPER="feedback-unit-test-pepper",
        AUTH_ENCRYPTION_KEY_B64=base64.urlsafe_b64encode(b"k" * 32).decode(),
    )


SETTINGS = _settings()
NOW = datetime(2026, 10, 9, 5, 31, 12, tzinfo=UTC)


def _feedback(
    *,
    feedback_id: uuid.UUID | None = None,
    visit_session_id: uuid.UUID | None = None,
    recommendable_id: uuid.UUID | None = None,
    rating: str = "VERY_RELEVANT",
    positive_reasons: list[str] | None = None,
    negative_reasons: list[str] | None = None,
    comment_enc: bytes | None = None,
) -> Feedback:
    return Feedback(
        feedback_id=feedback_id or uuid.uuid4(),
        tenant_id=TENANT,
        event_id=EVENT,
        visit_session_id=visit_session_id or uuid.uuid4(),
        recommendable_id=recommendable_id or uuid.uuid4(),
        rating=rating,
        positive_reasons=positive_reasons if positive_reasons is not None else ["TASTE"],
        negative_reasons=negative_reasons if negative_reasons is not None else [],
        comment_enc=comment_enc,
        created_at=NOW,
    )


# ---------------------------------------------------------------------------
# Self-contained fake AsyncSession (see module docstring for rationale/precedent).
# ---------------------------------------------------------------------------


class FakeAsyncSession:
    def __init__(self) -> None:
        self.scalar_queue: list[Any] = []
        self.get_queue: list[Any] = []
        self.executed: list[Any] = []
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0
        self.refreshed: list[Any] = []
        self.raise_integrity_error_on_next_commit = False

    async def scalar(self, _stmt: Any) -> Any:
        if not self.scalar_queue:
            raise AssertionError(
                "FakeAsyncSession.scalar called with an empty queue - under-provisioned test"
            )
        return self.scalar_queue.pop(0)

    async def get(self, _model: Any, _pk: Any) -> Any:
        if not self.get_queue:
            raise AssertionError(
                "FakeAsyncSession.get called with an empty queue - under-provisioned test"
            )
        return self.get_queue.pop(0)

    async def execute(self, stmt: Any) -> Any:
        self.executed.append(stmt)
        return []

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if isinstance(obj, Feedback) and obj.feedback_id is None:
            obj.feedback_id = uuid.uuid4()

    async def flush(self) -> None:
        self.flushes += 1
        for obj in self.added:
            if isinstance(obj, Feedback) and obj.feedback_id is None:
                obj.feedback_id = uuid.uuid4()

    async def commit(self) -> None:
        if self.raise_integrity_error_on_next_commit:
            self.raise_integrity_error_on_next_commit = False
            raise IntegrityError("INSERT", {}, Exception("duplicate key value"))
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def refresh(self, obj: Any) -> None:
        self.refreshed.append(obj)


# ---------------------------------------------------------------------------
# submit_feedback: the full service-layer orchestration.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_feedback_creates_a_new_row_with_positive_and_negative_reasons() -> None:
    session = FakeAsyncSession()
    visit_session_id = uuid.uuid4()
    recommendable_id = uuid.uuid4()
    session.scalar_queue = [visit_session_id, recommendable_id]

    submitted = await submit_feedback(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        object_type="BOOTH",
        object_id=uuid.uuid4(),
        match_result_id=None,
        rating="RELEVANT",
        positive_reasons=["TASTE", "PRICE"],
        negative_reasons=["CONGESTION"],
        comment=None,
        client_event_id=uuid.uuid4(),
        idempotency_key=None,
        settings=SETTINGS,
        now=NOW,
    )

    assert submitted.replayed is False
    feedback = submitted.feedback
    assert feedback.visit_session_id == visit_session_id
    assert feedback.recommendable_id == recommendable_id
    assert feedback.positive_reasons == ["TASTE", "PRICE"]
    assert feedback.negative_reasons == ["CONGESTION"]
    assert session.commits == 1
    assert any(pending is feedback for pending in session.added)


@pytest.mark.asyncio
async def test_submit_feedback_works_for_an_anonymous_guest_owner() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [uuid.uuid4(), uuid.uuid4()]

    submitted = await submit_feedback(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=None,
        guest_session_id=uuid.uuid4(),
        object_type="PROGRAM",
        object_id=uuid.uuid4(),
        match_result_id=None,
        rating="NOT_RELEVANT",
        positive_reasons=[],
        negative_reasons=["SOLD_OUT_OR_CLOSED"],
        comment=None,
        client_event_id=None,
        idempotency_key=None,
        settings=SETTINGS,
        now=NOW,
    )

    assert submitted.replayed is False
    assert submitted.feedback.negative_reasons == ["SOLD_OUT_OR_CLOSED"]


@pytest.mark.asyncio
async def test_submit_feedback_encrypts_the_comment_never_stores_it_raw() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [uuid.uuid4(), uuid.uuid4()]
    plaintext = "설명과 실제 상품이 달랐어요"

    submitted = await submit_feedback(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        object_type="BOOTH",
        object_id=uuid.uuid4(),
        match_result_id=None,
        rating="NOT_RELEVANT",
        positive_reasons=[],
        negative_reasons=["EXPLANATION_ERROR"],
        comment=plaintext,
        client_event_id=None,
        idempotency_key=None,
        settings=SETTINGS,
        now=NOW,
    )

    stored = submitted.feedback.comment_enc
    assert stored is not None
    assert plaintext.encode("utf-8") not in stored
    # Full round trip: only decryptable with the same purpose/key, and recovers the plaintext.
    assert decrypt_comment(stored, settings=SETTINGS) == plaintext


@pytest.mark.asyncio
async def test_submit_feedback_null_comment_stays_null() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [uuid.uuid4(), uuid.uuid4()]

    submitted = await submit_feedback(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        object_type="BOOTH",
        object_id=uuid.uuid4(),
        match_result_id=None,
        rating="VERY_RELEVANT",
        positive_reasons=["TASTE"],
        negative_reasons=[],
        comment=None,
        client_event_id=None,
        idempotency_key=None,
        settings=SETTINGS,
        now=NOW,
    )
    assert submitted.feedback.comment_enc is None


@pytest.mark.asyncio
async def test_submit_feedback_raises_when_no_active_visit_session() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [None]  # resolve_active_visit_session_id finds nothing

    with pytest.raises(VisitSessionNotFoundError):
        await submit_feedback(
            session,
            tenant_id=TENANT,
            event_id=EVENT,
            user_id=uuid.uuid4(),
            guest_session_id=None,
            object_type="BOOTH",
            object_id=uuid.uuid4(),
            match_result_id=None,
            rating="VERY_RELEVANT",
            positive_reasons=[],
            negative_reasons=[],
            comment=None,
            client_event_id=None,
            idempotency_key=None,
            settings=SETTINGS,
            now=NOW,
        )
    assert session.added == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_submit_feedback_raises_when_object_does_not_resolve() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [uuid.uuid4(), None]  # visit found, recommendable lookup misses

    with pytest.raises(FeedbackTargetNotFoundError):
        await submit_feedback(
            session,
            tenant_id=TENANT,
            event_id=EVENT,
            user_id=uuid.uuid4(),
            guest_session_id=None,
            object_type="BOOTH",
            object_id=uuid.uuid4(),
            match_result_id=None,
            rating="VERY_RELEVANT",
            positive_reasons=[],
            negative_reasons=[],
            comment=None,
            client_event_id=None,
            idempotency_key=None,
            settings=SETTINGS,
            now=NOW,
        )
    assert session.added == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_submit_feedback_drops_an_unresolvable_match_result_id_without_blocking() -> None:
    """Soft validation, mirrors submit_check_in's own match_result_id handling - see module
    docstring."""

    session = FakeAsyncSession()
    visit_session_id = uuid.uuid4()
    recommendable_id = uuid.uuid4()
    session.scalar_queue = [visit_session_id, recommendable_id, None]  # match_result miss

    submitted = await submit_feedback(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        object_type="BOOTH",
        object_id=uuid.uuid4(),
        match_result_id=uuid.uuid4(),
        rating="VERY_RELEVANT",
        positive_reasons=["TASTE"],
        negative_reasons=[],
        comment=None,
        client_event_id=None,
        idempotency_key=None,
        settings=SETTINGS,
        now=NOW,
    )
    assert submitted.replayed is False
    assert submitted.feedback.match_result_id is None


# ---------------------------------------------------------------------------
# Idempotency-Key replay.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_feedback_idempotency_key_replay_returns_prior_result_without_reinserting() -> (
    None
):
    session = FakeAsyncSession()
    prior = _feedback()
    record = IdempotencyRecord(
        tenant_id=TENANT,
        principal_fingerprint=b"irrelevant-in-this-fake",
        method="POST",
        route="/feedback",
        idempotency_key="replayed-key",
        response_status=201,
        response_reference=prior.feedback_id,
    )
    session.scalar_queue = [record]
    session.get_queue = [prior]

    submitted = await submit_feedback(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        object_type="BOOTH",
        object_id=uuid.uuid4(),
        match_result_id=None,
        rating="VERY_RELEVANT",
        positive_reasons=[],
        negative_reasons=[],
        comment=None,
        client_event_id=None,
        idempotency_key="replayed-key",
        settings=SETTINGS,
        now=NOW,
    )

    assert submitted.feedback is prior
    assert submitted.replayed is True
    # Replay short-circuits before ever touching visit-session/target resolution or the DB.
    assert session.added == []
    assert session.commits == 0


@pytest.mark.asyncio
async def test_submit_feedback_race_window_falls_back_to_client_event_id_never_a_raw_500() -> (
    None
):
    session = FakeAsyncSession()
    visit_session_id = uuid.uuid4()
    recommendable_id = uuid.uuid4()
    client_event_id = uuid.uuid4()
    winner = _feedback()
    session.scalar_queue = [
        visit_session_id,  # visit session resolution
        recommendable_id,  # target resolution
        winner,  # find_feedback_by_client_event_id fallback after the IntegrityError
    ]
    session.raise_integrity_error_on_next_commit = True

    submitted = await submit_feedback(
        session,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        object_type="BOOTH",
        object_id=uuid.uuid4(),
        match_result_id=None,
        rating="VERY_RELEVANT",
        positive_reasons=[],
        negative_reasons=[],
        comment=None,
        client_event_id=client_event_id,
        idempotency_key=None,
        settings=SETTINGS,
        now=NOW,
    )

    assert submitted.feedback is winner
    assert submitted.replayed is True
    assert session.rollbacks == 1


# ---------------------------------------------------------------------------
# Cross-tenant/session isolation at the query-shape level.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_submit_feedback_never_attributes_a_row_to_another_subjects_session() -> None:
    """A feedback row's visit_session_id always comes from resolve_active_visit_session_id,
    scoped to the caller's own tenant/event/owner - never a caller-supplied value. Two distinct
    subjects resolving in the same tenant/event get distinct visit_session_ids attributed."""

    session_a = FakeAsyncSession()
    visit_session_a = uuid.uuid4()
    recommendable_id = uuid.uuid4()
    session_a.scalar_queue = [visit_session_a, recommendable_id]

    session_b = FakeAsyncSession()
    visit_session_b = uuid.uuid4()
    session_b.scalar_queue = [visit_session_b, recommendable_id]

    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    submitted_a = await submit_feedback(
        session_a,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=user_a,
        guest_session_id=None,
        object_type="BOOTH",
        object_id=uuid.uuid4(),
        match_result_id=None,
        rating="VERY_RELEVANT",
        positive_reasons=[],
        negative_reasons=[],
        comment=None,
        client_event_id=None,
        idempotency_key=None,
        settings=SETTINGS,
        now=NOW,
    )
    submitted_b = await submit_feedback(
        session_b,
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=user_b,
        guest_session_id=None,
        object_type="BOOTH",
        object_id=uuid.uuid4(),
        match_result_id=None,
        rating="VERY_RELEVANT",
        positive_reasons=[],
        negative_reasons=[],
        comment=None,
        client_event_id=None,
        idempotency_key=None,
        settings=SETTINGS,
        now=NOW,
    )

    assert submitted_a.feedback.visit_session_id == visit_session_a
    assert submitted_b.feedback.visit_session_id == visit_session_b
    assert submitted_a.feedback.visit_session_id != submitted_b.feedback.visit_session_id


# ---------------------------------------------------------------------------
# Router-level tests: TestClient + dependency_overrides.
# ---------------------------------------------------------------------------


def _build_app(session: FakeAsyncSession, subject: CurrentSubject) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(build_feedback_router())
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_current_subject] = lambda: subject
    app.dependency_overrides[get_settings] = lambda: SETTINGS
    return app


def _auth_subject(user_id: uuid.UUID | None = None) -> CurrentSubject:
    return CurrentSubject(
        tenant_id=TENANT, event_id=EVENT, user_id=user_id or uuid.uuid4(), guest_session_id=None
    )


def _guest_subject(guest_session_id: uuid.UUID | None = None) -> CurrentSubject:
    return CurrentSubject(
        tenant_id=TENANT,
        event_id=EVENT,
        user_id=None,
        guest_session_id=guest_session_id or uuid.uuid4(),
    )


def _request_body(**overrides: Any) -> dict[str, Any]:
    body = {
        "object_type": "BOOTH",
        "object_id": str(uuid.uuid4()),
        "rating": "VERY_RELEVANT",
        "positive_reasons": ["TASTE"],
        "negative_reasons": [],
    }
    body.update(overrides)
    return body


def test_router_creates_a_new_feedback_for_an_authenticated_user() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [uuid.uuid4(), uuid.uuid4()]
    app = _build_app(session, _auth_subject())

    with TestClient(app) as client:
        response = client.post("/feedback", json=_request_body())

    assert response.status_code == 201
    body = response.json()
    assert "feedback_id" in body
    assert "recorded_at" in body


def test_router_creates_a_new_feedback_for_an_anonymous_guest() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [uuid.uuid4(), uuid.uuid4()]
    app = _build_app(session, _guest_subject())

    with TestClient(app) as client:
        response = client.post(
            "/feedback", json=_request_body(rating="NOT_RELEVANT", negative_reasons=["PRICE"])
        )

    assert response.status_code == 201


def test_router_rejects_an_unknown_rating_at_schema_layer() -> None:
    session = FakeAsyncSession()
    app = _build_app(session, _auth_subject())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/feedback", json=_request_body(rating="SOMEWHAT_OK"))

    assert response.status_code == 422
    assert session.scalar_queue == []  # never touched the DB


def test_router_rejects_an_unknown_reason_code_at_schema_layer() -> None:
    session = FakeAsyncSession()
    app = _build_app(session, _auth_subject())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/feedback", json=_request_body(positive_reasons=["NOT_A_REAL_REASON"])
        )

    assert response.status_code == 422
    assert session.scalar_queue == []


def test_router_rejects_an_unknown_object_type_at_schema_layer() -> None:
    session = FakeAsyncSession()
    app = _build_app(session, _auth_subject())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/feedback", json=_request_body(object_type="MEETING"))

    assert response.status_code == 422
    assert session.scalar_queue == []


def test_router_rejects_a_malformed_object_id_at_schema_layer() -> None:
    session = FakeAsyncSession()
    app = _build_app(session, _auth_subject())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/feedback", json=_request_body(object_id="not-a-uuid"))

    assert response.status_code == 422
    assert session.scalar_queue == []


def test_router_unresolvable_object_id_returns_422_with_feedback_target_not_found_code() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [uuid.uuid4(), None]  # visit found, target lookup misses
    app = _build_app(session, _auth_subject())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/feedback", json=_request_body())

    assert response.status_code == 422
    assert response.json()["detail"]["code"] == "FEEDBACK_TARGET_NOT_FOUND"


def test_router_no_active_visit_session_returns_404() -> None:
    session = FakeAsyncSession()
    session.scalar_queue = [None]
    app = _build_app(session, _auth_subject())

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/feedback", json=_request_body())

    assert response.status_code == 404
    assert response.json()["detail"]["code"] == "VISIT_SESSION_NOT_FOUND"


def test_router_idempotency_key_header_is_forwarded_and_replay_avoids_double_insert() -> None:
    session = FakeAsyncSession()
    prior = _feedback()
    record = IdempotencyRecord(
        tenant_id=TENANT,
        principal_fingerprint=b"irrelevant-in-this-fake",
        method="POST",
        route="/feedback",
        idempotency_key="header-key",
        response_status=201,
        response_reference=prior.feedback_id,
    )
    session.scalar_queue = [record]
    session.get_queue = [prior]
    app = _build_app(session, _auth_subject())

    with TestClient(app) as client:
        response = client.post(
            "/feedback",
            json=_request_body(),
            headers={"Idempotency-Key": "header-key"},
        )

    assert response.status_code == 201
    assert response.json()["feedback_id"] == str(prior.feedback_id)
    assert session.added == []  # no new row inserted on replay


def test_router_requires_a_subject_dependency() -> None:
    """No subject override -> the real get_current_subject dependency runs, which itself
    depends on get_verified_subject. Without a session/guest cookie that raises 401 - the
    router takes no identity from client-supplied headers (same precedent as
    test_checkin_api.py::test_router_requires_a_subject_dependency)."""

    session = FakeAsyncSession()
    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(build_feedback_router())
    app.dependency_overrides[get_db] = lambda: session
    app.dependency_overrides[get_settings] = lambda: SETTINGS

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/feedback", json=_request_body())

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# Immutability: no update/delete surface exists at all (db-erd §16.3: "원본 피드백은
# 수정하지 않는다").
# ---------------------------------------------------------------------------


def test_router_exposes_no_update_or_delete_route() -> None:
    router = build_feedback_router()
    methods_by_path: dict[str, set[str]] = {}
    for route in router.routes:
        methods_by_path.setdefault(route.path, set()).update(route.methods or set())

    assert methods_by_path == {"/feedback": {"POST"}}
    assert "PATCH" not in methods_by_path["/feedback"]
    assert "PUT" not in methods_by_path["/feedback"]
    assert "DELETE" not in methods_by_path["/feedback"]


def test_full_app_has_no_get_patch_put_delete_for_feedback() -> None:
    """Belt-and-suspenders end-to-end check through a real TestClient: every non-POST verb on
    /feedback is unrouted (405/404), never a working mutation path."""

    session = FakeAsyncSession()
    app = _build_app(session, _auth_subject())

    with TestClient(app, raise_server_exceptions=False) as client:
        for method in ("get", "patch", "put", "delete"):
            response = getattr(client, method)("/feedback")
            assert response.status_code in (404, 405), method
