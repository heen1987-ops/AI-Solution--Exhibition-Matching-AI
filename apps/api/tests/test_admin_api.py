"""Tests for BACKEND-007 - exhibitor master-approval decision + booth operating-status change.

No live Postgres is assumed reachable in this environment, so these follow the project's
established convention (see test_exhibitor_preference_api.py, test_recommendation_api.py):
fake the AsyncSession at the service/router boundary with a small queue-backed stub, and
compile SQLAlchemy statements to text where a WHERE-clause fragment needs verifying.

Coverage:
    - route registration (build_admin_router() exposes exactly the three documented routes)
    - schema <-> model Literal/tuple drift guard
    - service layer (no DB, no HTTP): every allowed/disallowed exhibitor transition, the
      race-lost conflict path, the audit_log row shape, the booth conditional-UPDATE row_version
      guard, the booth_status_history row shape, and partial-update (None-field) semantics
    - router layer (TestClient + dependency overrides): RBAC (401/403/AAL2), tenant-scoped 404,
      happy path, and 409 conflict propagation
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql

from app.api.v1.routers import admin as router_module
from app.core.auth import (
    AuthException,
    VerifiedPrincipal,
    auth_exception_handler,
    get_verified_principal,
)
from app.core.router_auth import get_actor_user_id as shared_get_actor_user_id
from app.db.session import get_db
from app.models.consent import AuditLog
from app.models.exhibitor import (
    BOOTH_CONGESTION_LEVELS,
    BOOTH_OPERATING_STATUSES,
    MASTER_APPROVAL_STATUSES,
    Booth,
    BoothStatusHistory,
    Exhibitor,
)
from app.schemas import admin as admin_schemas
from app.schemas.auth import AuthPrincipal, AuthRoleGrant
from app.services.admin import booth_status, exhibitor_approval

# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_build_admin_router_exposes_exactly_the_documented_routes() -> None:
    api_router = router_module.build_admin_router()
    routes = {(route.path, method) for route in api_router.routes for method in route.methods}

    expected = {
        ("/admin/exhibitors/{exhibitor_id}/approve", "POST"),
        ("/admin/exhibitors/{exhibitor_id}/reject", "POST"),
        ("/admin/booths/{booth_id}/status", "PATCH"),
    }
    assert expected <= routes


def test_build_admin_router_returns_the_same_module_singleton() -> None:
    """Matches app/api/v1/routers/analytics.py's convention (module-level router, not rebuilt
    per call) - a repeated build_admin_router() call must not double-register routes."""

    assert router_module.build_admin_router() is router_module.build_admin_router()
    assert router_module.build_admin_router() is router_module.router


# ---------------------------------------------------------------------------
# Schema <-> model drift guard
# ---------------------------------------------------------------------------


def test_master_approval_status_literal_matches_model_tuple() -> None:
    assert set(admin_schemas.MasterApprovalStatus.__args__) == set(MASTER_APPROVAL_STATUSES)


def test_booth_operating_status_literal_matches_model_tuple() -> None:
    assert set(admin_schemas.BoothOperatingStatus.__args__) == set(BOOTH_OPERATING_STATUSES)


def test_booth_congestion_level_literal_matches_model_tuple() -> None:
    assert set(admin_schemas.BoothCongestionLevel.__args__) == set(BOOTH_CONGESTION_LEVELS)


def test_exhibitor_reject_reason_code_literal_matches_its_own_tuple() -> None:
    assert set(admin_schemas.ExhibitorRejectReasonCode.__args__) == set(
        admin_schemas.EXHIBITOR_REJECT_REASON_CODES
    )


def test_admin_role_dependency_uses_exactly_the_acceptance_criteria_role_list() -> None:
    """The task's RBAC section names an exact role list - a regression here would silently
    widen or narrow who may approve/reject exhibitors or change booth status."""

    code = __import__("inspect").getsource(router_module)
    assert 'require_roles("EVENT_ADMIN", "DATA_REVIEWER")' in code


# ---------------------------------------------------------------------------
# Service layer: no DB, no HTTP - queue-backed fake AsyncSession
# ---------------------------------------------------------------------------


class _FakeResult:
    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value


class _QueueSession:
    """Returns queued results in call order and records every statement + added row."""

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.executed: list[Any] = []
        self.added: list[Any] = []

    async def execute(self, stmt: Any) -> _FakeResult:
        self.executed.append(stmt)
        return _FakeResult(self._results.pop(0))

    def add(self, obj: Any) -> None:
        self.added.append(obj)


def _compiled(stmt: Any) -> str:
    # dialect=postgresql.dialect() is required for literal_binds to render UUID/enum-like
    # values as text instead of leaving them as unresolved bind params (see
    # test_exhibition_public_api.py's identical helper for the same reason).
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def _set_clause(sql: str) -> str:
    """Isolates the ``SET ...`` clause of a compiled UPDATE from its ``RETURNING`` column
    list, which always lists every column regardless of what was actually assigned."""

    after_set = sql.split("SET ", 1)[1]
    return after_set.split(" WHERE ", 1)[0]


def _exhibitor(status: str, **overrides: Any) -> Exhibitor:
    defaults: dict[str, Any] = {
        "exhibitor_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "company_name": "테스트양조",
        "master_approval_status": status,
    }
    defaults.update(overrides)
    return Exhibitor(**defaults)


def _booth(**overrides: Any) -> Booth:
    defaults: dict[str, Any] = {
        "booth_id": uuid.uuid4(),
        "tenant_id": uuid.uuid4(),
        "event_id": uuid.uuid4(),
        "participation_id": uuid.uuid4(),
        "booth_number": "A-01",
        "operating_status": "CLOSED",
        "congestion_level": "UNKNOWN",
        "estimated_wait_minutes": None,
        "row_version": 1,
        # server_default-only in the model - a plain Python instantiation (no DB flush) leaves
        # it None unless supplied, which the response schema (a real timestamp) would reject.
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    return Booth(**defaults)


# -- exhibitor approve --------------------------------------------------------


@pytest.mark.parametrize("from_status", ["DRAFT", "REJECTED"])
async def test_approve_succeeds_from_every_allowed_status(from_status: str) -> None:
    exhibitor = _exhibitor(from_status)
    updated = _exhibitor("APPROVED", exhibitor_id=exhibitor.exhibitor_id, tenant_id=exhibitor.tenant_id)
    session = _QueueSession([updated])
    actor_id = uuid.uuid4()

    result = await exhibitor_approval.approve_exhibitor(
        session, exhibitor, actor_user_id=actor_id, reason_code=None
    )

    assert result.master_approval_status == "APPROVED"
    assert len(session.added) == 1
    audit_row = session.added[0]
    assert isinstance(audit_row, AuditLog)
    assert audit_row.action_type == "APPROVE"
    assert audit_row.resource_type == "exhibition.exhibitor"
    assert audit_row.resource_id == exhibitor.exhibitor_id
    assert audit_row.actor_user_id == actor_id
    assert audit_row.actor_role == "ADMIN"


async def test_approve_from_already_approved_is_rejected_without_touching_the_db() -> None:
    exhibitor = _exhibitor("APPROVED")
    session = _QueueSession([])  # any db.execute call would raise IndexError - none expected

    with pytest.raises(exhibitor_approval.InvalidApprovalTransitionError) as exc_info:
        await exhibitor_approval.approve_exhibitor(
            session, exhibitor, actor_user_id=uuid.uuid4(), reason_code=None
        )
    assert exc_info.value.current_status == "APPROVED"
    assert exc_info.value.target_status == "APPROVED"
    assert session.added == []


async def test_approve_race_lost_when_conditional_update_matches_no_row() -> None:
    exhibitor = _exhibitor("DRAFT")
    session = _QueueSession([None])  # simulates 0 rows updated - status changed concurrently

    with pytest.raises(exhibitor_approval.ApprovalRaceLostError):
        await exhibitor_approval.approve_exhibitor(
            session, exhibitor, actor_user_id=uuid.uuid4(), reason_code=None
        )
    # the conflict must be surfaced *before* any audit row is added for a change that never
    # actually happened
    assert session.added == []


async def test_approve_update_statement_guards_on_the_observed_master_approval_status() -> None:
    """Real conditional UPDATE, not a blind overwrite: the WHERE clause must re-check the
    exact status this caller observed, not just the exhibitor_id."""

    exhibitor = _exhibitor("DRAFT")
    session = _QueueSession([_exhibitor("APPROVED", exhibitor_id=exhibitor.exhibitor_id)])

    await exhibitor_approval.approve_exhibitor(
        session, exhibitor, actor_user_id=uuid.uuid4(), reason_code=None
    )

    sql = _compiled(session.executed[0])
    assert str(exhibitor.exhibitor_id) in sql
    assert "master_approval_status" in sql
    assert "'DRAFT'" in sql
    assert "'APPROVED'" in sql


# -- exhibitor reject ----------------------------------------------------------


@pytest.mark.parametrize("from_status", ["DRAFT", "APPROVED"])
async def test_reject_succeeds_from_every_allowed_status(from_status: str) -> None:
    exhibitor = _exhibitor(from_status)
    updated = _exhibitor("REJECTED", exhibitor_id=exhibitor.exhibitor_id, tenant_id=exhibitor.tenant_id)
    session = _QueueSession([updated])

    result = await exhibitor_approval.reject_exhibitor(
        session, exhibitor, actor_user_id=uuid.uuid4(), reason_code="POLICY_VIOLATION"
    )

    assert result.master_approval_status == "REJECTED"
    audit_row = session.added[0]
    # 'REJECT' is not a member of audit.audit_log's action_type CHECK constraint
    # ('VIEW','CREATE','UPDATE','DELETE','EXPORT','APPROVE') - see the service module
    # docstring for why 'UPDATE' is used instead.
    assert audit_row.action_type == "UPDATE"
    assert audit_row.reason_code == "POLICY_VIOLATION"


async def test_reject_from_already_rejected_is_a_conflict_not_a_silent_noop() -> None:
    exhibitor = _exhibitor("REJECTED")
    session = _QueueSession([])

    with pytest.raises(exhibitor_approval.InvalidApprovalTransitionError):
        await exhibitor_approval.reject_exhibitor(
            session, exhibitor, actor_user_id=uuid.uuid4(), reason_code="OTHER"
        )


async def test_every_exhibitor_reject_reason_code_is_accepted_by_the_service() -> None:
    for reason_code in admin_schemas.EXHIBITOR_REJECT_REASON_CODES:
        exhibitor = _exhibitor("DRAFT")
        session = _QueueSession([_exhibitor("REJECTED", exhibitor_id=exhibitor.exhibitor_id)])
        result = await exhibitor_approval.reject_exhibitor(
            session, exhibitor, actor_user_id=uuid.uuid4(), reason_code=reason_code
        )
        assert result.master_approval_status == "REJECTED"
        assert session.added[0].reason_code == reason_code


# -- booth status ---------------------------------------------------------------


async def test_booth_status_update_succeeds_and_bumps_row_version() -> None:
    booth = _booth(operating_status="CLOSED", row_version=3)
    updated = _booth(
        booth_id=booth.booth_id, operating_status="OPEN", row_version=4, congestion_level="LOW"
    )
    session = _QueueSession([updated])
    actor_id = uuid.uuid4()

    result = await booth_status.update_booth_status(
        session,
        booth,
        operating_status="OPEN",
        congestion_level="LOW",
        estimated_wait_minutes=None,
        expected_row_version=3,
        actor_user_id=actor_id,
        reason_code="MANUAL_REOPEN",
    )

    assert result.operating_status == "OPEN"
    assert len(session.added) == 1
    history_row = session.added[0]
    assert isinstance(history_row, BoothStatusHistory)
    assert history_row.booth_id == updated.booth_id
    assert history_row.previous_status == "CLOSED"  # captured before the update, not after
    assert history_row.new_status == "OPEN"
    assert history_row.changed_by_user_id == actor_id
    assert history_row.reason_code == "MANUAL_REOPEN"


async def test_booth_status_version_conflict_when_row_version_does_not_match() -> None:
    booth = _booth(row_version=5)
    session = _QueueSession([None])  # 0 rows matched - caller's row_version is stale

    with pytest.raises(booth_status.BoothVersionConflictError):
        await booth_status.update_booth_status(
            session,
            booth,
            operating_status="PAUSED",
            congestion_level=None,
            estimated_wait_minutes=None,
            expected_row_version=1,  # stale on purpose
            actor_user_id=uuid.uuid4(),
            reason_code=None,
        )
    # no history row for a change that never actually happened
    assert session.added == []


async def test_booth_status_update_statement_guards_on_row_version_not_just_booth_id() -> None:
    booth = _booth(row_version=7)
    session = _QueueSession([_booth(booth_id=booth.booth_id, row_version=8)])

    await booth_status.update_booth_status(
        session,
        booth,
        operating_status="OPEN",
        congestion_level=None,
        estimated_wait_minutes=None,
        expected_row_version=7,
        actor_user_id=uuid.uuid4(),
        reason_code=None,
    )

    sql = _compiled(session.executed[0])
    assert str(booth.booth_id) in sql
    assert "row_version" in sql


async def test_booth_status_omitted_optional_fields_leave_congestion_and_wait_unchanged() -> None:
    """None means 'not provided' for a PATCH - the UPDATE must not overwrite congestion_level /
    estimated_wait_minutes with NULL when the caller didn't send them."""

    booth = _booth(row_version=1)
    session = _QueueSession([_booth(booth_id=booth.booth_id, row_version=2)])

    await booth_status.update_booth_status(
        session,
        booth,
        operating_status="OPEN",
        congestion_level=None,
        estimated_wait_minutes=None,
        expected_row_version=1,
        actor_user_id=uuid.uuid4(),
        reason_code=None,
    )

    set_clause = _set_clause(_compiled(session.executed[0]))
    assert "congestion_level" not in set_clause
    assert "estimated_wait_minutes" not in set_clause


async def test_booth_status_explicit_zero_wait_minutes_is_applied_not_skipped() -> None:
    """0 is falsy but a legitimate value (no wait) - only None must be treated as 'omitted'."""

    booth = _booth(row_version=1)
    session = _QueueSession([_booth(booth_id=booth.booth_id, row_version=2)])

    await booth_status.update_booth_status(
        session,
        booth,
        operating_status="OPEN",
        congestion_level=None,
        estimated_wait_minutes=0,
        expected_row_version=1,
        actor_user_id=uuid.uuid4(),
        reason_code=None,
    )

    set_clause = _set_clause(_compiled(session.executed[0]))
    assert "estimated_wait_minutes" in set_clause


# ---------------------------------------------------------------------------
# Router layer: TestClient + dependency overrides
# ---------------------------------------------------------------------------

_EXHIBITOR_ID = uuid.uuid4()
_BOOTH_ID = uuid.uuid4()


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(router_module.build_admin_router())
    return app


def _verified_principal(
    *,
    roles: tuple[str, ...] = ("EVENT_ADMIN",),
    authn_level: str = "AAL2",
    mfa_at: datetime | None = None,
    tenant_id: uuid.UUID | None = None,
) -> VerifiedPrincipal:
    tenant_id = tenant_id or uuid.uuid4()
    return VerifiedPrincipal(
        principal=AuthPrincipal(
            subject_type="USER",
            subject_id=uuid.uuid4(),
            tenant_id=tenant_id,
            event_id=uuid.uuid4(),
            role_grants=[
                AuthRoleGrant(role=role, tenant_id=tenant_id, event_id=None, exhibitor_id=None)
                for role in roles
            ],
            authn_level=authn_level,  # type: ignore[arg-type]
            amr={"webauthn"},
            authenticated_at=datetime.now(UTC),
            mfa_at=mfa_at if mfa_at is not None else datetime.now(UTC),
        ),
        session=None,
    )


ADMIN_ROUTES = [
    ("POST", f"/admin/exhibitors/{_EXHIBITOR_ID}/approve", {}),
    ("POST", f"/admin/exhibitors/{_EXHIBITOR_ID}/reject", {"reason_code": "OTHER"}),
    ("PATCH", f"/admin/booths/{_BOOTH_ID}/status", {"operating_status": "OPEN", "row_version": 1}),
]


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
def test_every_admin_route_is_401_without_a_session(
    method: str, path: str, body: dict | None
) -> None:
    app = _build_app()
    app.dependency_overrides[get_db] = lambda: iter([object()])
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
def test_every_admin_route_rejects_a_role_outside_the_acceptance_criteria_list(
    method: str, path: str, body: dict | None
) -> None:
    app = _build_app()
    app.dependency_overrides[get_db] = lambda: iter([object()])
    app.dependency_overrides[get_verified_principal] = lambda: _verified_principal(
        roles=("EXHIBITOR_ADMIN",)
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 403
    assert response.json()["code"] == "RESOURCE_FORBIDDEN"


@pytest.mark.parametrize("role", ["EVENT_ADMIN", "DATA_REVIEWER"])
@pytest.mark.parametrize(("method", "path", "body"), ADMIN_ROUTES)
def test_every_admin_route_requires_aal2_for_both_acceptance_criteria_roles(
    role: str, method: str, path: str, body: dict | None
) -> None:
    """EVENT_ADMIN and DATA_REVIEWER are PRIVILEGED_ADMIN_ROLES - AAL1 must be refused even
    with a real role grant (app/core/auth.py), with no fresh_mfa=True needed on top of that."""

    app = _build_app()
    app.dependency_overrides[get_db] = lambda: iter([object()])
    app.dependency_overrides[get_verified_principal] = lambda: _verified_principal(
        roles=(role,), authn_level="AAL1"
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 403
    assert response.json()["code"] == "MFA_REQUIRED"


def test_the_router_module_defines_no_header_derived_identity_helper() -> None:
    import ast
    import inspect

    source = inspect.getsource(router_module)
    tree = ast.parse(source)
    docstring = ast.get_docstring(tree)
    code = source
    if docstring is not None:
        first_statement = tree.body[0]
        assert first_statement.end_lineno is not None
        code = "\n".join(source.splitlines()[first_statement.end_lineno :])

    assert "Header" not in code
    assert "X-Actor-User-Id" not in code
    assert "X-Tenant-Id" not in code
    assert router_module.get_actor_user_id is shared_get_actor_user_id


class _RouterFakeSession:
    """Router-level fake: a FIFO queue of db.execute() results plus commit/add tracking, for
    exercising the full HTTP path (auth -> 404 lookup -> service -> commit) without a live DB."""

    def __init__(self, results: list[Any]) -> None:
        self._results = list(results)
        self.added: list[Any] = []
        self.committed = False

    async def execute(self, stmt: Any) -> _FakeResult:
        return _FakeResult(self._results.pop(0))

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    async def commit(self) -> None:
        self.committed = True


def _app_with_session(session: _RouterFakeSession, *, tenant_id: uuid.UUID) -> FastAPI:
    app = _build_app()

    def _get_db_override():
        # Must be a generator function (not a plain callable returning an iterator) so
        # FastAPI's dependency system recognizes and drives it like the real async-generator
        # get_db - a bare `lambda: iter([session])` hands FastAPI the iterator object itself
        # as `db`, not `session` (only harmless in tests that never reach db.execute()).
        yield session

    app.dependency_overrides[get_db] = _get_db_override
    app.dependency_overrides[get_verified_principal] = lambda: _verified_principal(
        tenant_id=tenant_id
    )
    return app


def test_approve_exhibitor_happy_path_returns_200_and_commits() -> None:
    tenant_id = uuid.uuid4()
    exhibitor = _exhibitor("DRAFT", exhibitor_id=_EXHIBITOR_ID, tenant_id=tenant_id)
    updated = _exhibitor("APPROVED", exhibitor_id=_EXHIBITOR_ID, tenant_id=tenant_id)
    session = _RouterFakeSession([exhibitor, updated])
    app = _app_with_session(session, tenant_id=tenant_id)

    with TestClient(app) as client:
        response = client.post(f"/admin/exhibitors/{_EXHIBITOR_ID}/approve", json={})

    assert response.status_code == 200
    body = response.json()
    assert body["master_approval_status"] == "APPROVED"
    assert body["previous_status"] == "DRAFT"
    assert session.committed is True


def test_approve_exhibitor_not_found_in_this_tenant_is_404() -> None:
    tenant_id = uuid.uuid4()
    session = _RouterFakeSession([None])  # the tenant-scoped SELECT finds nothing
    app = _app_with_session(session, tenant_id=tenant_id)

    with TestClient(app) as client:
        response = client.post(f"/admin/exhibitors/{_EXHIBITOR_ID}/approve", json={})

    assert response.status_code == 404
    assert response.json()["detail"] == "EXHIBITOR_NOT_FOUND"


def test_approve_exhibitor_already_approved_is_409() -> None:
    tenant_id = uuid.uuid4()
    exhibitor = _exhibitor("APPROVED", exhibitor_id=_EXHIBITOR_ID, tenant_id=tenant_id)
    session = _RouterFakeSession([exhibitor])  # no second (UPDATE) call expected
    app = _app_with_session(session, tenant_id=tenant_id)

    with TestClient(app) as client:
        response = client.post(f"/admin/exhibitors/{_EXHIBITOR_ID}/approve", json={})

    assert response.status_code == 409
    assert "EXHIBITOR_APPROVAL_INVALID_TRANSITION" in response.json()["detail"]


def test_reject_exhibitor_without_reason_code_is_422() -> None:
    tenant_id = uuid.uuid4()
    session = _RouterFakeSession([])  # must fail validation before any DB access
    app = _app_with_session(session, tenant_id=tenant_id)

    with TestClient(app) as client:
        response = client.post(f"/admin/exhibitors/{_EXHIBITOR_ID}/reject", json={})

    assert response.status_code == 422


def test_reject_exhibitor_happy_path_returns_200() -> None:
    tenant_id = uuid.uuid4()
    exhibitor = _exhibitor("DRAFT", exhibitor_id=_EXHIBITOR_ID, tenant_id=tenant_id)
    updated = _exhibitor("REJECTED", exhibitor_id=_EXHIBITOR_ID, tenant_id=tenant_id)
    session = _RouterFakeSession([exhibitor, updated])
    app = _app_with_session(session, tenant_id=tenant_id)

    with TestClient(app) as client:
        response = client.post(
            f"/admin/exhibitors/{_EXHIBITOR_ID}/reject", json={"reason_code": "OTHER"}
        )

    assert response.status_code == 200
    assert response.json()["master_approval_status"] == "REJECTED"


def test_patch_booth_status_happy_path_returns_200() -> None:
    tenant_id = uuid.uuid4()
    booth = _booth(booth_id=_BOOTH_ID, tenant_id=tenant_id, operating_status="CLOSED", row_version=1)
    updated = _booth(
        booth_id=_BOOTH_ID, tenant_id=tenant_id, operating_status="OPEN", row_version=2
    )
    session = _RouterFakeSession([booth, updated])
    app = _app_with_session(session, tenant_id=tenant_id)

    with TestClient(app) as client:
        response = client.patch(
            f"/admin/booths/{_BOOTH_ID}/status",
            json={"operating_status": "OPEN", "row_version": 1},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["operating_status"] == "OPEN"
    assert body["row_version"] == 2
    assert len(session.added) == 1
    assert isinstance(session.added[0], BoothStatusHistory)


def test_patch_booth_status_version_conflict_is_409() -> None:
    tenant_id = uuid.uuid4()
    booth = _booth(booth_id=_BOOTH_ID, tenant_id=tenant_id, row_version=5)
    session = _RouterFakeSession([booth, None])  # the conditional UPDATE matches 0 rows
    app = _app_with_session(session, tenant_id=tenant_id)

    with TestClient(app) as client:
        response = client.patch(
            f"/admin/booths/{_BOOTH_ID}/status",
            json={"operating_status": "OPEN", "row_version": 1},
        )

    assert response.status_code == 409
    assert response.json()["detail"] == "BOOTH_VERSION_CONFLICT"


def test_patch_booth_status_not_found_in_this_tenant_is_404() -> None:
    tenant_id = uuid.uuid4()
    session = _RouterFakeSession([None])
    app = _app_with_session(session, tenant_id=tenant_id)

    with TestClient(app) as client:
        response = client.patch(
            f"/admin/booths/{_BOOTH_ID}/status",
            json={"operating_status": "OPEN", "row_version": 1},
        )

    assert response.status_code == 404
    assert response.json()["detail"] == "BOOTH_NOT_FOUND"


def test_patch_booth_status_invalid_operating_status_is_422() -> None:
    tenant_id = uuid.uuid4()
    session = _RouterFakeSession([])
    app = _app_with_session(session, tenant_id=tenant_id)

    with TestClient(app) as client:
        response = client.patch(
            f"/admin/booths/{_BOOTH_ID}/status",
            json={"operating_status": "SOLD_OUT", "row_version": 1},
        )

    assert response.status_code == 422
