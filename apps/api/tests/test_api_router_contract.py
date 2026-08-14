from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from app.main import app

#: MERGE STEP 28: a placeholder value substituted for every ``{param}`` path segment so a
#: bare call can be routed at all (its actual value never matters - a route that trusted
#: it would already be the header-trust defect this test exists to catch).
_PATH_PARAM_PLACEHOLDER = "11111111-1111-4111-8111-111111111111"

#: Routes intentionally reachable with NO verified principal/subject at all, matched by
#: exact ``(method, openapi_path_template)``. Every one of these is public BY DESIGN and
#: was true before this merge - the plan's "resolved conflicts" section names the first
#: four explicitly; the rest are pre-existing main routes verified by direct read (see
#: each router's own docstring/comment):
#:   - GET /exhibitors/{exhibitor_id}/profile: partner.py 28.1 - "공개, PUBLIC 등급만 반환"
#:   - POST /api/v1/webhooks/backju: HMAC X-Webhook-Signature IS its auth, not a principal
#:   - GET /healthz: liveness probe
_EXPLICITLY_PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("POST", "/api/v1/auth/magic-links/exchange"),
        ("POST", "/api/v1/sessions"),
        ("GET", "/api/v1/exhibitor-preference/{exhibitor_id}"),
        ("GET", "/api/v1/partner/documents/download"),
        ("GET", "/api/v1/exhibitors/{exhibitor_id}/profile"),
        ("POST", "/api/v1/webhooks/backju"),
        ("GET", "/healthz"),
    }
)

#: Whole OpenAPI-tag categories that are public by design (module docstrings / the merge
#: plan's "public catalog/search/kiosk routes" carve-out): the anonymous public catalog
#: (exhibitors.router -> exhibition_public.py), full-text search, the kiosk device surface
#: (no long-term identity is ever collected there - a hard product invariant), and the
#: shared ontology concept catalog (pre-existing main behaviour, unrelated to this merge).
_PUBLIC_TAGS: frozenset[str] = frozenset({"public-catalog", "search", "kiosk", "ontology"})


def _iter_routes() -> list[tuple[str, str, str, frozenset[str]]]:
    """Yield ``(method, openapi_path_template, concrete_path, tags)`` for every mounted
    v1 operation."""

    spec = app.openapi()
    rows: list[tuple[str, str, str, frozenset[str]]] = []
    for path, operations in spec["paths"].items():
        concrete_path = re.sub(r"\{[^/]+\}", _PATH_PARAM_PLACEHOLDER, path)
        for method, operation in operations.items():
            if method.upper() not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
                continue
            rows.append(
                (method.upper(), path, concrete_path, frozenset(operation.get("tags", [])))
            )
    return rows


def test_all_implemented_v1_domains_are_mounted() -> None:
    paths = set(app.openapi()["paths"])

    expected = {
        "/api/v1/profiles/me",
        "/api/v1/consents/me",
        "/api/v1/recommendations",
        "/api/v1/profiles/{profile_id}/cold-start",
        "/api/v1/partner/products",
        "/api/v1/conversations",
        "/api/v1/conversations/{conversation_id}/messages",
        "/api/v1/conversations/{conversation_id}/extractions/{extraction_id}/decision",
    }
    assert expected <= paths


def test_conversation_routes_use_the_public_success_envelope() -> None:
    spec = app.openapi()
    expected_schemas = {
        "/api/v1/conversations": "Envelope_ConversationStartResponse_",
        "/api/v1/conversations/{conversation_id}/messages": (
            "Envelope_ConversationMessageResponse_"
        ),
        "/api/v1/conversations/{conversation_id}/extractions/"
        "{extraction_id}/decision": "Envelope_ExtractionDecisionResponse_",
    }

    for path, schema_name in expected_schemas.items():
        response_schema = spec["paths"][path]["post"]["responses"]["200"][
            "content"
        ]["application/json"]["schema"]
        assert response_schema["$ref"] == f"#/components/schemas/{schema_name}"


def test_conversation_start_requires_a_verified_subject() -> None:
    response = TestClient(app, raise_server_exceptions=False).post(
        "/api/v1/conversations",
        json={"language": "ko"},
    )

    assert response.status_code == 401


def test_adaptive_routes_require_a_verified_subject() -> None:
    response = TestClient(app, raise_server_exceptions=False).get(
        "/api/v1/profiles/11111111-1111-4111-8111-111111111111/cold-start"
    )

    assert response.status_code == 401


# ---------------------------------------------------------------------------
# MERGE STEP 28: standing negative-authentication contract.
#
# 58 of the 60 originally-ported worktree endpoints identified the caller from a
# client-controlled header (X-Actor-User-Id / X-Profile-Id / X-Staff-Id / X-Tenant-Id).
# Steps 20-24 swapped every one of those for a principal-derived dependency. This test is
# the regression guard for that swap: it does not name individual endpoints (a future
# router added without reading this file would silently not be covered), it walks
# whatever ``app.openapi()['paths']`` mounts right now and demands 401 from anything not
# on the explicit public allowlist above. A future port that reintroduces a header-trust
# stub, or that is registered in api.py before its auth is rewired, fails this test
# immediately instead of shipping a silent PII/write exposure.
# ---------------------------------------------------------------------------

_ROUTE_CASES = [
    pytest.param(method, path, concrete_path, tags, id=f"{method} {path}")
    for method, path, concrete_path, tags in _iter_routes()
    if (method, path) not in _EXPLICITLY_PUBLIC_ROUTES and not (tags & _PUBLIC_TAGS)
]


@pytest.mark.parametrize("method,path,concrete_path,tags", _ROUTE_CASES)
def test_every_non_public_v1_route_rejects_an_unauthenticated_bare_call(
    method: str, path: str, concrete_path: str, tags: frozenset[str]
) -> None:
    del path, tags
    client = TestClient(app, raise_server_exceptions=False)
    if method in {"POST", "PUT", "PATCH"}:
        response = client.request(method, concrete_path, json={})
    else:
        response = client.request(method, concrete_path)

    assert response.status_code == 401, (
        f"{method} {concrete_path} returned {response.status_code} for a bare, "
        "unauthenticated call - expected 401. If this route is genuinely public by "
        "design, add it to _EXPLICITLY_PUBLIC_ROUTES/_PUBLIC_TAGS above with a reason; "
        "otherwise it is identifying the caller from something other than a verified "
        "server-side principal (MERGE STEP 20/21)."
    )


def test_public_allowlist_entries_still_exist_in_the_mounted_api() -> None:
    """Guards the allowlist itself against drift - an entry naming a path/tag that no
    longer exists would otherwise silently stop being exercised by anything."""

    routes = _iter_routes()
    mounted = {(method, path) for method, path, _, _ in routes}
    stale = {
        (method, path)
        for method, path in _EXPLICITLY_PUBLIC_ROUTES
        if (method, path) not in mounted
    }
    assert not stale, f"stale allowlist entries no longer mounted: {stale}"

    mounted_tags = {tag for _, _, _, tags in routes for tag in tags}
    stale_tags = _PUBLIC_TAGS - mounted_tags
    assert not stale_tags, f"stale public tags no longer mounted: {stale_tags}"
