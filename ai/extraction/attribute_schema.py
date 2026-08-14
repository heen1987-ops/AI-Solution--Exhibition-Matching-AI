"""``ai/schemas/extraction/attribute_schema.json``(ALLOWED SCHEMA) 로더.

``src/meet_ai/ontology/catalog.py``의 ``load_catalog()``와 같은 철학 - 순수 함수, 프로세스당
1회 캐시(``AttributeSchema.load``), 파일이 계약을 어기면 즉시 예외.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "extraction" / "attribute_schema.json"

_VALID_DATA_TYPES = {"TEXT", "TEXT_LIST", "NUMBER", "BOOLEAN", "ENUM", "CODE", "CODE_LIST"}


class AttributeSchemaError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = tuple(errors)
        super().__init__("\n".join(self.errors))


@dataclass(frozen=True)
class AttributeDefinition:
    attribute_code: str
    applies_to: tuple[str, ...]
    data_type: str
    trade_condition: bool
    critical: bool
    allowed_concept_types: tuple[str, ...]
    description_ko: str
    allowed_values: tuple[str, ...] = ()

    def accepts_entity_type(self, entity_type: str) -> bool:
        return entity_type in self.applies_to


class AttributeSchema:
    def __init__(self, payload: dict[str, Any]):
        self.metadata = payload.get("metadata", {})
        self._by_code: dict[str, AttributeDefinition] = {}
        errors: list[str] = []
        for item in payload.get("attributes", ()):
            code = item.get("attribute_code", "")
            if not code:
                errors.append("attribute missing attribute_code")
                continue
            if code in self._by_code:
                errors.append(f"duplicate attribute_code: {code}")
                continue
            data_type = item.get("data_type", "")
            if data_type not in _VALID_DATA_TYPES:
                errors.append(f"invalid data_type for {code}: {data_type!r}")
            applies_to = tuple(item.get("applies_to", ()))
            if not applies_to:
                errors.append(f"attribute {code} has empty applies_to")
            self._by_code[code] = AttributeDefinition(
                attribute_code=code,
                applies_to=applies_to,
                data_type=data_type,
                trade_condition=bool(item.get("trade_condition", False)),
                critical=bool(item.get("critical", False)),
                allowed_concept_types=tuple(item.get("allowed_concept_types", ())),
                description_ko=str(item.get("description_ko", "")),
                allowed_values=tuple(item.get("allowed_values", ())),
            )
        if errors:
            raise AttributeSchemaError(errors)

    def get(self, attribute_code: str) -> AttributeDefinition | None:
        return self._by_code.get(attribute_code)

    def all(self) -> tuple[AttributeDefinition, ...]:
        return tuple(self._by_code.values())

    def for_entity_type(self, entity_type: str) -> tuple[AttributeDefinition, ...]:
        return tuple(d for d in self._by_code.values() if d.accepts_entity_type(entity_type))

    def critical_for_entity_type(self, entity_type: str) -> tuple[AttributeDefinition, ...]:
        return tuple(d for d in self.for_entity_type(entity_type) if d.critical)


@lru_cache(maxsize=1)
def load_attribute_schema(path: str | Path | None = None) -> AttributeSchema:
    target = Path(path) if path is not None else _SCHEMA_PATH
    payload = json.loads(target.read_text(encoding="utf-8"))
    return AttributeSchema(payload)
