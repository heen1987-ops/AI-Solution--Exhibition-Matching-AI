from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
EVENT_CATALOG = ROOT / ".harness/contracts/event-catalog.yaml"
FORBIDDEN_PAYLOAD_FIELDS = {
    "email",
    "phone",
    "tel",
    "mobile",
    "address",
    "name",
    "business_email",
    "message",
    "message_text",
    "query_text",
    "raw_text",
}


def test_event_catalog_payloads_do_not_include_direct_personal_data() -> None:
    catalog = yaml.safe_load(EVENT_CATALOG.read_text(encoding="utf-8"))
    violations: list[str] = []

    for event in catalog["events"]:
        fields = event.get("payload_fields") or []
        for field in fields:
            normalized = str(field).lower()
            if normalized in FORBIDDEN_PAYLOAD_FIELDS:
                violations.append(f"{event['name']} payload_fields includes {field}")

    assert violations == []
