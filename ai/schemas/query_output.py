"""자연어 검색 질의 - AI 해석 결과 출력 스키마 (AIS-005).

근거: `.harness/backlog.yaml` AIS-005 acceptance, `AGENTS.md` §5(AI 규칙 - "출력 JSON
Schema 검증, 허용 온톨로지 코드만 사용, 원문에 없는 조건 생성 금지, 실패 시 Fallback,
미승인 업체정보 사용 금지, 최종 필터·순위는 규칙엔진 담당 - AI가 최종 결정을 내리지
않는다"), `.harness/contracts/domain-model.md` §12(자연어 검색 채널 - LLM 호출 1회로
자연어 문장을 concept_id 목록으로 변환, 실행 결과는 `ai.ai_execution_log`에 기록).

이 스키마가 표현하는 것과 표현하지 않는 것
--------------------------------------------
이 모델은 자연어 질의에 대한 AI의 **해석**(intent/조건/확신도)만 표현한다. 다음은 이
스키마의 책임이 **아니다** - 그 최종 결정은 규칙엔진(하드필터·재랭킹·RRF)의 몫이다
(AGENTS.md §5, C-4 §1 RRF/가중합 레이어 분리 결정과 동일한 원칙):

- 검색 결과(업체·제품 ID), 순위, 점수 - 이 모델에는 그런 필드가 없다.
- 최종 필터 통과 여부 - `master_approval_status`/하드필터 판정은 `hard_filter_engine.py`
  책임이다(그 파일은 이 태스크에서 읽기만 하고 수정하지 않았다).
- 이 모델은 `model_config = ConfigDict(extra="forbid")`로 닫혀 있다 - LLM 출력이 스키마에
  없는 필드(예: `exhibitor_id`, `rank`, `phone_number`)를 추가로 만들어내도 파싱 단계에서
  즉시 거부된다. 이것이 "업체 ID·추천순위 직접 생성 금지"와 "개인정보 필드 금지"를 스키마
  차원에서 강제하는 1차 방어선이다. 2차 방어선은 아래 `_reject_personal_data`(자유 텍스트
  필드 안에 전화번호·이메일·UUID 패턴이 섞여 들어오는 경우까지 잡는다).

"원문에 없는 조건 생성 금지"(AGENTS.md §5)는 스키마 하나만으로 기계적으로 완전히
검증할 수 없다(자연어 동의어 매핑이 다양해 "원문 텍스트에 개념 라벨이 그대로 등장하는가"
같은 단순 문자열 포함 검사로는 오탐·누락이 많다) - 이 규칙은 AIS-001 Gold Set의
`forbidden_inferences` 필드와 AIS-003(Fallback 시나리오)에서 프롬프트·평가 단계로
보강해야 한다. 이 모델이 기계적으로 강제하는 것은 "그 조건이 최소한 카탈로그에 실재하는
개념인가"(허용 온톨로지 코드만 사용)까지다.

온톨로지 코드 검증
------------------
`concept_codes`/`required_conditions`/`preferred_conditions`/`excluded_concept_codes`에
등장하는 모든 concept_code는 `src/meet_ai/ontology/catalog.v1.json`(CONTRACTS 트랙 소유,
읽기 전용으로만 참조)에 실재해야 하고, `assignable` 플래그가 `false`인 구조적 헤더
코드(예: `PRODUCT.ALL`, `CHANNEL.ONLINE`)는 조건으로 직접 쓸 수 없다 - 이는
`backend/app/api/v1/endpoints/ontology.py`의 `assignable_only` 필터와 동일한 관례다
(그 파일도 `concept.get("assignable", True)`로 기본값 True 처리).

target_type
-----------
`.harness/contracts/domain-model.md` §7(`exhibition.recommendable.object_type IN
('BOOTH','EVENT_PRODUCT','EXHIBITOR','PROGRAM')`)의 4종 그대로 사용한다 -
`candidate_generator.py`가 현재 두 채널(EVENT_PRODUCT/EXHIBITOR)만 구현했다는 사실 때문에
스키마를 2종으로 좁히지 않는다(도메인 계약이 코드 구현 상태보다 우선한다 - CTR-001이
정본).
"""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from meet_ai.ontology import Catalog, load_catalog

TargetType = Literal["BOOTH", "EVENT_PRODUCT", "EXHIBITOR", "PROGRAM"]
Comparator = Literal["EQUALS", "AT_LEAST", "AT_MOST", "BETWEEN"]

# 개인정보 패턴(2차 방어선) - AGENTS.md §8 "키오스크 세션 종료 후 개인정보가 잔존하지
# 않는다", §5 "AI: ... 개인정보 필드 금지"의 근거를 자유 텍스트 필드에도 적용한다.
_EMAIL_PATTERN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
# 한국 휴대폰(010-1234-5678 등) + 일반 전화번호 형태. 온톨로지 코드(예: ALCOHOL.TAKJU)나
# 숫자 하나짜리 값과 혼동하지 않도록 구분자 포함 다자리 패턴만 잡는다.
_PHONE_PATTERN = re.compile(r"\b0\d{1,2}[-.\s]\d{3,4}[-.\s]\d{4}\b")
_UUID_PATTERN = re.compile(
    r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}"
)


@lru_cache(maxsize=1)
def _catalog() -> Catalog:
    return load_catalog()


@lru_cache(maxsize=1)
def _assignable_codes() -> frozenset[str]:
    catalog = _catalog()
    return frozenset(
        code for code, item in catalog.by_code.items() if item.get("assignable", True)
    )


def _reject_personal_data(value: str | None, *, field_name: str) -> str | None:
    if not value:
        return value
    if _EMAIL_PATTERN.search(value):
        raise ValueError(f"{field_name} must not contain an email address")
    if _PHONE_PATTERN.search(value):
        raise ValueError(f"{field_name} must not contain a phone number")
    if _UUID_PATTERN.search(value):
        raise ValueError(
            f"{field_name} must not contain an identifier-like value "
            "(no direct exhibitor-ID generation)"
        )
    return value


def _validate_concept_code(code: str) -> str:
    catalog = _catalog()
    if code not in catalog.by_code:
        raise ValueError(f"unknown ontology concept code: {code!r}")
    if code not in _assignable_codes():
        raise ValueError(
            f"concept code {code!r} is a structural header (assignable=false) "
            "and cannot be used as a search condition"
        )
    return code


class ConceptCondition(BaseModel):
    """조건 1건 - concept_code + (숫자형 concept의 경우) 선택적 비교 연산자.

    카탈로그의 TASTE.*/AROMA.* 같은 개념은 `data_type: "NUMBER"`에 `validation.min/max`가
    있고(예: 0~5), ALCOHOL_LEVEL.*/PRICE_BAND.*는 `derived_bands`로 구간이 이미 정의돼
    있다 - 둘 다 실제 카탈로그 구조이며 이 모델이 새로 지어낸 개념이 아니다.
    """

    model_config = ConfigDict(extra="forbid")

    concept_code: str
    comparator: Comparator | None = None
    value: float | None = None
    value_max: float | None = None

    @field_validator("concept_code")
    @classmethod
    def _check_code(cls, v: str) -> str:
        return _validate_concept_code(v)

    @model_validator(mode="after")
    def _check_comparator_value(self) -> ConceptCondition:
        if self.comparator == "BETWEEN":
            if self.value is None or self.value_max is None:
                raise ValueError("BETWEEN comparator requires both value and value_max")
        elif self.comparator in {"EQUALS", "AT_LEAST", "AT_MOST"}:
            if self.value is None:
                raise ValueError(f"{self.comparator} comparator requires value")
        elif self.comparator is None and (
            self.value is not None or self.value_max is not None
        ):
            raise ValueError("value/value_max requires a comparator to be set")
        return self


class QueryInterpretation(BaseModel):
    """자연어 검색 질의 1건에 대한 AI 해석 결과.

    이 값은 그대로 검색·추천에 쓰이지 않는다 - `SearchProvider`(AIS-006,
    `backend/app/services/matching/search_provider.py`)와 기존 하드필터·재랭킹 엔진의
    입력일 뿐이다.
    """

    model_config = ConfigDict(extra="forbid")

    intent: str = Field(
        min_length=1,
        max_length=100,
        description="자유 형식 의도 라벨(예: PRODUCT_DISCOVERY, BUYER_SUPPLIER_MATCHING). "
        "고정 enum이 아니다 - 새 의도 유형이 늘어날 수 있어 값 자체는 강제하지 않되, "
        "개인정보·식별자 혼입은 검증한다.",
    )
    target_type: TargetType
    concept_codes: list[str] = Field(
        default_factory=list,
        description="이 질의에서 인식한 모든 concept_code의 합집합(검색채널 색인용).",
    )
    required_conditions: list[ConceptCondition] = Field(default_factory=list)
    preferred_conditions: list[ConceptCondition] = Field(default_factory=list)
    excluded_concept_codes: list[str] = Field(default_factory=list)
    confidence: float = Field(
        ge=0.0, le=1.0, description="0(전혀 확신 없음) ~ 1(완전히 확신) 구간."
    )
    clarification_required: bool = False
    clarification_question: str | None = Field(default=None, max_length=300)

    @field_validator("intent")
    @classmethod
    def _intent_no_personal_data(cls, v: str) -> str:
        return _reject_personal_data(v, field_name="intent") or v

    @field_validator("clarification_question")
    @classmethod
    def _clarification_no_personal_data(cls, v: str | None) -> str | None:
        return _reject_personal_data(v, field_name="clarification_question")

    @field_validator("concept_codes", "excluded_concept_codes")
    @classmethod
    def _check_codes_list(cls, v: list[str]) -> list[str]:
        return [_validate_concept_code(code) for code in v]

    @model_validator(mode="after")
    def _check_clarification_consistency(self) -> QueryInterpretation:
        question = (self.clarification_question or "").strip()
        if self.clarification_required and not question:
            raise ValueError(
                "clarification_required=True requires a non-empty "
                "clarification_question"
            )
        if not self.clarification_required and self.clarification_question:
            raise ValueError(
                "clarification_question must be empty/None when "
                "clarification_required=False"
            )
        return self
