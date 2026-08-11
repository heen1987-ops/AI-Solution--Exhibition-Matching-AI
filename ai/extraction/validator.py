"""모델이 반환한 원시 JSON을 신뢰하지 않고 다시 검증·정제해 ``ExtractionResult``로 바꾸는
계층. 이 파일이 이 트랙의 핵심 안전장치다 - 프롬프트가 아무리 잘 쓰였어도 모델 출력을 그대로
믿지 않는다(AGENTS.md 절대 규칙 "Validate all AI output against a JSON Schema before use" +
"AI must never assert a value the source text does not contain").

버려지는 모든 항목은 이유(``ValidationIssue``)와 함께 기록되어 감사 가능하다 - 조용히
사라지는 데이터가 없다.
"""

from __future__ import annotations

import json
import re
from collections import defaultdict
from typing import Any

from ai.extraction.attribute_schema import AttributeSchema
from ai.extraction.grounding import (
    has_lexical_support,
    is_unreliable_hedge,
    looks_like_injection,
)
from ai.extraction.ontology_support import concept_label, is_valid_concept_code
from ai.extraction.types import (
    ENTITY_TYPES,
    FACT_TYPES,
    ISSUE_AUTO_DETECTED_CONFLICT,
    ISSUE_AUTO_DETECTED_MISSING_CRITICAL_FIELD,
    ISSUE_HEDGED_CLAIM_REJECTED,
    ISSUE_INJECTION_SUSPECTED_EVIDENCE,
    ISSUE_INVALID_CONFIDENCE,
    ISSUE_INVALID_FACT_TYPE,
    ISSUE_INVALID_ONTOLOGY_CODE,
    ISSUE_MALFORMED_ATTRIBUTE,
    ISSUE_MALFORMED_CONFLICT,
    ISSUE_MALFORMED_ENTITY,
    ISSUE_MALFORMED_TOP_LEVEL,
    ISSUE_MISSING_EVIDENCE,
    ISSUE_PII_LEAK_DETECTED,
    ISSUE_UNGROUNDED_CLAIM,
    ISSUE_UNKNOWN_ATTRIBUTE_CODE,
    ISSUE_UNKNOWN_ENTITY_TYPE,
    ISSUE_UNKNOWN_EVIDENCE_SEGMENT,
    Attribute,
    Conflict,
    ConflictEvidence,
    Entity,
    ExtractionResult,
    MissingCriticalField,
    TextSegment,
    ValidationIssue,
    normalize_text,
)
from meet_ai.ontology import Catalog

# PII 마스킹이 상류(WORKER-PARSING)에서 실패했거나, 모델이 마스킹 플레이스홀더 대신 원문을
# 다시 만들어낸 극단적인 경우를 잡기 위한 방어선(2중 방어 - apps/worker의 mask_pii와 같은
# 성격이지만 트랙 경계상 독립 구현이다. 문서화된 한계도 동일하게 적용된다: 정규식 기반
# MVP 수준 탐지).
_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?<!\d)0\d{1,2}[-\s]?\d{3,4}[-\s]?\d{4}(?!\d)")
_RRN_RE = re.compile(r"(?<!\d)\d{6}[-\s]?[1-8]\d{6}(?!\d)")
_PII_RES: tuple[re.Pattern[str], ...] = (_EMAIL_RE, _PHONE_RE, _RRN_RE)


def _contains_pii(value: Any) -> bool:
    if isinstance(value, (list, tuple)):
        return any(_contains_pii(v) for v in value)
    text = str(value)
    return any(pattern.search(text) for pattern in _PII_RES)


class ExtractionValidator:
    """``GroundedExtractor``가 감싸는 순수 검증기. DB도, 백엔드 프로토콜도 모른다 - 입력은
    원시 JSON(문자열 또는 이미 파싱된 dict)과 이 실행에 쓰인 ``TextSegment`` 목록뿐이다."""

    def __init__(
        self,
        *,
        catalog: Catalog,
        attribute_schema: AttributeSchema,
        segments: tuple[TextSegment, ...],
        entity_types: tuple[str, ...] = ENTITY_TYPES,
    ) -> None:
        self._catalog = catalog
        self._schema = attribute_schema
        self._segments_by_id = {segment.segment_id: segment for segment in segments}
        self._entity_types = set(entity_types)
        self._issues: list[ValidationIssue] = []

    def validate(self, raw: str | dict[str, Any]) -> ExtractionResult:
        self._issues = []
        payload = self._parse(raw)
        if payload is None:
            return ExtractionResult(issues=tuple(self._issues))

        entities = self._validate_entities(payload.get("entities", []))
        model_conflicts = self._validate_conflicts(payload.get("conflicts", []))
        model_missing = self._validate_missing_fields(payload.get("missing_critical_fields", []))

        entities, auto_conflicts = self._detect_conflicts(entities)
        conflicts = self._merge_conflicts(model_conflicts, auto_conflicts)
        missing = self._merge_missing_fields(model_missing, entities)

        return ExtractionResult(
            entities=tuple(entities),
            conflicts=tuple(conflicts),
            missing_critical_fields=tuple(missing),
            issues=tuple(self._issues),
        )

    # -- 최상위 파싱 ---------------------------------------------------

    def _parse(self, raw: str | dict[str, Any]) -> dict[str, Any] | None:
        if isinstance(raw, dict):
            payload = raw
        else:
            try:
                payload = json.loads(raw)
            except (json.JSONDecodeError, TypeError) as exc:
                self._issue(ISSUE_MALFORMED_TOP_LEVEL, f"invalid JSON: {exc}")
                return None
        if not isinstance(payload, dict):
            self._issue(ISSUE_MALFORMED_TOP_LEVEL, "top-level response must be a JSON object")
            return None
        return payload

    def _issue(
        self,
        code: str,
        message: str,
        *,
        temporary_entity_id: str | None = None,
        attribute_code: str | None = None,
    ) -> None:
        self._issues.append(
            ValidationIssue(
                code=code,
                message=message,
                temporary_entity_id=temporary_entity_id,
                attribute_code=attribute_code,
            )
        )

    # -- entities[] ------------------------------------------------------

    def _validate_entities(self, raw_entities: Any) -> list[Entity]:
        if not isinstance(raw_entities, list):
            self._issue(ISSUE_MALFORMED_TOP_LEVEL, "entities must be a list")
            return []

        entities: list[Entity] = []
        for raw_entity in raw_entities:
            if not isinstance(raw_entity, dict):
                self._issue(ISSUE_MALFORMED_ENTITY, "entity must be an object")
                continue
            entity_type = raw_entity.get("entity_type")
            temp_id = raw_entity.get("temporary_entity_id")
            if entity_type not in self._entity_types:
                self._issue(
                    ISSUE_UNKNOWN_ENTITY_TYPE,
                    f"unknown or disallowed entity_type: {entity_type!r}",
                    temporary_entity_id=str(temp_id) if temp_id else None,
                )
                continue
            if not isinstance(temp_id, str) or not temp_id:
                self._issue(ISSUE_MALFORMED_ENTITY, "entity missing temporary_entity_id")
                continue

            attributes = self._validate_attributes(
                raw_entity.get("attributes", []), entity_type=entity_type, temp_id=temp_id
            )
            entities.append(
                Entity(entity_type=entity_type, temporary_entity_id=temp_id, attributes=tuple(attributes))
            )
        return entities

    def _validate_attributes(
        self, raw_attributes: Any, *, entity_type: str, temp_id: str
    ) -> list[Attribute]:
        if not isinstance(raw_attributes, list):
            self._issue(
                ISSUE_MALFORMED_ENTITY, "attributes must be a list", temporary_entity_id=temp_id
            )
            return []

        results: list[Attribute] = []
        for raw_attr in raw_attributes:
            attribute = self._validate_one_attribute(raw_attr, entity_type=entity_type, temp_id=temp_id)
            if attribute is not None:
                results.append(attribute)
        return results

    def _validate_one_attribute(
        self, raw_attr: Any, *, entity_type: str, temp_id: str
    ) -> Attribute | None:
        if not isinstance(raw_attr, dict):
            self._issue(ISSUE_MALFORMED_ATTRIBUTE, "attribute must be an object", temporary_entity_id=temp_id)
            return None

        attribute_code = raw_attr.get("attribute_code")
        definition = self._schema.get(attribute_code) if isinstance(attribute_code, str) else None
        if definition is None or not definition.accepts_entity_type(entity_type):
            self._issue(
                ISSUE_UNKNOWN_ATTRIBUTE_CODE,
                f"attribute_code not in ALLOWED SCHEMA for {entity_type}: {attribute_code!r}",
                temporary_entity_id=temp_id,
                attribute_code=str(attribute_code) if attribute_code else None,
            )
            return None

        if "value" not in raw_attr or raw_attr.get("value") is None:
            self._issue(
                ISSUE_MALFORMED_ATTRIBUTE,
                "attribute missing value",
                temporary_entity_id=temp_id,
                attribute_code=attribute_code,
            )
            return None
        value = raw_attr["value"]

        fact_type = raw_attr.get("fact_type")
        if fact_type not in FACT_TYPES:
            self._issue(
                ISSUE_INVALID_FACT_TYPE,
                f"invalid fact_type: {fact_type!r}",
                temporary_entity_id=temp_id,
                attribute_code=attribute_code,
            )
            return None

        confidence_raw = raw_attr.get("confidence")
        try:
            confidence = float(confidence_raw)
        except (TypeError, ValueError):
            self._issue(
                ISSUE_INVALID_CONFIDENCE,
                f"invalid confidence: {confidence_raw!r}",
                temporary_entity_id=temp_id,
                attribute_code=attribute_code,
            )
            return None
        if confidence < 0.0 or confidence > 1.0:
            confidence = max(0.0, min(1.0, confidence))

        concept_codes = self._validate_concept_codes(
            raw_attr.get("concept_codes", []), temp_id=temp_id, attribute_code=attribute_code
        )

        evidence_segment_ids = self._validate_evidence(
            raw_attr.get("evidence_segment_ids", []), temp_id=temp_id, attribute_code=attribute_code
        )
        if not evidence_segment_ids:
            self._issue(
                ISSUE_MISSING_EVIDENCE,
                "attribute has no valid evidence_segment_ids",
                temporary_entity_id=temp_id,
                attribute_code=attribute_code,
            )
            return None

        evidence_texts = [self._segments_by_id[sid].masked_text for sid in evidence_segment_ids]

        if all(looks_like_injection(text) for text in evidence_texts):
            self._issue(
                ISSUE_INJECTION_SUSPECTED_EVIDENCE,
                "all cited evidence looks like an instruction directed at the model, not a "
                "factual statement - rejected",
                temporary_entity_id=temp_id,
                attribute_code=attribute_code,
            )
            return None

        if all(is_unreliable_hedge(text) for text in evidence_texts):
            self._issue(
                ISSUE_HEDGED_CLAIM_REJECTED,
                "all cited evidence is hedged/rumor phrasing, not a confirmed statement - "
                "rejected",
                temporary_entity_id=temp_id,
                attribute_code=attribute_code,
            )
            return None

        concept_labels = [
            label
            for code in concept_codes
            if (label := concept_label(self._catalog, code)) is not None
        ]
        candidate_labels = concept_labels + [definition.description_ko]
        if not has_lexical_support(
            value=value, concept_labels=candidate_labels, evidence_texts=evidence_texts
        ):
            self._issue(
                ISSUE_UNGROUNDED_CLAIM,
                "asserted value has no lexical support in its cited evidence segment(s)",
                temporary_entity_id=temp_id,
                attribute_code=attribute_code,
            )
            return None

        if _contains_pii(value):
            self._issue(
                ISSUE_PII_LEAK_DETECTED,
                "attribute value matches a PII pattern and was dropped",
                temporary_entity_id=temp_id,
                attribute_code=attribute_code,
            )
            return None

        return Attribute(
            attribute_code=attribute_code,
            value=value,
            fact_type=fact_type,
            confidence=confidence,
            concept_codes=tuple(concept_codes),
            evidence_segment_ids=tuple(evidence_segment_ids),
        )

    def _validate_concept_codes(
        self, raw_codes: Any, *, temp_id: str, attribute_code: str
    ) -> list[str]:
        if not isinstance(raw_codes, list):
            return []
        valid: list[str] = []
        for code in raw_codes:
            if isinstance(code, str) and is_valid_concept_code(self._catalog, code):
                valid.append(code)
            else:
                self._issue(
                    ISSUE_INVALID_ONTOLOGY_CODE,
                    f"concept_code not in catalog, dropped: {code!r}",
                    temporary_entity_id=temp_id,
                    attribute_code=attribute_code,
                )
        return valid

    def _validate_evidence(
        self, raw_ids: Any, *, temp_id: str, attribute_code: str
    ) -> list[str]:
        if not isinstance(raw_ids, list):
            return []
        valid: list[str] = []
        for segment_id in raw_ids:
            if isinstance(segment_id, str) and segment_id in self._segments_by_id:
                valid.append(segment_id)
            else:
                self._issue(
                    ISSUE_UNKNOWN_EVIDENCE_SEGMENT,
                    f"evidence_segment_id does not match any provided segment: {segment_id!r}",
                    temporary_entity_id=temp_id,
                    attribute_code=attribute_code,
                )
        return valid

    # -- conflicts[] (모델 자체 보고분) -----------------------------------

    def _validate_conflicts(self, raw_conflicts: Any) -> list[Conflict]:
        if not isinstance(raw_conflicts, list):
            return []
        conflicts: list[Conflict] = []
        for raw in raw_conflicts:
            if not isinstance(raw, dict):
                self._issue(ISSUE_MALFORMED_CONFLICT, "conflict must be an object")
                continue
            temp_id = raw.get("temporary_entity_id")
            attribute_code = raw.get("attribute_code")
            raw_values = raw.get("values", [])
            if not isinstance(temp_id, str) or not isinstance(attribute_code, str) or not isinstance(
                raw_values, list
            ):
                self._issue(ISSUE_MALFORMED_CONFLICT, "conflict missing required fields")
                continue
            values: list[ConflictEvidence] = []
            for raw_value in raw_values:
                if not isinstance(raw_value, dict):
                    continue
                evidence_ids = [
                    sid
                    for sid in raw_value.get("evidence_segment_ids", [])
                    if isinstance(sid, str) and sid in self._segments_by_id
                ]
                if not evidence_ids or "value" not in raw_value:
                    continue
                fact_type = raw_value.get("fact_type")
                if fact_type not in FACT_TYPES:
                    fact_type = "UNKNOWN"
                values.append(
                    ConflictEvidence(
                        value=raw_value["value"],
                        fact_type=fact_type,
                        evidence_segment_ids=tuple(evidence_ids),
                    )
                )
            if len(values) < 2:
                continue
            conflicts.append(
                Conflict(
                    temporary_entity_id=temp_id,
                    attribute_code=attribute_code,
                    values=tuple(values),
                    reason=str(raw.get("reason", "")),
                )
            )
        return conflicts

    def _validate_missing_fields(self, raw_items: Any) -> list[MissingCriticalField]:
        if not isinstance(raw_items, list):
            return []
        results: list[MissingCriticalField] = []
        for raw in raw_items:
            if not isinstance(raw, dict):
                continue
            temp_id = raw.get("temporary_entity_id")
            attribute_code = raw.get("attribute_code")
            if not isinstance(temp_id, str) or not isinstance(attribute_code, str):
                continue
            results.append(
                MissingCriticalField(
                    temporary_entity_id=temp_id,
                    attribute_code=attribute_code,
                    reason=str(raw.get("reason", "")),
                )
            )
        return results

    # -- 결정적 후처리: 충돌 자동 탐지, 필수 필드 자동 보강 ------------------

    def _detect_conflicts(self, entities: list[Entity]) -> tuple[list[Entity], list[Conflict]]:
        """"두 근거가 같은 (entity, attribute_code)에 대해 다른 값을 주장하면 CONFLICTED로
        표시하고 둘 다 보존한다"는 임무 지시를 모델의 자체 보고에만 맡기지 않고, 살아남은
        속성들을 직접 다시 훑어 결정적으로 재확인한다. 어느 쪽 속성도 버리지 않는다 - 둘 다
        entities[]에 그대로 남고, conflicts[]에 정리된 요약만 추가된다."""

        grouped: dict[tuple[str, str], list[Attribute]] = defaultdict(list)
        for entity in entities:
            for attribute in entity.attributes:
                grouped[(entity.temporary_entity_id, attribute.attribute_code)].append(attribute)

        auto_conflicts: list[Conflict] = []
        for (temp_id, attribute_code), attributes in grouped.items():
            distinct_values = {normalize_text(json.dumps(a.value, sort_keys=True, default=str)) for a in attributes}
            if len(distinct_values) < 2:
                continue
            self._issue(
                ISSUE_AUTO_DETECTED_CONFLICT,
                f"{len(distinct_values)} distinct values asserted for the same attribute",
                temporary_entity_id=temp_id,
                attribute_code=attribute_code,
            )
            auto_conflicts.append(
                Conflict(
                    temporary_entity_id=temp_id,
                    attribute_code=attribute_code,
                    values=tuple(
                        ConflictEvidence(
                            value=a.value, fact_type=a.fact_type, evidence_segment_ids=a.evidence_segment_ids
                        )
                        for a in attributes
                    ),
                    reason="auto-detected: conflicting evidence for the same attribute",
                )
            )
        return entities, auto_conflicts

    def _merge_conflicts(
        self, model_conflicts: list[Conflict], auto_conflicts: list[Conflict]
    ) -> list[Conflict]:
        seen: set[tuple[str, str]] = set()
        merged: list[Conflict] = []
        for conflict in [*auto_conflicts, *model_conflicts]:
            key = (conflict.temporary_entity_id, conflict.attribute_code)
            if key in seen:
                continue
            seen.add(key)
            merged.append(conflict)
        return merged

    def _merge_missing_fields(
        self, model_missing: list[MissingCriticalField], entities: list[Entity]
    ) -> list[MissingCriticalField]:
        """모델이 스스로 보고한 ``missing_critical_fields``에 더해, ALLOWED SCHEMA가
        critical로 표시한 속성 중 실제로 살아남은 속성이 하나도 없는 것을 결정적으로
        찾아 보강한다 - 모델이 빠뜨렸어도 운영자가 빈 구멍을 놓치지 않게 한다."""

        merged: dict[tuple[str, str], MissingCriticalField] = {
            (item.temporary_entity_id, item.attribute_code): item for item in model_missing
        }
        for entity in entities:
            present_codes = {attribute.attribute_code for attribute in entity.attributes}
            for definition in self._schema.critical_for_entity_type(entity.entity_type):
                key = (entity.temporary_entity_id, definition.attribute_code)
                if definition.attribute_code in present_codes or key in merged:
                    continue
                self._issue(
                    ISSUE_AUTO_DETECTED_MISSING_CRITICAL_FIELD,
                    "critical attribute not found in source text",
                    temporary_entity_id=entity.temporary_entity_id,
                    attribute_code=definition.attribute_code,
                )
                merged[key] = MissingCriticalField(
                    temporary_entity_id=entity.temporary_entity_id,
                    attribute_code=definition.attribute_code,
                    reason="not found in source text",
                )
        return list(merged.values())
