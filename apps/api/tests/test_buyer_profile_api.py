"""Tests for the verified-buyer trade profile API (WAVE2C BACKEND-BUYER-PROFILE).

No live Postgres is assumed to be reachable in this environment (this repo's established
convention - see tests/test_exhibition_public_api.py, tests/test_search_api.py). HTTP-level
tests build a standalone app around just this router and monkeypatch the service layer
(tests/test_exhibition_public_api.py's `_standalone_app` + `monkeypatch.setattr(service, ...)`
pattern); service-layer tests exercise the real ``app.services.buyer_profile.service.apply_patch``
logic (including the real ontology catalog) against a minimal fake session that only supports
``flush`` (tests/test_hard_filter_persistence.py's ``_FakeSession`` pattern) - no DB I/O either
way.

Authentication (merge STEP 21)
--------------------------------
The WAVE2C original read the acting subject straight off ``X-Tenant-Id``/``X-User-Id`` headers
(``_tenant_header``/``_user_header``). Both helpers are gone. The subject now comes from
``app.core.auth.get_verified_principal``, so the HTTP tests below authenticate by overriding
that dependency (``tests/test_analytics_api.py``'s technique) - never by sending a header.

The cross-user 403 test is the load-bearing one: before the merge the by-id ownership check
compared the stored profile against the very headers the caller supplied, so "user A asks for
user B's profile" was satisfiable simply by editing a header. It is now a comparison against
the server-derived principal, and a supplied header that disagrees with the session is a 403
rather than a substitution.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.api.v1.routers.buyer_profile import build_buyer_profile_router
from app.core.auth import (
    AuthException,
    VerifiedPrincipal,
    auth_exception_handler,
    get_verified_principal,
)
from app.db.base import Base
from app.db.session import get_db
from app.models.buyer_profile import (
    BUYER_TYPES,
    VERIFICATION_STATUSES,
    BuyerProfile,
    BuyerProfileCode,
)
from app.schemas.auth import AuthPrincipal
from app.schemas.buyer_profile import BuyerProfilePatchRequest, BuyerType
from app.services.buyer_profile import eligibility, service, verification
from app.services.buyer_profile.errors import (
    InvalidVerificationStatusError,
    UnknownOntologyCodeError,
    VersionConflictError,
)

# ---------------------------------------------------------------------------
# Model registration (mirrors tests/test_exhibitor_models.py's conventions)
# ---------------------------------------------------------------------------


def test_buyer_profile_tables_are_registered_with_expected_columns() -> None:
    columns = set(Base.metadata.tables["profile.buyer_profile"].columns.keys())
    assert {
        "buyer_profile_id",
        "tenant_id",
        "user_id",
        "buyer_type",
        "order_scale_code",
        "decision_timeline",
        "verification_status",
        "verification_reason",
        "verification_reviewed_by_user_id",
        "verification_reviewed_at",
        "version",
        "created_at",
        "updated_at",
    } <= columns


def test_buyer_profile_code_has_a_composite_ontology_fk() -> None:
    table = Base.metadata.tables["profile.buyer_profile_code"]
    fk_targets = {
        tuple(element.target_fullname for element in constraint.elements)
        for constraint in table.foreign_key_constraints
    }
    assert (
        "ontology.concept_revision.taxonomy_version_id",
        "ontology.concept_revision.concept_id",
    ) in fk_targets
    assert (
        "ontology.concept.concept_id",
        "ontology.concept.concept_code",
    ) in fk_targets


def test_buyer_profile_check_constraints_cover_the_documented_enums() -> None:
    check_texts = {
        constraint.sqltext.text
        for constraint in Base.metadata.tables["profile.buyer_profile"].constraints
        if constraint.__class__.__name__ == "CheckConstraint"
    }
    assert any("DISTRIBUTOR" in text and "OTHER" in text for text in check_texts)
    assert any("UNVERIFIED" in text and "EXPIRED" in text for text in check_texts)


def test_buyer_type_literal_matches_the_model_check_constraint() -> None:
    assert set(BuyerType.__args__) == set(BUYER_TYPES)  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# app.services.buyer_profile.service.buyer_profile_lookup_stmt - compiled, no live DB
# (mirrors tests/test_search_api.py's `_compiled_where` convention)
# ---------------------------------------------------------------------------


def test_buyer_profile_lookup_stmt_filters_by_tenant_and_user() -> None:
    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()

    stmt = service.buyer_profile_lookup_stmt(tenant_id, user_id)
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))

    # postgresql.UUID literal_binds renders without dashes.
    assert f"buyer_profile.tenant_id = '{tenant_id.hex}'" in sql
    assert f"buyer_profile.user_id = '{user_id.hex}'" in sql


# ---------------------------------------------------------------------------
# app.services.buyer_profile.service.apply_patch - real ontology catalog, fake session
# ---------------------------------------------------------------------------


class _FakeSession:
    def __init__(self) -> None:
        self.flushed = False

    async def flush(self) -> None:
        self.flushed = True


def _profile(**overrides: object) -> BuyerProfile:
    defaults: dict[str, object] = dict(
        buyer_profile_id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        buyer_type="OTHER",
        verification_status="UNVERIFIED",
        version=1,
    )
    defaults.update(overrides)
    profile = BuyerProfile(**defaults)
    profile.codes = []
    return profile


async def test_apply_patch_rejects_an_unknown_ontology_code() -> None:
    profile = _profile()
    patch = BuyerProfilePatchRequest(version=1, channel_codes=["CHANNEL.NOT_A_REAL_CODE"])

    with pytest.raises(UnknownOntologyCodeError) as exc_info:
        await service.apply_patch(_FakeSession(), profile, patch)

    assert exc_info.value.field == "channel_codes"
    assert exc_info.value.code == "CHANNEL.NOT_A_REAL_CODE"
    # all-or-nothing: nothing should have been mutated
    assert profile.version == 1
    assert profile.codes == []


async def test_apply_patch_rejects_a_stale_version() -> None:
    profile = _profile(version=5, buyer_type="OTHER")
    patch = BuyerProfilePatchRequest(version=4, buyer_type="RETAILER")

    with pytest.raises(VersionConflictError) as exc_info:
        await service.apply_patch(_FakeSession(), profile, patch)

    assert exc_info.value.expected == 4
    assert exc_info.value.actual == 5
    assert profile.buyer_type == "OTHER"  # never touched


async def test_apply_patch_replaces_a_code_group_dedupes_and_bumps_version() -> None:
    profile = _profile()
    session = _FakeSession()
    patch = BuyerProfilePatchRequest(
        version=1,
        buyer_type="RETAILER",
        channel_codes=["CHANNEL.OFFLINE", "CHANNEL.OFFLINE"],
        preferred_region_codes=["REGION.KR.SEOUL"],
    )

    result = await service.apply_patch(session, profile, patch)

    assert result is profile
    assert result.version == 2
    assert result.buyer_type == "RETAILER"
    assert session.flushed is True
    channel_codes = sorted(row.attribute_code for row in result.codes if row.code_group == "CHANNEL")
    assert channel_codes == ["CHANNEL.OFFLINE"]
    region_codes = [row.attribute_code for row in result.codes if row.code_group == "PREFERRED_REGION"]
    assert region_codes == ["REGION.KR.SEOUL"]
    for row in result.codes:
        assert isinstance(row, BuyerProfileCode)
        assert row.buyer_profile_id == profile.buyer_profile_id


async def test_apply_patch_leaves_unmentioned_code_groups_untouched() -> None:
    profile = _profile()
    profile.codes = [
        BuyerProfileCode(
            buyer_profile_id=profile.buyer_profile_id,
            code_group="CHANNEL",
            taxonomy_version_id=uuid.uuid4(),
            concept_id=uuid.uuid4(),
            attribute_code="CHANNEL.OFFLINE",
        )
    ]
    patch = BuyerProfilePatchRequest(version=1, decision_timeline="WITHIN_1_MONTH")

    result = await service.apply_patch(_FakeSession(), profile, patch)

    assert [row.attribute_code for row in result.codes] == ["CHANNEL.OFFLINE"]
    assert result.decision_timeline == "WITHIN_1_MONTH"


# ---------------------------------------------------------------------------
# app.services.buyer_profile.eligibility.is_meeting_eligible
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("status_value", ["VERIFIED", "LIMITED"])
def test_is_meeting_eligible_true_for_verified_and_limited(status_value: str) -> None:
    assert eligibility.is_meeting_eligible(SimpleNamespace(verification_status=status_value)) is True


@pytest.mark.parametrize(
    "status_value",
    [s for s in VERIFICATION_STATUSES if s not in {"VERIFIED", "LIMITED"}],
)
def test_is_meeting_eligible_false_for_every_other_status(status_value: str) -> None:
    assert eligibility.is_meeting_eligible(SimpleNamespace(verification_status=status_value)) is False


def test_is_meeting_eligible_false_when_no_profile_exists_yet() -> None:
    assert eligibility.is_meeting_eligible(None) is False


# ---------------------------------------------------------------------------
# app.services.buyer_profile.verification.set_verification_status (operator-only stub)
# ---------------------------------------------------------------------------


def test_set_verification_status_updates_fields_and_bumps_version() -> None:
    profile = _profile(verification_status="PENDING", version=2)
    operator_id = uuid.uuid4()

    result = verification.set_verification_status(
        profile, new_status="VERIFIED", operator_user_id=operator_id, reason="KYB documents checked"
    )

    assert result is profile
    assert profile.verification_status == "VERIFIED"
    assert profile.verification_reason == "KYB documents checked"
    assert profile.verification_reviewed_by_user_id == operator_id
    assert profile.verification_reviewed_at is not None
    assert profile.version == 3


def test_set_verification_status_rejects_an_unknown_target_status() -> None:
    profile = _profile()
    with pytest.raises(InvalidVerificationStatusError):
        verification.set_verification_status(
            profile, new_status="NOT_A_REAL_STATUS", operator_user_id=uuid.uuid4()
        )


# ---------------------------------------------------------------------------
# BuyerProfilePatchRequest - "verification_status immutable by the buyer themselves"
# ---------------------------------------------------------------------------


def test_patch_request_schema_has_no_verification_status_field() -> None:
    assert "verification_status" not in BuyerProfilePatchRequest.model_fields


def test_patch_request_schema_rejects_a_smuggled_verification_status_field() -> None:
    with pytest.raises(ValidationError):
        BuyerProfilePatchRequest(version=1, verification_status="VERIFIED")


# ---------------------------------------------------------------------------
# HTTP layer - standalone app around just this router, service monkeypatched
# ---------------------------------------------------------------------------


class _NoopDb:
    """Stand-in for AsyncSession - the router only ever calls commit()/rollback() on it
    directly (all real query/mutation work goes through the monkeypatched service layer)."""

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def _verified_principal(tenant_id: uuid.UUID, user_id: uuid.UUID) -> VerifiedPrincipal:
    return VerifiedPrincipal(
        principal=AuthPrincipal(
            subject_type="USER",
            subject_id=user_id,
            tenant_id=tenant_id,
            event_id=uuid.uuid4(),
            role_grants=[],
            authn_level="AAL1",
            amr={"magic_link"},
            authenticated_at=datetime.now(UTC),
            mfa_at=None,
        ),
        session=None,
    )


def _standalone_app(
    tenant_id: uuid.UUID | None = None, user_id: uuid.UUID | None = None
) -> FastAPI:
    """Standalone app around just this router.

    Pass no ids to get an *unauthenticated* app - ``get_verified_principal`` then runs for
    real and raises 401 AUTH_REQUIRED, which is exactly the "no session" contract.
    """

    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(build_buyer_profile_router(), prefix="/api/v1")
    app.dependency_overrides[get_db] = lambda: _NoopDb()
    if tenant_id is not None and user_id is not None:
        principal = _verified_principal(tenant_id, user_id)
        app.dependency_overrides[get_verified_principal] = lambda: principal
    return app


def _headers() -> dict[str, str]:
    return {"X-Request-ID": "req-buyer-profile-test"}


def _fake_profile(*, tenant_id: uuid.UUID, user_id: uuid.UUID, **overrides: object) -> SimpleNamespace:
    now = datetime.now(UTC)
    defaults: dict[str, object] = dict(
        buyer_profile_id=uuid.uuid4(),
        tenant_id=tenant_id,
        user_id=user_id,
        buyer_type="OTHER",
        order_scale_code=None,
        decision_timeline=None,
        verification_status="UNVERIFIED",
        version=1,
        created_at=now,
        updated_at=now,
        codes=[],
    )
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_every_endpoint_rejects_a_caller_with_no_session() -> None:
    """STEP 21: there is no header a caller can send to become somebody."""

    app = _standalone_app()
    client = TestClient(app)
    spoofed = {
        "X-Tenant-Id": str(uuid.uuid4()),
        "X-User-Id": str(uuid.uuid4()),
    }

    for method, path, body in (
        ("GET", "/api/v1/me/buyer-profile", None),
        ("PATCH", "/api/v1/me/buyer-profile", {"version": 1}),
        ("GET", f"/api/v1/buyer-profile/{uuid.uuid4()}", None),
    ):
        response = client.request(method, path, headers=spoofed, json=body)
        assert response.status_code == 401, (method, path, response.status_code)
        assert response.json()["code"] == "AUTH_REQUIRED"


def test_the_router_module_derives_the_subject_from_the_verified_principal() -> None:
    """STEP 21 regression guard: the deleted header helpers must not come back."""

    import inspect

    from app.api.v1.routers import buyer_profile as buyer_profile_router

    source = inspect.getsource(buyer_profile_router)

    assert "get_verified_principal" in source
    assert not hasattr(buyer_profile_router, "_tenant_header")
    assert not hasattr(buyer_profile_router, "_user_header")

    # X-Tenant-Id/X-User-Id survive ONLY inside resolve_buyer_subject, and only as a
    # cross-check: no endpoint may take them directly.
    subject_source = inspect.getsource(buyer_profile_router.resolve_buyer_subject)
    assert 'Header(alias="X-Tenant-Id")' in subject_source
    assert source.count('Header(alias="X-Tenant-Id")') == 1
    assert source.count('Header(alias="X-User-Id")') == 1
    for handler in (
        buyer_profile_router.get_my_buyer_profile,
        buyer_profile_router.patch_my_buyer_profile,
        buyer_profile_router.get_buyer_profile_by_id,
    ):
        parameters = inspect.signature(handler).parameters
        assert "x_tenant_id" not in parameters
        assert "x_user_id" not in parameters


def test_get_my_buyer_profile_returns_the_callers_own_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    profile = _fake_profile(
        tenant_id=tenant_id,
        user_id=user_id,
        codes=[SimpleNamespace(code_group="CHANNEL", attribute_code="CHANNEL.OFFLINE")],
    )
    seen: dict[str, uuid.UUID] = {}

    async def _fake_get_or_create(db: object, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> SimpleNamespace:
        seen["tenant_id"], seen["user_id"] = tenant_id, user_id
        return profile

    monkeypatch.setattr(service, "get_or_create_buyer_profile", _fake_get_or_create)
    app = _standalone_app(tenant_id, user_id)
    client = TestClient(app)

    response = client.get("/api/v1/me/buyer-profile", headers=_headers())

    assert response.status_code == 200
    body = response.json()
    assert body["success"] is True
    assert body["data"]["buyer_profile_id"] == str(profile.buyer_profile_id)
    assert body["data"]["channel_codes"] == ["CHANNEL.OFFLINE"]
    assert body["data"]["verification_status"] == "UNVERIFIED"
    assert body["meta"]["request_id"] == "req-buyer-profile-test"
    # the service was called with the *principal-derived* pair, not with anything the
    # client could influence
    assert seen == {"tenant_id": tenant_id, "user_id": user_id}


def test_a_context_header_that_disagrees_with_the_session_is_403_not_a_substitution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy adapters may still send X-Tenant-Id/X-User-Id. They are a claim to be
    checked, never identity (recommendations.py:269-278's discipline)."""

    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    victim_user = uuid.uuid4()

    async def _fail_if_called(*args: object, **kwargs: object) -> None:
        raise AssertionError("the service must never run for a mismatched context")

    monkeypatch.setattr(service, "get_or_create_buyer_profile", _fail_if_called)
    client = TestClient(_standalone_app(tenant_id, user_id))

    response = client.get(
        "/api/v1/me/buyer-profile",
        headers={"X-Tenant-Id": str(tenant_id), "X-User-Id": str(victim_user)},
    )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "RESOURCE_FORBIDDEN"


def test_a_matching_context_header_is_accepted(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    profile = _fake_profile(tenant_id=tenant_id, user_id=user_id)

    async def _fake_get_or_create(db: object, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> SimpleNamespace:
        return profile

    monkeypatch.setattr(service, "get_or_create_buyer_profile", _fake_get_or_create)
    client = TestClient(_standalone_app(tenant_id, user_id))

    response = client.get(
        "/api/v1/me/buyer-profile",
        headers={"X-Tenant-Id": str(tenant_id), "X-User-Id": str(user_id)},
    )

    assert response.status_code == 200


def test_patch_my_buyer_profile_returns_409_on_version_conflict(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    profile = _fake_profile(tenant_id=tenant_id, user_id=user_id, version=3)

    async def _fake_get_or_create(db: object, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> SimpleNamespace:
        return profile

    async def _fake_apply_patch(db: object, profile_arg: object, patch: BuyerProfilePatchRequest) -> None:
        raise VersionConflictError(expected=patch.version, actual=3)

    monkeypatch.setattr(service, "get_or_create_buyer_profile", _fake_get_or_create)
    monkeypatch.setattr(service, "apply_patch", _fake_apply_patch)
    app = _standalone_app(tenant_id, user_id)
    client = TestClient(app)

    response = client.patch(
        "/api/v1/me/buyer-profile",
        headers=_headers(),
        json={"version": 1, "buyer_type": "RETAILER"},
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "BUYER_PROFILE_VERSION_CONFLICT"
    assert response.json()["error"]["retryable"] is True


def test_patch_my_buyer_profile_returns_422_for_an_unknown_ontology_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    profile = _fake_profile(tenant_id=tenant_id, user_id=user_id, version=1)

    async def _fake_get_or_create(db: object, *, tenant_id: uuid.UUID, user_id: uuid.UUID) -> SimpleNamespace:
        return profile

    async def _fake_apply_patch(db: object, profile_arg: object, patch: BuyerProfilePatchRequest) -> None:
        raise UnknownOntologyCodeError("channel_codes", "CHANNEL.NOT_A_REAL_CODE")

    monkeypatch.setattr(service, "get_or_create_buyer_profile", _fake_get_or_create)
    monkeypatch.setattr(service, "apply_patch", _fake_apply_patch)
    app = _standalone_app(tenant_id, user_id)
    client = TestClient(app)

    response = client.patch(
        "/api/v1/me/buyer-profile",
        headers=_headers(),
        json={"version": 1, "channel_codes": ["CHANNEL.NOT_A_REAL_CODE"]},
    )

    assert response.status_code == 422
    body = response.json()
    assert body["error"]["code"] == "VALIDATION_FAILED"
    assert body["error"]["field_errors"] == [
        {"field": "channel_codes", "reason": "unknown_ontology_code"}
    ]


def test_patch_my_buyer_profile_rejects_a_verification_status_field_before_touching_the_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant_id, user_id = uuid.uuid4(), uuid.uuid4()
    calls: list[str] = []

    async def _fail_if_called(*args: object, **kwargs: object) -> None:
        calls.append("called")
        raise AssertionError("service.apply_patch must not run for a rejected body")

    monkeypatch.setattr(service, "apply_patch", _fail_if_called)
    app = _standalone_app(tenant_id, user_id)
    client = TestClient(app)

    response = client.patch(
        "/api/v1/me/buyer-profile",
        headers=_headers(),
        json={"version": 1, "verification_status": "VERIFIED"},
    )

    assert response.status_code == 422
    assert calls == []


def test_get_buyer_profile_by_id_rejects_another_users_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    """The STEP 21 load-bearing test: authenticate as user A, ask for user B's profile.

    Before the merge this comparison read the caller's own ``X-Tenant-Id``/``X-User-Id``
    headers, so it could be satisfied by editing them. There is now no header to edit -
    the only way to be user B is to hold user B's session.
    """

    owner_tenant, owner_user = uuid.uuid4(), uuid.uuid4()
    other_user = uuid.uuid4()
    profile = _fake_profile(tenant_id=owner_tenant, user_id=owner_user)

    async def _fake_get_by_id(db: object, buyer_profile_id: uuid.UUID) -> SimpleNamespace:
        return profile

    monkeypatch.setattr(service, "get_buyer_profile_by_id", _fake_get_by_id)

    intruder = TestClient(_standalone_app(owner_tenant, other_user))
    forbidden = intruder.get(f"/api/v1/buyer-profile/{profile.buyer_profile_id}")
    assert forbidden.status_code == 403
    assert forbidden.json()["error"]["code"] == "RESOURCE_FORBIDDEN"

    # asserting the owner's identity in headers changes nothing - it is now a cross-check
    still_forbidden = intruder.get(
        f"/api/v1/buyer-profile/{profile.buyer_profile_id}",
        headers={"X-Tenant-Id": str(owner_tenant), "X-User-Id": str(owner_user)},
    )
    assert still_forbidden.status_code == 403

    owner = TestClient(_standalone_app(owner_tenant, owner_user))
    allowed = owner.get(f"/api/v1/buyer-profile/{profile.buyer_profile_id}")
    assert allowed.status_code == 200
    assert allowed.json()["data"]["buyer_profile_id"] == str(profile.buyer_profile_id)


def test_get_buyer_profile_by_id_rejects_a_profile_from_another_tenant(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner_tenant, owner_user = uuid.uuid4(), uuid.uuid4()
    profile = _fake_profile(tenant_id=owner_tenant, user_id=owner_user)

    async def _fake_get_by_id(db: object, buyer_profile_id: uuid.UUID) -> SimpleNamespace:
        return profile

    monkeypatch.setattr(service, "get_buyer_profile_by_id", _fake_get_by_id)
    # same user_id, different tenant - must still be refused
    client = TestClient(_standalone_app(uuid.uuid4(), owner_user))

    response = client.get(f"/api/v1/buyer-profile/{profile.buyer_profile_id}")

    assert response.status_code == 403


def test_get_buyer_profile_by_id_returns_403_rather_than_404_for_a_missing_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Same status for "exists, not yours" and "doesn't exist" - don't leak existence
    (mirrors app/api/v1/routers/recommendations.py's identical choice)."""

    async def _fake_get_by_id(db: object, buyer_profile_id: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(service, "get_buyer_profile_by_id", _fake_get_by_id)
    app = _standalone_app(uuid.uuid4(), uuid.uuid4())
    client = TestClient(app)

    response = client.get(f"/api/v1/buyer-profile/{uuid.uuid4()}")

    assert response.status_code == 403
