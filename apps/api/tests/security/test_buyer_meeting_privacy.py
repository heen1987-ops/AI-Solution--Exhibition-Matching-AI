"""WAVE 2C (QA-BUYER) security/privacy tests for the buyer -> match -> meeting flow.

Scope: apps/api/tests/security/test_buyer_meeting_privacy.py (owned by the QA-BUYER track,
.harness/locks.yaml QA / this task's explicit OWNED PATHS override).

These tests target the seven highest-priority failure modes called out for this track:

    1. zero contact-info exposure before meeting acceptance + consent
    2. zero cross-buyer / cross-exhibitor data access
    3. zero unverified-buyer meeting requests succeeding
    4. zero hard-filter violations in match results
    5. zero unapproved/unpublished exhibitors appearing in match results
    6. UNKNOWN trade-condition fields are never silently rendered/treated as YES or NO
    7. meeting status transitions never skip states illegally

No live PostgreSQL is assumed to be reachable in this environment (verified: no
POSTGRES_TEST_DATABASE_URL, no local docker daemon). Two techniques are used, mirroring the
project's own established test conventions (see test_recommendation_api.py, test_search_api.py):

  * For the hard-filter / UNKNOWN-handling checks (4/5/6), the *real* production functions in
    app.services.matching.hard_filter / feature_builder are called directly with hand-built
    dataclasses -- no mocking of business logic at all, only the absence of a database.
  * For the meeting-router checks (1/2/3/7), the actual router coroutines in
    app.api.v1.routers.meetings are awaited directly with a small scripted fake AsyncSession
    whose execute()/get() call sequence mirrors the exact order traced from the router source
    (see the module docstring notes above each fake construction below). This exercises the
    real authorization/consent/state-machine code paths without needing Postgres.

Anything that genuinely requires infrastructure not available in this sandbox (a live DB, or
another track's not-yet-landed endpoint) is marked with pytest.skip and a clear reason rather
than deleted, per this task's instructions.

Retargeted for the unified repository (MERGE STEP 22)
-----------------------------------------------------
Two things changed relative to the WAVE 2C original, both because the merge closed real
defects rather than because the tests were wrong:

  * Contact disclosure now requires THREE gates, not two. ``contact_reveal_allowed()``
    (app/services/meeting/buyer_matching.py) additionally requires
    ``MeetingContactShare.exhibitor_enabled_at`` -- the exhibitor's own per-meeting opt-in.
    Every positive-control fixture below therefore sets it, and a new negative test
    (``test_contact_not_exposed_when_exhibitor_never_enabled_sharing``) pins the third gate.
  * Identity columns are AESGCM envelopes, not plaintext. The router's ``_decrypt_text`` is
    fail-closed, so fixtures build ``name_enc``/``phone_enc``/``email_enc`` with
    ``encrypt_secret``; feeding raw bytes would (correctly) yield no contact at all.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Any

from fastapi.responses import JSONResponse

from app.api.v1.routers import meetings as meetings_router
from app.core.auth import encrypt_secret
from app.core.config import get_settings
from app.models.exhibitor import ExhibitorStaff
from app.models.meeting import (
    MEETING_CONFIRMED_STATUS,
    MEETING_STATUSES,
    MeetingRequest,
)
from app.schemas.meeting import (
    MeetingCancelRequest,
    MeetingCreateRequest,
    MeetingOutcomeRequest,
    PartnerDecisionRequest,
)
from app.services.matching import feature_builder, hard_filter
from app.services.matching.types import (
    GoalItem,
    MatchCandidate,
    ResolvedContext,
    ResolvedProfile,
)

# Note: apps/api/pyproject.toml sets asyncio_mode = "auto", so ``async def test_*`` functions
# are collected as coroutine tests without needing an explicit @pytest.mark.asyncio marker.


# ---------------------------------------------------------------------------
# Shared fakes
# ---------------------------------------------------------------------------


class _Result:
    """Fakes the subset of sqlalchemy.Result used by app/api/v1/routers/meetings.py:
    .scalar_one_or_none(), .scalar_one(), .scalars().first(), .scalars().all(), .all().
    """

    def __init__(self, rows: list[Any]) -> None:
        self._rows = list(rows)

    def scalar_one_or_none(self) -> Any:
        return self._rows[0] if self._rows else None

    def scalar_one(self) -> Any:
        return self._rows[0]

    def scalars(self) -> _Result:
        return self

    def first(self) -> Any:
        return self._rows[0] if self._rows else None

    def all(self) -> list[Any]:
        return list(self._rows)


def _row(obj: Any) -> _Result:
    return _Result([obj])


def _none() -> _Result:
    return _Result([])


def _rows(objs: list[Any]) -> _Result:
    return _Result(objs)


class FakeSession:
    """Minimal AsyncSession double.

    ``get_map`` answers ``db.get(Model, pk)`` calls (the router never round-trips through more
    than one live row per model in the scenarios below, so a flat dict keyed by model class is
    sufficient and keeps each test's fixture readable).

    ``execute_queue`` is consumed strictly in call order to answer ``db.execute(stmt)`` calls.
    The order for each router function was traced by reading
    apps/api/app/api/v1/routers/meetings.py line by line; each test that uses this fake states
    the traced order in a comment immediately above its queue construction so a future reader
    can verify it against the source without re-deriving it.
    """

    def __init__(
        self,
        *,
        get_map: dict[type, Any] | None = None,
        execute_queue: list[_Result] | None = None,
    ) -> None:
        self._get_map = get_map or {}
        self._queue = list(execute_queue or [])
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.flushes = 0

    async def get(self, model: type, _pk: Any) -> Any:
        return self._get_map.get(model)

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flushes += 1

    async def commit(self) -> None:
        self.commits += 1

    async def rollback(self) -> None:
        self.rollbacks += 1

    async def execute(self, statement: Any) -> _Result:
        if not self._queue:
            raise AssertionError(f"unscripted db.execute() call: {statement}")
        return self._queue.pop(0)


def _body(response: JSONResponse) -> dict[str, Any]:
    assert isinstance(response, JSONResponse)
    return json.loads(bytes(response.body).decode("utf-8"))


def _now() -> datetime:
    return datetime.now(UTC)


def _identity(
    *, name: str | None = None, phone: str | None = None, email: str | None = None
) -> SimpleNamespace:
    """AESGCM 봉투로 감싼 UserIdentity 대역.

    라우터의 ``_decrypt_text``는 fail-closed다 - 평문 바이트를 넣으면(통합 전 worktree
    fixture가 그랬다) 연락처가 아예 조립되지 않는다. purpose 태그도 라우터가 쓰는 값과
    정확히 같아야 한다.
    """

    settings = get_settings()

    def _enc(value: str | None, purpose: str) -> bytes | None:
        if value is None:
            return None
        return encrypt_secret(value, purpose=purpose, settings=settings)

    return SimpleNamespace(
        name_enc=_enc(name, "identity-name"),
        phone_enc=_enc(phone, "identity-phone"),
        email_enc=_enc(email, "identity-email"),
    )


def _contact_share(
    *,
    shared_fields: list[str],
    accepted_at: datetime | None,
    exhibitor_enabled_at: datetime | None,
    disclosed_at: datetime | None = None,
    disclosed_to_user_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    """세 번째 게이트(exhibitor_enabled_at)를 반드시 명시하게 만드는 fixture 헬퍼."""

    return SimpleNamespace(
        shared_fields=shared_fields,
        accepted_at=accepted_at,
        exhibitor_enabled_at=exhibitor_enabled_at,
        exhibitor_enabled_by_staff_id=None,
        disclosed_at=disclosed_at,
        disclosed_to_user_id=disclosed_to_user_id,
        meeting_contact_share_id=uuid.uuid4(),
    )


# ===========================================================================
# CHECK 1 -- zero contact-info exposure before meeting acceptance + consent
# ===========================================================================


def _staff(participation_id: uuid.UUID, *, user_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        staff_id=uuid.uuid4(),
        participation_id=participation_id,
        user_id=user_id or uuid.uuid4(),
        active=True,
    )


def _meeting(
    *,
    participation_id: uuid.UUID,
    buyer_profile_id: uuid.UUID,
    status: str,
    tenant_id: uuid.UUID | None = None,
    event_id: uuid.UUID | None = None,
    row_version: int = 0,
    concept_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    return SimpleNamespace(
        meeting_id=uuid.uuid4(),
        participation_id=participation_id,
        buyer_profile_id=buyer_profile_id,
        tenant_id=tenant_id or uuid.uuid4(),
        event_id=event_id or uuid.uuid4(),
        status=status,
        row_version=row_version,
        concept_id=concept_id,
        message_enc=None,
        viewed_at=None,
    )


async def test_contact_not_exposed_before_acceptance() -> None:
    """meeting.status == 'requested' (not yet accepted) -> contact must stay hidden.

    Traced db.execute() order inside get_partner_buyer_summary for this branch:
      1) select(BuyerNeed)...        -> scalar_one_or_none()
      2) select(MeetingContactShare)... -> scalar_one_or_none()
    The identity/contact-assembly block is only entered when status == MEETING_CONFIRMED_STATUS,
    so no further execute() calls happen when status == 'requested' -- if the router regresses
    and queries identity anyway, this fake raises AssertionError("unscripted call").
    """

    participation_id = uuid.uuid4()
    staff = _staff(participation_id)
    meeting = _meeting(
        participation_id=participation_id, buyer_profile_id=uuid.uuid4(), status="requested"
    )
    contact_share = _contact_share(
        shared_fields=["NAME", "PHONE"],
        accepted_at=_now(),
        exhibitor_enabled_at=_now(),
    )
    session = FakeSession(
        get_map={ExhibitorStaff: staff, MeetingRequest: meeting},
        execute_queue=[_none(), _row(contact_share)],
    )

    response = await meetings_router.get_partner_buyer_summary(
        meeting.meeting_id, db=session, staff_id=staff.staff_id, x_request_id="req-1"
    )

    body = _body(response)
    assert response.status_code == 200
    assert body["data"]["contact"] is None
    assert body["data"]["contact_disclosed"] is False
    assert session.added == [], "no audit log should be written when contact stays hidden"


async def test_contact_not_exposed_without_recorded_consent() -> None:
    """meeting.status == accepted but no MeetingContactShare row exists -> still hidden.

    A confirmed meeting alone must never be sufficient; interface-spec 12.3/15절 and
    meeting.py's MeetingContactShare docstring both require an explicit consent row.
    """

    participation_id = uuid.uuid4()
    staff = _staff(participation_id)
    meeting = _meeting(
        participation_id=participation_id,
        buyer_profile_id=uuid.uuid4(),
        status=MEETING_CONFIRMED_STATUS,
    )
    session = FakeSession(
        get_map={ExhibitorStaff: staff, MeetingRequest: meeting},
        execute_queue=[_none(), _none()],  # BuyerNeed, MeetingContactShare (absent)
    )

    response = await meetings_router.get_partner_buyer_summary(
        meeting.meeting_id, db=session, staff_id=staff.staff_id, x_request_id="req-2"
    )

    body = _body(response)
    assert body["data"]["contact"] is None
    assert body["data"]["contact_disclosed"] is False


async def test_contact_not_exposed_when_consent_accepted_at_is_missing() -> None:
    """A contact_share row whose accepted_at is unset must not count as consent.

    meeting.py's MeetingContactShare docstring: "accepted_at만으로 연락처를 공개하지 않는다"
    also implies the converse must hold -- no accepted_at, no disclosure, ever.
    """

    participation_id = uuid.uuid4()
    staff = _staff(participation_id)
    meeting = _meeting(
        participation_id=participation_id,
        buyer_profile_id=uuid.uuid4(),
        status=MEETING_CONFIRMED_STATUS,
    )
    contact_share = _contact_share(
        shared_fields=["NAME"], accepted_at=None, exhibitor_enabled_at=_now()
    )
    session = FakeSession(
        get_map={ExhibitorStaff: staff, MeetingRequest: meeting},
        execute_queue=[_none(), _row(contact_share)],
    )

    response = await meetings_router.get_partner_buyer_summary(
        meeting.meeting_id, db=session, staff_id=staff.staff_id, x_request_id="req-3"
    )

    assert _body(response)["data"]["contact"] is None


async def test_contact_not_exposed_when_exhibitor_never_enabled_sharing() -> None:
    """세 번째 게이트 회귀 테스트 (MERGE STEP 15/22).

    상담은 accepted이고 바이어 동의(accepted_at)도 있지만 참가업체가 이 상담에 한해
    공유를 켜지 않았다(exhibitor_enabled_at IS NULL). 통합 전 main은 이 조건을 아예
    확인하지 않아 바이어 동의만으로 이름/전화/이메일을 파트너 포털에 노출했다.

    이 경로에서는 identity를 조회하는 execute()가 일어나면 안 된다 - FakeSession의 큐가
    비어 있으므로 라우터가 회귀하면 "unscripted db.execute() call"로 즉시 터진다.
    """

    participation_id = uuid.uuid4()
    staff = _staff(participation_id)
    meeting = _meeting(
        participation_id=participation_id,
        buyer_profile_id=uuid.uuid4(),
        status=MEETING_CONFIRMED_STATUS,
    )
    contact_share = _contact_share(
        shared_fields=["NAME", "PHONE", "BUSINESS_EMAIL"],
        accepted_at=_now(),
        exhibitor_enabled_at=None,
    )
    session = FakeSession(
        get_map={ExhibitorStaff: staff, MeetingRequest: meeting},
        execute_queue=[_none(), _row(contact_share)],
    )

    response = await meetings_router.get_partner_buyer_summary(
        meeting.meeting_id, db=session, staff_id=staff.staff_id, x_request_id="req-3b"
    )

    body = _body(response)
    assert body["data"]["contact"] is None
    assert body["data"]["contact_disclosed"] is False
    assert contact_share.disclosed_at is None
    assert session.added == [], "숨긴 연락처에 대해 열람 감사로그를 남겨서는 안 된다"


async def test_contact_exposed_only_after_acceptance_and_consent_and_audit_logged() -> None:
    """Positive control: status == accepted AND consent recorded -> contact appears, and the
    disclosure is audit-logged exactly once (wireframes 8절 E-03 "연락처 열람 시 ... 감사로그").

    Traced db.execute() order for this branch:
      1) select(BuyerNeed)...            -> scalar_one_or_none()
      2) select(MeetingContactShare)...  -> scalar_one_or_none()
      3) select(UserIdentity)...         -> scalar_one_or_none()
    Plus one db.get(UserProfile, ...) for the buyer profile lookup.
    """

    participation_id = uuid.uuid4()
    staff = _staff(participation_id)
    buyer_profile_id = uuid.uuid4()
    buyer_user_id = uuid.uuid4()
    meeting = _meeting(
        participation_id=participation_id,
        buyer_profile_id=buyer_profile_id,
        status=MEETING_CONFIRMED_STATUS,
    )
    contact_share = _contact_share(
        shared_fields=["NAME", "PHONE"],
        accepted_at=_now(),
        exhibitor_enabled_at=_now(),
    )
    buyer_profile = SimpleNamespace(profile_id=buyer_profile_id, user_id=buyer_user_id)
    identity = _identity(name="김희섭", phone="010-0000-0000", email="buyer@example.com")

    class Session(FakeSession):
        async def get(self, model: type, pk: Any) -> Any:  # type: ignore[override]
            if model is ExhibitorStaff:
                return staff
            if model is MeetingRequest:
                return meeting
            # UserProfile lookup by buyer_profile_id, keyed dynamically since two different
            # models (staff/meeting) already occupy the flat get_map.
            if getattr(model, "__name__", "") == "UserProfile":
                return buyer_profile
            return None

    session = Session(execute_queue=[_none(), _row(contact_share), _row(identity)])

    response = await meetings_router.get_partner_buyer_summary(
        meeting.meeting_id, db=session, staff_id=staff.staff_id, x_request_id="req-4"
    )

    body = _body(response)
    assert body["data"]["contact"] == {"NAME": "김희섭", "PHONE": "010-0000-0000"}
    assert body["data"]["contact_disclosed"] is True
    assert contact_share.disclosed_at is not None
    assert contact_share.disclosed_to_user_id == staff.user_id
    audit_rows = [row for row in session.added if type(row).__name__ == "AuditLog"]
    assert len(audit_rows) == 1
    assert audit_rows[0].action_type == "VIEW"
    assert audit_rows[0].reason_code == "PARTNER_BUYER_CONTACT_VIEW"
    assert session.commits == 1


async def test_contact_disclosure_is_only_audit_logged_once() -> None:
    """A second view of an already-disclosed contact must not write a duplicate audit row."""

    participation_id = uuid.uuid4()
    staff = _staff(participation_id)
    buyer_profile_id = uuid.uuid4()
    meeting = _meeting(
        participation_id=participation_id,
        buyer_profile_id=buyer_profile_id,
        status=MEETING_CONFIRMED_STATUS,
    )
    already_disclosed_at = _now() - timedelta(minutes=5)
    contact_share = _contact_share(
        shared_fields=["NAME"],
        accepted_at=_now() - timedelta(minutes=10),
        exhibitor_enabled_at=_now() - timedelta(minutes=8),
        disclosed_at=already_disclosed_at,
        disclosed_to_user_id=staff.user_id,
    )
    buyer_profile = SimpleNamespace(profile_id=buyer_profile_id, user_id=uuid.uuid4())
    identity = _identity(name="홍길동")

    class Session(FakeSession):
        async def get(self, model: type, pk: Any) -> Any:  # type: ignore[override]
            if model is ExhibitorStaff:
                return staff
            if model is MeetingRequest:
                return meeting
            if getattr(model, "__name__", "") == "UserProfile":
                return buyer_profile
            return None

    session = Session(execute_queue=[_none(), _row(contact_share), _row(identity)])

    response = await meetings_router.get_partner_buyer_summary(
        meeting.meeting_id, db=session, staff_id=staff.staff_id, x_request_id="req-5"
    )

    assert _body(response)["data"]["contact_disclosed"] is True
    assert contact_share.disclosed_at == already_disclosed_at, "must not overwrite first disclosure time"
    assert [row for row in session.added if type(row).__name__ == "AuditLog"] == []


# ===========================================================================
# CHECK 2 -- zero cross-buyer / cross-exhibitor data access
# ===========================================================================


async def test_buyer_cannot_read_another_buyers_meeting() -> None:
    owner_id, attacker_id = uuid.uuid4(), uuid.uuid4()
    meeting = _meeting(participation_id=uuid.uuid4(), buyer_profile_id=owner_id, status="requested")
    session = FakeSession(get_map={MeetingRequest: meeting})

    response = await meetings_router.get_meeting(
        meeting.meeting_id, db=session, buyer_profile_id=attacker_id, x_request_id="req-6"
    )

    assert response.status_code == 404
    assert _body(response)["error"]["code"] == "RESOURCE_FORBIDDEN"


async def test_buyer_cannot_cancel_another_buyers_meeting() -> None:
    owner_id, attacker_id = uuid.uuid4(), uuid.uuid4()
    meeting = _meeting(participation_id=uuid.uuid4(), buyer_profile_id=owner_id, status="requested")
    session = FakeSession(execute_queue=[_row(meeting)])

    response = await meetings_router.cancel_meeting(
        meeting.meeting_id,
        MeetingCancelRequest(version=0),
        db=session,
        buyer_profile_id=attacker_id,
        idempotency_key=None,
        x_request_id="req-7",
    )

    assert response.status_code == 404
    assert _body(response)["error"]["code"] == "RESOURCE_FORBIDDEN"
    assert session.rollbacks == 1
    assert session.commits == 0


async def test_exhibitor_staff_cannot_read_meeting_from_another_participation() -> None:
    real_participation = uuid.uuid4()
    other_participation = uuid.uuid4()
    staff = _staff(other_participation)
    meeting = _meeting(
        participation_id=real_participation, buyer_profile_id=uuid.uuid4(), status=MEETING_CONFIRMED_STATUS
    )
    session = FakeSession(get_map={ExhibitorStaff: staff, MeetingRequest: meeting})

    response = await meetings_router.get_partner_buyer_summary(
        meeting.meeting_id, db=session, staff_id=staff.staff_id, x_request_id="req-8"
    )

    assert response.status_code == 404
    assert _body(response)["error"]["code"] == "RESOURCE_FORBIDDEN"


async def test_exhibitor_staff_cannot_decide_on_meeting_from_another_participation() -> None:
    real_participation = uuid.uuid4()
    other_participation = uuid.uuid4()
    staff = _staff(other_participation)
    meeting = _meeting(
        participation_id=real_participation, buyer_profile_id=uuid.uuid4(), status="requested"
    )
    session = FakeSession(get_map={ExhibitorStaff: staff}, execute_queue=[_row(meeting)])

    response = await meetings_router.decide_meeting(
        meeting.meeting_id,
        PartnerDecisionRequest(action="REJECT", version=0),
        db=session,
        staff_id=staff.staff_id,
        idempotency_key=None,
        x_request_id="req-9",
    )

    assert response.status_code == 404
    assert _body(response)["error"]["code"] == "RESOURCE_FORBIDDEN"
    assert session.rollbacks == 1


async def test_inactive_staff_account_is_treated_as_unauthenticated() -> None:
    """An ExhibitorStaff row with active=False must not authenticate (offboarded staff)."""

    participation_id = uuid.uuid4()
    inactive_staff = SimpleNamespace(
        staff_id=uuid.uuid4(), participation_id=participation_id, user_id=uuid.uuid4(), active=False
    )
    session = FakeSession(get_map={ExhibitorStaff: inactive_staff})

    response = await meetings_router.list_partner_meetings(
        db=session, staff_id=inactive_staff.staff_id, x_request_id="req-10"
    )

    assert response.status_code == 401
    assert _body(response)["error"]["code"] == "AUTH_REQUIRED"


# ===========================================================================
# CHECK 3 -- zero unverified-buyer meeting requests succeeding
# ===========================================================================


def _create_payload(exhibitor_id: uuid.UUID, slot_id: uuid.UUID) -> MeetingCreateRequest:
    return MeetingCreateRequest(
        exhibitor_id=exhibitor_id,
        topic="BIZ_GOAL.DISTRIBUTION",
        requested_slot_ids=[slot_id],
        message="상담을 요청합니다.",
        contact_share=None,
    )


async def test_meeting_creation_rejected_when_no_buyer_profile_header_present() -> None:
    """The unauthenticated-request gate must reject before ever touching the database."""

    class ExplodingSession:
        async def get(self, *_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("must not query the database for an unauthenticated request")

        async def execute(self, *_args: Any, **_kwargs: Any) -> Any:
            raise AssertionError("must not query the database for an unauthenticated request")

    response = await meetings_router.create_meeting(
        _create_payload(uuid.uuid4(), uuid.uuid4()),
        db=ExplodingSession(),  # type: ignore[arg-type]
        buyer_profile_id=None,
        idempotency_key=None,
        x_request_id="req-11",
    )

    assert response.status_code == 401
    assert _body(response)["error"]["code"] == "AUTH_REQUIRED"


async def test_meeting_creation_rejected_for_unverified_account_state() -> None:
    """profile.user_id resolves but the linked account is not PHONE_VERIFIED/ACCOUNT_AUTHENTICATED."""

    buyer_profile_id = uuid.uuid4()
    user_id = uuid.uuid4()
    profile = SimpleNamespace(
        profile_id=buyer_profile_id,
        user_id=user_id,
        user_type="BUYER",
        deleted_at=None,
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
    )
    unverified_account = SimpleNamespace(user_id=user_id, authentication_state="GUEST")

    class Session(FakeSession):
        async def get(self, model: type, _pk: Any) -> Any:  # type: ignore[override]
            if getattr(model, "__name__", "") == "UserProfile":
                return profile
            if getattr(model, "__name__", "") == "UserAccount":
                return unverified_account
            return None

    response = await meetings_router.create_meeting(
        _create_payload(uuid.uuid4(), uuid.uuid4()),
        db=Session(),
        buyer_profile_id=buyer_profile_id,
        idempotency_key=None,
        x_request_id="req-12",
    )

    assert response.status_code == 401
    assert _body(response)["error"]["code"] == "AUTH_REQUIRED"


async def test_meeting_creation_rejected_when_account_missing_entirely() -> None:
    buyer_profile_id = uuid.uuid4()
    user_id = uuid.uuid4()
    profile = SimpleNamespace(
        profile_id=buyer_profile_id,
        user_id=user_id,
        user_type="BUYER",
        deleted_at=None,
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
    )

    class Session(FakeSession):
        async def get(self, model: type, _pk: Any) -> Any:  # type: ignore[override]
            if getattr(model, "__name__", "") == "UserProfile":
                return profile
            return None  # UserAccount row absent entirely

    response = await meetings_router.create_meeting(
        _create_payload(uuid.uuid4(), uuid.uuid4()),
        db=Session(),
        buyer_profile_id=buyer_profile_id,
        idempotency_key=None,
        x_request_id="req-13",
    )

    assert response.status_code == 401


async def test_meeting_creation_rejected_for_a_deleted_profile() -> None:
    buyer_profile_id = uuid.uuid4()
    deleted_profile = SimpleNamespace(
        profile_id=buyer_profile_id, user_id=uuid.uuid4(), user_type="BUYER", deleted_at=_now()
    )

    class Session(FakeSession):
        async def get(self, model: type, _pk: Any) -> Any:  # type: ignore[override]
            if getattr(model, "__name__", "") == "UserProfile":
                return deleted_profile
            return None

    response = await meetings_router.create_meeting(
        _create_payload(uuid.uuid4(), uuid.uuid4()),
        db=Session(),
        buyer_profile_id=buyer_profile_id,
        idempotency_key=None,
        x_request_id="req-14",
    )

    assert response.status_code == 403
    assert _body(response)["error"]["code"] == "RESOURCE_FORBIDDEN"


async def test_meeting_creation_rejected_for_a_general_visitor_profile() -> None:
    """A GENERAL_VISITOR profile must never be able to submit a buyer meeting request."""

    buyer_profile_id = uuid.uuid4()
    user_id = uuid.uuid4()
    visitor_profile = SimpleNamespace(
        profile_id=buyer_profile_id,
        user_id=user_id,
        user_type="GENERAL_VISITOR",
        deleted_at=None,
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
    )
    verified_account = SimpleNamespace(user_id=user_id, authentication_state="PHONE_VERIFIED")

    class Session(FakeSession):
        async def get(self, model: type, _pk: Any) -> Any:  # type: ignore[override]
            if getattr(model, "__name__", "") == "UserProfile":
                return visitor_profile
            if getattr(model, "__name__", "") == "UserAccount":
                return verified_account
            return None

    response = await meetings_router.create_meeting(
        _create_payload(uuid.uuid4(), uuid.uuid4()),
        db=Session(),
        buyer_profile_id=buyer_profile_id,
        idempotency_key=None,
        x_request_id="req-15",
    )

    assert response.status_code == 403
    assert _body(response)["error"]["code"] == "RESOURCE_FORBIDDEN"


# ===========================================================================
# CHECK 4 -- zero hard-filter violations in match results
# CHECK 5 -- zero unapproved/unpublished exhibitors appearing in match results
# CHECK 6 -- UNKNOWN trade-condition fields are never coerced to YES/NO
# ===========================================================================
#
# These three checks are exercised against the *real* production hard-filter engine
# (app.services.matching.hard_filter.evaluate_hard_filters), not a reimplementation, so a
# regression in the actual filter logic fails these tests.


def _profile(
    *,
    numeric_conditions: dict[str, Any] | None = None,
    goals: list[GoalItem] | None = None,
    raw_context: dict[str, Any] | None = None,
) -> ResolvedProfile:
    return ResolvedProfile(
        profile_id=uuid.uuid4(),
        profile_version=1,
        profile_version_id=uuid.uuid4(),
        user_type="BUYER",
        completeness=100.0,
        goals=goals or [],
        categories=[],
        channels=[],
        regions=[],
        taste=[],
        aroma=[],
        extra={},
        numeric_conditions=numeric_conditions or {},
        raw_context=raw_context or {},
    )


def _context() -> ResolvedContext:
    return ResolvedContext(
        current_zone=None,
        current_zone_id=None,
        remaining_minutes=None,
        visited_booth_ids=set(),
        upcoming_meetings=[],
        upcoming_meeting_booth_ids=set(),
        operational_snapshot_version=1,
        exclude_visited=False,
        include_meetings=False,
        avoid_congestion=False,
        server_time=_now(),
    )


def _exhibitor_candidate(
    *,
    master_approval_status: str = "APPROVED",
    participation_status: str = "APPROVED",
    oem_status: str = "UNKNOWN",
    export_status: str = "UNKNOWN",
    private_label_status: str = "UNKNOWN",
    min_order_quantity: int | None = None,
) -> MatchCandidate:
    return MatchCandidate(
        object_type="EXHIBITOR",
        object_id=uuid.uuid4(),
        recommendable_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        participation_id=uuid.uuid4(),
        public_object_id="exhibitor-public-001",
        payload={
            "master_approval_status": master_approval_status,
            "participation_status": participation_status,
            "consultation_enabled": True,
            "supply_profile": {
                "trade_profile": {
                    "channels": [],
                    "regions": [],
                    "min_order_quantity": min_order_quantity,
                    "monthly_available_capacity": None,
                    "oem_status": oem_status,
                    "export_status": export_status,
                    "private_label_status": private_label_status,
                }
            },
        },
    )


def _run(profile: ResolvedProfile, candidates: list[MatchCandidate]) -> hard_filter.HardFilterEvaluation:
    from app.services.matching.types import SubjectContext

    subject = SubjectContext(
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        profile_id=profile.profile_id,
        visit_session_id=None,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        request_id="req-hard-filter",
        idempotency_key=None,
        server_time=_now(),
    )
    return hard_filter.evaluate_hard_filters(
        candidates=candidates,
        subject=subject,
        profile=profile,
        context=_context(),
        excluded_recommendable_ids=set(),
    )


def test_hard_filter_rejects_an_unapproved_exhibitor() -> None:
    candidate = _exhibitor_candidate(master_approval_status="SUBMITTED")
    evaluation = _run(_profile(), [candidate])

    assert evaluation.eligible_candidates == []
    assert evaluation.outcomes[0].passed is False
    assert evaluation.outcomes[0].filter_code == "ADMIN_NOT_APPROVED"


def test_hard_filter_rejects_a_cancelled_participation() -> None:
    candidate = _exhibitor_candidate(participation_status="CANCELLED")
    evaluation = _run(_profile(), [candidate])

    assert evaluation.eligible_candidates == []
    assert evaluation.outcomes[0].filter_code == "PARTICIPATION_CANCELLED"


def test_hard_filter_passes_a_fully_approved_exhibitor_with_no_buyer_requirements() -> None:
    candidate = _exhibitor_candidate()
    evaluation = _run(_profile(), [candidate])

    assert evaluation.eligible_candidates == [candidate]
    assert evaluation.outcomes[0].passed is True


def test_hard_filter_rejects_moq_below_buyer_minimum_requirement() -> None:
    candidate = _exhibitor_candidate(min_order_quantity=1_000)
    profile = _profile(numeric_conditions={"monthly_units_max": 100})
    evaluation = _run(profile, [candidate])

    assert evaluation.outcomes[0].filter_code == "MOQ_MISMATCH"


def test_hard_filter_treats_unknown_oem_status_as_not_a_violation() -> None:
    """A buyer whose goal REQUIRES OEM must not be blocked by an exhibitor whose OEM
    capability is simply not yet declared (UNKNOWN) -- only an explicit 'NO' is a hard
    mismatch. UNKNOWN must never be silently treated as a YES *or* a NO.
    """

    candidate = _exhibitor_candidate(oem_status="UNKNOWN")
    profile = _profile(
        goals=[GoalItem(code="BIZ_GOAL.OEM", priority=1, requirement_level="REQUIRED", confidence=1.0, source="PROFILE")]
    )
    evaluation = _run(profile, [candidate])

    assert evaluation.eligible_candidates == [candidate]
    assert evaluation.outcomes[0].passed is True


def test_hard_filter_treats_unknown_export_status_as_not_a_violation() -> None:
    candidate = _exhibitor_candidate(export_status="UNKNOWN")
    profile = _profile(
        goals=[GoalItem(code="BIZ_GOAL.EXPORT", priority=1, requirement_level="REQUIRED", confidence=1.0, source="PROFILE")]
    )
    evaluation = _run(profile, [candidate])

    assert evaluation.eligible_candidates == [candidate]


def test_hard_filter_rejects_only_an_explicit_no_for_oem_requirement() -> None:
    """Control for the two tests above: an explicit 'NO' (not UNKNOWN) is a real mismatch."""

    candidate = _exhibitor_candidate(oem_status="NO")
    profile = _profile(
        goals=[GoalItem(code="BIZ_GOAL.OEM", priority=1, requirement_level="REQUIRED", confidence=1.0, source="PROFILE")]
    )
    evaluation = _run(profile, [candidate])

    assert evaluation.eligible_candidates == []
    assert evaluation.outcomes[0].filter_code == "OEM_MISMATCH"


def test_hard_filter_rejects_only_an_explicit_no_for_export_requirement() -> None:
    candidate = _exhibitor_candidate(export_status="NO")
    profile = _profile(
        goals=[GoalItem(code="BIZ_GOAL.EXPORT", priority=1, requirement_level="REQUIRED", confidence=1.0, source="PROFILE")]
    )
    evaluation = _run(profile, [candidate])

    assert evaluation.eligible_candidates == []
    assert evaluation.outcomes[0].filter_code == "EXPORT_MISMATCH"


def test_hard_filter_batch_never_leaks_an_unapproved_candidate_alongside_valid_ones() -> None:
    """A realistic mixed batch: only the fully-approved, non-violating candidate survives."""

    approved = _exhibitor_candidate()
    unapproved = _exhibitor_candidate(master_approval_status="DRAFT")
    cancelled = _exhibitor_candidate(participation_status="CANCELLED")
    oem_violation = _exhibitor_candidate(oem_status="NO")
    profile = _profile(
        goals=[GoalItem(code="BIZ_GOAL.OEM", priority=1, requirement_level="REQUIRED", confidence=1.0, source="PROFILE")]
    )

    evaluation = _run(profile, [approved, unapproved, cancelled, oem_violation])

    assert evaluation.eligible_candidates == [approved]
    codes = {c.filter_code for c in evaluation.outcomes if not c.passed}
    assert codes == {"ADMIN_NOT_APPROVED", "PARTICIPATION_CANCELLED", "OEM_MISMATCH"}


def test_hard_filter_excludes_a_user_dismissed_recommendable_even_if_otherwise_eligible() -> None:
    candidate = _exhibitor_candidate()
    from app.services.matching.types import SubjectContext

    subject = SubjectContext(
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        profile_id=uuid.uuid4(),
        visit_session_id=None,
        user_id=uuid.uuid4(),
        guest_session_id=None,
        request_id="req-excluded",
        idempotency_key=None,
        server_time=_now(),
    )
    evaluation = hard_filter.evaluate_hard_filters(
        candidates=[candidate],
        subject=subject,
        profile=_profile(),
        context=_context(),
        excluded_recommendable_ids={candidate.recommendable_id},
    )
    assert evaluation.eligible_candidates == []
    assert evaluation.outcomes[0].filter_code == "USER_EXCLUDED"


def test_unknown_availability_status_never_collapses_to_a_numeric_score() -> None:
    """Stage-6 feature construction: UNKNOWN must yield None (component dropped from the
    weighted score), never a guessed numeric value -- see feature_builder module docstring
    ("The builder never converts an absent input into a neutral score").
    """

    assert feature_builder._AVAILABILITY_STATUS_SCORE["UNKNOWN"] is None
    for status, value in feature_builder._AVAILABILITY_STATUS_SCORE.items():
        if status != "UNKNOWN":
            assert value is not None, f"non-UNKNOWN status {status!r} must have a real score"


def test_meeting_response_never_invents_a_topic_code_for_an_unresolved_concept() -> None:
    """_concept_code_for(None) must return None, never a fabricated/guessed code string."""

    assert meetings_router._concept_code_for(None) is None


def test_supply_profile_defaults_trade_conditions_to_unknown_not_no() -> None:
    """Regression guard on the data-loading layer (candidate_generator._load_supply_profiles):
    an exhibitor with no TradeCondition row at all must default to UNKNOWN, never NO -- a
    missing trade condition is not evidence of refusal.
    """

    import inspect

    source = inspect.getsource(
        __import__(
            "app.services.matching.candidate_generator", fromlist=["_load_supply_profiles"]
        )._load_supply_profiles
    )
    assert '"oem_status": "UNKNOWN"' in source
    assert '"export_status": "UNKNOWN"' in source
    assert '"private_label_status": "UNKNOWN"' in source


# ===========================================================================
# CHECK 7 -- meeting status transitions never skip states illegally
# ===========================================================================


def test_meeting_status_vocabulary_only_has_the_documented_eight_states() -> None:
    assert set(MEETING_STATUSES) == {
        "draft",
        "requested",
        "accepted",
        "counter_proposed",
        "rejected",
        "cancelled",
        "completed",
        "no_show",
    }


async def test_outcome_recording_rejects_a_meeting_that_was_never_accepted() -> None:
    """This is the direct proof that REQUESTED -> COMPLETED cannot happen: recording an
    outcome (the only path to 'completed') is refused unless status is already
    'accepted' or 'completed'.
    """

    participation_id = uuid.uuid4()
    staff = _staff(participation_id)
    meeting = _meeting(participation_id=participation_id, buyer_profile_id=uuid.uuid4(), status="requested")
    session = FakeSession(get_map={ExhibitorStaff: staff, MeetingRequest: meeting})

    response = await meetings_router.record_meeting_outcome(
        meeting.meeting_id,
        MeetingOutcomeRequest(outcome_code="MEETING_OUTCOME.QUALIFIED_LEAD", is_qualified_lead=True),
        db=session,
        staff_id=staff.staff_id,
        x_request_id="req-16",
    )

    assert response.status_code == 409
    assert _body(response)["error"]["code"] == "MEETING_CONFLICT"
    assert meeting.status == "requested", "status must be unchanged after a rejected transition"


async def test_decision_action_rejects_accepting_an_already_accepted_meeting() -> None:
    """Once accepted, the exhibitor cannot re-run ACCEPT/REJECT/COUNTER_PROPOSE -- this is the
    concrete guard against any accidental double-transition or replay.
    """

    participation_id = uuid.uuid4()
    staff = _staff(participation_id)
    meeting = _meeting(
        participation_id=participation_id, buyer_profile_id=uuid.uuid4(), status="accepted"
    )
    session = FakeSession(get_map={ExhibitorStaff: staff}, execute_queue=[_row(meeting)])

    response = await meetings_router.decide_meeting(
        meeting.meeting_id,
        PartnerDecisionRequest(action="ACCEPT", slot_id=uuid.uuid4(), version=0),
        db=session,
        staff_id=staff.staff_id,
        idempotency_key=None,
        x_request_id="req-17",
    )

    assert response.status_code == 409
    assert _body(response)["error"]["code"] == "MEETING_CONFLICT"


async def test_buyer_cannot_cancel_a_completed_meeting() -> None:
    """'completed' is a terminal state -- cancellation must not resurrect it."""

    meeting = _meeting(participation_id=uuid.uuid4(), buyer_profile_id=uuid.uuid4(), status="completed")
    session = FakeSession(execute_queue=[_row(meeting)])

    response = await meetings_router.cancel_meeting(
        meeting.meeting_id,
        MeetingCancelRequest(version=0),
        db=session,
        buyer_profile_id=meeting.buyer_profile_id,
        idempotency_key=None,
        x_request_id="req-18",
    )

    assert response.status_code == 409
    assert _body(response)["error"]["code"] == "MEETING_CONFLICT"
    assert meeting.status == "completed"


def test_decidable_source_statuses_never_include_a_terminal_state() -> None:
    """Static audit of the state-machine tables themselves: ACCEPT/REJECT/COUNTER_PROPOSE
    must only be reachable from 'requested' or 'counter_proposed', never from a terminal
    status (accepted/rejected/cancelled/completed/no_show/draft).
    """

    terminal_or_initial = {"draft", "accepted", "rejected", "cancelled", "completed", "no_show"}
    for action, sources in meetings_router._DECIDABLE_SOURCE_STATUSES.items():
        assert set(sources).isdisjoint(terminal_or_initial), (
            f"{action} source statuses {sources} must not include a terminal/initial state"
        )
        assert set(sources) <= set(MEETING_STATUSES)


def test_outcome_allowed_statuses_require_prior_acceptance() -> None:
    assert set(meetings_router._OUTCOME_ALLOWED_SOURCE_STATUSES) == {"accepted", "completed"}
    assert "requested" not in meetings_router._OUTCOME_ALLOWED_SOURCE_STATUSES
    assert "draft" not in meetings_router._OUTCOME_ALLOWED_SOURCE_STATUSES


def test_buyer_cancellable_statuses_exclude_all_terminal_states() -> None:
    for terminal in ("rejected", "cancelled", "completed", "no_show"):
        assert terminal not in meetings_router._BUYER_CANCELLABLE_STATUSES
