"""`.harness/contracts/error-codes.yaml` parses, no duplicate codes.

CTR-004 had not landed at the time this file was written: error-codes.yaml is
still the `status: draft` / `codes: []` placeholder. Each entry is expected to
carry at least a `code` field (per the "VALIDATION_ERROR ~ INTERNAL_ERROR" style
naming used in `.harness/backlog.yaml` CTR-004's acceptance) - duplicate
detection is keyed on that field.
"""

from __future__ import annotations

import pytest
from _contracts import ERROR_CODES_PATH, load_yaml


def test_error_codes_yaml_parses():
    doc = load_yaml(ERROR_CODES_PATH)
    assert isinstance(doc, dict), "error-codes.yaml must parse to a YAML mapping"
    assert "codes" in doc, "error-codes.yaml is missing top-level 'codes'"


def test_no_duplicate_error_codes():
    doc = load_yaml(ERROR_CODES_PATH)
    codes = doc.get("codes") or []
    if not codes:
        pytest.skip(
            "error-codes.yaml has no codes yet (CTR-004 draft/placeholder state, "
            f"status={doc.get('status')!r}) - nothing to check; re-run once "
            "CTR-004 lands."
        )

    names: list[str] = []
    for entry in codes:
        code = entry.get("code") if isinstance(entry, dict) else None
        names.append(code if code else f"<unnamed code entry: {entry!r}>")

    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)

    assert not duplicates, f"duplicate error code(s) found: {sorted(duplicates)}"
