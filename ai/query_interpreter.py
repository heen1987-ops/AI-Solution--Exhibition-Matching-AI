"""자연어 질의 -> InterpretedQuery 구조화기.

파이프라인 (임무 지시 그대로):

    정규화 -> 동의어 사전(카탈로그 synonym) 매칭 -> 온톨로지 코드 매핑(개념 라벨 직접일치)
    -> 규칙기반 의도분류 -> PostgreSQL 검색용 조건(required/preferred/excluded) 생성.

LLM은 지금 단계에 넣지 않는다(임무 지시). 대신 ``QueryInterpreterBackend`` 프로토콜로 해석
로직을 분리해 두어, 나중에 같은 인터페이스 뒤에 LLM 백엔드를 꽂을 수 있게 한다 - 그때도
``QueryInterpreter.interpret(query, channel, language) -> InterpretedQuery`` 시그니처는 그대로
유지된다.

온톨로지 코드는 전부 ``meet_ai.ontology.load_catalog()``가 로드하는
``src/meet_ai/ontology/catalog.v1.json``에서만 가져온다(DECISION-004). 이 모듈은 카탈로그에
없는 코드를 만들어내지 않는다 - ``ai/tests/test_query_interpreter.py``의
``test_never_invents_codes_outside_catalog``가 이를 검증한다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Protocol

from meet_ai.ontology import Catalog, load_catalog
from meet_ai.ontology.catalog import normalize_text

from ai.types import CHANNELS, DEFAULT_CHANNEL, InterpretedQuery, MatchedTerm, target_types_for_intent

# 부정어 표지. Korean 활용형이 다양해 "안 되는/안 되고/안됩니다"처럼 어미가 갈리므로, 완성된
# 단어가 아니라 어간(안되/안 되)까지만 표지로 둔다 - 뒤이은 어미와 무관하게 걸리도록.
NEGATION_MARKERS: tuple[str, ...] = (
    "말고",
    "빼고",
    "제외",
    "아닌",
    "안되",
    "안 되",
    "없이",
)
# 부정어 표지를 찾는 창 크기(개념 매칭 끝 위치부터 몇 글자 안에서 찾을지). 한국어 조사 1~2자 +
# 부정어 표지(2~3자) 정도를 넉넉히 포괄한다.
_NEGATION_WINDOW = 10

# concept_type -> 기본 요구수준. catalog.v1.json metadata.requirement_levels
# (REQUIRED/PREFERRED/ACCEPTABLE/EXCLUDED)와 이름을 맞추되, 규칙기반 1단계에서는 ACCEPTABLE을
# 따로 산출하지 않는다(REQUIRED 아니면 PREFERRED). 카테고리·원료·도수·가격대·바이어유형·
# 채널·거래유형·상담주제·부스서비스·지역처럼 "이 조건 자체가 검색의 핵심 필터"인 개념유형은
# REQUIRED로, 맛·향·용도·차별성처럼 "있으면 가점, 없어도 후보에서 빼지 않는" 개념유형은
# PREFERRED로 분류한다. 부정어가 검출되면 이 기본값과 무관하게 EXCLUDED로 덮어쓴다.
_REQUIRED_CONCEPT_TYPES: frozenset[str] = frozenset(
    {
        "PRODUCT_CATEGORY",
        "INGREDIENT",
        "ALCOHOL_LEVEL",
        "PRICE_BAND",
        "BUYER_TYPE",
        "CHANNEL",
        "TRADE_TYPE",
        "MEETING_TOPIC",
        "BOOTH_SERVICE",
        "REGION",
    }
)

# 의도 판별용 명시적 대상 명사 키워드. 온톨로지 코드가 아니라 순수 어휘 휴리스틱이다(카탈로그
# 코드를 만들어내는 것이 아니므로 "코드를 발명하지 않는다" 규칙과 무관).
# 주의: 순수 "브랜드"는 넣지 않는다 - "자체 브랜드 제품"처럼 제품 질의 안에도 흔히 등장해
# SEARCH_EXHIBITOR로 잘못 끌어당긴다. 더 구체적인 "브랜드사"만 남긴다.
_BOOTH_KEYWORDS: tuple[str, ...] = ("부스",)
_EXHIBITOR_KEYWORDS: tuple[str, ...] = (
    "업체",
    "브랜드사",
    "회사",
    "제조사",
    "양조장",
    "증류소",
    "생산자",
    "공급업체",
    "바이어",
)
_PRODUCT_KEYWORDS: tuple[str, ...] = ("제품", "상품", "술", "주류")

# 우선순위: 부스 > 업체 > 제품. "탁주 파는 업체 찾아줘"처럼 제품 개념과 업체 명사가 함께
# 나오면 명시적으로 지목된 대상(업체)이 이겨야 한다.
_KEYWORD_INTENT_ORDER: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("SEARCH_BOOTH", _BOOTH_KEYWORDS),
    ("SEARCH_EXHIBITOR", _EXHIBITOR_KEYWORDS),
    ("SEARCH_PRODUCT_SERVICE", _PRODUCT_KEYWORDS),
)

# 명시적 대상 명사가 전혀 없을 때만 쓰는 concept_type -> 의도 폴백.
_PRODUCT_FAMILY_TYPES: frozenset[str] = frozenset(
    {
        "PRODUCT_CATEGORY",
        "INGREDIENT",
        "TASTE",
        "AROMA",
        "ALCOHOL_LEVEL",
        "PRICE_BAND",
        "USE_CASE",
        "PRODUCT_FEATURE",
    }
)
_BOOTH_FAMILY_TYPES: frozenset[str] = frozenset({"BOOTH_SERVICE", "BOOTH_STATUS", "CONGESTION"})
_EXHIBITOR_FAMILY_TYPES: frozenset[str] = frozenset(
    {"BUYER_TYPE", "CHANNEL", "TRADE_TYPE", "SUPPLY_CAPACITY", "MEETING_TOPIC"}
)

# 라벨 직접일치에서 오탐을 줄이기 위한 최소 길이(한 글자짜리 라벨, 예: INGREDIENT.RICE="쌀"은
# 다른 단어 안에 우연히 포함되기 쉬워 규칙기반 1단계에서는 제외한다).
_MIN_LABEL_LENGTH = 2

# 라벨 직접일치의 기본 우선순위. catalog.synonyms 항목의 priority(보통 10~30)보다 항상 낮은
# 우선순위로 두어, 큐레이션된 동의어가 라벨 직접일치보다 항상 이기게 한다(숫자가 작을수록
# 우선 - Catalog.resolve_synonym과 동일한 규칙).
_LABEL_MATCH_PRIORITY = 200


class QueryInterpreterBackend(Protocol):
    """QueryInterpreter가 실제 해석을 위임하는 백엔드 인터페이스. 지금은
    ``RuleBasedQueryInterpreter``가 유일한 구현체이고, 추후 LLM 백엔드를 추가할 때도 이
    프로토콜만 만족하면 QueryInterpreter 쪽 코드는 바꿀 필요가 없다.
    """

    def interpret(self, query: str, *, channel: str, language: str) -> InterpretedQuery: ...


@lru_cache(maxsize=1)
def _default_catalog() -> Catalog:
    return load_catalog()


@dataclass(frozen=True)
class _RawMatch:
    concept_code: str
    concept_type: str
    matched_text: str
    source: str  # SYNONYM | LABEL
    end: int
    priority: int


def _iter_synonym_matches(catalog: Catalog, normalized: str) -> list[_RawMatch]:
    matches: list[_RawMatch] = []
    for item in catalog.synonyms:
        text = normalize_text(str(item.get("text", "")))
        if not text:
            continue
        concept_code = str(item.get("concept_code", ""))
        concept = catalog.by_code.get(concept_code)
        if concept is None:
            # 카탈로그 자체 검증(Catalog.validate)이 통과했다면 이 경로는 도달하지 않는다.
            # 방어적으로만 건너뛴다.
            continue
        for occurrence in re.finditer(re.escape(text), normalized):
            matches.append(
                _RawMatch(
                    concept_code=concept_code,
                    concept_type=str(concept.get("concept_type", "")),
                    matched_text=text,
                    source="SYNONYM",
                    end=occurrence.end(),
                    priority=int(item.get("priority", 100)),
                )
            )
    return matches


def _iter_label_matches(catalog: Catalog, normalized: str) -> list[_RawMatch]:
    matches: list[_RawMatch] = []
    for concept in catalog.concepts:
        if concept.get("assignable") is False:
            # "*.ALL" 같은 상위 카테고리 노드는 실제 검색 필터로 쓰기엔 너무 광범위하다.
            continue
        label = normalize_text(str(concept.get("label_ko", "")))
        if len(label) < _MIN_LABEL_LENGTH:
            continue
        code = str(concept.get("code", ""))
        for occurrence in re.finditer(re.escape(label), normalized):
            matches.append(
                _RawMatch(
                    concept_code=code,
                    concept_type=str(concept.get("concept_type", "")),
                    matched_text=label,
                    source="LABEL",
                    end=occurrence.end(),
                    priority=_LABEL_MATCH_PRIORITY,
                )
            )
    return matches


def _is_negated(normalized: str, end: int) -> bool:
    window = normalized[end : end + _NEGATION_WINDOW]
    return any(marker in window for marker in NEGATION_MARKERS)


def _dedupe_best_per_code(raw_matches: list[_RawMatch]) -> dict[str, _RawMatch]:
    """같은 개념 코드가 동의어·라벨 양쪽에서 잡히면, 우선순위가 더 좋은(숫자가 더 작은) 근거
    하나만 남긴다 - Catalog.resolve_synonym의 "priority가 낮을수록 우선" 규칙을 그대로 따른다.
    동률이면 더 긴 매칭 텍스트를 우선한다(더 구체적인 근거).
    """

    best: dict[str, _RawMatch] = {}
    for match in raw_matches:
        current = best.get(match.concept_code)
        if current is None:
            best[match.concept_code] = match
            continue
        candidate_key = (match.priority, -len(match.matched_text))
        current_key = (current.priority, -len(current.matched_text))
        if candidate_key < current_key:
            best[match.concept_code] = match
    return best


def _requirement_level(concept_type: str) -> str:
    return "REQUIRED" if concept_type in _REQUIRED_CONCEPT_TYPES else "PREFERRED"


def _classify_intent(normalized: str, matched_terms: list[MatchedTerm]) -> tuple[str, float]:
    for intent, keywords in _KEYWORD_INTENT_ORDER:
        if any(keyword in normalized for keyword in keywords):
            return intent, 0.9

    type_counts = {"SEARCH_PRODUCT_SERVICE": 0, "SEARCH_BOOTH": 0, "SEARCH_EXHIBITOR": 0}
    for term in matched_terms:
        if term.requirement_level == "EXCLUDED":
            # 사용자가 명시적으로 뺀 개념은 "무엇을 찾는지"의 근거로 쓰지 않는다.
            continue
        if term.concept_type in _PRODUCT_FAMILY_TYPES:
            type_counts["SEARCH_PRODUCT_SERVICE"] += 1
        elif term.concept_type in _BOOTH_FAMILY_TYPES:
            type_counts["SEARCH_BOOTH"] += 1
        elif term.concept_type in _EXHIBITOR_FAMILY_TYPES:
            type_counts["SEARCH_EXHIBITOR"] += 1

    best_intent = max(type_counts, key=lambda key: type_counts[key])
    if type_counts[best_intent] == 0:
        return "UNKNOWN", 0.0
    return best_intent, 0.7


_CLARIFICATION_MESSAGE = (
    "제품, 업체, 부스 중 어떤 것을 찾으시나요? 예: '드라이한 증류주', '탁주 만드는 업체', "
    "'시음 가능한 부스'"
)
_EMPTY_QUERY_CLARIFICATION = "검색어를 입력해 주세요."


class RuleBasedQueryInterpreter:
    """카탈로그 동의어·라벨 매칭 + 규칙기반 의도분류. LLM을 호출하지 않는다."""

    def __init__(self, catalog: Catalog | None = None) -> None:
        self._catalog = catalog if catalog is not None else _default_catalog()

    def interpret(self, query: str, *, channel: str, language: str = "ko") -> InterpretedQuery:
        raw_query = query or ""
        normalized = normalize_text(raw_query)
        resolved_channel = channel if channel in CHANNELS else DEFAULT_CHANNEL
        catalog = self._catalog

        if not normalized:
            return InterpretedQuery(
                raw_query=raw_query,
                normalized_query=normalized,
                channel=resolved_channel,
                language=language,
                intent="UNKNOWN",
                target_types=(),
                concept_codes=(),
                required_concepts=(),
                preferred_concepts=(),
                excluded_concepts=(),
                confidence=0.0,
                clarification_required=True,
                clarification=_EMPTY_QUERY_CLARIFICATION,
            )

        raw_matches = _iter_synonym_matches(catalog, normalized) + _iter_label_matches(
            catalog, normalized
        )
        best_by_code = _dedupe_best_per_code(raw_matches)

        matched_terms: list[MatchedTerm] = []
        for match in best_by_code.values():
            level = (
                "EXCLUDED"
                if _is_negated(normalized, match.end)
                else _requirement_level(match.concept_type)
            )
            matched_terms.append(
                MatchedTerm(
                    concept_code=match.concept_code,
                    concept_type=match.concept_type,
                    matched_text=match.matched_text,
                    source=match.source,
                    requirement_level=level,
                )
            )
        matched_terms.sort(key=lambda term: term.concept_code)

        intent, confidence = _classify_intent(normalized, matched_terms)
        if language not in ("ko", "ko-KR"):
            # 규칙기반 사전은 ko-KR 동의어·라벨만 갖고 있다(카탈로그 default_locale). 다른
            # 언어는 매칭이 우연에 가까우므로 신뢰도를 낮춘다.
            confidence = min(confidence, 0.4)

        required = tuple(
            sorted({t.concept_code for t in matched_terms if t.requirement_level == "REQUIRED"})
        )
        preferred = tuple(
            sorted({t.concept_code for t in matched_terms if t.requirement_level == "PREFERRED"})
        )
        excluded = tuple(
            sorted({t.concept_code for t in matched_terms if t.requirement_level == "EXCLUDED"})
        )
        concept_codes = tuple(sorted({t.concept_code for t in matched_terms}))

        clarification_required = intent == "UNKNOWN"

        return InterpretedQuery(
            raw_query=raw_query,
            normalized_query=normalized,
            channel=resolved_channel,
            language=language,
            intent=intent,
            target_types=target_types_for_intent(intent),
            concept_codes=concept_codes,
            required_concepts=required,
            preferred_concepts=preferred,
            excluded_concepts=excluded,
            confidence=confidence,
            clarification_required=clarification_required,
            clarification=_CLARIFICATION_MESSAGE if clarification_required else None,
            matched_terms=tuple(matched_terms),
        )


class QueryInterpreter:
    """임무가 요구한 정확한 시그니처의 파사드: ``interpret(query, channel, language)``.

    실제 해석은 ``backend``(기본값: ``RuleBasedQueryInterpreter``)에 위임한다. 이후 LLM
    백엔드가 추가되면 ``QueryInterpreter(backend=LlmQueryInterpreterBackend(...))``처럼
    교체만 하면 되고, 호출부는 바뀌지 않는다.
    """

    def __init__(self, backend: QueryInterpreterBackend | None = None) -> None:
        self._backend = backend if backend is not None else RuleBasedQueryInterpreter()

    def interpret(
        self, query: str, channel: str = DEFAULT_CHANNEL, language: str = "ko"
    ) -> InterpretedQuery:
        return self._backend.interpret(query, channel=channel, language=language)
