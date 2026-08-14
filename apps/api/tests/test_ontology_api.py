from __future__ import annotations

from app.main import app
from fastapi.testclient import TestClient

client = TestClient(app)


def test_catalog_metadata_is_available_without_database() -> None:
    response = client.get("/api/v1/ontology")
    assert response.status_code == 200
    assert response.json()["taxonomy_version"] == "1.0.0"
    assert response.json()["concept_count"] >= 250


def test_resolve_marks_ambiguous_synonym_for_review() -> None:
    response = client.post(
        "/api/v1/ontology/resolve",
        json={"text": "향긋한", "locale": "ko-KR", "context": "CONSUMER"},
    )
    assert response.status_code == 200
    assert response.json()["review_required"] is True
    assert len(response.json()["matches"]) >= 2


def test_derive_band_uses_explicit_boundary() -> None:
    response = client.post(
        "/api/v1/ontology/derive-band",
        json={"metric": "price_krw", "value": 50_000},
    )
    assert response.status_code == 200
    assert response.json()["concept_code"] == "PRICE_BAND.K20_TO_K50"


def test_unknown_code_is_404() -> None:
    response = client.get("/api/v1/ontology/concepts/UNKNOWN.CODE")
    assert response.status_code == 404
    assert response.json()["detail"] == "ONTOLOGY_CODE_NOT_FOUND"
