"""Shared helpers for tests/api/** contract-validation tests (QAS-003).

This module is not a test module itself - pytest only collects `test_*.py` /
`*_test.py` by default - it just holds the small amount of YAML-loading /
JSON-pointer-resolution logic that every contract test in this directory reuses,
so each `test_*.py` file can stay focused on exactly one QAS-003 acceptance
criterion (see `.harness/backlog.yaml` QAS-003 and `.harness/handoffs/qa/QAS-003.md`
for the full mapping).

No relative imports are used anywhere in this directory on purpose: `tests/`
(and `tests/api/`) have no `__init__.py` in this repo (see `backend/tests/` for the
same convention), so pytest's default "prepend" import mode adds `tests/api/`
itself to `sys.path` and each test file is imported as a top-level module. A
relative import (`from . import _contracts`) would fail under that mode.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_DIR = REPO_ROOT / ".harness" / "contracts"

OPENAPI_PATH = CONTRACTS_DIR / "openapi.yaml"
ONTOLOGY_PATH = CONTRACTS_DIR / "ontology.yaml"
EVENT_CATALOG_PATH = CONTRACTS_DIR / "event-catalog.yaml"
ERROR_CODES_PATH = CONTRACTS_DIR / "error-codes.yaml"

HTTP_METHODS = {"get", "put", "post", "delete", "options", "head", "patch", "trace"}


def load_yaml(path: Path) -> Any:
    """Parse a YAML contract file. Raises the underlying yaml.YAMLError (with
    file/line context from PyYAML) straight through on syntax errors, which is
    exactly what we want a "syntax validity" test to fail loudly on."""

    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def is_success_status(status_key: str) -> bool:
    """OpenAPI response map keys look like '200', '404', '5XX', or 'default'.

    `default` is conventionally used as the catch-all *error* response in this
    kind of API (there is always an explicit 2xx per operation), so we do not
    treat it as a success status here.
    """

    key = str(status_key).strip().lower()
    if key == "default":
        return False
    return key.startswith("2")


def resolve_ref(root: dict, ref: str) -> Any:
    """Resolve a local JSON pointer `$ref` such as '#/components/schemas/Error'.

    Only local (same-document) refs are supported - this repo's contracts are
    meant to be self-contained single files. Missing segments raise
    KeyError/IndexError/TypeError, which callers turn into readable assertion
    failures rather than letting a raw traceback stand in for a report.
    """

    if not ref.startswith("#/"):
        raise ValueError(f"non-local $ref not supported by this checker: {ref}")
    node: Any = root
    for raw_segment in ref[2:].split("/"):
        segment = raw_segment.replace("~1", "/").replace("~0", "~")
        node = node[int(segment)] if isinstance(node, list) else node[segment]
    return node


def resolve_schema(root: dict, node: Any) -> Any:
    """If node is (or chains through) bare {'$ref': ...} wrappers, follow them."""

    seen: set[str] = set()
    while isinstance(node, dict) and "$ref" in node:
        ref = node["$ref"]
        if ref in seen:
            raise ValueError(f"circular $ref detected: {ref}")
        seen.add(ref)
        node = resolve_ref(root, ref)
    return node


def iter_refs(node: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    """Yield (json_path, ref_string) for every {'$ref': ...} found anywhere."""

    if isinstance(node, dict):
        ref = node.get("$ref")
        if isinstance(ref, str):
            yield f"{path}.$ref", ref
        for key, value in node.items():
            yield from iter_refs(value, f"{path}.{key}")
    elif isinstance(node, list):
        for idx, value in enumerate(node):
            yield from iter_refs(value, f"{path}[{idx}]")


def iter_operations(spec: dict) -> Iterator[tuple[str, str, dict]]:
    """Yield (path, method, operation_dict) for every operation in an OpenAPI doc."""

    for path, path_item in (spec.get("paths") or {}).items():
        if not isinstance(path_item, dict):
            continue
        for method, operation in path_item.items():
            if method.lower() not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            yield path, method, operation
