"""Every $ref in openapi.yaml resolves within the document (QAS-003 acceptance).

Only local same-document refs (`#/components/...`) are expected in this repo's
contracts (they are meant to be single self-contained files), so any $ref found
is resolved as a JSON pointer against the already-parsed document.
"""

from __future__ import annotations

import pytest
from _contracts import OPENAPI_PATH, iter_refs, load_yaml, resolve_ref


def test_all_schema_refs_resolve_within_the_document():
    spec = load_yaml(OPENAPI_PATH)
    refs = list(iter_refs(spec))
    if not refs:
        pytest.skip(
            "openapi.yaml has no $ref usages yet (CTR-002 draft/placeholder "
            "state, paths: {} / no components) - nothing to check; re-run once "
            "CTR-002 lands."
        )

    unresolved: list[str] = []
    for json_path, ref in refs:
        try:
            resolve_ref(spec, ref)
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            unresolved.append(f"{json_path} -> {ref} ({exc})")

    assert not unresolved, "unresolved $ref(s) found:\n" + "\n".join(unresolved)
