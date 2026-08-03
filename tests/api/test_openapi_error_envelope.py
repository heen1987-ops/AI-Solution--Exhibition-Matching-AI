"""Every non-2xx response follows {error:{code,message,request_id,details}}.

This exact envelope shape is not invented by this test - it is quoted verbatim
from `.harness/backlog.yaml` CTR-002 acceptance ("오류 응답은
{error:{code,message,request_id,details}} 구조로 통일") and repeated in this
task's own instructions, so CONTRACTS and QA_SECURITY are checking against the
same source of truth.

Note this differs from the older `docs/frontend-backend-ai-interface-spec.md`
§4.4 example (which nests `request_id` under a top-level `meta` object instead of
inside `error`) - that doc predates the harness-era CTR-002 acceptance criterion
quoted above, which is the authoritative target for the contract CONTRACTS is
building now.
"""

from __future__ import annotations

import pytest
from _contracts import (
    OPENAPI_PATH,
    is_success_status,
    iter_operations,
    load_yaml,
    resolve_schema,
)

REQUIRED_ERROR_FIELDS = {"code", "message", "request_id", "details"}


def _properties(schema: dict) -> set[str]:
    return set((schema.get("properties") or {}).keys())


# resolve_schema() raises these when a $ref does not resolve. This test does not
# duplicate test_openapi_schema_refs.py's job of reporting *which* ref is broken -
# it just needs to fail cleanly (as a normal assertion violation) instead of
# crashing with a raw traceback when it walks through one.
_REF_RESOLUTION_ERRORS = (KeyError, IndexError, TypeError, ValueError)


def test_non_2xx_responses_use_the_error_envelope_shape():
    spec = load_yaml(OPENAPI_PATH)

    checked: list[str] = []
    violations: list[str] = []

    for path, method, operation in iter_operations(spec):
        responses = operation.get("responses") or {}
        for status_key, response in responses.items():
            if is_success_status(status_key):
                continue
            location = f"{method.upper()} {path} -> {status_key}"

            try:
                response = resolve_schema(spec, response or {})
            except _REF_RESOLUTION_ERRORS as exc:
                violations.append(f"{location}: unresolved $ref on response ({exc})")
                continue
            content = (response or {}).get("content") or {}
            media = content.get("application/json")
            if media is None:
                violations.append(f"{location}: no application/json content defined")
                continue
            schema = media.get("schema")
            if schema is None:
                violations.append(f"{location}: application/json content has no schema")
                continue
            try:
                schema = resolve_schema(spec, schema)
            except _REF_RESOLUTION_ERRORS as exc:
                violations.append(f"{location}: unresolved $ref on response schema ({exc})")
                continue
            checked.append(location)

            properties = _properties(schema)
            if "error" not in properties:
                violations.append(
                    f"{location}: response schema has no top-level 'error' property"
                )
                continue

            try:
                error_schema = resolve_schema(spec, schema["properties"]["error"])
            except _REF_RESOLUTION_ERRORS as exc:
                violations.append(f"{location}: unresolved $ref on 'error' property ({exc})")
                continue
            missing = REQUIRED_ERROR_FIELDS - _properties(error_schema)
            if missing:
                violations.append(
                    f"{location}: error object missing field(s) {sorted(missing)}"
                )

    if not checked and not violations:
        pytest.skip(
            "openapi.yaml defines no non-2xx responses yet (CTR-002 draft/"
            "placeholder state, paths: {}) - nothing to check; re-run once "
            "CTR-002 lands."
        )

    assert not violations, "error envelope violation(s):\n" + "\n".join(violations)
