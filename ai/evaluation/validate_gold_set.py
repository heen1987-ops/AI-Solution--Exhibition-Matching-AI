#!/usr/bin/env python
"""AIS-001 Gold Set 검증 스크립트.

`ai/evaluation/queries/*.jsonl`/`ai/evaluation/expected/*.jsonl`이 실제로
1) 각자의 JSON Schema(`ai/evaluation/schemas/*.json`)를 만족하는지,
2) queries<->expected 간 id가 1:1로 대응하는지,
3) 모든 concept_code가 실제 온톨로지 카탈로그(`src/meet_ai/ontology/catalog.v1.json`)에
   존재하고 assignable(구조 헤더가 아님)한지
를 실제로 검사한다 - 손으로 채운 Gold Set이 스스로 어긋나지 않았는지 기계적으로
확인하기 위한 것이다(이 스크립트 자체가 실제로 실행되어 통과했다는 사실이
AIS-001 핸드오프의 TESTED 근거다).

실행: `python ai/evaluation/validate_gold_set.py`
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

_THIS_DIR = Path(__file__).resolve().parent
_REPO_ROOT = _THIS_DIR.parent.parent

sys.path.insert(0, str(_REPO_ROOT / "src"))
from meet_ai.ontology.catalog import load_catalog

QUERY_FILES = {
    "queries/guest-web-ko.jsonl": "schemas/query-sample.schema.json",
    "queries/consumer-ko.jsonl": "schemas/query-sample.schema.json",
    "queries/buyer-ko.jsonl": "schemas/query-sample.schema.json",
    "queries/multilingual.jsonl": "schemas/query-sample.schema.json",
}
EXPECTED_FILES = {
    "expected/intent.jsonl": "schemas/expected-intent.schema.json",
    "expected/ontology-mapping.jsonl": "schemas/expected-ontology-mapping.schema.json",
    "expected/search-relevance.jsonl": "schemas/expected-search-relevance.schema.json",
}


def _load_jsonl(relative_path: str) -> list[dict]:
    path = _THIS_DIR / relative_path
    records = []
    with path.open(encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError as exc:
                raise SystemExit(f"{relative_path}:{line_number} invalid JSON: {exc}") from exc
    return records


def _load_schema(relative_path: str) -> dict:
    path = _THIS_DIR / relative_path
    return json.loads(path.read_text(encoding="utf-8"))


def _all_concept_codes(record: dict) -> set[str]:
    codes: set[str] = set()
    for key in (
        "required_concept_codes",
        "preferred_concept_codes",
        "excluded_concept_codes",
        "aspirational_concept_codes_via_llm",
    ):
        codes.update(record.get(key, []) or [])
    return codes


def main() -> int:
    errors: list[str] = []

    catalog = load_catalog()
    assignable_codes = {
        code for code, item in catalog.by_code.items() if item.get("assignable", True)
    }

    query_records: dict[str, dict] = {}
    for relative_path, schema_path in QUERY_FILES.items():
        schema = _load_schema(schema_path)
        records = _load_jsonl(relative_path)
        for record in records:
            try:
                jsonschema.validate(record, schema)
            except jsonschema.ValidationError as exc:
                errors.append(f"{relative_path}: schema violation ({record.get('id')}): {exc.message}")
                continue
            record_id = record["id"]
            if record_id in query_records:
                errors.append(f"{relative_path}: duplicate id {record_id!r}")
            query_records[record_id] = record

            for code in _all_concept_codes(record):
                if code not in catalog.by_code:
                    errors.append(
                        f"{relative_path} [{record_id}]: unknown ontology code {code!r}"
                    )
                elif code not in assignable_codes:
                    errors.append(
                        f"{relative_path} [{record_id}]: code {code!r} is a "
                        "non-assignable structural header and cannot be used as a condition"
                    )

    expected_records: dict[str, dict[str, dict]] = {}
    for relative_path, schema_path in EXPECTED_FILES.items():
        schema = _load_schema(schema_path)
        records = _load_jsonl(relative_path)
        by_id: dict[str, dict] = {}
        for record in records:
            try:
                jsonschema.validate(record, schema)
            except jsonschema.ValidationError as exc:
                errors.append(
                    f"{relative_path}: schema violation ({record.get('query_id')}): {exc.message}"
                )
                continue
            query_id = record["query_id"]
            if query_id in by_id:
                errors.append(f"{relative_path}: duplicate query_id {query_id!r}")
            by_id[query_id] = record

            for code in _all_concept_codes(
                {
                    "required_concept_codes": record.get("required_concept_codes", []),
                    "preferred_concept_codes": record.get("preferred_concept_codes", []),
                    "excluded_concept_codes": record.get("excluded_concept_codes", []),
                    "aspirational_concept_codes_via_llm": record.get(
                        "aspirational_concept_codes_via_llm", []
                    ),
                }
            ):
                if code not in catalog.by_code:
                    errors.append(
                        f"{relative_path} [{query_id}]: unknown ontology code {code!r}"
                    )
                elif code not in assignable_codes:
                    errors.append(
                        f"{relative_path} [{query_id}]: code {code!r} is a "
                        "non-assignable structural header and cannot be used as a condition"
                    )
        expected_records[relative_path] = by_id

    query_ids = set(query_records)
    for relative_path, by_id in expected_records.items():
        expected_ids = set(by_id)
        missing_in_expected = query_ids - expected_ids
        extra_in_expected = expected_ids - query_ids
        for missing_id in sorted(missing_in_expected):
            errors.append(f"{relative_path}: missing entry for query id {missing_id!r}")
        for extra_id in sorted(extra_in_expected):
            errors.append(f"{relative_path}: entry for unknown query id {extra_id!r}")

    total_queries = len(query_records)
    total_expected_files = len(expected_records)

    if errors:
        print(f"FAIL - {len(errors)} problem(s) found across {total_queries} query samples:")
        for error in errors:
            print(f"  - {error}")
        return 1

    print(
        f"PASS - {total_queries} query samples across {len(QUERY_FILES)} files, "
        f"cross-checked against {total_expected_files} expected/*.jsonl files and "
        f"{len(catalog.by_code)} real ontology concept codes "
        f"({len(assignable_codes)} assignable). 0 schema violations, 0 unknown/invented "
        "concept codes, 0 id mismatches."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
