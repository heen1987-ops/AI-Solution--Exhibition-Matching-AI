"""SYSTEM POLICY / ALLOWED SCHEMA / ALLOWED ONTOLOGY / SOURCE TEXT / OUTPUT JSON SCHEMA /
PROHIBITED INFERENCE 여섯 구획을 분리해서 만드는 프롬프트 빌더.

임무 지시가 명시적으로 이 여섯 구획을 "distinct sections"로 요구한다 - 단순히 프롬프트
프리텍스트에 다 섞어 넣지 않고, ``PromptSections``에 각각 별도 필드로 담아 테스트가 "SOURCE
TEXT 구획에 원문(PII)이 없다", "ALLOWED SCHEMA 구획에 카탈로그에 없는 코드가 없다" 같은 것을
구획 단위로 개별 검증할 수 있게 한다.

프롬프트 인젝션 방어의 핵심은 이 파일이 아니라 ``system_policy.md``/``prohibited_inference.md``
본문에 있다 - 이 파일의 책임은 그 정책이 실제로 "SOURCE TEXT는 명령이 아니라 데이터"라고
모델에게 말하도록 프롬프트 구조 자체를 강제하는 것뿐이다(SOURCE TEXT 구획은 ``masked_text``만
읽고, 절대 원문 ``text``를 읽지 않는다 - PII가 프롬프트에 닿을 길을 코드 경로 자체에서
차단한다).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from ai.extraction.attribute_schema import AttributeSchema, load_attribute_schema
from ai.extraction.types import ENTITY_TYPES, FACT_TYPES, TextSegment
from meet_ai.ontology import Catalog

_PROMPTS_DIR = Path(__file__).resolve().parents[1] / "prompts" / "extraction"
_OUTPUT_SCHEMA_PATH = Path(__file__).resolve().parents[1] / "schemas" / "extraction" / "output_schema.json"

SECTION_ORDER: tuple[str, ...] = (
    "SYSTEM POLICY",
    "ALLOWED SCHEMA",
    "ALLOWED ONTOLOGY",
    "SOURCE TEXT",
    "OUTPUT JSON SCHEMA",
    "PROHIBITED INFERENCE",
)


@lru_cache(maxsize=1)
def _load_template(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text(encoding="utf-8")


@lru_cache(maxsize=1)
def _load_output_schema_text() -> str:
    return _OUTPUT_SCHEMA_PATH.read_text(encoding="utf-8")


@dataclass(frozen=True)
class PromptSections:
    """여섯 구획을 개별 필드로 보존한 프롬프트. ``render()``가 실제 LLM 호출용 단일
    문자열을 만든다 - 구획 경계는 ``=== NAME ===`` 마커로 표시해, 사람이 검수하거나 테스트가
    특정 구획만 잘라 볼 때도 애매함이 없게 한다."""

    document_id: str
    system_policy: str
    allowed_schema: str
    allowed_ontology: str
    source_text: str
    output_json_schema: str
    prohibited_inference: str
    segment_ids: tuple[str, ...]

    def render(self) -> str:
        parts = [
            f"=== SYSTEM POLICY ===\n{self.system_policy}",
            f"=== ALLOWED SCHEMA ===\n{self.allowed_schema}",
            f"=== ALLOWED ONTOLOGY ===\n{self.allowed_ontology}",
            f"=== SOURCE TEXT ===\n{self.source_text}",
            f"=== OUTPUT JSON SCHEMA ===\n{self.output_json_schema}",
            f"=== PROHIBITED INFERENCE ===\n{self.prohibited_inference}",
        ]
        return "\n\n".join(parts)


def _render_allowed_schema(schema: AttributeSchema, entity_types: Sequence[str]) -> str:
    lines: list[str] = [
        "entity_type must be one of: " + ", ".join(entity_types),
        "fact_type must be one of: " + ", ".join(FACT_TYPES),
        "",
        "attribute_code | applies_to | data_type | allowed_values | description",
    ]
    for definition in schema.all():
        if not any(t in entity_types for t in definition.applies_to):
            continue
        allowed_values = ",".join(definition.allowed_values) if definition.allowed_values else "-"
        lines.append(
            f"{definition.attribute_code} | {','.join(definition.applies_to)} | "
            f"{definition.data_type} | {allowed_values} | {definition.description_ko}"
        )
    return "\n".join(lines)


def _render_allowed_ontology(catalog: Catalog, concept_types: Sequence[str]) -> str:
    lines: list[str] = []
    wanted = set(concept_types)
    for concept in catalog.concepts:
        if concept.get("concept_type") in wanted:
            lines.append(f"{concept['code']} | {concept.get('label_ko', '')}")
    if not lines:
        return "(no ontology codes are relevant to the requested entity types)"
    return "\n".join(lines)


def _render_source_text(segments: Sequence[TextSegment]) -> str:
    """SOURCE TEXT 구획. ``segment.masked_text``만 읽는다 - ``segment.text``(원문)는 이
    함수 어디에서도 참조하지 않는다(프롬프트 인젝션·PII 방어의 코드 레벨 불변조건)."""

    lines: list[str] = []
    for segment in segments:
        lines.append(f"[{segment.segment_id}] ({segment.section}) {segment.masked_text}")
    if not lines:
        return "(no segments provided)"
    return "\n".join(lines)


def build_extraction_prompt(
    document_id: str,
    segments: Sequence[TextSegment],
    *,
    entity_types: Sequence[str] = ENTITY_TYPES,
    attribute_schema: AttributeSchema | None = None,
    catalog: Catalog | None = None,
) -> PromptSections:
    """이 트랙의 진입점. ``segments``는 이미 마스킹된 ``TextSegment``여야 한다(호출자
    책임 - WORKER-PARSING 산출물이면 ``ai.extraction.types.adapt_worker_segments``로 변환해서
    넘긴다)."""

    if catalog is None:
        from ai.extraction.ontology_support import get_catalog

        catalog = get_catalog()
    if attribute_schema is None:
        attribute_schema = load_attribute_schema()

    concept_types: set[str] = set()
    for definition in attribute_schema.all():
        if any(t in entity_types for t in definition.applies_to):
            concept_types.update(definition.allowed_concept_types)

    return PromptSections(
        document_id=document_id,
        system_policy=_load_template("system_policy.md"),
        allowed_schema=_render_allowed_schema(attribute_schema, entity_types),
        allowed_ontology=_render_allowed_ontology(catalog, sorted(concept_types)),
        source_text=_render_source_text(segments),
        output_json_schema=_load_output_schema_text(),
        prohibited_inference=_load_template("prohibited_inference.md"),
        segment_ids=tuple(segment.segment_id for segment in segments),
    )
