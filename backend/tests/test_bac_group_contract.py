from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import yaml
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ROOT = Path(__file__).resolve().parents[2]
STATIC_OPENAPI_PATH = ROOT / ".harness" / "contracts" / "openapi.yaml"

IMPLEMENTED_OPERATION_IDS = {
    "getHealthLive",
    "getHealthReady",
    "getSystemInfo",
    "getOntologyMetadata",
    "listOntologyConcepts",
    "getOntologyConcept",
    "resolveOntologySynonym",
    "deriveOntologyBand",
    "getMyProfile",
    "patchMyProfileAttributes",
    "startGuestWebSession",
    "getGuestWebSession",
    "submitGuestWebSearch",
    "addGuestWebFavorite",
    "removeGuestWebFavorite",
    "convertGuestWebSession",
    "submitSearch",
    "clarifySearch",
    "getSearchSession",
    "getRecommendations",
    "getRecommendationSession",
    "listFavorites",
    "addFavorite",
    "removeFavorite",
    "listBuyerMatches",
    "createMeetingRequest",
    "updateMeetingStatus",
    "createContentApproval",
    "getExhibitor",
    "getBooth",
    "updateBoothStatus",
}

KNOWN_UNIMPLEMENTED_STATIC_OPERATION_IDS: set[str] = set()

HTTP_METHODS = {"get", "put", "post", "delete", "patch"}


def _static_openapi() -> dict[str, Any]:
    return yaml.safe_load(STATIC_OPENAPI_PATH.read_text(encoding="utf-8"))


def _runtime_path(static_path: str) -> str:
    if static_path.startswith("/health"):
        return static_path
    return f"/api/v1{static_path}"


def _static_operations_by_id() -> dict[str, tuple[str, str, dict[str, Any]]]:
    spec = _static_openapi()
    operations: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            operations[operation["operationId"]] = (path, method, operation)
    return operations


def _runtime_operations_by_id() -> dict[str, tuple[str, str, dict[str, Any]]]:
    spec = app.openapi()
    operations: dict[str, tuple[str, str, dict[str, Any]]] = {}
    for path, path_item in spec["paths"].items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS:
                continue
            operations[operation["operationId"]] = (path, method, operation)
    return operations


def _assert_error_envelope(response, *, status_code: int, code: str) -> None:
    assert response.status_code == status_code
    body = response.json()
    assert set(body) == {"error"}
    error = body["error"]
    assert error["code"] == code
    assert isinstance(error["message"], str) and error["message"]
    assert isinstance(error["request_id"], str)
    uuid.UUID(error["request_id"])
    assert "details" in error


def test_implemented_operation_ids_match_static_openapi_contract() -> None:
    static_operations = _static_operations_by_id()
    runtime_spec = app.openapi()

    for operation_id in sorted(IMPLEMENTED_OPERATION_IDS):
        static_path, method, static_operation = static_operations[operation_id]
        runtime_path = _runtime_path(static_path)
        runtime_operation = runtime_spec["paths"][runtime_path][method]

        assert runtime_operation["operationId"] == static_operation["operationId"]


def test_static_backend_contract_gaps_are_explicit() -> None:
    static_operations = _static_operations_by_id()
    runtime_operations = _runtime_operations_by_id()
    static_ids = set(static_operations)
    runtime_ids = set(runtime_operations)

    missing = (static_ids - runtime_ids) - KNOWN_UNIMPLEMENTED_STATIC_OPERATION_IDS

    assert not missing
    assert KNOWN_UNIMPLEMENTED_STATIC_OPERATION_IDS == static_ids - runtime_ids


def test_runtime_error_responses_use_contract_envelope_without_database() -> None:
    random_profile_id = str(uuid.uuid4())

    cases = [
        (
            client.get("/api/v1/favorites"),
            401,
            "AUTHENTICATION_REQUIRED",
        ),
        (
            client.get("/api/v1/favorites", headers={"X-MeetAI-User-Type": "GUEST_WEB"}),
            403,
            "PERMISSION_DENIED",
        ),
        (
            client.get(
                "/api/v1/buyer/matches",
                headers={"X-MeetAI-Profile-Id": random_profile_id},
            ),
            403,
            "PERMISSION_DENIED",
        ),
        (
            client.post(
                "/api/v1/admin/content-approvals",
                json={"exhibitor_id": str(uuid.uuid4()), "decision": "APPROVED"},
            ),
            403,
            "PERMISSION_DENIED",
        ),
        (
            client.post(
                "/api/v1/admin/content-approvals",
                headers={"X-MeetAI-Actor-Role": "OPERATOR"},
                json={"exhibitor_id": str(uuid.uuid4()), "decision": "APPROVED"},
            ),
            401,
            "AUTHENTICATION_REQUIRED",
        ),
        (
            client.patch(
                f"/api/v1/admin/booths/{uuid.uuid4()}/status",
                json={"operating_status": "OPEN"},
            ),
            403,
            "PERMISSION_DENIED",
        ),
        (
            client.patch(
                f"/api/v1/admin/booths/{uuid.uuid4()}/status",
                headers={"X-MeetAI-Actor-Role": "OPERATOR"},
                json={"operating_status": "OPEN"},
            ),
            401,
            "AUTHENTICATION_REQUIRED",
        ),
        (
            client.post(
                "/api/v1/search",
                json={"channel": "REGISTERED_WEB", "query_type": "FREE_TEXT"},
            ),
            422,
            "SEARCH_QUERY_INVALID",
        ),
        (
            client.get("/api/v1/search/not-a-uuid"),
            422,
            "VALIDATION_ERROR",
        ),
        (
            client.get("/api/v1/recommendations"),
            401,
            "AUTHENTICATION_REQUIRED",
        ),
    ]

    for response, status_code, code in cases:
        _assert_error_envelope(response, status_code=status_code, code=code)


def test_contact_details_are_not_exposed_before_meeting_confirmation() -> None:
    schema = app.openapi()["components"]["schemas"]["MeetingResponse"]

    assert set(schema["properties"]) == {
        "meeting_id",
        "status",
        "contact_disclosed",
    }
