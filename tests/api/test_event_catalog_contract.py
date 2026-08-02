"""`.harness/contracts/event-catalog.yaml` parses, no duplicate event names.

CTR-005 had not landed at the time this file was written: event-catalog.yaml is
still the `status: draft` / `events: []` placeholder. Each event is expected to
carry at least a `name` field (per the "PROFILE.CONFIRMED ~ ADMIN.BOOTH_STATUS_
CHANGED" style naming used in `.harness/backlog.yaml` CTR-005's acceptance) -
duplicate detection is keyed on that field.
"""

from __future__ import annotations

import pytest
from _contracts import EVENT_CATALOG_PATH, load_yaml


def test_event_catalog_yaml_parses():
    doc = load_yaml(EVENT_CATALOG_PATH)
    assert isinstance(doc, dict), "event-catalog.yaml must parse to a YAML mapping"
    assert "events" in doc, "event-catalog.yaml is missing top-level 'events'"


def test_no_duplicate_event_names():
    doc = load_yaml(EVENT_CATALOG_PATH)
    events = doc.get("events") or []
    if not events:
        pytest.skip(
            "event-catalog.yaml has no events yet (CTR-005 draft/placeholder "
            f"state, status={doc.get('status')!r}) - nothing to check; re-run "
            "once CTR-005 lands."
        )

    names: list[str] = []
    for event in events:
        name = event.get("name") if isinstance(event, dict) else None
        names.append(name if name else f"<unnamed event: {event!r}>")

    seen: set[str] = set()
    duplicates: set[str] = set()
    for name in names:
        if name in seen:
            duplicates.add(name)
        seen.add(name)

    assert not duplicates, f"duplicate event name(s) found: {sorted(duplicates)}"
