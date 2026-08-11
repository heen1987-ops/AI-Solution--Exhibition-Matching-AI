"""AI-EXTRACTION 산출물(``ai/extraction/types.py``의 ``ExtractionResult``)을
``app/models/extraction.py``의 검수 대기 행으로 옮겨 적는다.

입력 모양에 대한 메모 - 왜 dataclass가 아니라 plain dict인가
--------------------------------------------------------------
``ai/extraction/types.py``를 직접 import하지 않는다. ``app/services/extraction/attribute_schema.py``
모듈 docstring에 적은 것과 같은 이유(``ai/`` 최상위 패키지가 ``apps/api``의 pytest
``pythonpath``에 없어 ``ModuleNotFoundError`` - ``tests/test_ai_buyer_matching.py``가 이미
같은 이유로 깨져 있는 것으로 확인함)다. 대신 ``ExtractionResult.to_contract_dict()``가 만드는
plain dict 모양(``entities``/``conflicts``/``missing_critical_fields``)을 그대로
``result`` 인자로 받는다 - 실제 통합 시점에는 워커가 AI 실행 후 이 dict를 (프로세스 경계를
넘어) 넘겨줄 것이므로 어차피 이 모양이 진짜 인터페이스다. ``segments``도 같은 이유로
``ai.extraction.types.TextSegment`` 대신 duck-typed dict를 받는다.

공개등급(visibility)에 대한 메모 (통합 MERGE STEP 16 (a))
-----------------------------------------------------------
``default_visibility`` 인자는 이제 "모든 속성에 그대로 찍히는 값"이 아니라 "제한 대상이
아닌 속성의 기본값"이다. 실제 저장 등급은
``app/services/extraction/visibility.resolve_default_visibility()``가 attribute_code별로
결정한다 - ``attribute_schema.json``의 ``trade_condition: true`` 아홉 개 코드와
``product.price_krw``는 호출자가 PUBLIC을 넘겨도 VERIFIED_BUYER로 좁혀진다. 통합 전에는
전부 PUBLIC으로 찍혀 익명 공개면에 도매 결제조건·MOQ·가격이 노출될 수 있었다.
"""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.extraction import (
    TEMPORAL_VALIDITY_VALUES,
    ExtractedAttribute,
    ExtractionConflict,
    SourceEvidence,
)
from app.services.extraction.errors import UnknownOntologyCodeError
from app.services.extraction.ontology_validation import invalid_concept_codes
from app.services.extraction.visibility import resolve_default_visibility


def _evidence_hash(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


def _temporal_validity(raw: str | None) -> str | None:
    return raw if raw in TEMPORAL_VALIDITY_VALUES else None


@dataclass
class IngestSummary:
    proposed_extraction_ids: list[uuid.UUID] = field(default_factory=list)
    conflicted_extraction_ids: list[uuid.UUID] = field(default_factory=list)
    unknown_extraction_ids: list[uuid.UUID] = field(default_factory=list)
    conflict_ids: list[uuid.UUID] = field(default_factory=list)


def _make_extraction(
    *,
    tenant_id: uuid.UUID,
    exhibitor_id: uuid.UUID,
    document_id: uuid.UUID | None,
    ai_run_id: uuid.UUID | None,
    entity_type: str,
    temporary_entity_ref: str | None,
    attribute_code: str,
    proposed_value: Any,
    fact_type: str,
    temporal_validity: str | None,
    confidence: float | None,
    concept_codes: list[str] | None,
    review_status: str,
    default_visibility: str,
) -> ExtractedAttribute:
    if concept_codes:
        bad = invalid_concept_codes(concept_codes)
        if bad:
            # AGENTS.md: "AI는 온톨로지 카탈로그에 없는 개념 코드를 절대 지어내면 안 된다" -
            # 여기서 조용히 걸러내지 않고 곧바로 실패시켜(fail loud) 수집 파이프라인이 문제를
            # 즉시 드러내게 한다(부분 커밋 방지는 호출자의 트랜잭션 경계 책임).
            raise UnknownOntologyCodeError(bad[0])

    return ExtractedAttribute(
        tenant_id=tenant_id,
        exhibitor_id=exhibitor_id,
        document_id=document_id,
        ai_run_id=ai_run_id,
        entity_type=entity_type,
        temporary_entity_ref=temporary_entity_ref,
        attribute_code=attribute_code,
        proposed_value=proposed_value,
        normalized_value=None,
        concept_codes=list(concept_codes) if concept_codes else None,
        fact_type=fact_type,
        temporal_validity=temporal_validity,
        confidence=confidence,
        review_status=review_status,
        # 공개등급은 attribute_code별로 결정한다 - 모듈 docstring 참고.
        visibility=resolve_default_visibility(
            attribute_code, default_visibility=default_visibility
        ),
    )


def _add_evidence(
    db: AsyncSession,
    *,
    extraction_id: uuid.UUID,
    document_id: uuid.UUID | None,
    evidence_segment_ids: list[str] | tuple[str, ...],
    segments: dict[str, dict[str, Any]] | None,
) -> None:
    for segment_id in evidence_segment_ids or ():
        seg = (segments or {}).get(segment_id)
        text = str(seg.get("masked_text") or seg.get("text") or "") if seg else ""
        db.add(
            SourceEvidence(
                extraction_id=extraction_id,
                document_id=document_id,
                segment_ref=segment_id,
                page_number=(seg or {}).get("page") if isinstance((seg or {}).get("page"), int) else None,
                section_title=(seg or {}).get("section"),
                text_start=(seg or {}).get("start_offset"),
                text_end=(seg or {}).get("end_offset"),
                evidence_text=text,
                evidence_hash=_evidence_hash(text),
            )
        )


async def ingest_extraction_result(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    exhibitor_id: uuid.UUID,
    document_id: uuid.UUID,
    ai_run_id: uuid.UUID | None,
    result: dict[str, Any],
    segments: dict[str, dict[str, Any]] | None = None,
    default_visibility: str = "PUBLIC",
) -> IngestSummary:
    """``result``(``ExtractionResult.to_contract_dict()`` 모양)의 모든 entity/attribute/
    conflict/missing-critical-field를 ``extracted_attribute``(+``source_evidence``,
    ``extraction_conflict``) 행으로 만든다.

    fact_type을 왜 전부 'AI_INFERRED'로 매기는지는 ``app/models/extraction.py`` 모듈
    docstring "핵심 설계 결정"을 참고 - 이 함수는 그 결정을 실행할 뿐이다.

    ``default_visibility``는 제한 대상이 아닌 attribute_code에만 적용된다(모듈 docstring
    "공개등급에 대한 메모" 참고).
    """

    summary = IngestSummary()

    for entity in result.get("entities", ()):
        entity_type = entity.get("entity_type", "")
        temp_ref = entity.get("temporary_entity_id")
        for attr in entity.get("attributes", ()):
            row = _make_extraction(
                tenant_id=tenant_id,
                exhibitor_id=exhibitor_id,
                document_id=document_id,
                ai_run_id=ai_run_id,
                entity_type=entity_type,
                temporary_entity_ref=temp_ref,
                attribute_code=attr["attribute_code"],
                proposed_value=attr.get("value"),
                fact_type="AI_INFERRED",
                temporal_validity=_temporal_validity(attr.get("fact_type")),
                confidence=attr.get("confidence"),
                concept_codes=attr.get("concept_codes"),
                review_status="PROPOSED",
                default_visibility=default_visibility,
            )
            db.add(row)
            await db.flush()
            summary.proposed_extraction_ids.append(row.extraction_id)
            _add_evidence(
                db,
                extraction_id=row.extraction_id,
                document_id=document_id,
                evidence_segment_ids=attr.get("evidence_segment_ids", ()),
                segments=segments,
            )

    for conflict in result.get("conflicts", ()):
        member_ids: list[uuid.UUID] = []
        entity_type = "EXHIBITOR"
        for candidate_entity in result.get("entities", ()):
            if candidate_entity.get("temporary_entity_id") == conflict.get("temporary_entity_id"):
                entity_type = candidate_entity.get("entity_type", entity_type)
                break
        for value_entry in conflict.get("values", ()):
            row = _make_extraction(
                tenant_id=tenant_id,
                exhibitor_id=exhibitor_id,
                document_id=document_id,
                ai_run_id=ai_run_id,
                entity_type=entity_type,
                temporary_entity_ref=conflict.get("temporary_entity_id"),
                attribute_code=conflict["attribute_code"],
                proposed_value=value_entry.get("value"),
                fact_type="AI_INFERRED",
                temporal_validity=_temporal_validity(value_entry.get("fact_type")),
                confidence=None,
                concept_codes=None,
                review_status="CONFLICTED",
                default_visibility=default_visibility,
            )
            db.add(row)
            await db.flush()
            member_ids.append(row.extraction_id)
            summary.conflicted_extraction_ids.append(row.extraction_id)
            _add_evidence(
                db,
                extraction_id=row.extraction_id,
                document_id=document_id,
                evidence_segment_ids=value_entry.get("evidence_segment_ids", ()),
                segments=segments,
            )

        conflict_row = ExtractionConflict(
            tenant_id=tenant_id,
            exhibitor_id=exhibitor_id,
            entity_type=entity_type,
            temporary_entity_ref=conflict.get("temporary_entity_id"),
            attribute_code=conflict["attribute_code"],
            member_extraction_ids=[str(i) for i in member_ids],
            status="OPEN",
        )
        db.add(conflict_row)
        await db.flush()
        summary.conflict_ids.append(conflict_row.conflict_id)

    for missing in result.get("missing_critical_fields", ()):
        entity_type = "EXHIBITOR"
        for candidate_entity in result.get("entities", ()):
            if candidate_entity.get("temporary_entity_id") == missing.get("temporary_entity_id"):
                entity_type = candidate_entity.get("entity_type", entity_type)
                break
        row = _make_extraction(
            tenant_id=tenant_id,
            exhibitor_id=exhibitor_id,
            document_id=document_id,
            ai_run_id=ai_run_id,
            entity_type=entity_type,
            temporary_entity_ref=missing.get("temporary_entity_id"),
            attribute_code=missing["attribute_code"],
            proposed_value=None,
            fact_type="UNKNOWN",
            temporal_validity=None,
            confidence=None,
            concept_codes=None,
            review_status="PROPOSED",
            default_visibility=default_visibility,
        )
        db.add(row)
        await db.flush()
        summary.unknown_extraction_ids.append(row.extraction_id)

    return summary
