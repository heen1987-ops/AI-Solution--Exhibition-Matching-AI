"""Tests for WAVE 2E BACKEND-NOTIFICATION.

No live Postgres is assumed reachable in this environment, so these tests follow the
project's established convention (see test_exhibitor_preference_api.py, test_search_api.py):

  - model/constraint metadata is asserted directly against ``Base.metadata``,
  - SQL statement builders are compiled and their WHERE clauses asserted as text,
  - the storage-agnostic pipeline (``NotificationService``) is exercised against
    ``InMemoryNotificationRepository`` (the reference implementation
    ``app/services/notification/service.py`` itself designed for exactly this),
  - the router is exercised through a real ``fastapi.testclient.TestClient`` with
    ``app.dependency_overrides[get_notification_service]`` swapped for an in-memory-backed
    service (see ``app/api/v1/routers/notification.py``'s own docstring for why that
    dependency exists).

Covers every behavior named in this track's task spec:
    1. creation from a simulated business event
    2. dedup on repeat event (same business event fired twice -> one notification)
    3. frequency-cap enforcement (RECOMMENDATION_READY 1/day; OPERATOR_NOTICE exempt)
    4. read / read-all
    5. preference-gated email attempt (disabled / no consent basis / sent)
    6. email failure never removes the in-app record
    7. cross-user access denial (service level and router level)
    8. retry/failure logging for delivery attempts (append-only AttemptRecord rows)
"""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routers import notification as notification_router_module
from app.api.v1.routers.notification import (
    build_notification_router,
    get_notification_service,
)
from app.core.auth import (
    AuthException,
    VerifiedPrincipal,
    auth_exception_handler,
    digest_secret,
    get_verified_principal,
)
from app.core.config import get_settings
from app.db.base import Base
from app.models import notification  # noqa: F401  (registers this track's tables)
from app.models.auth import AuthSession
from app.models.notification import NOTIFICATION_CHANNELS, NOTIFICATION_TYPES
from app.schemas.auth import AuthPrincipal
from app.schemas.notification import NotificationChannel, NotificationType
from app.services.notification import triggers
from app.services.notification.email_adapter import EmailSendResult
from app.services.notification.service import (
    BusinessEvent,
    InMemoryNotificationRepository,
    NotificationService,
    RuleResolution,
    UnknownNotificationTypeError,
    dedup_lookup_stmt,
    email_processing_basis_stmt,
    frequency_count_stmt,
    own_notification_stmt,
    own_notifications_stmt,
)

TENANT = uuid.uuid4()
EVENT = uuid.uuid4()


def _event(
    *,
    notification_type: str = "MEETING_ACCEPTED",
    recipient_user_id: uuid.UUID | None = None,
    object_id: uuid.UUID | None = None,
    relevant_version: str | None = "1",
    business_event_code: str = "MEETING_STATUS_CHANGED",
) -> BusinessEvent:
    return BusinessEvent(
        business_event_code=business_event_code,
        notification_type=notification_type,
        tenant_id=TENANT,
        recipient_user_id=recipient_user_id or uuid.uuid4(),
        event_id=EVENT,
        object_type="interaction.meeting",
        object_id=object_id or uuid.uuid4(),
        relevant_version=relevant_version,
        title="상담 요청이 수락되었습니다",
        body="확정된 시간을 확인해 주세요.",
    )


# ---------------------------------------------------------------------------
# Model metadata: tables/constraints exist as the module docstring promises.
# ---------------------------------------------------------------------------


def test_notification_tables_are_registered_with_expected_schema() -> None:
    for table_name in (
        "notification.notification_preferences",
        "notification.notification_templates",
        "notification.notification_rules",
        "notification.notifications",
        "notification.notification_deliveries",
        "notification.notification_delivery_attempts",
    ):
        assert table_name in Base.metadata.tables


def test_notifications_dedup_key_is_a_real_unique_constraint_with_nulls_not_distinct() -> None:
    table = Base.metadata.tables["notification.notifications"]
    dedup_constraints = [
        c
        for c in table.constraints
        if c.__class__.__name__ == "UniqueConstraint"
        and {col.name for col in c.columns}
        == {
            "tenant_id",
            "notification_type",
            "recipient_user_id",
            "object_id",
            "relevant_version",
        }
    ]
    assert len(dedup_constraints) == 1
    assert dedup_constraints[0].dialect_options["postgresql"]["nulls_not_distinct"] is True


def test_notification_deliveries_one_row_per_notification_per_channel() -> None:
    table = Base.metadata.tables["notification.notification_deliveries"]
    unique_columns = {
        tuple(c.name for c in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("notification_id", "channel") in unique_columns


def test_delivery_attempts_table_is_append_only_shaped_unique_per_attempt_number() -> None:
    table = Base.metadata.tables["notification.notification_delivery_attempts"]
    unique_columns = {
        tuple(c.name for c in constraint.columns)
        for constraint in table.constraints
        if constraint.__class__.__name__ == "UniqueConstraint"
    }
    assert ("notification_delivery_id", "attempt_number") in unique_columns


def test_notification_type_literal_matches_the_check_constraint_source_of_truth() -> None:
    """Guards against the two lists (schemas Literal vs models CHECK tuple) drifting - see
    app/schemas/notification.py's own docstring for why this duplication exists."""

    assert set(NotificationType.__args__) == set(NOTIFICATION_TYPES)
    assert set(NotificationChannel.__args__) == set(NOTIFICATION_CHANNELS)


# ---------------------------------------------------------------------------
# Statement builders: compile and assert the WHERE clauses.
# ---------------------------------------------------------------------------


def _compiled(stmt: Any) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


def test_dedup_lookup_stmt_is_null_safe_for_object_id_and_relevant_version() -> None:
    tenant_id = uuid.uuid4()
    recipient = uuid.uuid4()
    sql = _compiled(
        dedup_lookup_stmt(
            tenant_id=tenant_id,
            notification_type="OPERATOR_NOTICE",
            recipient_user_id=recipient,
            object_id=None,
            relevant_version=None,
        )
    )
    assert "notifications.object_id IS NULL" in sql
    assert "notifications.relevant_version IS NULL" in sql
    assert tenant_id.hex in sql.replace("-", "")


def test_frequency_count_stmt_scopes_to_recipient_type_and_day_window() -> None:
    tenant_id = uuid.uuid4()
    recipient = uuid.uuid4()
    day_start = datetime(2026, 8, 3, tzinfo=UTC)
    sql = _compiled(
        frequency_count_stmt(
            tenant_id=tenant_id,
            recipient_user_id=recipient,
            notification_type="RECOMMENDATION_READY",
            day_start=day_start,
            day_end=day_start + timedelta(days=1),
        )
    )
    assert "notifications.notification_type = 'RECOMMENDATION_READY'" in sql
    assert "notifications.created_at >=" in sql
    assert "notifications.created_at <" in sql


def test_email_processing_basis_stmt_requires_notification_email_purpose_and_effective_window() -> (
    None
):
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    now = datetime(2026, 8, 3, tzinfo=UTC)
    sql = _compiled(email_processing_basis_stmt(tenant_id=tenant_id, user_id=user_id, now=now))
    assert "consent_policy.purpose = 'NOTIFICATION_EMAIL'" in sql
    assert "consent_policy.effective_from <=" in sql


def test_own_notifications_stmt_filters_by_recipient_never_a_post_filter() -> None:
    recipient = uuid.uuid4()
    sql = _compiled(
        own_notifications_stmt(
            tenant_id=uuid.uuid4(),
            recipient_user_id=recipient, unread_only=True, before=None, limit=20
        )
    )
    assert recipient.hex in sql.replace("-", "")
    assert "notifications.recipient_user_id =" in sql
    assert "notifications.read_at IS NULL" in sql


def test_own_notification_stmt_requires_both_id_and_recipient_match() -> None:
    recipient = uuid.uuid4()
    notification_id = uuid.uuid4()
    sql = _compiled(
        own_notification_stmt(tenant_id=uuid.uuid4(), recipient_user_id=recipient, notification_id=notification_id)
    )
    stripped = sql.replace("-", "")
    assert notification_id.hex in stripped
    assert recipient.hex in stripped


# ---------------------------------------------------------------------------
# 1 & 2. Creation from a simulated business event + dedup on repeat.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_handle_business_event_creates_notification_and_in_app_delivery() -> None:
    service = NotificationService(InMemoryNotificationRepository())
    recipient = uuid.uuid4()

    outcome = await service.handle_business_event(_event(recipient_user_id=recipient))

    assert outcome.result == "CREATED"
    assert outcome.notification is not None
    assert outcome.notification.recipient_user_id == recipient
    records = await service.list_notifications(tenant_id=TENANT, recipient_user_id=recipient)
    assert len(records) == 1
    assert records[0].notification_type == "MEETING_ACCEPTED"


@pytest.mark.asyncio
async def test_firing_the_same_business_event_twice_creates_only_one_notification() -> None:
    service = NotificationService(InMemoryNotificationRepository())
    recipient = uuid.uuid4()
    object_id = uuid.uuid4()
    event = _event(recipient_user_id=recipient, object_id=object_id, relevant_version="4")

    first = await service.handle_business_event(event)
    second = await service.handle_business_event(event)

    assert first.result == "CREATED"
    assert second.result == "DUPLICATE"
    records = await service.list_notifications(tenant_id=TENANT, recipient_user_id=recipient)
    assert len(records) == 1


@pytest.mark.asyncio
async def test_a_new_relevant_version_is_a_distinct_notification_not_a_duplicate() -> None:
    """The counterpart of the dedup test: an actual state change (new row_version) must fire
    again - "status-change notifications only fire on an actual state change"."""

    service = NotificationService(InMemoryNotificationRepository())
    recipient = uuid.uuid4()
    object_id = uuid.uuid4()

    first = await service.handle_business_event(
        _event(recipient_user_id=recipient, object_id=object_id, relevant_version="1")
    )
    second = await service.handle_business_event(
        _event(recipient_user_id=recipient, object_id=object_id, relevant_version="2")
    )

    assert first.result == "CREATED"
    assert second.result == "CREATED"
    records = await service.list_notifications(tenant_id=TENANT, recipient_user_id=recipient)
    assert len(records) == 2


@pytest.mark.asyncio
async def test_unknown_notification_type_is_rejected() -> None:
    service = NotificationService(InMemoryNotificationRepository())
    with pytest.raises(UnknownNotificationTypeError):
        await service.handle_business_event(_event(notification_type="NOT_A_REAL_TYPE"))


# ---------------------------------------------------------------------------
# 3. Frequency cap enforcement.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_recommendation_ready_is_capped_at_one_per_recipient_per_day() -> None:
    service = NotificationService(InMemoryNotificationRepository())
    recipient = uuid.uuid4()

    first = await service.handle_business_event(
        _event(
            notification_type="RECOMMENDATION_READY",
            recipient_user_id=recipient,
            object_id=uuid.uuid4(),
            relevant_version="session-a",
            business_event_code="RECOMMENDATION_GENERATED",
        )
    )
    second = await service.handle_business_event(
        _event(
            notification_type="RECOMMENDATION_READY",
            recipient_user_id=recipient,
            object_id=uuid.uuid4(),  # a different session -> would not dedup on its own
            relevant_version="session-b",
            business_event_code="RECOMMENDATION_GENERATED",
        )
    )

    assert first.result == "CREATED"
    assert second.result == "SUPPRESSED_FREQUENCY_CAP"
    records = await service.list_notifications(tenant_id=TENANT, recipient_user_id=recipient)
    assert len(records) == 1


@pytest.mark.asyncio
async def test_operator_notice_is_exempt_from_any_frequency_cap() -> None:
    service = NotificationService(InMemoryNotificationRepository())
    recipient = uuid.uuid4()

    outcomes = []
    for i in range(3):
        outcomes.append(
            await service.handle_business_event(
                _event(
                    notification_type="OPERATOR_NOTICE",
                    recipient_user_id=recipient,
                    object_id=uuid.uuid4(),
                    relevant_version=str(i),
                    business_event_code="OPERATOR_NOTICE_PUBLISHED",
                )
            )
        )

    assert all(outcome.result == "CREATED" for outcome in outcomes)
    records = await service.list_notifications(tenant_id=TENANT, recipient_user_id=recipient)
    assert len(records) == 3


@pytest.mark.asyncio
async def test_persisted_rule_overrides_the_in_code_default_cap() -> None:
    repository = InMemoryNotificationRepository()
    repository.rules["MEETING_ACCEPTED"] = RuleResolution(
        notification_type="MEETING_ACCEPTED",
        frequency_cap_per_recipient_per_day=1,
        is_operational=False,
    )
    service = NotificationService(repository)
    recipient = uuid.uuid4()

    first = await service.handle_business_event(
        _event(recipient_user_id=recipient, object_id=uuid.uuid4(), relevant_version="1")
    )
    second = await service.handle_business_event(
        _event(recipient_user_id=recipient, object_id=uuid.uuid4(), relevant_version="2")
    )

    assert first.result == "CREATED"
    assert second.result == "SUPPRESSED_FREQUENCY_CAP"


# ---------------------------------------------------------------------------
# 4. Read / read-all.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_read_flips_read_at_and_unread_count_drops() -> None:
    service = NotificationService(InMemoryNotificationRepository())
    recipient = uuid.uuid4()
    outcome = await service.handle_business_event(_event(recipient_user_id=recipient))
    notification_id = outcome.notification.notification_id

    assert await service.unread_count(tenant_id=TENANT, recipient_user_id=recipient) == 1
    read_at = await service.mark_read(
        tenant_id=TENANT,
        recipient_user_id=recipient, notification_id=notification_id
    )
    assert read_at is not None
    assert await service.unread_count(tenant_id=TENANT, recipient_user_id=recipient) == 0


@pytest.mark.asyncio
async def test_mark_read_is_idempotent_keeps_first_read_at() -> None:
    service = NotificationService(InMemoryNotificationRepository())
    recipient = uuid.uuid4()
    outcome = await service.handle_business_event(_event(recipient_user_id=recipient))
    notification_id = outcome.notification.notification_id

    first = await service.mark_read(tenant_id=TENANT, recipient_user_id=recipient, notification_id=notification_id)
    second = await service.mark_read(
        tenant_id=TENANT,
        recipient_user_id=recipient, notification_id=notification_id, now=datetime.now(UTC)
    )
    assert first == second


@pytest.mark.asyncio
async def test_mark_all_read_marks_only_that_recipients_unread_rows() -> None:
    service = NotificationService(InMemoryNotificationRepository())
    recipient = uuid.uuid4()
    other = uuid.uuid4()
    await service.handle_business_event(
        _event(recipient_user_id=recipient, object_id=uuid.uuid4(), relevant_version="1")
    )
    await service.handle_business_event(
        _event(recipient_user_id=recipient, object_id=uuid.uuid4(), relevant_version="2")
    )
    await service.handle_business_event(_event(recipient_user_id=other))

    marked = await service.mark_all_read(tenant_id=TENANT, recipient_user_id=recipient)

    assert marked == 2
    assert await service.unread_count(tenant_id=TENANT, recipient_user_id=recipient) == 0
    assert await service.unread_count(tenant_id=TENANT, recipient_user_id=other) == 1


# ---------------------------------------------------------------------------
# 5 & 6 & 8. Email preference/consent gating, failure isolation, attempt logging.
# ---------------------------------------------------------------------------


class _FakeAdapter:
    def __init__(self, *, succeed: bool = True, raise_instead: bool = False) -> None:
        self.succeed = succeed
        self.raise_instead = raise_instead
        self.calls: list[uuid.UUID] = []

    async def send(self, *, recipient_user_id: uuid.UUID, subject: str, body: str) -> EmailSendResult:
        del subject, body
        self.calls.append(recipient_user_id)
        if self.raise_instead:
            raise RuntimeError("simulated adapter bug")
        return EmailSendResult(success=self.succeed, error_message=None if self.succeed else "boom")


@pytest.mark.asyncio
async def test_email_skipped_when_preference_disabled_in_app_still_created() -> None:
    repository = InMemoryNotificationRepository()
    adapter = _FakeAdapter()
    service = NotificationService(repository, email_adapter=adapter)
    recipient = uuid.uuid4()

    outcome = await service.handle_business_event(_event(recipient_user_id=recipient))

    assert outcome.result == "CREATED"
    assert outcome.email_result == "SKIPPED_PREFERENCE_DISABLED"
    assert adapter.calls == []
    in_app = [d for d in repository.deliveries if d.channel == "IN_APP"]
    assert len(in_app) == 1 and in_app[0].status == "SENT"


@pytest.mark.asyncio
async def test_email_skipped_when_preference_enabled_but_no_consent_basis() -> None:
    repository = InMemoryNotificationRepository()
    recipient = uuid.uuid4()
    repository.preferences[(TENANT, recipient, "MEETING_ACCEPTED")] = True
    adapter = _FakeAdapter()
    service = NotificationService(repository, email_adapter=adapter)

    outcome = await service.handle_business_event(_event(recipient_user_id=recipient))

    assert outcome.email_result == "SKIPPED_CONSENT_MISSING"
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_email_sent_when_preference_and_consent_basis_both_present() -> None:
    repository = InMemoryNotificationRepository()
    recipient = uuid.uuid4()
    repository.preferences[(TENANT, recipient, "MEETING_ACCEPTED")] = True
    repository.email_consent_basis.add((TENANT, recipient))
    adapter = _FakeAdapter(succeed=True)
    service = NotificationService(repository, email_adapter=adapter)

    outcome = await service.handle_business_event(_event(recipient_user_id=recipient))

    assert outcome.email_result == "SENT"
    assert adapter.calls == [recipient]
    email_deliveries = [d for d in repository.deliveries if d.channel == "EMAIL"]
    assert len(email_deliveries) == 1 and email_deliveries[0].status == "SENT"
    attempts = [a for a in repository.attempts if a.status == "SUCCESS"]
    assert len(attempts) == 1
    assert attempts[0].attempt_number == 1


@pytest.mark.asyncio
async def test_email_provider_failure_never_removes_the_in_app_record() -> None:
    repository = InMemoryNotificationRepository()
    recipient = uuid.uuid4()
    repository.preferences[(TENANT, recipient, "MEETING_ACCEPTED")] = True
    repository.email_consent_basis.add((TENANT, recipient))
    adapter = _FakeAdapter(succeed=False)
    service = NotificationService(repository, email_adapter=adapter)

    outcome = await service.handle_business_event(_event(recipient_user_id=recipient))

    assert outcome.result == "CREATED"
    assert outcome.email_result == "FAILED"
    in_app = [d for d in repository.deliveries if d.channel == "IN_APP"]
    assert len(in_app) == 1 and in_app[0].status == "SENT"
    records = await service.list_notifications(tenant_id=TENANT, recipient_user_id=recipient)
    assert len(records) == 1
    email_attempts = [a for a in repository.attempts if a.status == "FAILED"]
    assert len(email_attempts) == 1


@pytest.mark.asyncio
async def test_a_misbehaving_adapter_that_raises_still_never_touches_the_in_app_record() -> None:
    repository = InMemoryNotificationRepository()
    recipient = uuid.uuid4()
    repository.preferences[(TENANT, recipient, "MEETING_ACCEPTED")] = True
    repository.email_consent_basis.add((TENANT, recipient))
    adapter = _FakeAdapter(raise_instead=True)
    service = NotificationService(repository, email_adapter=adapter)

    outcome = await service.handle_business_event(_event(recipient_user_id=recipient))

    assert outcome.result == "CREATED"
    assert outcome.email_result == "FAILED"
    in_app = [d for d in repository.deliveries if d.channel == "IN_APP"]
    assert len(in_app) == 1 and in_app[0].status == "SENT"


# ---------------------------------------------------------------------------
# 7. Cross-user access denial (service level).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_mark_read_for_someone_elses_notification_returns_none() -> None:
    service = NotificationService(InMemoryNotificationRepository())
    owner = uuid.uuid4()
    intruder = uuid.uuid4()
    outcome = await service.handle_business_event(_event(recipient_user_id=owner))

    result = await service.mark_read(
        tenant_id=TENANT,
        recipient_user_id=intruder, notification_id=outcome.notification.notification_id
    )

    assert result is None
    # and the owner's copy is genuinely untouched
    assert await service.unread_count(tenant_id=TENANT, recipient_user_id=owner) == 1


@pytest.mark.asyncio
async def test_list_notifications_never_leaks_another_recipients_rows() -> None:
    service = NotificationService(InMemoryNotificationRepository())
    owner = uuid.uuid4()
    intruder = uuid.uuid4()
    await service.handle_business_event(_event(recipient_user_id=owner))

    assert await service.list_notifications(tenant_id=TENANT, recipient_user_id=intruder) == []


# ---------------------------------------------------------------------------
# Trigger builders (app/services/notification/triggers.py).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_notify_meeting_accepted_builds_the_expected_business_event() -> None:
    service = NotificationService(InMemoryNotificationRepository())
    recipient = uuid.uuid4()
    meeting_id = uuid.uuid4()

    outcome = await triggers.notify_meeting_accepted(
        service,
        tenant_id=TENANT,
        event_id=EVENT,
        recipient_user_id=recipient,
        meeting_id=meeting_id,
        row_version=3,
    )

    assert outcome.result == "CREATED"
    assert outcome.notification.notification_type == "MEETING_ACCEPTED"
    assert outcome.notification.object_id == meeting_id
    assert outcome.notification.relevant_version == "3"


@pytest.mark.asyncio
async def test_firing_notify_meeting_accepted_twice_via_the_trigger_helper_does_not_duplicate() -> (
    None
):
    service = NotificationService(InMemoryNotificationRepository())
    recipient = uuid.uuid4()
    meeting_id = uuid.uuid4()

    await triggers.notify_meeting_accepted(
        service,
        tenant_id=TENANT,
        event_id=EVENT,
        recipient_user_id=recipient,
        meeting_id=meeting_id,
        row_version=5,
    )
    second = await triggers.notify_meeting_accepted(
        service,
        tenant_id=TENANT,
        event_id=EVENT,
        recipient_user_id=recipient,
        meeting_id=meeting_id,
        row_version=5,
    )

    assert second.result == "DUPLICATE"
    records = await service.list_notifications(tenant_id=TENANT, recipient_user_id=recipient)
    assert len(records) == 1


@pytest.mark.asyncio
async def test_notify_recommendation_ready_versions_by_calendar_date() -> None:
    service = NotificationService(InMemoryNotificationRepository())
    recipient = uuid.uuid4()

    outcome = await triggers.notify_recommendation_ready(
        service,
        tenant_id=TENANT,
        event_id=EVENT,
        recipient_user_id=recipient,
        recommendation_session_id=uuid.uuid4(),
        batch_date=date(2026, 8, 3),
    )

    assert outcome.notification.relevant_version == "2026-08-03"


@pytest.mark.asyncio
async def test_notify_content_review_result_distinguishes_approved_vs_rejected_versions() -> (
    None
):
    service = NotificationService(InMemoryNotificationRepository())
    recipient = uuid.uuid4()
    document_id = uuid.uuid4()

    approved = await triggers.notify_content_review_result(
        service,
        tenant_id=TENANT,
        event_id=EVENT,
        recipient_user_id=recipient,
        document_id=document_id,
        version_no=1,
        approved=True,
    )
    rejected_then_reapproved = await triggers.notify_content_review_result(
        service,
        tenant_id=TENANT,
        event_id=EVENT,
        recipient_user_id=recipient,
        document_id=document_id,
        version_no=1,
        approved=False,
    )

    assert approved.result == "CREATED"
    # same version_no but a different decision -> a distinct notification, not a duplicate
    assert rejected_then_reapproved.result == "CREATED"


# ---------------------------------------------------------------------------
# Router-level tests: TestClient + dependency_overrides.
#
# Authentication (merge plan STEP 24): the router no longer reads X-Actor-User-Id or
# X-Tenant-Id. The caller is a verified principal, so these tests establish one by
# overriding ``app.core.auth.get_verified_principal`` - and, because the three mutating
# routes are CSRF-protected, the principal carries a browser session whose real
# ``csrf_hmac`` the test matches with a genuine ``X-CSRF-Token`` header.
# ---------------------------------------------------------------------------


CSRF_TOKEN = "notification-router-test-csrf-token"


def _session(*, csrf_token: str = CSRF_TOKEN) -> AuthSession:
    """A browser session object (never persisted) carrying a real CSRF hmac."""

    return AuthSession(
        state="AUTHENTICATED",
        csrf_hmac=digest_secret(csrf_token, purpose="csrf", settings=get_settings()),
    )


def _principal(
    user_id: uuid.UUID,
    *,
    tenant_id: uuid.UUID = TENANT,
    session: AuthSession | None = None,
) -> VerifiedPrincipal:
    return VerifiedPrincipal(
        principal=AuthPrincipal(
            subject_type="USER",
            subject_id=user_id,
            tenant_id=tenant_id,
            event_id=EVENT,
            role_grants=[],
            authn_level="AAL1",
            amr={"magic_link"},
            authenticated_at=datetime.now(UTC),
            mfa_at=None,
        ),
        session=session if session is not None else _session(),
    )


def _build_app(
    service: NotificationService,
    *,
    user_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID = TENANT,
    principal: VerifiedPrincipal | None = None,
    authenticated: bool = True,
) -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(build_notification_router())
    app.dependency_overrides[get_notification_service] = lambda: service
    if authenticated:
        resolved = principal or _principal(user_id or uuid.uuid4(), tenant_id=tenant_id)
        app.dependency_overrides[get_verified_principal] = lambda: resolved
    return app


def _csrf() -> dict[str, str]:
    return {"X-CSRF-Token": CSRF_TOKEN}


@pytest.fixture
def repository() -> InMemoryNotificationRepository:
    return InMemoryNotificationRepository()


NOTIFICATION_ROUTES = [
    ("GET", "/me/notifications", None),
    ("GET", "/me/notifications/unread-count", None),
    ("POST", f"/me/notifications/{uuid.uuid4()}/read", None),
    ("POST", "/me/notifications/read-all", None),
    ("GET", "/me/notification-preferences", None),
    ("PATCH", "/me/notification-preferences", {"items": []}),
]


@pytest.mark.parametrize(("method", "path", "body"), NOTIFICATION_ROUTES)
def test_router_requires_a_verified_session(method: str, path: str, body: dict | None) -> None:
    """No header identifies a caller any more - all six routes are 401 without a session."""

    service = NotificationService(InMemoryNotificationRepository())
    app = _build_app(service, authenticated=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize(("method", "path", "body"), NOTIFICATION_ROUTES)
def test_router_ignores_a_forged_actor_header(method: str, path: str, body: dict | None) -> None:
    service = NotificationService(InMemoryNotificationRepository())
    app = _build_app(service, authenticated=False)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request(
            method,
            path,
            json=body,
            headers={
                "X-Actor-User-Id": str(uuid.uuid4()),
                "X-Tenant-Id": str(uuid.uuid4()),
                **_csrf(),
            },
        )
    assert response.status_code == 401


def test_router_module_takes_no_identity_from_headers() -> None:
    """Regression guard for the two deleted header stubs. ``get_verified_subject`` must not
    appear either: a kiosk ``VerifiedGuest`` has no ``user_id`` and owns no inbox."""

    source = inspect.getsource(notification_router_module)
    tree = ast.parse(source)
    docstring_end = tree.body[0].end_lineno or 0
    code = "\n".join(source.splitlines()[docstring_end:])

    assert not hasattr(notification_router_module, "get_actor_user_id")
    assert not hasattr(notification_router_module, "get_actor_tenant_id")
    assert "get_verified_subject" not in code
    assert "Header(" not in code
    assert "X-Actor-User-Id" not in code
    assert "X-Tenant-Id" not in code


def test_router_lists_and_counts_unread_notifications(repository) -> None:
    service = NotificationService(repository)
    recipient = uuid.uuid4()
    app = _build_app(service, user_id=recipient)

    import asyncio

    asyncio.run(service.handle_business_event(_event(recipient_user_id=recipient)))

    with TestClient(app) as client:
        listed = client.get("/me/notifications")
        unread = client.get("/me/notifications/unread-count")

    assert listed.status_code == 200
    body = listed.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["notification_type"] == "MEETING_ACCEPTED"
    assert unread.json() == {"unread_count": 1}


def test_router_scopes_reads_to_the_sessions_own_tenant(repository) -> None:
    """The tenant is the session's, not a header's: the same user id under a different
    tenant sees an empty inbox rather than another tenant's rows."""

    service = NotificationService(repository)
    recipient = uuid.uuid4()

    import asyncio

    asyncio.run(service.handle_business_event(_event(recipient_user_id=recipient)))

    own_tenant_app = _build_app(service, user_id=recipient, tenant_id=TENANT)
    with TestClient(own_tenant_app) as client:
        assert len(client.get("/me/notifications").json()["items"]) == 1

    other_tenant_app = _build_app(service, user_id=recipient, tenant_id=uuid.uuid4())
    with TestClient(other_tenant_app) as client:
        assert client.get("/me/notifications").json()["items"] == []
        assert client.get("/me/notifications/unread-count").json() == {"unread_count": 0}


def test_router_mark_read_then_unread_count_drops(repository) -> None:
    service = NotificationService(repository)
    recipient = uuid.uuid4()
    app = _build_app(service, user_id=recipient)

    import asyncio

    outcome = asyncio.run(service.handle_business_event(_event(recipient_user_id=recipient)))
    notification_id = outcome.notification.notification_id

    with TestClient(app) as client:
        response = client.post(
            f"/me/notifications/{notification_id}/read", headers=_csrf()
        )
        unread = client.get("/me/notifications/unread-count")

    assert response.status_code == 200
    assert response.json()["notification_id"] == str(notification_id)
    assert unread.json() == {"unread_count": 0}


def test_router_mark_read_on_someone_elses_notification_is_404(repository) -> None:
    """The intruder is fully authenticated - the refusal comes from the ownership WHERE
    clause, and it is 404 rather than 403 so the row's existence is not disclosed."""

    service = NotificationService(repository)
    owner = uuid.uuid4()
    intruder = uuid.uuid4()
    app = _build_app(service, user_id=intruder)

    import asyncio

    outcome = asyncio.run(service.handle_business_event(_event(recipient_user_id=owner)))
    notification_id = outcome.notification.notification_id

    with TestClient(app) as client:
        response = client.post(
            f"/me/notifications/{notification_id}/read", headers=_csrf()
        )

    assert response.status_code == 404
    # ...and the owner's row is untouched.
    assert asyncio.run(
        service.unread_count(tenant_id=TENANT, recipient_user_id=owner)
    ) == 1


def test_router_mark_all_read_never_touches_another_users_rows(repository) -> None:
    service = NotificationService(repository)
    recipient = uuid.uuid4()
    other = uuid.uuid4()
    app = _build_app(service, user_id=recipient)

    import asyncio

    asyncio.run(
        service.handle_business_event(
            _event(recipient_user_id=recipient, object_id=uuid.uuid4(), relevant_version="1")
        )
    )
    asyncio.run(
        service.handle_business_event(
            _event(recipient_user_id=recipient, object_id=uuid.uuid4(), relevant_version="2")
        )
    )
    asyncio.run(service.handle_business_event(_event(recipient_user_id=other)))

    with TestClient(app) as client:
        response = client.post("/me/notifications/read-all", headers=_csrf())

    assert response.status_code == 200
    assert response.json() == {"marked_count": 2}
    assert asyncio.run(
        service.unread_count(tenant_id=TENANT, recipient_user_id=other)
    ) == 1


@pytest.mark.parametrize(
    ("method", "path", "body"),
    [
        ("POST", f"/me/notifications/{uuid.uuid4()}/read", None),
        ("POST", "/me/notifications/read-all", None),
        ("PATCH", "/me/notification-preferences", {"items": []}),
    ],
)
def test_mutating_routes_require_a_csrf_token(
    method: str, path: str, body: dict | None
) -> None:
    service = NotificationService(InMemoryNotificationRepository())
    app = _build_app(service)
    with TestClient(app, raise_server_exceptions=False) as client:
        missing = client.request(method, path, json=body)
        wrong = client.request(
            method, path, json=body, headers={"X-CSRF-Token": "not-the-session-token"}
        )
    assert missing.status_code == 403
    assert missing.json()["code"] == "CSRF_FAILED"
    assert wrong.status_code == 403
    assert wrong.json()["code"] == "CSRF_FAILED"


@pytest.mark.parametrize(
    "path", ["/me/notifications", "/me/notifications/unread-count", "/me/notification-preferences"]
)
def test_read_routes_do_not_require_a_csrf_token(path: str, repository) -> None:
    service = NotificationService(repository)
    app = _build_app(service)
    with TestClient(app, raise_server_exceptions=False) as client:
        assert client.get(path).status_code == 200


def test_a_non_browser_principal_cannot_mutate() -> None:
    """``require_csrf`` runs through ``require_browser_session``: a service-JWT principal
    (session is None) has no CSRF binding and is refused from a personal inbox."""

    service = NotificationService(InMemoryNotificationRepository())
    principal = VerifiedPrincipal(
        principal=AuthPrincipal(
            subject_type="SERVICE",
            subject_id=uuid.uuid4(),
            tenant_id=TENANT,
            event_id=EVENT,
            role_grants=[],
            authn_level="AAL1",
            amr={"service_jwt"},
            authenticated_at=datetime.now(UTC),
            mfa_at=None,
        ),
        session=None,
    )
    app = _build_app(service, principal=principal)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post("/me/notifications/read-all", headers=_csrf())
    assert response.status_code == 403
    assert response.json()["code"] == "RESOURCE_FORBIDDEN"


def test_router_get_and_patch_notification_preferences(repository) -> None:
    service = NotificationService(repository)
    user_id = uuid.uuid4()
    app = _build_app(service, user_id=user_id)

    with TestClient(app) as client:
        initial = client.get("/me/notification-preferences")
        assert initial.status_code == 200
        assert all(item["email_enabled"] is False for item in initial.json()["items"])

        patched = client.patch(
            "/me/notification-preferences",
            headers=_csrf(),
            json={"items": [{"notification_type": "MEETING_ACCEPTED", "email_enabled": True}]},
        )

    assert patched.status_code == 200
    items = {item["notification_type"]: item["email_enabled"] for item in patched.json()["items"]}
    assert items["MEETING_ACCEPTED"] is True
    assert items["OPERATOR_NOTICE"] is False


def test_preferences_are_written_under_the_sessions_tenant(repository) -> None:
    service = NotificationService(repository)
    user_id = uuid.uuid4()
    app = _build_app(service, user_id=user_id, tenant_id=TENANT)

    with TestClient(app) as client:
        client.patch(
            "/me/notification-preferences",
            headers=_csrf(),
            json={"items": [{"notification_type": "MEETING_ACCEPTED", "email_enabled": True}]},
        )

    assert repository.preferences[(TENANT, user_id, "MEETING_ACCEPTED")] is True


def test_router_patch_preferences_rejects_unknown_notification_type_at_schema_layer() -> None:
    """NotificationPreferenceItem.notification_type is a Literal - FastAPI/Pydantic reject an
    unknown type with 422 before the service layer's UnknownNotificationTypeError could even
    be reached, which is the stronger guarantee."""

    service = NotificationService(InMemoryNotificationRepository())
    app = _build_app(service)

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.patch(
            "/me/notification-preferences",
            headers=_csrf(),
            json={"items": [{"notification_type": "NOT_A_TYPE", "email_enabled": True}]},
        )

    assert response.status_code == 422
