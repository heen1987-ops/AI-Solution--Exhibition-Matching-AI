"""operationId uniqueness across all paths in openapi.yaml (QAS-003 acceptance).

`.harness/backlog.yaml` CTR-002 also requires "operationId 중복 없음" (no duplicate
operationId) directly, so this doubles as an early warning for CONTRACTS once
paths start landing.
"""

from __future__ import annotations

import pytest
from _contracts import OPENAPI_PATH, iter_operations, load_yaml


def test_every_operation_has_an_operation_id_and_ids_are_unique():
    spec = load_yaml(OPENAPI_PATH)
    operations = list(iter_operations(spec))
    if not operations:
        pytest.skip(
            "openapi.yaml has no paths yet (CTR-002 draft/placeholder state, "
            "paths: {}) - nothing to check; re-run once CTR-002 lands."
        )

    seen: dict[str, list[str]] = {}
    missing_operation_id: list[str] = []
    for path, method, operation in operations:
        location = f"{method.upper()} {path}"
        operation_id = operation.get("operationId")
        if not operation_id:
            missing_operation_id.append(location)
            continue
        seen.setdefault(operation_id, []).append(location)

    assert not missing_operation_id, (
        "every operation must declare operationId, missing at: "
        + ", ".join(missing_operation_id)
    )

    duplicates = {op_id: locs for op_id, locs in seen.items() if len(locs) > 1}
    assert not duplicates, f"duplicate operationId value(s) found: {duplicates}"
