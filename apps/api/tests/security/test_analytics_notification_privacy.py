"""WAVE 2E (QA-OPERATIONS) security/privacy tests for the
event-collection / aggregation / analytics-dashboard / notification pipeline.

Scope: ``apps/api/tests/security/test_analytics_notification_privacy.py`` (owned by the
QA-OPERATIONS track, this task's explicit OWNED PATHS override).

These tests target the seven highest-priority failure modes called out for this track:

    1. zero raw search-query-text/PII leakage anywhere in analytics output
    2. zero optional-notification sent without consent
    3. zero cross-user notification access
    4. zero kiosk user-identification (no user_id/contact info ever attached to a
       kiosk-sourced event)
    5. zero small-group (<5) statistic exposure
    6. event dedup/aggregation consistency (no double counting across a simulated
       re-aggregation)
    7. zero competitor-detail-stat leakage to the EXHIBITOR_ADMIN role

See ``apps/api/tests/integration/test_operations_analytics_e2e.py``'s module docstring for the
environment notes (no live Postgres; which routers exist vs. don't) - not repeated here.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
import uuid
from datetime import UTC, date, datetime
from types import SimpleNamespace
from typing import Any, Self

import pytest
from pydantic import ValidationError
from sqlalchemy import CheckConstraint

from app.models.analytics import (
    AnalyticsDailyMetric,
    AnalyticsFunnelMetric,
    AnalyticsSearchNoResultSummary,
)
from app.models.interaction_event import EventIngestionFailure
from app.schemas.analytics import SMALL_GROUP_SUPPRESSION_THRESHOLD, Metric
from app.schemas.interaction_event import ClientInteractionBatchRequest
from app.services.analytics.access import (
    AnalyticsAccessDenied,
    resolve_analytics_access,
)
from app.services.analytics.suppression import (
    drop_small_groups,
    redact_query_text,
    suppress_metric,
    suppress_rate,
)
from app.services.interaction_event.ingestion import ingest_client_events
from app.services.interaction_event.masking import mask_search_query
from app.services.interaction_event.validation import (
    find_forbidden_kiosk_keys,
    parse_client_event,
)
from app.services.notification.email_adapter import EmailSendResult
from app.services.notification.service import (
    BusinessEvent,
    InMemoryNotificationRepository,
    NotificationService,
    own_notification_stmt,
    own_notifications_stmt,
    unread_count_stmt,
)

# Note: apps/api/pyproject.toml sets asyncio_mode = "auto", so ``async def test_*`` functions
# are collected as coroutine tests without needing an explicit @pytest.mark.asyncio marker.

TENANT_ID = uuid.uuid4()
EVENT_ID = uuid.uuid4()


# ---------------------------------------------------------------------------
# A minimal AsyncSession double for ``ingest_client_events``, defined locally (not imported
# from test_operations_analytics_e2e.py) - this repo's convention is that each test file is
# self-contained (see test_buyer_meeting_e2e.py / test_buyer_meeting_privacy.py, which each
# define their own fakes independently rather than importing one another), and pytest's
# rootless (no __init__.py) test collection makes cross-test-file imports fragile anyway
# (module identity depends on collection order across two different tests/ subdirectories).
# ---------------------------------------------------------------------------


class _Result:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _NestedTxn:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(self, *exc_info: object) -> bool:
        return False


class FakeAsyncSession:
    """See test_operations_analytics_e2e.py's identical class for the full rationale."""

    def __init__(self, claim_queue: list[Any] | None = None) -> None:
        self._queue = list(claim_queue or [])
        self.added: list[Any] = []
        self.commits = 0

    async def execute(self, _statement: Any) -> _Result:
        if not self._queue:
            raise AssertionError(
                "FakeAsyncSession.execute called with an empty claim queue - "
                "the test under-provisioned it"
            )
        return _Result(self._queue.pop(0))

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        return None

    def begin_nested(self) -> _NestedTxn:
        return _NestedTxn()


def _worker_aggregation_path(repo_root: pathlib.Path) -> pathlib.Path | None:
    """Locate the worker's analytics_aggregation job.

    The merge renames the worker's import root from ``app`` to ``worker`` (plan STEP 29), so
    accept either layout: whichever one exists is the one to load.
    """

    for package_root in ("worker", "app"):
        candidate = (
            repo_root / "apps" / "worker" / package_root / "jobs" / "analytics_aggregation.py"
        )
        if candidate.is_file():
            return candidate
    return None


def _load_worker_analytics_aggregation() -> Any:
    """Load apps/worker's analytics_aggregation module by explicit file path under a private
    module name. apps/worker and apps/api both use the top-level package name ``app``, and
    apps/api's ``app`` is already bound in sys.modules by the time this test file's own
    imports (above) run, so a plain ``import app.jobs.analytics_aggregation`` would
    (correctly) fail to find a ``jobs`` submodule inside apps/api's ``app`` package instead of
    reaching apps/worker's. The repo root is located by walking upward looking for sibling
    ``apps/api``/``apps/worker`` directories rather than a hardcoded ``parents[N]`` depth -
    AGENTS.md/DECISION-006 documents two prior bugs in this exact codebase caused by a
    hardcoded parents[N] depth going stale after a directory move.
    """

    for candidate in pathlib.Path(__file__).resolve().parents:
        if (candidate / "apps" / "worker").is_dir() and (candidate / "apps" / "api").is_dir():
            repo_root = candidate
            break
    else:
        # apps/worker lands later in the merge (plan STEP 29-31). Skip rather than fail so
        # this file stays green in the meantime and the check re-arms automatically the
        # moment the worker directory exists.
        pytest.skip("apps/worker not present yet (merge plan STEP 29-31)", allow_module_level=False)

    module_path = _worker_aggregation_path(repo_root)
    if module_path is None:
        pytest.skip("apps/worker analytics_aggregation job not ported yet (merge plan STEP 31)")
    spec = importlib.util.spec_from_file_location(
        "qa_security_worker_analytics_aggregation", module_path
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Must be registered in sys.modules *before* exec_module - see docstring above (dataclass
    # field-type resolution needs sys.modules[cls.__module__] while the class body executes).
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


# ===========================================================================
# 1. Zero raw search-query-text/PII leakage anywhere in analytics output
# ===========================================================================


@pytest.mark.parametrize(
    ("raw", "must_not_contain", "must_contain"),
    [
        ("연락처는 kim0803@example.com 입니다", "kim0803@example.com", "[EMAIL]"),
        ("010-1234-5678로 연락주세요", "010-1234-5678", "[PHONE]"),
        ("주민번호 900101-1234567 확인용", "900101-1234567", "[RRN]"),
        ("계좌 110-234-567890 입금", "110-234-567890", "[ACCOUNT]"),
    ],
)
def test_mask_search_query_removes_pii_shapes(
    raw: str, must_not_contain: str, must_contain: str
) -> None:
    masked = mask_search_query(raw)
    assert masked is not None
    assert must_not_contain not in masked
    assert must_contain in masked


def test_mask_search_query_caps_length_and_strips_control_chars() -> None:
    raw = "a" * 5000 + "\x00\x01evil"
    masked = mask_search_query(raw)
    assert masked is not None
    assert len(masked) <= 200
    assert "\x00" not in masked and "\x01" not in masked


def test_redact_query_text_is_a_second_independent_pass() -> None:
    """``app/services/analytics/suppression.py``'s defensive re-mask, documented as an
    independent second pass in case the upstream masking step regresses."""

    assert redact_query_text("email me at leaked@example.com") == "email me at [masked]"
    assert redact_query_text("") == ""
    assert redact_query_text("no pii here") == "no pii here"


@pytest.mark.asyncio
async def test_ingested_web_event_never_persists_a_raw_search_query() -> None:
    """Full path check: the value the ingestion pipeline actually hands to ``db.add`` for a
    persisted row must be the masked value, never the client's raw text - not just that the
    pure masking function works in isolation."""

    from app.schemas.interaction_event import ClientInteractionBatchRequest as _Batch

    raw_email = "buyer-contact@example.com"
    payload = _Batch.model_validate(
        {
            "tenant_id": str(TENANT_ID),
            "event_id": str(EVENT_ID),
            "source": "WEB",
            "guest_session_id": str(uuid.uuid4()),
            "events": [
                {
                    "client_event_id": str(uuid.uuid4()),
                    "event_type": "UI_SEARCH_SUBMIT",
                    "occurred_at": datetime.now(UTC).isoformat(),
                    "search_query": f"이메일로 회신주세요 {raw_email}",
                }
            ],
        }
    )
    session = FakeAsyncSession(claim_queue=[None])

    await ingest_client_events(session, payload)

    [row] = [r for r in session.added if r.__class__.__name__ == "InteractionEvent"]
    serialized = str(row.context_json)
    assert raw_email not in serialized
    assert "[EMAIL]" in serialized


@pytest.mark.xfail(
    strict=True,
    reason=(
        "CONFIRMED BUG (see .harness/reports/operations/WAVE2E-QA.md, priority check 1): "
        "app/services/interaction_event/masking.py::sanitize_context only allow-lists "
        "*keys* for the free-form 'context' dict - it never runs mask_search_query's PII "
        "regexes over the *values* of allow-listed string keys (e.g. 'referrer_screen', "
        "'zone', 'filter_code'). Only the dedicated 'search_query' field is masked. A client "
        "that puts a phone number or email into any allow-listed string field survives "
        "verbatim into interaction_event.context_json (and from there, once "
        "WORKER-ANALYTICS's aggregation reads real interaction_event data instead of "
        "synthetic fixtures, into analytics output). This test is xfail(strict=True) as a "
        "regression tripwire: it will start *failing the suite* (XPASS) the moment someone "
        "fixes sanitize_context to redact allow-listed string values too, which is exactly "
        "when this xfail marker should be deleted."
    ),
)
@pytest.mark.asyncio
async def test_allowlisted_context_string_values_are_not_yet_pii_redacted() -> None:
    from app.schemas.interaction_event import ClientInteractionBatchRequest as _Batch

    raw_phone = "010-9876-5432"
    payload = _Batch.model_validate(
        {
            "tenant_id": str(TENANT_ID),
            "event_id": str(EVENT_ID),
            "source": "WEB",
            "guest_session_id": str(uuid.uuid4()),
            "events": [
                {
                    "client_event_id": str(uuid.uuid4()),
                    "event_type": "UI_VIEW_IMPRESSION",
                    "occurred_at": datetime.now(UTC).isoformat(),
                    # "referrer_screen" is in ALLOWED_CONTEXT_KEYS and is free text.
                    "context": {"referrer_screen": raw_phone},
                }
            ],
        }
    )
    session = FakeAsyncSession(claim_queue=[None])

    await ingest_client_events(session, payload)

    [row] = [r for r in session.added if r.__class__.__name__ == "InteractionEvent"]
    # Desired (currently failing) behaviour: the raw phone number must not survive.
    assert raw_phone not in str(row.context_json)


def test_rejection_ledger_never_records_the_raw_client_payload() -> None:
    """``EventIngestionFailure.detail`` (and the HTTP error message built from the same
    summary) must only ever contain field locations/error types, never the client's actual
    input values - checked directly against ``safe_validation_summary``'s contract, and
    against the model column carrying it."""

    leaked_value = "raw-secret-should-never-appear-anywhere"
    bad_raw_item = {
        "client_event_id": str(uuid.uuid4()),
        "event_type": "UI_VIEW_IMPRESSION",
        "occurred_at": leaked_value,  # fails datetime parsing -> ValidationError
    }
    event, client_event_id, summary = parse_client_event(bad_raw_item)
    assert event is None
    assert client_event_id is not None
    assert summary is not None
    assert leaked_value not in summary

    # EventIngestionFailure.detail is a bounded, app-constructed string column - assert the
    # model itself caps it (defense in depth even if a future caller forgets to truncate).
    detail_column = EventIngestionFailure.__table__.columns["detail"]
    assert detail_column.type.length == 300


# ===========================================================================
# 5. Zero small-group (<5) statistic exposure
# (grouped here, ahead of 2/3, because check 1's fixtures above and check 5's fixtures below
#  share the same "masking/suppression only in app/services/analytics" module neighborhood)
# ===========================================================================


def test_small_group_threshold_is_five() -> None:
    assert SMALL_GROUP_SUPPRESSION_THRESHOLD == 5


@pytest.mark.parametrize("count", [1, 2, 3, 4])
def test_suppress_metric_masks_one_through_four(count: int) -> None:
    metric = suppress_metric(count, count)
    assert metric == Metric(value=None, suppressed=True)


def test_suppress_metric_does_not_mask_a_true_zero() -> None:
    metric = suppress_metric(0, 0)
    assert metric == Metric(value=0, suppressed=False)


def test_suppress_metric_does_not_mask_five_or_more() -> None:
    metric = suppress_metric(37, 5)
    assert metric == Metric(value=37, suppressed=False)


def test_suppress_rate_masks_when_either_side_is_a_small_group() -> None:
    # Numerator small (2 no-result searches out of a big denominator) must still be masked -
    # otherwise "2/1000 = 0.2%" would leak the numerator back out via the ratio's precision.
    masked_by_numerator = suppress_rate(2, 2, 1000, 200)
    assert masked_by_numerator.suppressed is True
    assert masked_by_numerator.value is None

    masked_by_denominator = suppress_rate(1, 1, 3, 3)
    assert masked_by_denominator.suppressed is True

    not_masked = suppress_rate(50, 50, 200, 200)
    assert not_masked.suppressed is False
    assert not_masked.value == 0.25


def test_drop_small_groups_removes_rows_entirely_not_just_their_value() -> None:
    rows = [
        {"query": "막걸리", "underlying": 12},
        {"query": "매우 희귀한 검색어", "underlying": 1},  # would itself be identifying
        {"query": "소주", "underlying": 5},
    ]
    kept = drop_small_groups(rows, underlying_count_of=lambda r: r["underlying"])
    assert [r["query"] for r in kept] == ["막걸리", "소주"]


@pytest.mark.parametrize(
    "model",
    [AnalyticsDailyMetric, AnalyticsFunnelMetric, AnalyticsSearchNoResultSummary],
)
def test_analytics_tables_have_a_db_level_suppression_backstop(model: type) -> None:
    """Application-layer suppression (suppress_metric/suppress_rate) is the primary
    mechanism, but each analytics.* table this track's model defines also carries a real
    CHECK constraint forcing the numeric columns to NULL whenever suppressed=true - so a
    future application-layer bug (a forgotten suppress_metric call) cannot leak an exact
    small-group figure through this table."""

    check_constraints = [
        c for c in model.__table__.constraints if isinstance(c, CheckConstraint)
    ]
    suppression_checks = [c for c in check_constraints if "suppressed" in str(c.sqltext)]
    assert suppression_checks, f"{model.__name__} has no suppression-hides-values CHECK"


# ===========================================================================
# 2. Zero optional-notification sent without consent
# ===========================================================================


class _RecordingEmailAdapter:
    def __init__(self) -> None:
        self.calls: list[uuid.UUID] = []

    async def send(self, *, recipient_user_id: uuid.UUID, subject: str, body: str) -> EmailSendResult:
        del subject, body
        self.calls.append(recipient_user_id)
        return EmailSendResult(success=True)


def _meeting_event(*, tenant_id: uuid.UUID, recipient_user_id: uuid.UUID, object_id: uuid.UUID) -> BusinessEvent:
    return BusinessEvent(
        business_event_code="MEETING_STATUS_CHANGED",
        notification_type="MEETING_ACCEPTED",
        tenant_id=tenant_id,
        recipient_user_id=recipient_user_id,
        title="미팅이 수락되었습니다",
        body="전시업체가 미팅 요청을 수락했습니다.",
        object_id=object_id,
        relevant_version="1",
    )


@pytest.mark.asyncio
async def test_email_is_never_attempted_without_a_preference_row() -> None:
    """Default (no NotificationPreference row at all) is opt-in=False, per the model's own
    documented privacy-preserving default - never treated as implicit consent to email."""

    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    repository = InMemoryNotificationRepository()
    repository.email_consent_basis.add((tenant_id, user_id))  # consent present ...
    adapter = _RecordingEmailAdapter()
    service = NotificationService(repository, email_adapter=adapter)

    outcome = await service.handle_business_event(
        _meeting_event(tenant_id=tenant_id, recipient_user_id=user_id, object_id=uuid.uuid4())
    )

    # ... but the preference toggle was never turned on, so EMAIL must still be skipped.
    assert outcome.email_result == "SKIPPED_PREFERENCE_DISABLED"
    assert adapter.calls == []
    [delivery] = [d for d in repository.deliveries if d.channel == "EMAIL"]
    assert delivery.status == "SKIPPED"
    assert delivery.skipped_reason == "PREFERENCE_DISABLED"


@pytest.mark.asyncio
async def test_email_is_never_attempted_without_a_consent_basis() -> None:
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    repository = InMemoryNotificationRepository()
    repository.preferences[(tenant_id, user_id, "MEETING_ACCEPTED")] = True  # opted in ...
    adapter = _RecordingEmailAdapter()
    service = NotificationService(repository, email_adapter=adapter)

    outcome = await service.handle_business_event(
        _meeting_event(tenant_id=tenant_id, recipient_user_id=user_id, object_id=uuid.uuid4())
    )

    # ... but there is no accepted, currently-effective NOTIFICATION_EMAIL consent on file.
    assert outcome.email_result == "SKIPPED_CONSENT_MISSING"
    assert adapter.calls == []


@pytest.mark.asyncio
async def test_email_sends_only_once_both_preference_and_consent_align() -> None:
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    repository = InMemoryNotificationRepository()
    repository.preferences[(tenant_id, user_id, "MEETING_ACCEPTED")] = True
    repository.email_consent_basis.add((tenant_id, user_id))
    adapter = _RecordingEmailAdapter()
    service = NotificationService(repository, email_adapter=adapter)

    outcome = await service.handle_business_event(
        _meeting_event(tenant_id=tenant_id, recipient_user_id=user_id, object_id=uuid.uuid4())
    )

    assert outcome.email_result == "SENT"
    assert adapter.calls == [user_id]


@pytest.mark.asyncio
async def test_in_app_notification_survives_an_email_adapter_outage() -> None:
    """The IN_APP record must exist independent of EMAIL's fate - an email provider outage
    (even an adapter that misbehaves and raises) can never remove/roll back the in-app one."""

    class _ExplodingAdapter:
        async def send(self, **_kwargs: Any) -> EmailSendResult:
            raise RuntimeError("simulated provider outage")

    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    repository = InMemoryNotificationRepository()
    repository.preferences[(tenant_id, user_id, "MEETING_ACCEPTED")] = True
    repository.email_consent_basis.add((tenant_id, user_id))
    service = NotificationService(repository, email_adapter=_ExplodingAdapter())

    outcome = await service.handle_business_event(
        _meeting_event(tenant_id=tenant_id, recipient_user_id=user_id, object_id=uuid.uuid4())
    )

    assert outcome.result == "CREATED"
    assert outcome.email_result == "FAILED"
    [in_app] = [d for d in repository.deliveries if d.channel == "IN_APP"]
    assert in_app.status == "SENT"


@pytest.mark.asyncio
async def test_operator_notice_is_exempt_from_the_frequency_cap_but_recommendation_ready_is_not() -> None:
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    repository = InMemoryNotificationRepository()
    service = NotificationService(repository)

    first_reco = await service.handle_business_event(
        BusinessEvent(
            business_event_code="RECOMMENDATION_GENERATED",
            notification_type="RECOMMENDATION_READY",
            tenant_id=tenant_id,
            recipient_user_id=user_id,
            title="추천이 준비되었습니다",
            body="새로운 추천을 확인해보세요.",
            object_id=uuid.uuid4(),
            relevant_version="2026-08-03",
        )
    )
    second_reco = await service.handle_business_event(
        BusinessEvent(
            business_event_code="RECOMMENDATION_GENERATED",
            notification_type="RECOMMENDATION_READY",
            tenant_id=tenant_id,
            recipient_user_id=user_id,
            title="추천이 준비되었습니다 (2차 배치)",
            body="새로운 추천을 확인해보세요.",
            object_id=uuid.uuid4(),  # different object -> not a dedup, must hit the cap
            relevant_version="2026-08-03",
        )
    )
    assert first_reco.result == "CREATED"
    assert second_reco.result == "SUPPRESSED_FREQUENCY_CAP"

    first_notice = await service.handle_business_event(
        BusinessEvent(
            business_event_code="OPERATOR_NOTICE_PUBLISHED",
            notification_type="OPERATOR_NOTICE",
            tenant_id=tenant_id,
            recipient_user_id=user_id,
            title="공지 1",
            body="본문",
            relevant_version="1",
        )
    )
    second_notice = await service.handle_business_event(
        BusinessEvent(
            business_event_code="OPERATOR_NOTICE_PUBLISHED",
            notification_type="OPERATOR_NOTICE",
            tenant_id=tenant_id,
            recipient_user_id=user_id,
            title="공지 2",
            body="본문",
            relevant_version="2",
        )
    )
    assert first_notice.result == "CREATED"
    assert second_notice.result == "CREATED"  # operational notices are exempt


# ===========================================================================
# 3. Zero cross-user notification access
# ===========================================================================


@pytest.mark.asyncio
async def test_a_users_notification_list_never_includes_another_users_rows() -> None:
    repository = InMemoryNotificationRepository()
    service = NotificationService(repository)
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    tenant_id = uuid.uuid4()

    await service.handle_business_event(
        _meeting_event(tenant_id=tenant_id, recipient_user_id=user_a, object_id=uuid.uuid4())
    )
    await service.handle_business_event(
        _meeting_event(tenant_id=tenant_id, recipient_user_id=user_b, object_id=uuid.uuid4())
    )

    a_inbox = await service.list_notifications(tenant_id=tenant_id, recipient_user_id=user_a)
    b_inbox = await service.list_notifications(tenant_id=tenant_id, recipient_user_id=user_b)
    assert len(a_inbox) == 1
    assert len(b_inbox) == 1
    assert a_inbox[0].recipient_user_id == user_a
    assert b_inbox[0].recipient_user_id == user_b

    assert await service.unread_count(tenant_id=tenant_id, recipient_user_id=user_a) == 1
    # A cannot inflate/deflate B's unread badge by reading their own inbox.
    assert await service.unread_count(tenant_id=tenant_id, recipient_user_id=user_b) == 1


@pytest.mark.asyncio
async def test_mark_read_and_mark_all_read_are_scoped_to_the_caller() -> None:
    repository = InMemoryNotificationRepository()
    service = NotificationService(repository)
    user_a, user_b = uuid.uuid4(), uuid.uuid4()
    tenant_id = uuid.uuid4()

    await service.handle_business_event(
        _meeting_event(tenant_id=tenant_id, recipient_user_id=user_a, object_id=uuid.uuid4())
    )
    [a_notification] = repository.notifications

    # user_b guessing/enumerating user_a's notification_id cannot mark it read.
    result = await service.mark_read(
        tenant_id=tenant_id,
        recipient_user_id=user_b,
        notification_id=a_notification.notification_id,
    )
    assert result is None
    assert a_notification.read_at is None

    # user_b's mark-all-read never touches user_a's unread notification.
    marked_count = await service.mark_all_read(tenant_id=tenant_id, recipient_user_id=user_b)
    assert marked_count == 0
    assert a_notification.read_at is None

    # The rightful owner can.
    own_result = await service.mark_read(
        tenant_id=tenant_id,
        recipient_user_id=user_a,
        notification_id=a_notification.notification_id,
    )
    assert own_result is not None


def test_every_production_read_statement_filters_by_recipient_user_id() -> None:
    """Compile-level guard on the real (non-in-memory) SQL path: the production
    ``SqlAlchemyNotificationRepository`` is built entirely on these ``*_stmt`` functions
    (``app/services/notification/service.py`` module docstring) - if a future edit ever
    dropped the ``recipient_user_id`` predicate from one of them, this test catches it
    without needing a live database.

    Integration note (merge plan STEP 18): every one of these statements is now also
    tenant-scoped, both because the two covering indexes lead with ``tenant_id`` and because
    the router derives the tenant from the session rather than a header - so the guard checks
    both predicates."""

    tenant_id = uuid.uuid4()
    recipient_user_id = uuid.uuid4()
    notification_id = uuid.uuid4()

    compiled_own = str(
        own_notification_stmt(
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            notification_id=notification_id,
        )
    )
    compiled_list = str(
        own_notifications_stmt(
            tenant_id=tenant_id,
            recipient_user_id=recipient_user_id,
            unread_only=False,
            before=None,
            limit=20,
        )
    )
    compiled_unread = str(
        unread_count_stmt(tenant_id=tenant_id, recipient_user_id=recipient_user_id)
    )

    for compiled in (compiled_own, compiled_list, compiled_unread):
        assert "recipient_user_id" in compiled
        assert "tenant_id" in compiled


# ===========================================================================
# 4. Zero kiosk user-identification
# ===========================================================================


@pytest.mark.parametrize(
    "identity_field",
    ["profile_id", "user_id", "guest_session_id", "visit_session_id"],
)
def test_kiosk_batch_request_rejects_any_web_identity_field(identity_field: str) -> None:
    with pytest.raises(ValidationError):
        ClientInteractionBatchRequest.model_validate(
            {
                "tenant_id": str(TENANT_ID),
                "event_id": str(EVENT_ID),
                "source": "KIOSK",
                "kiosk_id": "kiosk-01",
                identity_field: str(uuid.uuid4()),
                "events": [
                    {
                        "client_event_id": str(uuid.uuid4()),
                        "event_type": "UI_VIEW_IMPRESSION",
                        "occurred_at": datetime.now(UTC).isoformat(),
                    }
                ],
            }
        )


def test_web_batch_request_rejects_kiosk_only_fields() -> None:
    with pytest.raises(ValidationError):
        ClientInteractionBatchRequest.model_validate(
            {
                "tenant_id": str(TENANT_ID),
                "event_id": str(EVENT_ID),
                "source": "WEB",
                "kiosk_id": "kiosk-01",  # KIOSK-only field on a WEB batch
                "events": [
                    {
                        "client_event_id": str(uuid.uuid4()),
                        "event_type": "UI_VIEW_IMPRESSION",
                        "occurred_at": datetime.now(UTC).isoformat(),
                    }
                ],
            }
        )


@pytest.mark.parametrize(
    "variant_key",
    ["user_id_hash", "User-Id-Hash", "USERIDHASH", "device_fingerprint", "IP_Address", "advertisingId"],
)
def test_forbidden_kiosk_keys_are_caught_regardless_of_casing_or_separators(variant_key: str) -> None:
    found = find_forbidden_kiosk_keys({variant_key: "some-value", "zone": "hall-a"})
    assert found == [variant_key]


def test_forbidden_kiosk_keys_ignores_genuinely_unrelated_keys() -> None:
    assert find_forbidden_kiosk_keys({"zone": "hall-a", "dwell_ms": 1200}) == []
    assert find_forbidden_kiosk_keys(None) == []
    assert find_forbidden_kiosk_keys({}) == []


@pytest.mark.asyncio
async def test_kiosk_sourced_interaction_event_row_never_carries_any_subject_identifier() -> None:
    """Structural check on the actual persisted row (not just the request-level validator):
    a KIOSK-sourced event's ORM row has every subject column NULL."""

    payload = ClientInteractionBatchRequest.model_validate(
        {
            "tenant_id": str(TENANT_ID),
            "event_id": str(EVENT_ID),
            "source": "KIOSK",
            "kiosk_id": "kiosk-05",
            "kiosk_session_id": str(uuid.uuid4()),
            "events": [
                {
                    "client_event_id": str(uuid.uuid4()),
                    "event_type": "UI_VIEW_IMPRESSION",
                    "occurred_at": datetime.now(UTC).isoformat(),
                }
            ],
        }
    )
    session = FakeAsyncSession(claim_queue=[None])

    await ingest_client_events(session, payload)

    [row] = [r for r in session.added if r.__class__.__name__ == "InteractionEvent"]
    assert row.user_id is None
    assert row.guest_session_id is None
    assert row.visit_session_id is None
    # kiosk_id/kiosk_session_id are the anonymous device/session codes, not an identity -
    # they are allowed to be recorded, but only inside context, never as a subject column.
    assert row.context_json["kiosk_id"] == "kiosk-05"


# ===========================================================================
# 6. Event dedup/aggregation consistency (no double counting across a simulated
#    re-aggregation) - see test_operations_analytics_e2e.py for the ingestion-level and
#    pure-aggregation-level versions of this check; this file adds the analytics_aggregation
#    small-group interaction with duplicate-looking actors.
# ===========================================================================


def test_aggregation_distinct_actor_counting_does_not_double_count_a_repeat_actor() -> None:
    worker_module = _load_worker_analytics_aggregation()

    metric_date = date(2026, 8, 3)
    base = datetime(2026, 8, 3, 3, 0, tzinfo=UTC)
    # Same actor fires the same interaction twice (e.g. a genuine double-click or a client
    # retry that produced two distinct interaction_event rows for the same underlying
    # engagement) plus 4 other distinct actors -> 5 distinct actors total (at, not under, the
    # suppression threshold so this specific assertion is not itself masked), and the *actor*
    # count must not be inflated to 6 by the repeat.
    events = [
        worker_module.RawEvent(
            interaction_event_id=str(uuid.uuid4()),
            tenant_id=str(TENANT_ID),
            event_id=str(EVENT_ID),
            event_type="RECOMMENDATION_IMPRESSION",
            occurred_at=base,
            received_at=base,
            user_id="user-repeat",
        ),
        worker_module.RawEvent(
            interaction_event_id=str(uuid.uuid4()),
            tenant_id=str(TENANT_ID),
            event_id=str(EVENT_ID),
            event_type="RECOMMENDATION_IMPRESSION",
            occurred_at=base,
            received_at=base,
            user_id="user-repeat",
        ),
    ] + [
        worker_module.RawEvent(
            interaction_event_id=str(uuid.uuid4()),
            tenant_id=str(TENANT_ID),
            event_id=str(EVENT_ID),
            event_type="RECOMMENDATION_IMPRESSION",
            occurred_at=base,
            received_at=base,
            user_id=f"user-{i}",
        )
        for i in range(4)
    ]

    [row] = [
        row
        for row in worker_module.aggregate_daily_metrics(
            events, tenant_id=str(TENANT_ID), event_id=str(EVENT_ID), metric_date=metric_date
        )
        if row.metric_code == "RECOMMENDATION_IMPRESSION"
    ]
    assert row.distinct_actor_count == 5  # not 6
    assert row.suppressed is False
    assert row.event_count == 6  # raw event volume is still reported accurately


# ===========================================================================
# 7. Zero competitor-detail-stat leakage to the EXHIBITOR_ADMIN role
# ===========================================================================


class _RoleFakeSession:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    async def execute(self, _stmt: Any) -> Any:
        return SimpleNamespace(all=lambda: self._rows)


@pytest.mark.asyncio
async def test_exhibitor_admin_can_never_claim_event_admin_or_analyst() -> None:
    event_id = uuid.uuid4()
    session = _RoleFakeSession(
        [SimpleNamespace(role_code="EXHIBITOR", event_id=None, exhibitor_id=uuid.uuid4())]
    )

    for escalation_attempt in ("EVENT_ADMIN", "ANALYST", "DATA_REVIEWER"):
        with pytest.raises(AnalyticsAccessDenied) as exc_info:
            await resolve_analytics_access(
                session,
                actor_user_id=uuid.uuid4(),
                event_id=event_id,
                claimed_role=escalation_attempt,  # type: ignore[arg-type]
            )
        assert exc_info.value.reason == "ROLE_NOT_PERMITTED"


@pytest.mark.asyncio
async def test_exhibitor_admins_exhibitor_id_is_always_server_resolved() -> None:
    """The resolved ``exhibitor_id`` can only ever come from the actor's own
    ``profile.user_role`` row - the function accepts no exhibitor_id parameter at all, so
    there is no code path by which a client-supplied value could widen an EXHIBITOR_ADMIN's
    scope to a competitor's data."""

    import inspect

    signature = inspect.signature(resolve_analytics_access)
    assert "exhibitor_id" not in signature.parameters

    own_exhibitor_id = uuid.uuid4()
    session = _RoleFakeSession(
        [SimpleNamespace(role_code="EXHIBITOR", event_id=None, exhibitor_id=own_exhibitor_id)]
    )
    context = await resolve_analytics_access(
        session, actor_user_id=uuid.uuid4(), event_id=uuid.uuid4(), claimed_role=None
    )
    assert context.exhibitor_id == own_exhibitor_id


@pytest.mark.asyncio
async def test_no_role_and_visitor_or_buyer_only_actors_get_zero_analytics_access() -> None:
    event_id = uuid.uuid4()

    no_role_session = _RoleFakeSession([])
    with pytest.raises(AnalyticsAccessDenied) as exc_info:
        await resolve_analytics_access(
            no_role_session, actor_user_id=uuid.uuid4(), event_id=event_id, claimed_role=None
        )
    assert exc_info.value.reason == "NO_ROLE_ASSIGNED"

    # A VISITOR/BUYER row (per db-erd's 5-value role_code CHECK) grants no analytics claim.
    visitor_session = _RoleFakeSession(
        [SimpleNamespace(role_code="BUYER", event_id=None, exhibitor_id=None)]
    )
    with pytest.raises(AnalyticsAccessDenied) as exc_info:
        await resolve_analytics_access(
            visitor_session, actor_user_id=uuid.uuid4(), event_id=event_id, claimed_role=None
        )
    assert exc_info.value.reason == "INSUFFICIENT_ROLE"


@pytest.mark.asyncio
async def test_buyer_analytics_never_populates_a_per_exhibitor_breakdown() -> None:
    """``app/services/analytics/queries.py::get_buyer_analytics`` (BACKEND-ANALYTICS) landed
    mid-way through this QA session - re-checked directly against the real function rather
    than left as the "queries.py does not exist" gap this test used to document. Reading it:
    ``breakdown`` is hardcoded to ``[]`` on every branch (no ``analytics.*`` table carries an
    exhibitor dimension yet - see that function's own docstring), and an ``exhibitor_id``-
    scoped call returns fully masked metrics without querying anything - so there is currently
    no way for an EXHIBITOR_ADMIN (or anyone else) to see a competitor's row through this
    endpoint. Exercised here as a pure function (monkeypatching its two DB-touching helpers)
    since ``_daily_metric``/``_funnel_metric`` need real ``analytics.*`` tables this sandbox
    does not have."""

    from app.schemas.analytics import Metric
    from app.services.analytics import queries as analytics_queries

    async def _fake_daily_metric(*_args: Any, **_kwargs: Any) -> Metric:
        return Metric(value=42, suppressed=False)

    async def _fake_funnel_metric(*_args: Any, **_kwargs: Any) -> Metric:
        return Metric(value=17, suppressed=False)

    import pytest as _pytest  # local alias avoids shadowing the module-level `pytest` import

    monkeypatch = _pytest.MonkeyPatch()
    monkeypatch.setattr(analytics_queries, "_daily_metric", _fake_daily_metric)
    monkeypatch.setattr(analytics_queries, "_funnel_metric", _fake_funnel_metric)
    try:
        event_wide = await analytics_queries.get_buyer_analytics(
            object(),  # type: ignore[arg-type]  # unused once the two helpers are stubbed
            event_id=uuid.uuid4(),
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 3),
            role="EVENT_ADMIN",
            exhibitor_id=None,
        )
        assert event_wide.breakdown == []

        exhibitor_scoped = await analytics_queries.get_buyer_analytics(
            object(),  # type: ignore[arg-type]
            event_id=uuid.uuid4(),
            period_start=date(2026, 8, 1),
            period_end=date(2026, 8, 3),
            role="EXHIBITOR_ADMIN",
            exhibitor_id=uuid.uuid4(),
        )
        assert exhibitor_scoped.breakdown == []
        # A client-scoped request is masked, not computed from a live per-exhibitor query -
        # nothing here could ever expose an exact competitor figure.
        assert exhibitor_scoped.buyer_matches.suppressed is True
        assert exhibitor_scoped.buyer_matches.value is None
    finally:
        monkeypatch.undo()


# ===========================================================================
# 8. Operator event-message broadcasts (event_message domain - landed mid-way through this QA
#    session by a track this task's prompt did not originally name, but whose targeting/
#    consent/small-group logic is squarely priority checks 2 and 5). Light-touch coverage only
#    (no time budget in this pass for the full router/workflow surface - see the report's
#    "coverage gaps" section) against the real, pure ``app/services/event_message/targeting.py``
#    query builders, which need no live DB to compile and inspect.
# ===========================================================================


def test_event_message_rejects_a_disallowed_fine_grained_segment() -> None:
    from app.services.event_message.targeting import (
        TargetSegmentNotAllowedError,
        validate_target_segment,
    )

    with pytest.raises(TargetSegmentNotAllowedError):
        validate_target_segment("HAS_ABANDONED_FAVORITES", None)  # a behavioral/attribute
        # filter, not one of the fixed coarse segments - the exact kind of fine-grained
        # targeting this track's task spec says must be rejected.


def test_event_message_specific_role_requires_a_valid_role_code() -> None:
    from app.services.event_message.targeting import (
        TargetSegmentNotAllowedError,
        validate_target_segment,
    )

    with pytest.raises(TargetSegmentNotAllowedError):
        validate_target_segment("SPECIFIC_ROLE", None)
    with pytest.raises(TargetSegmentNotAllowedError):
        validate_target_segment("ALL_REGISTERED_USERS", "ADMIN")  # role_code only valid
        # alongside SPECIFIC_ROLE, never bolted onto a different segment.
    validate_target_segment("SPECIFIC_ROLE", "ADMIN")  # must not raise


@pytest.mark.parametrize(
    "segment",
    ["ALL_REGISTERED_USERS", "PROFILE_UNCONFIRMED", "RECOMMENDATION_READY", "BUYERS"],
)
def test_event_message_targeting_always_filters_active_undeleted_accounts(segment: str) -> None:
    from app.services.event_message.targeting import target_user_ids_stmt

    compiled = str(
        target_user_ids_stmt(
            tenant_id=uuid.uuid4(),
            event_id=uuid.uuid4(),
            target_segment=segment,
            target_role_code=None,
        )
    )
    assert "account_status" in compiled
    assert "deleted_at" in compiled


def test_event_message_email_exclusion_query_is_scoped_to_the_notification_email_purpose() -> None:
    """Priority check 2 for this domain: a message's EMAIL channel is only ever sent to a
    resolved recipient after checking the *same* NOTIFICATION_EMAIL consent purpose the
    system-generated notification pipeline relies on - not a separate, looser bar."""

    from app.services.event_message.targeting import (
        EMAIL_CONSENT_PURPOSE,
        email_consent_excluded_user_ids_stmt,
    )
    from app.services.notification.service import NOTIFICATION_EMAIL_CONSENT_PURPOSE

    assert EMAIL_CONSENT_PURPOSE == NOTIFICATION_EMAIL_CONSENT_PURPOSE

    compiled = str(
        email_consent_excluded_user_ids_stmt(
            tenant_id=uuid.uuid4(),
            event_id=uuid.uuid4(),
            target_segment="ALL_REGISTERED_USERS",
            target_role_code=None,
            now=datetime.now(UTC),
        )
    )
    assert "consent_policy" in compiled
    assert "user_consent" in compiled


def test_event_message_small_audience_never_shows_an_exact_count_below_five() -> None:
    """Priority check 5 for this domain, and pinned to the same repo-wide threshold constant
    used everywhere else in this report (not a locally-redefined '5')."""

    from app.services.event_message.targeting import (
        SMALL_AUDIENCE_THRESHOLD,
        display_target_count,
    )

    assert SMALL_AUDIENCE_THRESHOLD == SMALL_GROUP_SUPPRESSION_THRESHOLD

    for count in range(SMALL_AUDIENCE_THRESHOLD):
        exact_count, display, warning = display_target_count(count)
        assert exact_count is None
        assert warning is True
        assert str(SMALL_AUDIENCE_THRESHOLD) in display

    exact_count, _display, warning = display_target_count(SMALL_AUDIENCE_THRESHOLD)
    assert exact_count == SMALL_AUDIENCE_THRESHOLD
    assert warning is False
