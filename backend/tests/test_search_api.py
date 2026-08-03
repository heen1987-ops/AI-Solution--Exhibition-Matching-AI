from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_search_and_recommendation_routes_are_registered() -> None:
    paths = set(app.openapi()["paths"])

    assert "/api/v1/search" in paths
    assert "/api/v1/search/clarify" in paths
    assert "/api/v1/search/{search_session_id}" in paths
    assert "/api/v1/guest/sessions/{guest_session_id}/search" in paths
    assert "/api/v1/recommendations" in paths
    assert "/api/v1/recommendations/{recommendation_session_id}" in paths


def test_registered_search_requires_profile_without_touching_database() -> None:
    response = client.post(
        "/api/v1/search",
        json={
            "channel": "REGISTERED_WEB",
            "query_type": "FREE_TEXT",
            "query_text": "달지 않은 막걸리",
        },
    )

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"


def test_guest_search_requires_guest_session_id_before_database_lookup() -> None:
    response = client.post(
        "/api/v1/search",
        headers={"X-MeetAI-User-Type": "GUEST_WEB"},
        json={
            "channel": "GUEST_WEB",
            "query_type": "FREE_TEXT",
            "query_text": "친환경 포장재 업체",
        },
    )

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "SEARCH_QUERY_INVALID"


def test_recommendations_require_authentication() -> None:
    response = client.get("/api/v1/recommendations")

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "AUTHENTICATION_REQUIRED"
