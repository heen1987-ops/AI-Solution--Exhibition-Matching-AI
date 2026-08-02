from __future__ import annotations

from app.main import app


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
