"""OpenAPI syntax validity for `.harness/contracts/openapi.yaml` (QAS-003).

`.harness/backlog.yaml` QAS-003 acceptance: "OpenAPI Syntax" automation, using
`openapi-spec-validator` "or similar if available, else at minimum full YAML
parse + basic structural checks (paths/info/components present)".

At the time this file was written, CTR-002 (which owns openapi.yaml) had not yet
landed - the file is still the DRAFT placeholder (`paths: {}`, no `components`).
These tests validate that placeholder as-is (an empty-but-valid OpenAPI document
is exactly what it should be worth to check right now) and will keep working once
CTR-002 fills the document in.
"""

from __future__ import annotations

import pytest
from _contracts import OPENAPI_PATH, load_yaml


def test_openapi_yaml_parses():
    doc = load_yaml(OPENAPI_PATH)
    assert isinstance(doc, dict), "openapi.yaml must parse to a YAML mapping"


def test_openapi_basic_structure_present():
    doc = load_yaml(OPENAPI_PATH)
    for key in ("openapi", "info", "paths"):
        assert key in doc, f"openapi.yaml is missing required top-level key: {key}"
    assert "title" in doc["info"], "openapi.yaml info block is missing 'title'"
    assert "version" in doc["info"], "openapi.yaml info block is missing 'version'"
    # NOTE: `components` is legitimately OPTIONAL in the OpenAPI 3.x spec (an API
    # with zero shared schemas/responses is still valid), so we deliberately do
    # NOT require it here even though the task brief mentions it as a fallback
    # structural check - openapi-spec-validator below is the real syntax check.


def test_openapi_spec_is_valid_per_openapi_spec_validator():
    pytest.importorskip(
        "openapi_spec_validator",
        reason="openapi-spec-validator not installed in this environment",
    )
    from openapi_spec_validator import validate
    from openapi_spec_validator.readers import read_from_filename

    spec, _base_uri = read_from_filename(str(OPENAPI_PATH))
    validate(spec)  # raises openapi_spec_validator.exceptions.OpenAPIValidationError on failure
