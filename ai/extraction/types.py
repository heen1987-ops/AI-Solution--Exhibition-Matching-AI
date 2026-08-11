"""AI-EXTRACTION 트랙(WAVE 2D)이 파이프라인 단계 사이에서 주고받는 데이터 구조.

``ai/types.py``(QueryInterpreter/KeywordRetriever)와 같은 원칙을 따른다 - 단계마다 새
dataclass를 만드는 대신, 이 모듈이 정의하는 소수의 구조를 그대로 주고받는다.

TextSegment 계약에 대한 메모
-----------------------------
WORKER-PARSING 트랙(``apps/worker/app/jobs/document_parsing.py``)이 이미 자체
``TextSegment``(``segment_index``/``section_label``/``text``/``start_offset``/``end_offset``/
``pii_matches``)를 구현해 두었다. 이 모듈은 그것을 직접 import하지 않는다:

1. ``apps/worker``와 ``apps/api``가 각각 최상위 ``app`` 패키지를 갖고 있어, 둘 다 같은
   프로세스의 ``sys.path``에 올라오면 패키지 이름이 충돌한다(WORKER-PARSING 자체 테스트도
   ``apps/worker``를 루트로 별도 실행되는 것으로 보인다) - ``ai/**``에서 안전하게 import할
   방법이 없다.
2. 이 트랙의 임무 지시가 명시적으로 "그 트랙이 아직 안 끝났으면 스펙의 필드 목록으로 직접
   최소 dataclass를 정의하라"고 허용한다.

대신 ``adapt_worker_segments()``가 WORKER-PARSING의 실제 산출물 모양(속성 이름 기준 duck
typing, import 없음)을 이 모듈의 ``TextSegment``로 변환해 통합 시점의 마찰을 없앤다.

이 모듈에 등장하는 온톨로지 코드는 전부 ``src/meet_ai/ontology/catalog.v1.json``
(DECISION-004)에 실재해야 한다 - 이 모듈 자체는 카탈로그 코드를 만들어내지 않는다.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass, field
from typing import Any

# entities[].entity_type이 가질 수 있는 값. 전시업체 문서 구조화 산출물 범위(PROJECT_SCOPE.md
# "exhibitor-content AI structuring")에 맞춰 EXHIBITOR/PRODUCT만 둔다 - 부스는 운영 데이터로
# 문서에서 추출하지 않는다.
ENTITY_TYPES: tuple[str, ...] = ("EXHIBITOR", "PRODUCT")

# attributes[].fact_type. trade-condition류 속성에서 "지금도 가능"과 "예전에 해봤다"와
# "앞으로 할 계획"과 "문서에 시점 표시가 없다"를 섞지 않기 위한 별도 차원(임무 지시 명시
# 요구사항). trade-condition이 아닌 속성에도 항상 채워야 한다(단순화를 위해 전체 속성에
# 공통 필드로 둔다) - 시점 개념이 없는 속성은 CURRENT_CAPABILITY를 기본으로 본다.
FACT_TYPES: tuple[str, ...] = (
    "CURRENT_CAPABILITY",
    "PAST_EXPERIENCE",
    "FUTURE_PLAN",
    "UNKNOWN",
)

# ai/extraction/validator.py가 참조하는 검증 이슈 코드. 감사/평가 하네스가 특정 코드의
# 유무를 단언할 수 있도록 문자열 상수로 고정한다(자유 텍스트 메시지만으로는 회귀 테스트가
# 깨지기 쉽다).
ISSUE_UNKNOWN_ENTITY_TYPE = "UNKNOWN_ENTITY_TYPE"
ISSUE_UNKNOWN_ATTRIBUTE_CODE = "UNKNOWN_ATTRIBUTE_CODE"
ISSUE_INVALID_FACT_TYPE = "INVALID_FACT_TYPE"
ISSUE_INVALID_CONFIDENCE = "INVALID_CONFIDENCE"
ISSUE_INVALID_ONTOLOGY_CODE = "INVALID_ONTOLOGY_CODE"
ISSUE_MISSING_EVIDENCE = "MISSING_EVIDENCE"
ISSUE_UNKNOWN_EVIDENCE_SEGMENT = "UNKNOWN_EVIDENCE_SEGMENT"
ISSUE_INJECTION_SUSPECTED_EVIDENCE = "INJECTION_SUSPECTED_EVIDENCE"
ISSUE_HEDGED_CLAIM_REJECTED = "HEDGED_CLAIM_REJECTED"
ISSUE_UNGROUNDED_CLAIM = "UNGROUNDED_CLAIM"
ISSUE_PII_LEAK_DETECTED = "PII_LEAK_DETECTED"
ISSUE_MALFORMED_ENTITY = "MALFORMED_ENTITY"
ISSUE_MALFORMED_ATTRIBUTE = "MALFORMED_ATTRIBUTE"
ISSUE_MALFORMED_CONFLICT = "MALFORMED_CONFLICT"
ISSUE_MALFORMED_TOP_LEVEL = "MALFORMED_TOP_LEVEL"
ISSUE_AUTO_DETECTED_CONFLICT = "AUTO_DETECTED_CONFLICT"
ISSUE_AUTO_DETECTED_MISSING_CRITICAL_FIELD = "AUTO_DETECTED_MISSING_CRITICAL_FIELD"


def normalize_text(value: str) -> str:
    """``meet_ai.ontology.catalog.normalize_text``와 동일한 정규화(NFKC + casefold + 공백
    압축). 이 모듈이 apps/api 밖에서도 독립적으로 쓰이므로 별도 구현을 둔다(공개 동작은
    동일해야 한다 - 두 구현 모두 유닛 테스트가 있다)."""

    normalized = unicodedata.normalize("NFKC", value).casefold().strip()
    return " ".join(normalized.split())


@dataclass(frozen=True)
class TextSegment:
    """마스킹이 끝난 문서 조각 하나. GroundedExtractor 파이프라인의 유일한 입력 단위다.

    ``text``는 감사/오프셋 복원용 원문이며 프롬프트에는 절대 쓰이지 않는다
    (``ai/extraction/prompt_builder.py``는 ``masked_text``만 읽는다) - PII가 프롬프트에
    닿을 길을 코드 경로 자체에서 차단한다.
    """

    document_id: str
    order: int
    section: str
    text: str
    masked_text: str
    start_offset: int
    end_offset: int
    language: str = "ko"
    page: str | int | None = None
    content_hash: str = ""

    def __post_init__(self) -> None:
        if not self.content_hash:
            digest = hashlib.sha256(self.masked_text.encode("utf-8")).hexdigest()[:16]
            object.__setattr__(self, "content_hash", digest)

    @property
    def segment_id(self) -> str:
        """근거 인용(``evidence_segment_ids``)이 참조하는 안정적인 식별자.

        UUID가 아니라 ``{document_id}:{order}`` 형태로 사람이 읽을 수 있게 둔다 - 평가
        하네스와 프롬프트 SOURCE TEXT 섹션 양쪽에서 같은 값을 그대로 보여줘야 검증자가
        "모델이 인용한 id가 실제로 존재하는 세그먼트인지"를 오프셋 계산 없이 바로 비교할 수
        있다.
        """

        return f"{self.document_id}:{self.order}"


def adapt_worker_segments(
    document_id: str,
    worker_segments: Any,
    *,
    language: str = "ko",
) -> tuple[TextSegment, ...]:
    """WORKER-PARSING의 ``ParseResult.segments``(또는 그와 동일한 모양의 어떤 iterable)를
    이 모듈의 ``TextSegment``로 변환한다.

    ``worker_segments``의 각 항목은 다음 속성만 있으면 된다(런타임 duck typing, import
    없음): ``segment_index``, ``section_label``, ``text``(이미 마스킹된 텍스트),
    ``start_offset``, ``end_offset``. WORKER-PARSING의 실제 ``TextSegment``가 정확히 이
    모양이다 - 원문(마스킹 전) 텍스트는 그 트랙이 애초에 보존하지 않으므로(PII를 어디에도
    남기지 않는다는 그 트랙 자신의 설계), 여기서 나온 ``TextSegment.text``와
    ``.masked_text``는 둘 다 이미 마스킹된 동일한 문자열이다 - 이는 안전한 방향의 손실(원문을
    복원할 수 없을 뿐, PII가 새어 나갈 방법은 없다)이다.
    """

    result: list[TextSegment] = []
    for item in worker_segments:
        masked = str(item.text)
        result.append(
            TextSegment(
                document_id=document_id,
                order=int(item.segment_index),
                section=str(item.section_label),
                text=masked,
                masked_text=masked,
                start_offset=int(item.start_offset),
                end_offset=int(item.end_offset),
                language=language,
            )
        )
    return tuple(result)


@dataclass(frozen=True)
class Attribute:
    """entities[].attributes[] 항목 하나. 근거 없는 속성은 파이프라인 어디에도 존재할 수
    없다 - ``evidence_segment_ids``는 항상 최소 1개 이상이어야 한다(validator가 강제)."""

    attribute_code: str
    value: Any
    fact_type: str
    confidence: float
    concept_codes: tuple[str, ...] = ()
    evidence_segment_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Entity:
    entity_type: str
    temporary_entity_id: str
    attributes: tuple[Attribute, ...] = ()


@dataclass(frozen=True)
class ConflictEvidence:
    value: Any
    fact_type: str
    evidence_segment_ids: tuple[str, ...]


@dataclass(frozen=True)
class Conflict:
    """같은 (entity, attribute_code)에 대해 서로 다른 값을 주장하는 근거가 둘 이상 있을 때.

    임무 지시: "자동으로 하나를 고르지 말고 CONFLICTED로 표시하고 두 근거를 모두 보존하라" -
    그래서 이 구조체는 승자를 고르지 않고 ``values``에 모든 값-근거 쌍을 그대로 담는다.
    """

    temporary_entity_id: str
    attribute_code: str
    values: tuple[ConflictEvidence, ...]
    reason: str = ""


@dataclass(frozen=True)
class MissingCriticalField:
    temporary_entity_id: str
    attribute_code: str
    reason: str = ""


@dataclass(frozen=True)
class ValidationIssue:
    """감사/평가용 검증 이슈 한 건. 외부 계약(entities/conflicts/missing_critical_fields)에는
    포함되지 않는다 - ``ExtractionResult.issues``로만 노출되어, 평가 하네스와 운영자 로그가
    "무엇이 왜 버려졌는지"를 재구성할 수 있게 한다(값 자체가 PII일 수 있는 필드는 담지 않는다
    - attribute_code/entity_id/코드값 같은 메타데이터만 남긴다)."""

    code: str
    message: str
    temporary_entity_id: str | None = None
    attribute_code: str | None = None


@dataclass(frozen=True)
class ExtractionResult:
    entities: tuple[Entity, ...] = field(default_factory=tuple)
    conflicts: tuple[Conflict, ...] = field(default_factory=tuple)
    missing_critical_fields: tuple[MissingCriticalField, ...] = field(default_factory=tuple)
    issues: tuple[ValidationIssue, ...] = field(default_factory=tuple)

    def to_contract_dict(self) -> dict[str, Any]:
        """외부에 노출하는 계약 모양(entities/conflicts/missing_critical_fields)만 담은
        JSON-직렬화 가능 dict. ``issues``는 감사 전용이라 여기 포함하지 않는다."""

        return {
            "entities": [
                {
                    "entity_type": e.entity_type,
                    "temporary_entity_id": e.temporary_entity_id,
                    "attributes": [
                        {
                            "attribute_code": a.attribute_code,
                            "value": a.value,
                            "fact_type": a.fact_type,
                            "confidence": a.confidence,
                            "concept_codes": list(a.concept_codes),
                            "evidence_segment_ids": list(a.evidence_segment_ids),
                        }
                        for a in e.attributes
                    ],
                }
                for e in self.entities
            ],
            "conflicts": [
                {
                    "temporary_entity_id": c.temporary_entity_id,
                    "attribute_code": c.attribute_code,
                    "reason": c.reason,
                    "values": [
                        {
                            "value": v.value,
                            "fact_type": v.fact_type,
                            "evidence_segment_ids": list(v.evidence_segment_ids),
                        }
                        for v in c.values
                    ],
                }
                for c in self.conflicts
            ],
            "missing_critical_fields": [
                {
                    "temporary_entity_id": m.temporary_entity_id,
                    "attribute_code": m.attribute_code,
                    "reason": m.reason,
                }
                for m in self.missing_critical_fields
            ],
        }
