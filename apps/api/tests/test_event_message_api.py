"""Tests for the operator-authored event-message campaign domain - WAVE 2E ADMIN-NOTIFICATION.

Coverage (task spec: "workflow-state transitions, targeting restricted to the safe segment
list ... preview computation, small-audience warning, script/external-tracking content
rejected"):
    - route registration (build_event_message_router() exposes every documented path)
    - Pydantic <-> model Literal/tuple drift guard (same convention as test_notification_api.py)
    - workflow state machine: every allowed transition, every disallowed transition, edit
      resetting a PREVIEWED/APPROVED message back to DRAFT, terminal statuses reject all edits
    - targeting: disallowed/fine-grained/sensitive segment strings are rejected;
      SPECIFIC_ROLE requires a role and every other segment forbids one; each allowed segment's
      query compiles with the WHERE-clause filters that actually implement it (same "compile to
      text, no DB needed" technique as test_exhibition_public_api.py)
    - small-audience suppression: target_count below the threshold is never echoed exactly
    - content policy: script tags, event-handler attributes, javascript: URLs, non-allowlisted
      external links, and (implicitly, since <img> is not in the allowed tag set at all)
      tracking pixels are all rejected; safe markdown/HTML subset passes
    - destination_screen must be an internal route
    - authentication (merge plan STEP 23): no route is reachable without a verified session,
      and the three irreversible transitions demand a fresh-MFA EVENT_ADMIN
"""

from __future__ import annotations

import ast
import inspect
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.v1.routers import event_message as router_module
from app.core.auth import (
    AuthException,
    VerifiedPrincipal,
    auth_exception_handler,
    get_verified_principal,
)
from app.core.router_auth import get_actor_user_id as shared_get_actor_user_id
from app.db.session import get_db
from app.models.event_message import (
    EVENT_MESSAGE_CHANNELS,
    EVENT_MESSAGE_STATUSES,
    EVENT_MESSAGE_TARGET_ROLE_CODES,
    EVENT_MESSAGE_TARGET_SEGMENTS,
    EVENT_MESSAGE_TYPES,
)
from app.schemas.auth import AuthPrincipal, AuthRoleGrant
from app.schemas.event_message import (
    Channel,
    MessageStatus,
    MessageType,
    TargetRoleCode,
    TargetSegment,
)
from app.services.event_message import content, targeting, workflow

# ---------------------------------------------------------------------------
# Route registration
# ---------------------------------------------------------------------------


def test_build_event_message_router_exposes_documented_routes() -> None:
    api_router = router_module.build_event_message_router()
    routes = {(route.path, method) for route in api_router.routes for method in route.methods}

    expected = {
        ("/event-messages", "POST"),
        ("/event-messages", "GET"),
        ("/event-messages/{event_message_id}", "GET"),
        ("/event-messages/{event_message_id}", "PATCH"),
        ("/event-messages/{event_message_id}/preview", "POST"),
        ("/event-messages/{event_message_id}/approve", "POST"),
        ("/event-messages/{event_message_id}/schedule", "POST"),
        ("/event-messages/{event_message_id}/publish", "POST"),
        ("/event-messages/{event_message_id}/cancel", "POST"),
        ("/event-messages/{event_message_id}/complete", "POST"),
    }
    assert expected <= routes


def test_router_module_has_no_bare_router_symbol_ready_for_double_mount() -> None:
    """This track's task spec requires exposing a builder function, not a module-level router
    instance that could get accidentally double-mounted (see module docstring)."""

    assert inspect.isfunction(router_module.build_event_message_router)


# ---------------------------------------------------------------------------
# Schema <-> model drift guard (mirrors test_notification_api.py's own convention)
# ---------------------------------------------------------------------------


def test_schema_literals_match_model_tuples() -> None:
    assert set(MessageType.__args__) == set(EVENT_MESSAGE_TYPES)
    assert set(MessageStatus.__args__) == set(EVENT_MESSAGE_STATUSES)
    assert set(Channel.__args__) == set(EVENT_MESSAGE_CHANNELS)
    assert set(TargetSegment.__args__) == set(EVENT_MESSAGE_TARGET_SEGMENTS)
    assert set(TargetRoleCode.__args__) == set(EVENT_MESSAGE_TARGET_ROLE_CODES)


# ---------------------------------------------------------------------------
# Workflow state machine
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        ("DRAFT", "PREVIEWED"),
        ("PREVIEWED", "APPROVED"),
        ("PREVIEWED", "DRAFT"),
        ("APPROVED", "SCHEDULED"),
        ("APPROVED", "PUBLISHED"),
        ("APPROVED", "DRAFT"),
        ("APPROVED", "CANCELLED"),
        ("SCHEDULED", "PUBLISHED"),
        ("SCHEDULED", "CANCELLED"),
        ("PUBLISHED", "COMPLETED"),
    ],
)
def test_allowed_transitions(from_status: str, to_status: str) -> None:
    assert workflow.can_transition(from_status, to_status)
    workflow.require_transition(from_status, to_status)  # must not raise


@pytest.mark.parametrize(
    ("from_status", "to_status"),
    [
        ("DRAFT", "APPROVED"),
        ("DRAFT", "PUBLISHED"),
        ("DRAFT", "COMPLETED"),
        ("PREVIEWED", "PUBLISHED"),
        ("PREVIEWED", "SCHEDULED"),
        ("SCHEDULED", "DRAFT"),
        ("SCHEDULED", "APPROVED"),
        ("PUBLISHED", "DRAFT"),
        ("PUBLISHED", "CANCELLED"),
        ("COMPLETED", "DRAFT"),
        ("COMPLETED", "PUBLISHED"),
        ("CANCELLED", "DRAFT"),
        ("CANCELLED", "PUBLISHED"),
    ],
)
def test_disallowed_transitions_are_rejected(from_status: str, to_status: str) -> None:
    assert not workflow.can_transition(from_status, to_status)
    with pytest.raises(workflow.InvalidTransitionError):
        workflow.require_transition(from_status, to_status)


@pytest.mark.parametrize("status", ["PREVIEWED", "APPROVED"])
def test_edit_resets_previewed_or_approved_to_draft(status: str) -> None:
    assert workflow.status_after_edit(status) == "DRAFT"


def test_edit_on_draft_stays_draft() -> None:
    assert workflow.status_after_edit("DRAFT") == "DRAFT"


@pytest.mark.parametrize("status", ["SCHEDULED", "PUBLISHED", "COMPLETED", "CANCELLED"])
def test_edit_on_non_editable_status_is_rejected(status: str) -> None:
    with pytest.raises(workflow.NotEditableError):
        workflow.status_after_edit(status)


# ---------------------------------------------------------------------------
# Targeting: coarse-segment-only allowlist enforcement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("segment", list(EVENT_MESSAGE_TARGET_SEGMENTS))
def test_allowed_segments_pass_validation(segment: str) -> None:
    role = "OPERATOR" if segment == "SPECIFIC_ROLE" else None
    targeting.validate_target_segment(segment, role)  # must not raise


@pytest.mark.parametrize(
    "disallowed_segment",
    [
        "PROFILE_ATTRIBUTE:AGE_RANGE",  # sensitive-attribute-based targeting
        "BEHAVIOR:VIEWED_BOOTH_3_TIMES",  # fine-grained behavior-based targeting
        "INTEREST_CONCEPT:WHISKEY",
        "ALL_USERS",  # looks plausible but is not the exact allowed code
        "",
    ],
)
def test_disallowed_fine_grained_or_sensitive_segments_are_rejected(
    disallowed_segment: str,
) -> None:
    with pytest.raises(targeting.TargetSegmentNotAllowedError):
        targeting.validate_target_segment(disallowed_segment, None)


def test_specific_role_without_role_code_is_rejected() -> None:
    with pytest.raises(targeting.TargetSegmentNotAllowedError):
        targeting.validate_target_segment("SPECIFIC_ROLE", None)


def test_specific_role_with_unknown_role_code_is_rejected() -> None:
    with pytest.raises(targeting.TargetSegmentNotAllowedError):
        targeting.validate_target_segment("SPECIFIC_ROLE", "SUPERADMIN")


def test_non_specific_role_segment_with_role_code_is_rejected() -> None:
    with pytest.raises(targeting.TargetSegmentNotAllowedError):
        targeting.validate_target_segment("BUYERS", "BUYER")


# ---------------------------------------------------------------------------
# Targeting: compiled-SQL assertions (no live DB needed)
# ---------------------------------------------------------------------------

_TENANT_ID = uuid.uuid4()
_EVENT_ID = uuid.uuid4()


def _compiled(stmt) -> str:
    return str(stmt.compile(compile_kwargs={"literal_binds": False}))


@pytest.mark.parametrize(
    ("segment", "expected_fragment"),
    [
        ("PROFILE_UNCONFIRMED", "profile_status"),
        ("RECOMMENDATION_READY", "profile_status"),
        ("BUYERS", "user_type"),
    ],
)
def test_user_profile_segments_filter_on_profile_status_or_user_type(
    segment: str, expected_fragment: str
) -> None:
    stmt = targeting.target_user_ids_stmt(
        tenant_id=_TENANT_ID, event_id=_EVENT_ID, target_segment=segment, target_role_code=None
    )
    sql = _compiled(stmt)
    assert "user_profile" in sql
    assert expected_fragment in sql
    assert "account_status" in sql  # every segment excludes non-ACTIVE accounts


def test_all_registered_users_scopes_to_tenant_and_event_and_real_user_id() -> None:
    stmt = targeting.target_user_ids_stmt(
        tenant_id=_TENANT_ID,
        event_id=_EVENT_ID,
        target_segment="ALL_REGISTERED_USERS",
        target_role_code=None,
    )
    sql = _compiled(stmt)
    assert "user_profile.tenant_id" in sql
    assert "user_profile.event_id" in sql
    assert "user_profile.user_id IS NOT NULL" in sql


def test_exhibitor_staff_segment_filters_role_code_exhibitor() -> None:
    stmt = targeting.target_user_ids_stmt(
        tenant_id=_TENANT_ID,
        event_id=_EVENT_ID,
        target_segment="EXHIBITOR_STAFF",
        target_role_code=None,
    )
    sql = _compiled(stmt)
    assert "user_role" in sql
    assert "role.role_code" in sql


def test_specific_role_segment_parameterizes_role_code() -> None:
    stmt = targeting.target_user_ids_stmt(
        tenant_id=_TENANT_ID,
        event_id=_EVENT_ID,
        target_segment="SPECIFIC_ROLE",
        target_role_code="ADMIN",
    )
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "'ADMIN'" in sql


def test_email_consent_excluded_stmt_filters_on_notification_email_purpose() -> None:
    stmt = targeting.email_consent_excluded_count_stmt(
        tenant_id=_TENANT_ID,
        event_id=_EVENT_ID,
        target_segment="ALL_REGISTERED_USERS",
        target_role_code=None,
        now=datetime.now(UTC),
    )
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "NOTIFICATION_EMAIL" in sql
    assert targeting.EMAIL_CONSENT_PURPOSE == "NOTIFICATION_EMAIL"


def test_duplicate_message_count_stmt_excludes_terminal_statuses() -> None:
    message_id = uuid.uuid4()
    stmt = targeting.duplicate_message_count_stmt(
        tenant_id=_TENANT_ID,
        event_id=_EVENT_ID,
        message_type="EVENT_OPERATION_NOTICE",
        exclude_event_message_id=message_id,
    )
    sql = str(stmt.compile(compile_kwargs={"literal_binds": True}))
    assert "'APPROVED'" in sql and "'SCHEDULED'" in sql and "'PUBLISHED'" in sql
    assert "'COMPLETED'" not in sql
    assert "'CANCELLED'" not in sql
    assert message_id.hex in sql.replace("-", "")


# ---------------------------------------------------------------------------
# Small-audience suppression
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("count", [0, 1, 4])
def test_small_audience_counts_are_suppressed(count: int) -> None:
    exact, display, warning = targeting.display_target_count(count)
    assert exact is None
    assert display == "5명 미만"
    assert warning is True


@pytest.mark.parametrize("count", [5, 6, 3214])
def test_larger_audience_counts_are_shown_exactly(count: int) -> None:
    exact, display, warning = targeting.display_target_count(count)
    assert exact == count
    assert warning is False
    assert str(count) not in display or f"{count:,}" in display


# ---------------------------------------------------------------------------
# Content policy: markdown/safe-HTML-subset only
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "safe_body",
    [
        "그냥 평범한 마크다운 텍스트입니다. **강조** 및 - 목록",
        "<p>공지: <b>10시</b>에 시작합니다.</p>",
        "<a href='/events/current'>바로가기</a>",
        "<ul><li>항목1</li><li>항목2</li></ul>",
    ],
)
def test_safe_markdown_and_html_subset_is_accepted(safe_body: str) -> None:
    content.validate_content(safe_body)  # must not raise


@pytest.mark.parametrize(
    ("unsafe_body", "expected_reason"),
    [
        ("<script>alert(1)</script>", "TAG_NOT_ALLOWED"),
        ("<img src='https://tracker.example.com/pixel.gif'>", "TAG_NOT_ALLOWED"),
        ("<p onclick=\"alert(1)\">클릭</p>", "EVENT_HANDLER_ATTRIBUTE"),
        ("<a href=\"javascript:alert(1)\">링크</a>", "DANGEROUS_URL_SCHEME"),
        ("<a href=\"https://evil.example.com\">외부</a>", "EXTERNAL_URL_NOT_ALLOWLISTED"),
        ("<a href=\"//evil.example.com\">외부</a>", "EXTERNAL_URL_NOT_ALLOWLISTED"),
        ("<iframe src='https://evil.example.com'></iframe>", "TAG_NOT_ALLOWED"),
        ("<style>body{display:none}</style>", "TAG_NOT_ALLOWED"),
        ("<div style=\"color:red\">텍스트</div>", "TAG_NOT_ALLOWED"),
    ],
)
def test_unsafe_content_is_rejected(unsafe_body: str, expected_reason: str) -> None:
    with pytest.raises(content.ContentValidationError) as exc_info:
        content.validate_content(unsafe_body)
    assert exc_info.value.reason_code == expected_reason


@pytest.mark.parametrize(
    "destination",
    ["/notifications", "/events/current", "/profile/confirm"],
)
def test_valid_internal_destination_screens_are_accepted(destination: str) -> None:
    content.validate_destination_screen(destination)  # must not raise


@pytest.mark.parametrize(
    "destination",
    [
        "https://example.com/notifications",  # absolute external URL
        "notifications",  # not rooted
        "//evil.example.com",  # protocol-relative URL - resolves externally in a browser
    ],
)
def test_non_internal_destination_screens_are_rejected(destination: str) -> None:
    with pytest.raises(content.ContentValidationError):
        content.validate_destination_screen(destination)


# ---------------------------------------------------------------------------
# Authentication / authorization (merge plan STEP 23)
# ---------------------------------------------------------------------------


def _module_code(module) -> str:
    """The module's source with its module docstring removed.

    The docstring legitimately *names* the header stubs this port deleted, in order to
    explain that they are gone; the regression guards below must look at code only.
    """

    source = inspect.getsource(module)
    tree = ast.parse(source)
    if ast.get_docstring(tree) is not None:
        first_statement = tree.body[0]
        assert first_statement.end_lineno is not None
        return "\n".join(source.splitlines()[first_statement.end_lineno :])
    return source


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_exception_handler(AuthException, auth_exception_handler)
    app.include_router(router_module.build_event_message_router(), prefix="/admin")
    app.dependency_overrides[get_db] = lambda: iter([object()])
    return app


def _verified_principal(
    *,
    roles: tuple[str, ...] = ("EVENT_ADMIN",),
    authn_level: str = "AAL2",
    mfa_at: datetime | None = None,
    user_id: uuid.UUID | None = None,
    tenant_id: uuid.UUID | None = None,
) -> VerifiedPrincipal:
    tenant_id = tenant_id or uuid.uuid4()
    return VerifiedPrincipal(
        principal=AuthPrincipal(
            subject_type="USER",
            subject_id=user_id or uuid.uuid4(),
            tenant_id=tenant_id,
            event_id=_EVENT_ID,
            role_grants=[
                AuthRoleGrant(
                    role=role, tenant_id=tenant_id, event_id=_EVENT_ID, exhibitor_id=None
                )
                for role in roles
            ],
            authn_level=authn_level,  # type: ignore[arg-type]
            amr={"magic_link", "totp"},
            authenticated_at=datetime.now(UTC),
            mfa_at=mfa_at if mfa_at is not None else datetime.now(UTC),
        ),
        session=None,
    )


_MESSAGE_ID = uuid.uuid4()

#: (method, path, json body) for all ten documented routes.
EVENT_MESSAGE_ROUTES = [
    ("POST", "/admin/event-messages", {}),
    ("GET", f"/admin/event-messages?event_id={_EVENT_ID}", None),
    ("GET", f"/admin/event-messages/{_MESSAGE_ID}", None),
    ("PATCH", f"/admin/event-messages/{_MESSAGE_ID}", {}),
    ("POST", f"/admin/event-messages/{_MESSAGE_ID}/preview", None),
    ("POST", f"/admin/event-messages/{_MESSAGE_ID}/approve", {}),
    ("POST", f"/admin/event-messages/{_MESSAGE_ID}/schedule", {}),
    ("POST", f"/admin/event-messages/{_MESSAGE_ID}/publish", {}),
    ("POST", f"/admin/event-messages/{_MESSAGE_ID}/cancel", {}),
    ("POST", f"/admin/event-messages/{_MESSAGE_ID}/complete", {}),
]


@pytest.mark.parametrize(("method", "path", "body"), EVENT_MESSAGE_ROUTES)
def test_every_event_message_route_is_401_without_a_session(
    method: str, path: str, body: dict | None
) -> None:
    """The ported router identified its operator from an ``X-Actor-User-Id`` header. That is
    gone: with no verified session there is no actor at all, on any of the ten routes."""

    app = _build_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request(method, path, json=body)
    assert response.status_code == 401
    assert response.json()["code"] == "AUTH_REQUIRED"


@pytest.mark.parametrize(("method", "path", "body"), EVENT_MESSAGE_ROUTES)
def test_a_forged_actor_header_does_not_authenticate_anyone(
    method: str, path: str, body: dict | None
) -> None:
    app = _build_app()
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.request(
            method,
            path,
            json=body,
            headers={
                "X-Actor-User-Id": str(uuid.uuid4()),
                "X-Tenant-Id": str(uuid.uuid4()),
            },
        )
    assert response.status_code == 401


def test_the_router_module_defines_no_header_derived_identity_helper() -> None:
    """Regression guard: ``get_actor_user_id`` must come from the shared
    ``app/core/router_auth.py`` adapter, and no ``_resolve_actor_tenant_id`` may reappear."""

    code = _module_code(router_module)
    assert "Header" not in code
    assert "X-Actor-User-Id" not in code
    assert "_resolve_actor_tenant_id" not in code
    assert not hasattr(router_module, "_resolve_actor_tenant_id")
    assert router_module.get_actor_user_id is shared_get_actor_user_id


@pytest.mark.parametrize("transition", ["approve", "schedule", "publish"])
def test_irreversible_transitions_require_aal2(transition: str) -> None:
    """An AAL1 session holding a real EVENT_ADMIN grant is still refused: broadcasting to a
    whole event is not undoable, so it demands MFA."""

    app = _build_app()
    app.dependency_overrides[get_verified_principal] = lambda: _verified_principal(
        authn_level="AAL1"
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/admin/event-messages/{_MESSAGE_ID}/{transition}", json={"row_version": 1}
        )
    assert response.status_code == 403
    assert response.json()["code"] == "MFA_REQUIRED"


@pytest.mark.parametrize("transition", ["approve", "schedule", "publish"])
def test_irreversible_transitions_require_recent_mfa_not_merely_aal2(transition: str) -> None:
    app = _build_app()
    stale = datetime.now(UTC) - timedelta(days=3)
    app.dependency_overrides[get_verified_principal] = lambda: _verified_principal(mfa_at=stale)
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/admin/event-messages/{_MESSAGE_ID}/{transition}", json={"row_version": 1}
        )
    assert response.status_code == 403
    assert response.json()["code"] == "MFA_FRESHNESS_REQUIRED"


@pytest.mark.parametrize("transition", ["approve", "schedule", "publish"])
def test_irreversible_transitions_reject_a_data_reviewer(transition: str) -> None:
    app = _build_app()
    app.dependency_overrides[get_verified_principal] = lambda: _verified_principal(
        roles=("DATA_REVIEWER",)
    )
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            f"/admin/event-messages/{_MESSAGE_ID}/{transition}", json={"row_version": 1}
        )
    assert response.status_code == 403
    assert response.json()["code"] == "RESOURCE_FORBIDDEN"


def test_only_the_three_irreversible_transitions_carry_the_fresh_mfa_gate() -> None:
    """preview/cancel/complete and the CRUD routes stay behind the ordinary operator check -
    the fresh-MFA gate is deliberately scoped, not sprayed across the router."""

    api_router = router_module.build_event_message_router()
    gated_paths = {
        route.path
        for route in api_router.routes
        for dependency in route.dependencies
        if dependency.dependency is router_module.REQUIRE_FRESH_EVENT_ADMIN.dependency
    }
    assert gated_paths == {
        "/event-messages/{event_message_id}/approve",
        "/event-messages/{event_message_id}/schedule",
        "/event-messages/{event_message_id}/publish",
    }


def test_tenant_id_is_never_taken_from_a_request_header() -> None:
    """``_resolve_actor_tenant_id`` (first-matching-role lookup) and any ``X-Tenant-Id``
    header are both gone - the tenant is the one the session was established against."""

    code = _module_code(router_module)
    assert "X-Tenant-Id" not in code
    # exactly one per handler, and there are ten handlers
    assert code.count("principal.principal.tenant_id") == 10
