"""추출 속성 공개등급(visibility) 기본값 정책 (통합 MERGE STEP 16 (a)).

제품 불변식: 거래조건(도매 결제조건·MOQ·리드타임 등)과 가격은 익명 공개면에 노출되지
않는다. 통합 전 ``ingest_extraction_result``는 ``default_visibility="PUBLIC"``을 모든
속성에 그대로 찍어 그 불변식을 깨뜨릴 수 있었다.

DB는 다른 서비스 테스트(tests/test_indexing.py)와 동일하게 인메모리 fake 세션으로 대체한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from app.models.common import new_uuid7
from app.services.extraction.ingestion import ingest_extraction_result
from app.services.extraction.visibility import (
    resolve_default_visibility,
    restricted_attribute_codes,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCHEMA_PATH = _REPO_ROOT / "ai" / "schemas" / "extraction" / "attribute_schema.json"

#: attribute_schema.json에서 직접 읽지 않고 손으로 적은 기대값 - 스키마가 조용히 바뀌면
#: (또는 코드가 잘못된 파일을 읽으면) 아래 대조 테스트가 즉시 실패한다.
_EXPECTED_TRADE_CONDITION_CODES = {
    "trade.oem_capability",
    "trade.private_label_capability",
    "trade.export_capability",
    "trade.supply_capacity",
    "trade.preferred_trade_types",
    "trade.moq",
    "trade.moq_unit",
    "trade.lead_time_days",
    "trade.payment_terms",
}


def test_restricted_codes_are_the_nine_trade_conditions_plus_price() -> None:
    assert restricted_attribute_codes() == frozenset(
        _EXPECTED_TRADE_CONDITION_CODES | {"product.price_krw"}
    )


def test_schema_file_still_flags_exactly_those_nine_as_trade_conditions() -> None:
    payload = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    flagged = {
        item["attribute_code"]
        for item in payload["attributes"]
        if item.get("trade_condition")
    }
    assert flagged == _EXPECTED_TRADE_CONDITION_CODES


@pytest.mark.parametrize(
    "attribute_code,expected",
    [
        ("trade.moq", "VERIFIED_BUYER"),
        ("trade.payment_terms", "VERIFIED_BUYER"),
        ("product.price_krw", "VERIFIED_BUYER"),
        ("company.name", "PUBLIC"),
        ("product.name", "PUBLIC"),
    ],
)
def test_resolve_default_visibility(attribute_code: str, expected: str) -> None:
    assert resolve_default_visibility(attribute_code) == expected


def test_a_stricter_caller_choice_is_never_widened() -> None:
    assert resolve_default_visibility("trade.moq", default_visibility="OPERATOR_ONLY") == (
        "OPERATOR_ONLY"
    )
    assert resolve_default_visibility("company.name", default_visibility="OPERATOR_ONLY") == (
        "OPERATOR_ONLY"
    )
    # REGISTERED_USER is looser than VERIFIED_BUYER, so it must still be narrowed.
    assert resolve_default_visibility("trade.moq", default_visibility="REGISTERED_USER") == (
        "VERIFIED_BUYER"
    )


class _FakeIngestSession:
    """ingest_extraction_result가 실제로 부르는 add/flush만 지원한다."""

    def __init__(self) -> None:
        self.rows: list[Any] = []

    def add(self, obj: Any) -> None:
        pk = next(iter(type(obj).__table__.primary_key.columns)).key
        if getattr(obj, pk, None) is None:
            setattr(obj, pk, new_uuid7())
        self.rows.append(obj)

    async def flush(self) -> None:
        return None


def _result_with(attribute_code: str) -> dict[str, Any]:
    return {
        "entities": [
            {
                "entity_type": "EXHIBITOR",
                "temporary_entity_id": "e1",
                "attributes": [
                    {
                        "attribute_code": attribute_code,
                        "value": "100",
                        "confidence": 0.9,
                        "evidence_segment_ids": [],
                    }
                ],
            }
        ],
        "conflicts": [],
        "missing_critical_fields": [],
    }


async def _ingest_one(attribute_code: str) -> str | None:
    db = _FakeIngestSession()
    await ingest_extraction_result(
        db,  # type: ignore[arg-type]
        tenant_id=new_uuid7(),
        exhibitor_id=new_uuid7(),
        document_id=new_uuid7(),
        ai_run_id=None,
        result=_result_with(attribute_code),
    )
    rows = [r for r in db.rows if getattr(r, "attribute_code", None) == attribute_code]
    assert len(rows) == 1
    return rows[0].visibility


async def test_ingesting_a_trade_condition_defaults_to_verified_buyer() -> None:
    assert await _ingest_one("trade.moq") == "VERIFIED_BUYER"


async def test_ingesting_product_price_defaults_to_verified_buyer() -> None:
    assert await _ingest_one("product.price_krw") == "VERIFIED_BUYER"


async def test_ingesting_a_public_attribute_still_defaults_to_public() -> None:
    assert await _ingest_one("company.description") == "PUBLIC"
