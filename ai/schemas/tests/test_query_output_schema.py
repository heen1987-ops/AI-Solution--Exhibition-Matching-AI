"""AIS-005 유닛 테스트 - `ai/schemas/query_output.QueryInterpretation` 검증 규칙.

각 위반 케이스가 실제로 `pydantic.ValidationError`를 내는지 확인한다(거짓 assertion을
만들지 않기 위해 이 파일 자체를 실행해 통과를 확인했다 - 핸드오프 문서의 TESTED 섹션
참고).

실행: `python -m pytest ai/schemas/tests/test_query_output_schema.py -v`
(경로 트릭: 이 디렉터리는 `backend/tests`·루트 `tests/`처럼 QA_SECURITY 전속 경로가
아니라 `ai/schemas/**`(AI_SEARCH 소유) 밑에 둔다 - 아래 sys.path 삽입으로 패키지 설정
없이 `query_output.py`를 바로 import한다.)
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from query_output import ConceptCondition, QueryInterpretation

# --- 실제 카탈로그에 존재하는 코드만 사용(AIS-002와 동일한 원칙) ---
# ALCOHOL.TAKJU(막걸리), TASTE.DRY(달지 않은)는 catalog.v1.json synonyms에 그대로 있는
# 실제 코드다. PRODUCT.ALL은 assignable:false 구조 헤더로 실재하지만 조건으로 쓸 수 없다.
VALID_CODE = "ALCOHOL.TAKJU"
VALID_NUMBER_CODE = "TASTE.DRY"
NON_ASSIGNABLE_CODE = "PRODUCT.ALL"
UNKNOWN_CODE = "NOT.A.REAL.CODE"


def _base_kwargs(**overrides: object) -> dict:
    payload: dict[str, object] = {
        "intent": "PRODUCT_DISCOVERY",
        "target_type": "EVENT_PRODUCT",
        "concept_codes": [VALID_CODE],
        "required_conditions": [],
        "preferred_conditions": [],
        "excluded_concept_codes": [],
        "confidence": 0.8,
        "clarification_required": False,
        "clarification_question": None,
    }
    payload.update(overrides)
    return payload


def test_valid_sample_parses() -> None:
    result = QueryInterpretation(**_base_kwargs())
    assert result.target_type == "EVENT_PRODUCT"
    assert result.concept_codes == [VALID_CODE]


def test_unknown_concept_code_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryInterpretation(**_base_kwargs(concept_codes=[UNKNOWN_CODE]))


def test_non_assignable_header_code_rejected() -> None:
    """PRODUCT.ALL은 카탈로그에 실재하지만 assignable=false 구조 헤더다 - 조건 불가."""

    with pytest.raises(ValidationError):
        QueryInterpretation(**_base_kwargs(concept_codes=[NON_ASSIGNABLE_CODE]))


def test_excluded_concept_codes_validated_too() -> None:
    with pytest.raises(ValidationError):
        QueryInterpretation(**_base_kwargs(excluded_concept_codes=[UNKNOWN_CODE]))


@pytest.mark.parametrize("bad_confidence", [-0.01, 1.01, -5, 100])
def test_confidence_out_of_range_rejected(bad_confidence: float) -> None:
    with pytest.raises(ValidationError):
        QueryInterpretation(**_base_kwargs(confidence=bad_confidence))


@pytest.mark.parametrize("boundary_confidence", [0.0, 1.0])
def test_confidence_boundary_accepted(boundary_confidence: float) -> None:
    result = QueryInterpretation(**_base_kwargs(confidence=boundary_confidence))
    assert result.confidence == boundary_confidence


def test_clarification_required_without_question_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryInterpretation(
            **_base_kwargs(clarification_required=True, clarification_question=None)
        )


def test_clarification_required_with_blank_question_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryInterpretation(
            **_base_kwargs(clarification_required=True, clarification_question="   ")
        )


def test_clarification_not_required_but_question_present_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryInterpretation(
            **_base_kwargs(
                clarification_required=False,
                clarification_question="어떤 종류를 찾으세요?",
            )
        )


def test_clarification_required_with_question_accepted() -> None:
    result = QueryInterpretation(
        **_base_kwargs(
            clarification_required=True,
            clarification_question="어떤 온라인 채널을 찾으세요?",
        )
    )
    assert result.clarification_required is True


def test_extra_field_rejected_no_exhibitor_id_or_rank() -> None:
    """스키마가 닫혀 있어(extra=forbid) exhibitor_id/rank/score 같은 결과성 필드를
    LLM이 만들어내도 파싱 단계에서 거부된다 - "업체 ID·추천순위 직접 생성 금지"의
    스키마 차원 강제."""

    with pytest.raises(ValidationError):
        QueryInterpretation(**_base_kwargs(exhibitor_id="11111111-1111-1111-1111-111111111111"))


def test_extra_field_rejected_no_ranking_score() -> None:
    with pytest.raises(ValidationError):
        QueryInterpretation(**_base_kwargs(final_score=97.5))


def test_intent_with_phone_number_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryInterpretation(**_base_kwargs(intent="연락처 010-1234-5678 문의"))


def test_clarification_question_with_email_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryInterpretation(
            **_base_kwargs(
                clarification_required=True,
                clarification_question="담당자 이메일 buyer@example.com 맞나요?",
            )
        )


def test_clarification_question_with_uuid_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryInterpretation(
            **_base_kwargs(
                clarification_required=True,
                clarification_question="11111111-1111-1111-1111-111111111111 업체 맞나요?",
            )
        )


def test_target_type_invalid_literal_rejected() -> None:
    with pytest.raises(ValidationError):
        QueryInterpretation(**_base_kwargs(target_type="PRODUCT"))


def test_target_type_all_four_contract_values_accepted() -> None:
    """domain-model.md §7의 object_type 4종(BOOTH/EVENT_PRODUCT/EXHIBITOR/PROGRAM) 전부
    허용 - candidate_generator.py가 2종만 구현했다는 현재 상태로 스키마를 좁히지 않는다."""

    for target_type in ("BOOTH", "EVENT_PRODUCT", "EXHIBITOR", "PROGRAM"):
        result = QueryInterpretation(**_base_kwargs(target_type=target_type))
        assert result.target_type == target_type


def test_required_condition_numeric_comparator_valid() -> None:
    condition = ConceptCondition(
        concept_code=VALID_NUMBER_CODE, comparator="AT_LEAST", value=3.0
    )
    result = QueryInterpretation(
        **_base_kwargs(required_conditions=[condition.model_dump()])
    )
    assert result.required_conditions[0].concept_code == VALID_NUMBER_CODE


def test_condition_between_without_value_max_rejected() -> None:
    with pytest.raises(ValidationError):
        ConceptCondition(concept_code=VALID_NUMBER_CODE, comparator="BETWEEN", value=1.0)


def test_condition_value_without_comparator_rejected() -> None:
    with pytest.raises(ValidationError):
        ConceptCondition(concept_code=VALID_NUMBER_CODE, value=3.0)


def test_condition_unknown_code_rejected() -> None:
    with pytest.raises(ValidationError):
        ConceptCondition(concept_code=UNKNOWN_CODE)
