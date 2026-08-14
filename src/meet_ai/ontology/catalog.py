from __future__ import annotations

import json
import re
import unicodedata
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from decimal import Decimal
from importlib.resources import files
from pathlib import Path
from typing import Any

CODE_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*(?:\.[A-Z][A-Z0-9_]*)+$")
ALLOWED_DATA_TYPES = {"CODE", "NUMBER", "BOOLEAN", "TEXT"}
ALLOWED_RELATIONS = {
    "IS_A",
    "RELATED_TO",
    "MATCHES_GOAL",
    "SIMILAR_TO",
    "COMPLEMENTS",
    "CONFLICTS_WITH",
}
ALLOWED_MAPPING_TYPES = {"EXACT", "BROAD", "NARROW", "RELATED"}
CANONICAL_EVENTS = {
    "SERVICE_STARTED",
    "USER_TYPE_SELECTED",
    "CONSENT_CHOICE_RECORDED",
    "PROFILE_QUESTION_VIEWED",
    "PROFILE_ANSWER_SELECTED",
    "PROFILE_QUESTION_SKIPPED",
    "MINIMUM_PROFILE_COMPLETED",
    "RECOMMENDATION_IMPRESSION",
    "RECOMMENDATION_OPENED",
    "RECOMMENDATION_SAVED",
    "RECOMMENDATION_DISMISSED",
    "ROUTE_ITEM_ADDED",
    "ROUTE_STARTED",
    "BOOTH_CHECKED_IN",
    "VISIT_OUTCOME_SELECTED",
    "FEEDBACK_SUBMITTED",
    "MEETING_REQUEST_STARTED",
    "MEETING_REQUEST_SUBMITTED",
    "MEETING_REQUEST_DECIDED",
    "MEETING_COMPLETED",
}

_UUID_NAMESPACE = uuid.UUID("148b8598-0217-4c9b-acb7-d3a413f9bf5c")


class CatalogValidationError(ValueError):
    """Raised when the ontology catalog violates its published contract."""

    def __init__(self, errors: Iterable[str]):
        self.errors = tuple(errors)
        super().__init__("\n".join(self.errors))


@dataclass(frozen=True)
class SynonymMatch:
    concept_code: str
    priority: int
    context: str
    locale: str


def normalize_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(normalized.split())


def stable_uuid(kind: str, value: str) -> uuid.UUID:
    return uuid.uuid5(_UUID_NAMESPACE, f"{kind}:{value}")


class Catalog:
    def __init__(self, payload: dict[str, Any]):
        self.payload = payload
        self.metadata = payload.get("metadata", {})
        self.concepts = tuple(payload.get("concepts", ()))
        self.synonyms = tuple(payload.get("synonyms", ()))
        self.relations = tuple(payload.get("relations", ()))
        self.event_mappings = tuple(payload.get("event_mappings", ()))
        self.derived_bands = tuple(payload.get("derived_bands", ()))
        self.by_code = {item["code"]: item for item in self.concepts if "code" in item}

    @property
    def version(self) -> str:
        return str(self.metadata.get("version", ""))

    def validate(self) -> None:
        errors: list[str] = []
        self._validate_metadata(errors)
        self._validate_concepts(errors)
        self._validate_synonyms(errors)
        self._validate_relations(errors)
        self._validate_event_mappings(errors)
        self._validate_bands(errors)
        if errors:
            raise CatalogValidationError(errors)

    def _validate_metadata(self, errors: list[str]) -> None:
        if not re.fullmatch(r"\d+\.\d+\.\d+", self.version):
            errors.append("metadata.version must be semantic version X.Y.Z")
        if self.metadata.get("status") not in {
            "DRAFT",
            "REVIEW",
            "PUBLISHED",
            "RETIRED",
        }:
            errors.append("metadata.status is invalid")
        requirement_levels = set(self.metadata.get("requirement_levels", ()))
        if requirement_levels != {"REQUIRED", "PREFERRED", "ACCEPTABLE", "EXCLUDED"}:
            errors.append(
                "requirement_levels must not mix UNKNOWN with preference semantics"
            )
        knowledge_states = set(self.metadata.get("knowledge_states", ()))
        if knowledge_states != {"KNOWN", "UNKNOWN", "NOT_APPLICABLE"}:
            errors.append("knowledge_states must be KNOWN, UNKNOWN, NOT_APPLICABLE")

    def _validate_concepts(self, errors: list[str]) -> None:
        seen: set[str] = set()
        for item in self.concepts:
            code = item.get("code", "")
            if not CODE_PATTERN.fullmatch(code) or len(code) > 100:
                errors.append(f"invalid concept code: {code!r}")
            if code in seen:
                errors.append(f"duplicate concept code: {code}")
            seen.add(code)
            if not item.get("label_ko"):
                errors.append(f"missing Korean label: {code}")
            if item.get("data_type", "CODE") not in ALLOWED_DATA_TYPES:
                errors.append(f"invalid data_type: {code}")

        for item in self.concepts:
            code = item.get("code", "")
            parent = item.get("parent")
            if parent and parent not in self.by_code:
                errors.append(f"missing parent {parent} for {code}")
            elif parent and self.by_code[parent].get("concept_type") != item.get(
                "concept_type"
            ):
                errors.append(f"parent type mismatch: {parent} -> {code}")

        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(code: str) -> None:
            if code in visiting:
                errors.append(f"concept hierarchy cycle at {code}")
                return
            if code in visited:
                return
            visiting.add(code)
            parent = self.by_code.get(code, {}).get("parent")
            if parent in self.by_code:
                visit(parent)
            visiting.remove(code)
            visited.add(code)

        for code in self.by_code:
            visit(code)

    def _validate_synonyms(self, errors: list[str]) -> None:
        seen: set[tuple[str, str, str, str]] = set()
        for item in self.synonyms:
            target = item.get("concept_code", "")
            if target not in self.by_code:
                errors.append(f"synonym target does not exist: {target}")
            text = normalize_text(str(item.get("text", "")))
            if not text:
                errors.append(f"empty synonym for {target}")
            key = (
                text,
                item.get("locale", "ko-KR"),
                item.get("context", "ANY"),
                target,
            )
            if key in seen:
                errors.append(f"duplicate synonym mapping: {key}")
            seen.add(key)

    def _validate_relations(self, errors: list[str]) -> None:
        for item in self.relations:
            source = item.get("source")
            target = item.get("target")
            relation_type = item.get("type")
            if source not in self.by_code:
                errors.append(f"relation source does not exist: {source}")
            if target not in self.by_code:
                errors.append(f"relation target does not exist: {target}")
            if relation_type not in ALLOWED_RELATIONS:
                errors.append(f"invalid relation type: {relation_type}")
            weight = Decimal(str(item.get("weight", 1)))
            if weight < 0 or weight > 1:
                errors.append(f"relation weight outside 0..1: {source} -> {target}")

    def _validate_event_mappings(self, errors: list[str]) -> None:
        for item in self.event_mappings:
            concept_code = item.get("concept_code")
            event_type = item.get("event_type")
            if concept_code not in self.by_code:
                errors.append(f"event mapping concept does not exist: {concept_code}")
            if event_type not in CANONICAL_EVENTS:
                errors.append(
                    f"event mapping is not in interface contract: {event_type}"
                )

    def _validate_bands(self, errors: list[str]) -> None:
        for definition in self.derived_bands:
            bands = definition.get("bands", ())
            previous: dict[str, Any] | None = None
            for band in bands:
                code = band.get("code")
                if code not in self.by_code:
                    errors.append(f"derived band concept does not exist: {code}")
                minimum = _decimal_or_none(band.get("min"))
                maximum = _decimal_or_none(band.get("max"))
                if minimum is not None and maximum is not None and minimum > maximum:
                    errors.append(f"invalid band bounds: {code}")
                if previous is not None:
                    previous_max = _decimal_or_none(previous.get("max"))
                    if (
                        previous_max is None
                        or minimum is None
                        or previous_max != minimum
                    ):
                        errors.append(f"band gap or unordered boundary before {code}")
                    elif bool(previous.get("max_inclusive")) == bool(
                        band.get("min_inclusive")
                    ):
                        errors.append(
                            f"band boundary must belong to exactly one range: {code}"
                        )
                previous = band

    def get(self, code: str) -> dict[str, Any]:
        try:
            return self.by_code[code]
        except KeyError as exc:
            raise KeyError(f"unknown ontology code: {code}") from exc

    def ancestors(self, code: str) -> tuple[str, ...]:
        current = self.get(code)
        result: list[str] = []
        while current.get("parent"):
            parent = str(current["parent"])
            result.append(parent)
            current = self.get(parent)
        return tuple(result)

    def resolve_synonym(
        self, text: str, *, locale: str = "ko-KR", context: str = "ANY"
    ) -> tuple[SynonymMatch, ...]:
        normalized = normalize_text(text)
        matches = []
        for item in self.synonyms:
            item_context = item.get("context", "ANY")
            if normalize_text(item.get("text", "")) != normalized:
                continue
            if item.get("locale", "ko-KR") != locale:
                continue
            if item_context not in {"ANY", context}:
                continue
            matches.append(
                SynonymMatch(
                    concept_code=item["concept_code"],
                    priority=int(item.get("priority", 100)),
                    context=item_context,
                    locale=locale,
                )
            )
        return tuple(
            sorted(matches, key=lambda item: (item.priority, item.concept_code))
        )

    def derive_band(self, metric: str, value: float | Decimal) -> str:
        numeric = Decimal(str(value))
        definition = next(
            (item for item in self.derived_bands if item.get("metric") == metric), None
        )
        if definition is None:
            raise KeyError(f"unknown derived metric: {metric}")
        for band in definition.get("bands", ()):
            if _contains(band, numeric):
                return str(band["code"])
        raise ValueError(f"{metric} value outside catalog range: {value}")

    def match_strength(
        self, requested: str, offered: str, *, ancestor_decay: Decimal = Decimal("0.9")
    ) -> Decimal:
        self.get(requested)
        self.get(offered)
        if requested == offered:
            return Decimal(1)
        offered_ancestors = self.ancestors(offered)
        if requested in offered_ancestors:
            distance = offered_ancestors.index(requested) + 1
            return ancestor_decay**distance
        related = [
            item
            for item in self.relations
            if item.get("source") == requested and item.get("target") == offered
        ]
        if related:
            return max(Decimal(str(item.get("weight", 0))) for item in related)
        return Decimal(0)


def _decimal_or_none(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _contains(band: dict[str, Any], value: Decimal) -> bool:
    minimum = _decimal_or_none(band.get("min"))
    maximum = _decimal_or_none(band.get("max"))
    if minimum is not None and (
        value < minimum or (value == minimum and not band.get("min_inclusive", False))
    ):
        return False
    return not (
        maximum is not None
        and (
            value > maximum
            or (value == maximum and not band.get("max_inclusive", False))
        )
    )


def load_catalog(path: str | Path | None = None, *, validate: bool = True) -> Catalog:
    if path is None:
        catalog_path = files("meet_ai.ontology").joinpath("catalog.v1.json")
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    else:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    catalog = Catalog(payload)
    if validate:
        catalog.validate()
    return catalog


def emit_postgres_seed(catalog: Catalog) -> str:
    """Build deterministic SQL for the canonical JSON catalog.

    The migration creates structure; this output is applied once per semantic
    version and publishes the version only after all rows are inserted.
    """

    catalog.validate()
    version_id = stable_uuid("taxonomy-version", catalog.version)
    lines = [
        "BEGIN;",
        "",
        "INSERT INTO ontology.taxonomy_version",
        "  (taxonomy_version_id, semantic_version, status, default_locale, checksum)",
        "VALUES",
        f"  ('{version_id}', {_sql(catalog.version)}, 'DRAFT', {_sql(catalog.metadata.get('default_locale', 'ko-KR'))},",
        f"   decode(md5({_sql(json.dumps(catalog.payload, ensure_ascii=False, sort_keys=True))}), 'hex'))",
        "ON CONFLICT (semantic_version) DO NOTHING;",
        "",
    ]
    for item in catalog.concepts:
        concept_id = stable_uuid("concept", item["code"])
        lines.extend(
            [
                "INSERT INTO ontology.concept",
                "  (concept_id, concept_code, concept_type, data_type, unit_code)",
                "VALUES",
                f"  ('{concept_id}', {_sql(item['code'])}, {_sql(item['concept_type'])}, {_sql(item.get('data_type', 'CODE'))}, {_sql(item.get('unit'))})",
                "ON CONFLICT (concept_code) DO NOTHING;",
            ]
        )
    lines.append("")
    for item in catalog.concepts:
        concept_id = stable_uuid("concept", item["code"])
        parent_id = (
            stable_uuid("concept", item["parent"]) if item.get("parent") else None
        )
        lines.extend(
            [
                "INSERT INTO ontology.concept_revision",
                "  (taxonomy_version_id, concept_id, parent_concept_id, assignable, status, sort_order, validation_json)",
                "VALUES",
                f"  ('{version_id}', '{concept_id}', {_sql_uuid(parent_id)}, {_sql_bool(item.get('assignable', True))}, 'ACTIVE', {int(item.get('sort_order', 0))}, {_sql_json(item.get('validation', {}))})",
                "ON CONFLICT (taxonomy_version_id, concept_id) DO NOTHING;",
                "INSERT INTO ontology.concept_label",
                "  (taxonomy_version_id, concept_id, locale, display_name, description)",
                "VALUES",
                f"  ('{version_id}', '{concept_id}', 'ko-KR', {_sql(item['label_ko'])}, {_sql(item.get('description'))})",
                "ON CONFLICT (taxonomy_version_id, concept_id, locale) DO NOTHING;",
            ]
        )
    for item in catalog.synonyms:
        concept_id = stable_uuid("concept", item["concept_code"])
        synonym_id = stable_uuid(
            "synonym",
            "|".join(
                [
                    catalog.version,
                    item.get("locale", "ko-KR"),
                    item.get("context", "ANY"),
                    normalize_text(item["text"]),
                    item["concept_code"],
                ]
            ),
        )
        lines.extend(
            [
                "INSERT INTO ontology.concept_synonym",
                "  (synonym_id, taxonomy_version_id, concept_id, locale, synonym_text, normalized_text, context_type, priority, approval_status, source_type)",
                "VALUES",
                f"  ('{synonym_id}', '{version_id}', '{concept_id}', {_sql(item.get('locale', 'ko-KR'))}, {_sql(item['text'])}, {_sql(normalize_text(item['text']))}, {_sql(item.get('context', 'ANY'))}, {int(item.get('priority', 100))}, 'APPROVED', {_sql(item.get('source', 'CURATED'))})",
                "ON CONFLICT (synonym_id) DO NOTHING;",
            ]
        )
    for item in catalog.relations:
        source_id = stable_uuid("concept", item["source"])
        target_id = stable_uuid("concept", item["target"])
        relation_id = stable_uuid(
            "relation",
            f"{catalog.version}|{item['source']}|{item['type']}|{item['target']}",
        )
        lines.extend(
            [
                "INSERT INTO ontology.concept_relation",
                "  (relation_id, taxonomy_version_id, source_concept_id, relation_type, target_concept_id, semantic_weight, rule_json, status)",
                "VALUES",
                f"  ('{relation_id}', '{version_id}', '{source_id}', {_sql(item['type'])}, '{target_id}', {Decimal(str(item.get('weight', 1)))}, {_sql_json(item.get('rule', {}))}, 'ACTIVE')",
                "ON CONFLICT (relation_id) DO NOTHING;",
            ]
        )
    lines.extend(
        [
            "",
            "UPDATE ontology.taxonomy_version",
            "SET status = 'PUBLISHED', published_at = COALESCE(published_at, now())",
            f"WHERE taxonomy_version_id = '{version_id}' AND status = 'DRAFT';",
            "",
            "COMMIT;",
            "",
        ]
    )
    return "\n".join(lines)


def _sql(value: Any) -> str:
    if value is None:
        return "NULL"
    return "'" + str(value).replace("'", "''") + "'"


def _sql_uuid(value: uuid.UUID | None) -> str:
    return "NULL" if value is None else f"'{value}'"


def _sql_bool(value: bool) -> str:
    return "TRUE" if value else "FALSE"


def _sql_json(value: Any) -> str:
    return _sql(json.dumps(value, ensure_ascii=False, sort_keys=True)) + "::jsonb"
