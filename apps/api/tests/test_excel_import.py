from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from app.main import app
from app.services.excel_import import (
    EXCEL_IMPORT_SCHEMA_VERSION,
    ExcelImportValidationError,
    parse_excel_import,
)
from fastapi.testclient import TestClient

FIXTURES = Path(__file__).parent / "fixtures"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _fixture(name: str) -> bytes:
    return (FIXTURES / name).read_bytes()


def test_valid_workbook_normalizes_both_sheets_to_canonical_import_rows() -> None:
    parsed = parse_excel_import(_fixture("excel-import-v1-valid.xlsx"))

    assert parsed.schema_version == EXCEL_IMPORT_SCHEMA_VERSION
    assert parsed.visitors.total_rows == 1
    assert len(parsed.visitors.rows) == 1
    assert parsed.visitors.errors == ()
    visitor = parsed.visitors.rows[0]
    assert visitor.source_record_id == "VISITOR-001"
    assert {item.attribute_code for item in visitor.interest_categories} == {
        "ALCOHOL.TAKJU",
        "TASTE.SWEET",
    }
    assert {item.attribute_code for item in visitor.visit_goals} == {
        "GOAL.TASTING",
        "GOAL.GIFT_SEARCH",
    }
    assert visitor.consent_registration is True
    assert visitor.consent_marketing is False
    assert visitor.age_19_plus is True

    assert parsed.exhibitors.total_rows == 1
    assert len(parsed.exhibitors.rows) == 1
    exhibitor = parsed.exhibitors.rows[0]
    assert exhibitor.source_record_id == "EXHIBITOR-001"
    assert exhibitor.region is not None
    assert exhibitor.region.attribute_code == "REGION.KR.SEOUL"
    assert [item.attribute_code for item in exhibitor.categories] == ["ALCOHOL.TAKJU"]


def test_unknown_code_is_isolated_without_echoing_the_cell_value() -> None:
    parsed = parse_excel_import(_fixture("excel-import-v1-unknown-code.xlsx"))

    assert len(parsed.visitors.rows) == 0
    assert len(parsed.visitors.errors) == 1
    error = parsed.visitors.errors[0]
    assert error.row_index == 2
    assert error.source_record_id is None
    assert error.error_code == "EXCEL_ONTOLOGY_CODE_UNKNOWN"
    assert "UNKNOWN.CODE" not in error.message
    assert len(parsed.exhibitors.rows) == 1


def test_formula_row_is_rejected_but_other_sheet_remains_valid() -> None:
    parsed = parse_excel_import(_fixture("excel-import-v1-formula.xlsx"))

    assert len(parsed.visitors.rows) == 1
    assert len(parsed.exhibitors.rows) == 0
    assert parsed.exhibitors.errors[0].source_record_id is None
    assert parsed.exhibitors.errors[0].error_code == "EXCEL_FORMULA_NOT_ALLOWED"


@pytest.mark.parametrize("payload", [b"", b"not-an-xlsx"])
def test_invalid_archive_fails_closed(payload: bytes) -> None:
    with pytest.raises(ExcelImportValidationError):
        parse_excel_import(payload)


def test_excel_endpoint_defaults_to_non_mutating_dry_run() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/admin/imports/excel",
        params={"tenant_id": str(uuid.uuid4()), "event_id": str(uuid.uuid4())},
        content=_fixture("excel-import-v1-valid.xlsx"),
        headers={"Content-Type": XLSX_MEDIA_TYPE},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["schema_version"] == EXCEL_IMPORT_SCHEMA_VERSION
    assert payload["status"] == "VALID"
    assert payload["dry_run"] is True
    assert payload["visitors"]["valid_rows"] == 1
    assert payload["exhibitors"]["valid_rows"] == 1
    assert payload["visitor_import"] is None
    assert payload["exhibitor_import"] is None


def test_excel_endpoint_rejects_ambiguous_content_type() -> None:
    client = TestClient(app)
    response = client.post(
        "/api/v1/admin/imports/excel",
        params={"tenant_id": str(uuid.uuid4()), "event_id": str(uuid.uuid4())},
        content=_fixture("excel-import-v1-valid.xlsx"),
        headers={"Content-Type": "application/octet-stream"},
    )

    assert response.status_code == 415
    assert response.json()["detail"] == "EXCEL_CONTENT_TYPE_UNSUPPORTED"
