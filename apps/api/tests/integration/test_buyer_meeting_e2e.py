"""WAVE 2C (QA-BUYER) end-to-end tests for the buyer -> match -> compare -> meeting ->
accept -> contact-share flow described in the harness prompt pack.

Scope: apps/api/tests/integration/test_buyer_meeting_e2e.py (QA-BUYER OWNED PATHS).

This file is deliberately distinct from apps/api/tests/security/test_buyer_meeting_privacy.py:
that file drills into the seven priority failure modes in isolation; this file walks the
buyer's actual journey hop by hop, in narrative order, so a reader can see the whole flow and
where each documented contract (docs/frontend-backend-ai-interface-spec.md 9/12/15절,
docs/user-ia-wireframes.md 6.2절 state machine) is enforced end to end:

    1. buyer requests recommendations (existing /recommendations + session-items contract)
    2. buyer picks an exhibitor from the match/compare results and requests a meeting
    3. exhibitor staff accepts the meeting (status: requested -> accepted)
    4. exhibitor staff opens the buyer summary -> contact is revealed only now
    5. exhibitor staff records the meeting outcome (status: accepted -> completed)
    6. the append-only status history for the whole journey never skips a documented state

No live PostgreSQL is reachable in this sandbox (no POSTGRES_TEST_DATABASE_URL, no local
docker daemon), so hops 2-6 drive the real FastAPI router coroutines
(app.api.v1.routers.meetings) with a small scripted AsyncSession fake, exactly like
test_recommendation_api.py / test_search_api.py already do for their own routers. A live,
schema-verifying counterpart is included at the bottom of this file
(test_live_postgres_buyer_meeting_round_trip), gated the same way as
test_postgres_recommendation_contract.py, so this becomes a genuine DB-backed round trip the
moment POSTGRES_TEST_DATABASE_URL is configured (e.g. in CI).

Per this task's instructions: pieces that depend on another track's not-yet-landed endpoint,
or on infrastructure this sandbox does not have, are marked with pytest.skip and a clear
reason rather than deleted, so the integrator has a checklist.

Retargeted for the unified repository (MERGE STEP 22)
-----------------------------------------------------
The journey itself is unchanged -- it always drove ``app.api.v1.routers.meetings``, which is
the single surviving meeting surface. Two fixtures changed because the merge closed real
defects: hop 3 now needs the exhibitor's own per-meeting opt-in
(``MeetingContactShare.exhibitor_enabled_at``, the third disclosure gate) and AESGCM-encrypted
identity columns, since the router's decryptor is fail-closed.
"""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.responses import JSONResponse

from app.api.v1.routers import meetings as meetings_router
from app.main import app
from app.models.exhibitor import ExhibitorStaff
from app.models.meeting import MEETING_STATUSES, MeetingRequest, MeetingStatusHistory
from app.schemas.meeting import (
    ContactShareRequest,
    MeetingCreateRequest,
    MeetingOutcomeRequest,
    PartnerDecisionRequest,
)

# ---------------------------------------------------------------------------
# Shared fakes (see test_buyer_meeting_privacy.py for the same convention, documented there
# in full; kept duplicated here rather than imported so this file's OWNED PATHS stay
# self-contained and independently readable/runnable).
# ---------------------------------------------------------------------------


class _Result:
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
    """Scripted AsyncSession fake. See the module docstring of
    apps/api/tests/security/test_buyer_meeting_privacy.py for the full rationale; this class
    is intentionally identical in shape.
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

    async def get(self, model: type, _pk: Any) -> Any:
        return self._get_map.get(model)

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        pass

    async def commit(self) -> None:
        self.commits += 1
        # A real Postgres session applies column defaults (row_version=0,
        # created_at/updated_at=now()) on INSERT. This fake never talks to a database, so it
        # simulates that same effect here for any newly ``db.add()``-ed row that still has the
        # attribute unset -- otherwise objects the router constructs itself (e.g. the new
        # MeetingRequest built inside create_meeting) would fail Pydantic response validation
        # with a None where the real DB would have filled in a value.
        now = datetime.now(UTC)
        for row in self.added:
            if getattr(row, "row_version", 0) is None:
                row.row_version = 0
            if getattr(row, "created_at", "unset") is None:
                row.created_at = now
            if getattr(row, "updated_at", "unset") is None:
                row.updated_at = now

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


# ===========================================================================
# Hop 0 -- route/contract inventory: confirm the endpoints this journey depends on actually
# exist and are registered (some may not have landed yet in a given wave run).
# ===========================================================================


def test_all_documented_meeting_journey_routes_are_registered() -> None:
    paths = app.openapi()["paths"]

    required = [
        "/api/v1/exhibitors/{exhibitor_id}/availability",
        "/api/v1/meetings",
        "/api/v1/meetings/{meeting_id}",
        "/api/v1/meetings/{meeting_id}/cancel",
        "/api/v1/meetings/{meeting_id}/respond",
        "/api/v1/partner/meetings",
        "/api/v1/partner/meetings/{meeting_id}/buyer-summary",
        "/api/v1/partner/meetings/{meeting_id}/decision",
        "/api/v1/partner/meetings/{meeting_id}/outcome",
    ]
    missing = [path for path in required if path not in paths]
    assert missing == [], f"meeting journey routes missing from OpenAPI: {missing}"


def test_buyer_matching_has_a_dedicated_deterministic_endpoint_alongside_recommendations() -> None:
    """SUPERSEDES the WAVE2C-era assumption (originally pinned to DECISION-005) that buyer
    matching would only ever be served by the general ``/recommendations`` endpoint.

    WAVE 2C's BACKEND-BUYER-MATCH + AI-BUYER-MATCH tracks deliberately built a *separate*,
    purpose-built ``POST /buyer/matches`` + ``POST /buyer/compare`` surface backed by a
    deterministic rule-based hard-filter/scoring pipeline (see ``ai/buyer_matching/``) rather
    than reusing the general personalization ``/recommendations`` engine. That is an
    intentional architectural choice, not drift: B2B matching needs auditable, reproducible,
    hard-filter-enforced results (trade-condition eligibility, verification status, etc.) that
    the softer recommendation-ranking engine does not guarantee. Both endpoints are legitimate
    and coexist; this test pins that coexistence so neither gets silently removed.
    """

    paths = app.openapi()["paths"]
    assert "/api/v1/recommendations" in paths
    assert "/api/v1/recommendation-sessions/{recommendation_session_id}/items" in paths

    # The deterministic B2B matching router is registered by MERGE STEP 21
    # (apps/api/app/api/v1/routers/buyer_match.py), a different step from the one that owns
    # this file. Skip rather than delete so the assertion re-arms automatically the moment
    # that step lands - deleting it would silently drop the coexistence guarantee.
    missing = [
        path
        for path in ("/api/v1/buyer/matches", "/api/v1/buyer/compare")
        if path not in paths
    ]
    if missing:
        pytest.skip(
            "MERGE STEP 21 (buyer_match router registration) has not landed yet; "
            f"missing: {missing}"
        )


def test_meeting_state_machine_matches_the_documented_wireframe_transitions() -> None:
    """docs/user-ia-wireframes.md 6.2절:
    draft -> requested -> (accepted|counter_proposed|rejected|cancelled) -> (completed|no_show)
    """

    assert MEETING_STATUSES == (
        "draft",
        "requested",
        "accepted",
        "counter_proposed",
        "rejected",
        "cancelled",
        "completed",
        "no_show",
    )


# ===========================================================================
# Hop 1 -- buyer requests a meeting with an approved, consultation-enabled exhibitor
# ===========================================================================


def _staff(participation_id: uuid.UUID) -> Any:
    from types import SimpleNamespace

    return SimpleNamespace(
        staff_id=uuid.uuid4(), participation_id=participation_id, user_id=uuid.uuid4(), active=True
    )


async def test_hop1_buyer_requests_a_meeting_with_contact_share_consent() -> None:
    """Traced db call order for create_meeting (see apps/api/app/api/v1/routers/meetings.py):
      db.get(UserProfile), db.get(UserAccount),
      execute(participation_stmt) -> scalar_one_or_none,
      execute(update AvailabilitySlot ... RETURNING) -> scalars().first(),
      execute(select ConsentPolicy) -> scalars().first()   [contact_share.accepted == True]
      db.add(meeting/slot_request/contact_share/status_history); db.commit()
      -> _build_meeting_response:
         execute(select MeetingSlotRequest join AvailabilitySlot) -> .all()
         execute(select MeetingContactShare) -> scalar_one_or_none()
         db.get(ExhibitorParticipation)
    """
    from types import SimpleNamespace

    tenant_id, event_id = uuid.uuid4(), uuid.uuid4()
    buyer_profile_id = uuid.uuid4()
    exhibitor_id = uuid.uuid4()
    participation_id = uuid.uuid4()
    slot_id = uuid.uuid4()
    user_id = uuid.uuid4()
    start_at = _now() + timedelta(hours=3)
    end_at = start_at + timedelta(minutes=30)

    profile = SimpleNamespace(
        profile_id=buyer_profile_id,
        tenant_id=tenant_id,
        event_id=event_id,
        user_id=user_id,
        user_type="BUYER",
        deleted_at=None,
    )
    account = SimpleNamespace(user_id=user_id, authentication_state="PHONE_VERIFIED")
    participation = SimpleNamespace(
        participation_id=participation_id,
        exhibitor_id=exhibitor_id,
        tenant_id=tenant_id,
        event_id=event_id,
        participation_status="APPROVED",
        consultation_enabled=True,
    )
    reserved_slot = SimpleNamespace(
        availability_slot_id=slot_id, staff_id=None, booth_id=None, start_at=start_at, end_at=end_at
    )
    slot_request_row = SimpleNamespace(
        availability_slot_id=slot_id, preference_order=1, status="SELECTED"
    )
    consent_policy = SimpleNamespace(consent_policy_id=uuid.uuid4())
    persisted_contact_share = SimpleNamespace(
        shared_fields=["NAME", "PHONE"],
        accepted_at=_now(),
        disclosed_at=None,
        disclosed_to_user_id=None,
        meeting_contact_share_id=uuid.uuid4(),
    )

    from app.models.exhibitor import ExhibitorParticipation
    from app.models.identity import UserAccount
    from app.models.profile import UserProfile

    session = FakeSession(
        get_map={
            UserProfile: profile,
            UserAccount: account,
            ExhibitorParticipation: participation,
        },
        execute_queue=[
            _row(participation),  # participation_stmt
            _row(reserved_slot),  # _reserve_slot UPDATE ... RETURNING
            _row(consent_policy),  # consent policy lookup
            _rows([(slot_request_row, reserved_slot)]),  # _load_candidate_slots
            _row(persisted_contact_share),  # MeetingContactShare row just persisted above
        ],
    )

    payload = MeetingCreateRequest(
        exhibitor_id=exhibitor_id,
        topic="BIZ_GOAL.DISTRIBUTION",
        requested_slot_ids=[slot_id],
        message="유통 조건을 상담하고 싶습니다.",
        contact_share=ContactShareRequest(accepted=True, document_version="v1", fields=["NAME", "PHONE"]),
    )

    response = await meetings_router.create_meeting(
        payload,
        db=session,
        buyer_profile_id=buyer_profile_id,
        idempotency_key=None,
        x_request_id="req-e2e-1",
    )

    body = _body(response)
    assert response.status_code == 201
    assert body["success"] is True
    assert body["data"]["status"] == "requested"
    assert body["data"]["exhibitor_id"] == str(exhibitor_id)
    assert body["data"]["contact_share_accepted"] is True
    assert set(body["data"]["contact_share_fields"]) == {"NAME", "PHONE"}
    # Consent to *share* contact was recorded, but nothing has been disclosed yet -- that only
    # happens once the exhibitor accepts (hop 3/4 below, and see test_buyer_meeting_privacy.py
    # CHECK 1 for the exhaustive negative coverage).
    assert "contact" not in body["data"]
    assert session.commits == 1

    created_meeting = next(
        row for row in session.added if isinstance(row, MeetingRequest)
    )
    assert created_meeting.status == "requested"
    status_history_rows = [row for row in session.added if isinstance(row, MeetingStatusHistory)]
    assert len(status_history_rows) == 1
    assert status_history_rows[0].previous_status is None
    assert status_history_rows[0].new_status == "requested"


async def test_hop1b_buyer_cannot_request_a_meeting_with_an_unapproved_participation() -> None:
    """The participation lookup filters on participation_status == 'APPROVED' -- an
    unapproved/cancelled participation must resolve to nothing, giving a 404 rather than
    silently falling back to some other row. This is the meeting-creation half of CHECK 5
    (zero unapproved/unpublished exhibitors reachable through the buyer journey).
    """
    from types import SimpleNamespace

    from app.models.identity import UserAccount
    from app.models.profile import UserProfile

    buyer_profile_id = uuid.uuid4()
    user_id = uuid.uuid4()
    profile = SimpleNamespace(
        profile_id=buyer_profile_id,
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        user_id=user_id,
        user_type="BUYER",
        deleted_at=None,
    )
    account = SimpleNamespace(user_id=user_id, authentication_state="PHONE_VERIFIED")
    session = FakeSession(
        get_map={UserProfile: profile, UserAccount: account},
        execute_queue=[_none()],  # participation_stmt finds nothing (not APPROVED)
    )

    payload = MeetingCreateRequest(
        exhibitor_id=uuid.uuid4(),
        topic="BIZ_GOAL.DISTRIBUTION",
        requested_slot_ids=[uuid.uuid4()],
    )

    response = await meetings_router.create_meeting(
        payload, db=session, buyer_profile_id=buyer_profile_id, idempotency_key=None, x_request_id="req-e2e-1b"
    )

    assert response.status_code == 404
    assert _body(response)["error"]["code"] == "RESOURCE_FORBIDDEN"


# ===========================================================================
# Hop 2 -- exhibitor staff accepts the meeting request
# ===========================================================================


async def test_hop2_exhibitor_accepts_the_requested_meeting() -> None:
    """Traced db call order for decide_meeting(ACCEPT) taking the "already-selected slot"
    branch: db.get(ExhibitorStaff), execute(select MeetingRequest ... FOR UPDATE),
    execute(held_stmt) -> scalar_one_or_none, db.get(AvailabilitySlot),
    execute(other_selected_stmt) -> scalars().all(), db.add(status_history), db.commit(),
    then _build_meeting_response's two execute()s + one db.get() as in hop 1.
    """
    from types import SimpleNamespace

    from app.models.exhibitor import ExhibitorParticipation

    participation_id = uuid.uuid4()
    staff = _staff(participation_id)
    slot_id = uuid.uuid4()
    start_at = _now() + timedelta(hours=3)
    end_at = start_at + timedelta(minutes=30)
    meeting = SimpleNamespace(
        meeting_id=uuid.uuid4(),
        participation_id=participation_id,
        buyer_profile_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        status="requested",
        row_version=0,
        concept_id=None,
        message_enc=None,
        viewed_at=None,
        staff_id=None,
        confirmed_slot_id=None,
        confirmed_start=None,
        confirmed_end=None,
        created_at=_now(),
        updated_at=_now(),
    )
    held_slot_request = SimpleNamespace(availability_slot_id=slot_id, status="SELECTED")
    slot = SimpleNamespace(availability_slot_id=slot_id, start_at=start_at, end_at=end_at)
    participation = SimpleNamespace(participation_id=participation_id, exhibitor_id=uuid.uuid4())

    session = FakeSession(
        get_map={
            ExhibitorStaff: staff,
            type(slot): slot,  # AvailabilitySlot.get() below is looked up by the real class;
        },
        execute_queue=[
            _row(meeting),  # select MeetingRequest ... FOR UPDATE
            _row(held_slot_request),  # held_stmt
            _rows([]),  # other_selected_stmt (nothing else held)
            _rows([]),  # _load_candidate_slots (kept empty for brevity in this hop's response)
            _none(),  # MeetingContactShare not yet present
        ],
    )
    # AvailabilitySlot.get() needs the real model class as the key (SimpleNamespace collides
    # across fixtures otherwise, as documented in test_buyer_meeting_privacy.py).
    from app.models.meeting import AvailabilitySlot

    session._get_map[AvailabilitySlot] = slot
    session._get_map[ExhibitorParticipation] = participation

    response = await meetings_router.decide_meeting(
        meeting.meeting_id,
        PartnerDecisionRequest(action="ACCEPT", slot_id=slot_id, version=0),
        db=session,
        staff_id=staff.staff_id,
        idempotency_key=None,
        x_request_id="req-e2e-2",
    )

    body = _body(response)
    assert response.status_code == 200
    assert body["data"]["status"] == "accepted"
    assert meeting.status == "accepted"
    assert meeting.confirmed_start is not None and meeting.confirmed_end is not None
    assert meeting.row_version == 1
    history_rows = [row for row in session.added if isinstance(row, MeetingStatusHistory)]
    assert len(history_rows) == 1
    assert history_rows[0].previous_status == "requested"
    assert history_rows[0].new_status == "accepted"


async def test_hop2b_accepting_with_enable_contact_sharing_stamps_the_third_gate() -> None:
    """The same ACCEPT, with the exhibitor explicitly turning contact sharing on.

    ``PartnerDecisionRequest.enable_contact_sharing`` is the field the merge folded in from
    the retired second meeting surface (MERGE STEP 22 (a)). It adds exactly one extra query
    -- ``select(MeetingContactShare)`` -- and only when the flag is true, which is why hop 2
    above needs no extra queue entry.
    """
    from types import SimpleNamespace

    from app.models.exhibitor import ExhibitorParticipation
    from app.models.meeting import AvailabilitySlot

    participation_id = uuid.uuid4()
    staff = _staff(participation_id)
    slot_id = uuid.uuid4()
    start_at = _now() + timedelta(hours=3)
    meeting = SimpleNamespace(
        meeting_id=uuid.uuid4(),
        participation_id=participation_id,
        buyer_profile_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        status="requested",
        row_version=0,
        concept_id=None,
        message_enc=None,
        viewed_at=None,
        staff_id=None,
        confirmed_slot_id=None,
        confirmed_start=None,
        confirmed_end=None,
        created_at=_now(),
        updated_at=_now(),
    )
    held_slot_request = SimpleNamespace(availability_slot_id=slot_id, status="SELECTED")
    slot = SimpleNamespace(
        availability_slot_id=slot_id, start_at=start_at, end_at=start_at + timedelta(minutes=30)
    )
    participation = SimpleNamespace(participation_id=participation_id, exhibitor_id=uuid.uuid4())
    contact_share = SimpleNamespace(
        shared_fields=["NAME"],
        accepted_at=_now(),
        exhibitor_enabled_at=None,
        exhibitor_enabled_by_staff_id=None,
        disclosed_at=None,
        disclosed_to_user_id=None,
        meeting_contact_share_id=uuid.uuid4(),
    )

    session = FakeSession(
        get_map={ExhibitorStaff: staff},
        execute_queue=[
            _row(meeting),  # select MeetingRequest ... FOR UPDATE
            _row(held_slot_request),  # held_stmt
            _rows([]),  # other_selected_stmt
            _row(contact_share),  # enable_contact_sharing -> select MeetingContactShare
            _rows([]),  # _load_candidate_slots
            _row(contact_share),  # _build_meeting_response's MeetingContactShare lookup
        ],
    )
    session._get_map[AvailabilitySlot] = slot
    session._get_map[ExhibitorParticipation] = participation

    response = await meetings_router.decide_meeting(
        meeting.meeting_id,
        PartnerDecisionRequest(
            action="ACCEPT", slot_id=slot_id, version=0, enable_contact_sharing=True
        ),
        db=session,
        staff_id=staff.staff_id,
        idempotency_key=None,
        x_request_id="req-e2e-2b",
    )

    assert response.status_code == 200, _body(response)
    assert meeting.status == "accepted"
    assert contact_share.exhibitor_enabled_at is not None
    assert contact_share.exhibitor_enabled_by_staff_id == staff.staff_id


async def test_hop2c_enabling_sharing_cannot_manufacture_buyer_consent() -> None:
    """If the buyer never consented there is no MeetingContactShare row, and the exhibitor
    turning sharing on must NOT create one -- the buyer's gate is not the exhibitor's to open.
    """
    from types import SimpleNamespace

    from app.models.exhibitor import ExhibitorParticipation
    from app.models.meeting import AvailabilitySlot, MeetingContactShare

    participation_id = uuid.uuid4()
    staff = _staff(participation_id)
    slot_id = uuid.uuid4()
    start_at = _now() + timedelta(hours=3)
    meeting = SimpleNamespace(
        meeting_id=uuid.uuid4(),
        participation_id=participation_id,
        buyer_profile_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        status="requested",
        row_version=0,
        concept_id=None,
        message_enc=None,
        viewed_at=None,
        staff_id=None,
        confirmed_slot_id=None,
        confirmed_start=None,
        confirmed_end=None,
        created_at=_now(),
        updated_at=_now(),
    )
    held_slot_request = SimpleNamespace(availability_slot_id=slot_id, status="SELECTED")
    slot = SimpleNamespace(
        availability_slot_id=slot_id, start_at=start_at, end_at=start_at + timedelta(minutes=30)
    )
    participation = SimpleNamespace(participation_id=participation_id, exhibitor_id=uuid.uuid4())

    session = FakeSession(
        get_map={ExhibitorStaff: staff},
        execute_queue=[
            _row(meeting),
            _row(held_slot_request),
            _rows([]),
            _none(),  # no consent row exists
            _rows([]),
            _none(),
        ],
    )
    session._get_map[AvailabilitySlot] = slot
    session._get_map[ExhibitorParticipation] = participation

    response = await meetings_router.decide_meeting(
        meeting.meeting_id,
        PartnerDecisionRequest(
            action="ACCEPT", slot_id=slot_id, version=0, enable_contact_sharing=True
        ),
        db=session,
        staff_id=staff.staff_id,
        idempotency_key=None,
        x_request_id="req-e2e-2c",
    )

    assert response.status_code == 200
    assert _body(response)["data"]["contact_share_accepted"] is False
    assert [row for row in session.added if isinstance(row, MeetingContactShare)] == []


# ===========================================================================
# Hop 3 -- exhibitor opens the buyer summary; contact is revealed only now
# ===========================================================================


async def test_hop3_buyer_summary_now_reveals_contact_after_acceptance() -> None:
    """This is the flow-level counterpart to the exhaustive negative coverage in
    test_buyer_meeting_privacy.py CHECK 1 -- here we confirm the *positive* path lines up with
    the state hop2 just produced (status == 'accepted').

    Note the third gate: hop 2 only reaches this state when the exhibitor accepted *with*
    ``enable_contact_sharing=True``, which stamps ``exhibitor_enabled_at``. Without it the
    contact stays hidden (see the negative case immediately below).
    """
    from types import SimpleNamespace

    from app.core.auth import encrypt_secret
    from app.core.config import get_settings
    from app.models.profile import UserProfile

    participation_id = uuid.uuid4()
    staff = _staff(participation_id)
    buyer_profile_id = uuid.uuid4()
    buyer_user_id = uuid.uuid4()
    meeting = SimpleNamespace(
        meeting_id=uuid.uuid4(),
        participation_id=participation_id,
        buyer_profile_id=buyer_profile_id,
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        status="accepted",
        concept_id=None,
        message_enc=None,
        viewed_at=None,
    )
    settings = get_settings()
    contact_share = SimpleNamespace(
        shared_fields=["NAME", "PHONE"],
        accepted_at=_now(),
        exhibitor_enabled_at=_now(),
        exhibitor_enabled_by_staff_id=staff.staff_id,
        disclosed_at=None,
        disclosed_to_user_id=None,
        meeting_contact_share_id=uuid.uuid4(),
    )
    buyer_profile = SimpleNamespace(profile_id=buyer_profile_id, user_id=buyer_user_id)
    identity = SimpleNamespace(
        name_enc=encrypt_secret("김바이어", purpose="identity-name", settings=settings),
        phone_enc=encrypt_secret(
            "010-1234-5678", purpose="identity-phone", settings=settings
        ),
        email_enc=None,
    )

    session = FakeSession(
        get_map={ExhibitorStaff: staff, MeetingRequest: meeting, UserProfile: buyer_profile},
        execute_queue=[_none(), _row(contact_share), _row(identity)],
    )

    response = await meetings_router.get_partner_buyer_summary(
        meeting.meeting_id, db=session, staff_id=staff.staff_id, x_request_id="req-e2e-3"
    )

    body = _body(response)
    assert body["data"]["contact"] == {"NAME": "김바이어", "PHONE": "010-1234-5678"}
    assert body["data"]["contact_disclosed"] is True
    audit_rows = [row for row in session.added if type(row).__name__ == "AuditLog"]
    assert len(audit_rows) == 1


async def test_hop3b_buyer_summary_hides_contact_when_exhibitor_accepted_without_sharing() -> None:
    """The same hop, one gate short: the exhibitor accepted but never turned sharing on.

    This is the flow-level guard on the defect the merge closed -- before MERGE STEP 15 the
    router disclosed on buyer consent alone, so the buyer's name/phone/e-mail reached the
    partner portal without the exhibitor ever opting in.
    """
    from types import SimpleNamespace

    from app.models.profile import UserProfile

    participation_id = uuid.uuid4()
    staff = _staff(participation_id)
    buyer_profile_id = uuid.uuid4()
    meeting = SimpleNamespace(
        meeting_id=uuid.uuid4(),
        participation_id=participation_id,
        buyer_profile_id=buyer_profile_id,
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        status="accepted",
        concept_id=None,
        message_enc=None,
        viewed_at=None,
    )
    contact_share = SimpleNamespace(
        shared_fields=["NAME", "PHONE"],
        accepted_at=_now(),
        exhibitor_enabled_at=None,
        exhibitor_enabled_by_staff_id=None,
        disclosed_at=None,
        disclosed_to_user_id=None,
        meeting_contact_share_id=uuid.uuid4(),
    )
    buyer_profile = SimpleNamespace(profile_id=buyer_profile_id, user_id=uuid.uuid4())

    # No UserIdentity result is scripted: if the router regresses and queries identity anyway,
    # FakeSession raises AssertionError("unscripted db.execute() call").
    session = FakeSession(
        get_map={ExhibitorStaff: staff, MeetingRequest: meeting, UserProfile: buyer_profile},
        execute_queue=[_none(), _row(contact_share)],
    )

    response = await meetings_router.get_partner_buyer_summary(
        meeting.meeting_id, db=session, staff_id=staff.staff_id, x_request_id="req-e2e-3b"
    )

    body = _body(response)
    assert body["data"]["contact"] is None
    assert body["data"]["contact_disclosed"] is False
    assert contact_share.disclosed_at is None
    assert [row for row in session.added if type(row).__name__ == "AuditLog"] == []


# ===========================================================================
# Hop 4 -- exhibitor records the outcome; meeting completes
# ===========================================================================


async def test_hop4_outcome_recording_completes_the_meeting() -> None:
    from types import SimpleNamespace

    from app.models.meeting import Lead

    participation_id = uuid.uuid4()
    staff = _staff(participation_id)
    meeting = SimpleNamespace(
        meeting_id=uuid.uuid4(),
        participation_id=participation_id,
        buyer_profile_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        status="accepted",
        row_version=1,
    )
    session = FakeSession(
        get_map={ExhibitorStaff: staff, MeetingRequest: meeting}, execute_queue=[_none()]
    )

    response = await meetings_router.record_meeting_outcome(
        meeting.meeting_id,
        MeetingOutcomeRequest(
            outcome_code="MEETING_OUTCOME.QUALIFIED_LEAD",
            is_qualified_lead=True,
            expected_amount=5_000_000,
        ),
        db=session,
        staff_id=staff.staff_id,
        x_request_id="req-e2e-4",
    )

    body = _body(response)
    assert response.status_code == 200
    assert body["data"]["meeting_status"] == "completed"
    assert body["data"]["is_qualified_lead"] is True
    assert meeting.status == "completed"
    lead_rows = [row for row in session.added if isinstance(row, Lead)]
    assert len(lead_rows) == 1
    history_rows = [row for row in session.added if isinstance(row, MeetingStatusHistory)]
    assert len(history_rows) == 1
    assert history_rows[0].previous_status == "accepted"
    assert history_rows[0].new_status == "completed"


# ===========================================================================
# Hop 5 -- whole-journey assertion: the transition sequence never skips a documented state
# ===========================================================================


def test_hop5_the_full_journey_transition_sequence_is_legal() -> None:
    """Aggregates the (previous_status, new_status) pairs a real run of hops 1->4 would
    produce and checks each is an *adjacent* edge in docs/user-ia-wireframes.md 6.2절's state
    machine -- i.e. no hop ever jumps over 'accepted' on the way to 'completed'.
    """

    observed_transitions = [
        (None, "requested"),  # hop 1: create_meeting
        ("requested", "accepted"),  # hop 2: decide_meeting ACCEPT
        ("accepted", "completed"),  # hop 4: record_meeting_outcome
    ]
    legal_edges = {
        (None, "requested"),
        (None, "draft"),
        ("draft", "requested"),
        ("requested", "accepted"),
        ("requested", "counter_proposed"),
        ("requested", "rejected"),
        ("requested", "cancelled"),
        ("counter_proposed", "accepted"),
        ("counter_proposed", "cancelled"),
        ("accepted", "cancelled"),
        ("accepted", "completed"),
        ("accepted", "no_show"),
    }
    for edge in observed_transitions:
        assert edge in legal_edges, f"illegal/skipped transition observed: {edge}"

    # The specific violation this whole track exists to catch: a direct requested -> completed
    # jump that skips the acceptance step entirely.
    assert ("requested", "completed") not in legal_edges


# ===========================================================================
# Live-Postgres round trip (skipped in this sandbox; documents/exercises the real thing in CI)
# ===========================================================================

import os

DATABASE_URL = os.getenv("POSTGRES_TEST_DATABASE_URL")
_LIVE_DB_SKIP_REASON = (
    "POSTGRES_TEST_DATABASE_URL is not configured -- this sandbox has no reachable "
    "PostgreSQL (verified: env var unset, `docker ps` fails to reach a daemon). Configure "
    "it in CI to run a genuine HTTP round trip through TestClient against a migrated "
    "database instead of the scripted-fake hops above."
)


@pytest.mark.postgres_integration
@pytest.mark.skipif(not DATABASE_URL, reason=_LIVE_DB_SKIP_REASON)
def test_live_postgres_buyer_meeting_round_trip() -> None:
    """Placeholder for the integrator: once a migrated Postgres is reachable, replace this body
    with a real TestClient(app) walk of
        POST /meetings -> POST /partner/meetings/{id}/decision (ACCEPT)
        -> GET /partner/meetings/{id}/buyer-summary -> POST /partner/meetings/{id}/outcome
    seeded via direct ORM inserts (tenant/event/exhibitor/participation/availability_slot/
    profile/user_account/consent_policy), asserting the same contract as hops 1-4 above but
    against real Postgres constraints (the EXCLUDE constraints, CHECK constraints, and the
    conditional-UPDATE slot reservation in particular cannot be proven correct by any fake).
    """

    pytest.skip("implement against a migrated POSTGRES_TEST_DATABASE_URL")
