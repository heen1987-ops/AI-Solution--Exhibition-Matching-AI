"""프롬프트 구성 -> 백엔드 호출 -> 검증을 한 번에 묶는 진입점.

``ai/query_interpreter.py``의 ``QueryInterpreter`` 클래스와 같은 역할 - 이 파일 자체는
얇다. 실제 정책은 ``prompt_builder.py``(무엇을 묻는가)와 ``validator.py``(무엇을 믿는가)에
있다.
"""

from __future__ import annotations

from dataclasses import dataclass

from ai.extraction.attribute_schema import AttributeSchema, load_attribute_schema
from ai.extraction.ontology_support import get_catalog
from ai.extraction.prompt_builder import PromptSections, build_extraction_prompt
from ai.extraction.provider import ExtractionBackend, UnconfiguredExtractionBackend
from ai.extraction.types import ENTITY_TYPES, ExtractionResult, TextSegment
from ai.extraction.validator import ExtractionValidator
from meet_ai.ontology import Catalog


@dataclass(frozen=True)
class ExtractionRun:
    """감사용으로 프롬프트/원시응답/검증결과를 모두 함께 보존한 실행 기록. 외부 계약으로
    넘길 때는 ``result.to_contract_dict()``만 쓰면 되고, 나머지 필드는 리뷰/디버깅 전용."""

    document_id: str
    prompt: PromptSections
    raw_response: str
    result: ExtractionResult


class GroundedExtractor:
    def __init__(
        self,
        *,
        backend: ExtractionBackend | None = None,
        catalog: Catalog | None = None,
        attribute_schema: AttributeSchema | None = None,
    ) -> None:
        self._backend = backend or UnconfiguredExtractionBackend()
        self._catalog = catalog or get_catalog()
        self._attribute_schema = attribute_schema or load_attribute_schema()

    def extract(
        self,
        document_id: str,
        segments: tuple[TextSegment, ...],
        *,
        entity_types: tuple[str, ...] = ENTITY_TYPES,
    ) -> ExtractionRun:
        prompt = build_extraction_prompt(
            document_id,
            segments,
            entity_types=entity_types,
            attribute_schema=self._attribute_schema,
            catalog=self._catalog,
        )
        raw_response = self._backend.extract(prompt)
        validator = ExtractionValidator(
            catalog=self._catalog,
            attribute_schema=self._attribute_schema,
            segments=segments,
            entity_types=entity_types,
        )
        result = validator.validate(raw_response)
        return ExtractionRun(
            document_id=document_id, prompt=prompt, raw_response=raw_response, result=result
        )
