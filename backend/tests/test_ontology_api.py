from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

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


# ---------------------------------------------------------------------------
# AIS-002: 온톨로지 유사어 해석 테스트셋 (다국어 ko/en 케이스 포함)
#
# 아래 케이스는 src/meet_ai/ontology/catalog.v1.json의 실제 synonyms 배열(11건,
# 2026-08 기준)을 근거로 작성했다. 카탈로그 조사 결과 11건 모두 locale="ko-KR"이며
# locale="en-US"(또는 그 외 영문 로케일) 유사어 매핑은 현재 단 하나도 존재하지
# 않는다. 따라서 "실제 영문 유사어가 존재하는 것처럼" 매칭 성공 케이스를 지어내는
# 대신, 아래에서는
#   (a) ko-KR 유사어의 정상 해석(단일/PRODUCT/CONSUMER/BUYER 컨텍스트별)과
#   (b) 로케일 스코핑이 실제로 강제된다는 것 - 즉 동일 텍스트를 locale="en-US"로
#       질의하면 카탈로그에 해당 로케일 데이터가 없으므로 매치가 0건이고
#       review_required=True가 된다는 것 - 을 검증한다.
# (b)는 "영문 유사어 해석이 된다"는 주장이 아니라 "영문 유사어 데이터 부재가
# 로케일 스코프 필터를 통해 안전하게(허위 매치 없이) 드러난다"는 현재 동작을
# 문서화하는 회귀 테스트다. 카탈로그에 영문 유사어가 실제로 추가되면 이 테스트의
# 기대값(0건)은 갱신되어야 한다 - 자세한 내용은 handoff의 RISKS 참고
# (.harness/handoffs/qa/AIS-002.md).
# ---------------------------------------------------------------------------


def test_resolve_single_match_product_context_ko() -> None:
    """PRODUCT 컨텍스트의 단일 매치 유사어는 리뷰 없이 바로 해석된다."""
    response = client.post(
        "/api/v1/ontology/resolve",
        json={"text": "막걸리", "locale": "ko-KR", "context": "PRODUCT"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matches"] == [
        {
            "concept_code": "ALCOHOL.TAKJU",
            "priority": 10,
            "context": "PRODUCT",
            "locale": "ko-KR",
        }
    ]
    assert body["review_required"] is False


def test_resolve_single_match_consumer_context_ko() -> None:
    """CONSUMER 컨텍스트 - 맛 표현 유사어("달지 않은" -> TASTE.DRY)."""
    response = client.post(
        "/api/v1/ontology/resolve",
        json={"text": "달지 않은", "locale": "ko-KR", "context": "CONSUMER"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["review_required"] is False
    assert len(body["matches"]) == 1
    assert body["matches"][0]["concept_code"] == "TASTE.DRY"


def test_resolve_single_match_buyer_context_ko() -> None:
    """BUYER 컨텍스트 - 거래 관행 유사어("정기 납품" -> TRADE.REGULAR_SUPPLY)."""
    response = client.post(
        "/api/v1/ontology/resolve",
        json={"text": "정기 납품", "locale": "ko-KR", "context": "BUYER"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["review_required"] is False
    assert len(body["matches"]) == 1
    assert body["matches"][0]["concept_code"] == "TRADE.REGULAR_SUPPLY"


def test_resolve_context_mismatch_yields_no_match_ko() -> None:
    """PRODUCT 유사어("막걸리")를 다른 컨텍스트(BUYER)로 질의하면 매치가 없다.

    resolve_synonym()은 item_context가 "ANY"이거나 요청 컨텍스트와 정확히
    일치할 때만 매치한다(src/meet_ai/ontology/catalog.py Catalog.resolve_synonym).
    카탈로그에 context="ANY"인 유사어가 아직 없으므로, 컨텍스트가 어긋나면
    항상 0건이어야 한다.
    """
    response = client.post(
        "/api/v1/ontology/resolve",
        json={"text": "막걸리", "locale": "ko-KR", "context": "BUYER"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matches"] == []
    assert body["review_required"] is True


def test_resolve_context_query_is_case_insensitive() -> None:
    """API 레이어가 context를 대문자로 정규화한다(소문자 입력도 동일하게 매치)."""
    response = client.post(
        "/api/v1/ontology/resolve",
        json={"text": "막걸리", "locale": "ko-KR", "context": "product"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["review_required"] is False
    assert body["matches"][0]["context"] == "PRODUCT"


def test_resolve_en_locale_has_no_synonym_coverage_yet() -> None:
    """다국어(ko/en) 케이스: 동일 텍스트를 en-US 로케일로 질의.

    카탈로그 조사 결과(2026-08) src/meet_ai/ontology/catalog.v1.json에는
    locale="en-US" 유사어가 하나도 없다 - 11건 모두 ko-KR이다. 이는 실제
    카탈로그 데이터를 근거로 한 발견사항(finding)이며, 이 테스트는 그 부재를
    "허위 매치 없이" 안전하게 반영하는 현재 동작(로케일 불일치 시 0건 +
    review_required=True)을 고정하는 회귀 테스트다. 지어낸 영문 유사어 쌍을
    매치시키는 테스트가 아니다 - handoff RISKS 항목 참고.
    """
    response = client.post(
        "/api/v1/ontology/resolve",
        json={"text": "막걸리", "locale": "en-US", "context": "PRODUCT"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matches"] == []
    assert body["review_required"] is True


def test_resolve_unmapped_text_returns_empty_and_review_required() -> None:
    """카탈로그에 없는 임의 텍스트는 0건 매치 + review_required=True여야 한다."""
    response = client.post(
        "/api/v1/ontology/resolve",
        json={"text": "완전히 존재하지 않는 유사어 텍스트", "locale": "ko-KR"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["matches"] == []
    assert body["review_required"] is True
