"""`.harness/contracts/ontology.yaml` parses and every code has required fields.

Required per-code fields come straight from `.harness/backlog.yaml` CTR-003
acceptance ("코드별 한국어/영어 라벨·설명·상위코드·동의어·상태·버전 필드 정의" -
Korean/English label, description, parent code, synonyms, status, version) and
this task's own instructions (label ko/en, description, parent code reference
validity, status, version).

CTR-003 had not landed at the time this file was written: `ontology.yaml` is
still the `status: draft` / `categories: []` placeholder. The exact nesting shape
CTR-003 will use for "codes" is CTR-003's decision, not something this file can
know in advance - `_iter_category_codes` below encodes a best-effort guess
(`categories: [{codes: [...]}]`, one flat list of code objects per category, each
carrying `code`/`label_ko`/`label_en`/`description`/`parent`/`status`/`version`)
based on the field list in the acceptance criterion above. If CTR-003 lands with
a materially different shape, `_iter_category_codes` (and this test) will need a
follow-up update - this is called out explicitly in the QAS-003 handoff so it
isn't missed.

Until then, `test_ontology_codes_have_required_fields` SKIPS rather than
reporting a false PASS, since there is currently nothing to validate.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from _contracts import ONTOLOGY_PATH, load_yaml

REQUIRED_CODE_FIELDS = {"label_ko", "label_en", "description", "status", "version"}


def _iter_category_codes(doc: dict) -> Iterator[tuple[Any, Any]]:
    for category in doc.get("categories") or []:
        if not isinstance(category, dict):
            continue
        for code in category.get("codes") or []:
            yield category, code


def test_ontology_yaml_parses():
    doc = load_yaml(ONTOLOGY_PATH)
    assert isinstance(doc, dict), "ontology.yaml must parse to a YAML mapping"
    assert "status" in doc, "ontology.yaml is missing top-level 'status'"
    assert "categories" in doc, "ontology.yaml is missing top-level 'categories'"


def test_ontology_codes_have_required_fields_and_valid_parent_refs():
    doc = load_yaml(ONTOLOGY_PATH)
    entries = list(_iter_category_codes(doc))
    if not entries:
        pytest.skip(
            "ontology.yaml categories are still empty (CTR-003 draft/placeholder "
            f"state, status={doc.get('status')!r}) - no codes to validate yet; "
            "re-run once CTR-003 lands."
        )

    known_codes = {
        code.get("code") for _cat, code in entries if isinstance(code, dict)
    }

    violations: list[str] = []
    for category, code in entries:
        if not isinstance(code, dict):
            violations.append(
                f"non-mapping code entry in category {category!r}: {code!r}"
            )
            continue

        code_id = code.get("code", "<code field missing>")
        missing = REQUIRED_CODE_FIELDS - set(code.keys())
        if missing:
            violations.append(f"{code_id}: missing field(s) {sorted(missing)}")

        parent = code.get("parent")
        if parent is not None and parent not in known_codes:
            violations.append(
                f"{code_id}: parent '{parent}' does not reference a known code"
            )

    assert not violations, "ontology code validation failure(s):\n" + "\n".join(
        violations
    )
