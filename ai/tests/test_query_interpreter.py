"""QueryInterpreter 단위 테스트.

DB나 apps/api 없이 순수하게 ``meet_ai.ontology`` 카탈로그와 ``ai.query_interpreter``만으로
돌아간다. 커버리지: 한국어 자연어, 동의어 매칭, 복합질의, 결과없음(UNKNOWN 의도), 카탈로그에
없는 코드를 만들어내지 않는다는 것.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from meet_ai.ontology import load_catalog

from ai.query_interpreter import QueryInterpreter
from ai.types import CHANNELS, INTENTS, TARGET_TYPES

_GOLD_SET_PATH = Path(__file__).resolve().parents[1] / "evaluation" / "gold_set.json"


def _load_gold_cases() -> list[dict]:
    payload = json.loads(_GOLD_SET_PATH.read_text(encoding="utf-8"))
    return payload["cases"]


_CATALOG = load_catalog()
_INTERPRETER = QueryInterpreter()
_GOLD_CASES = _load_gold_cases()


def _ids(cases: list[dict]) -> list[str]:
    return [case["id"] for case in cases]


class TestGoldSet:
    """ai/evaluation/gold_set.json의 모든 사례에 대한 회귀 테스트."""

    @pytest.mark.parametrize("case", _GOLD_CASES, ids=_ids(_GOLD_CASES))
    def test_intent_matches_expectation(self, case: dict) -> None:
        result = _INTERPRETER.interpret(
            case["query"], channel=case["channel"], language=case["language"]
        )
        assert result.intent == case["expected_intent"], (
            f"{case['id']}: query={case['query']!r} -> intent={result.intent!r}, "
            f"expected {case['expected_intent']!r}"
        )

    @pytest.mark.parametrize("case", _GOLD_CASES, ids=_ids(_GOLD_CASES))
    def test_target_types_matches_expectation(self, case: dict) -> None:
        result = _INTERPRETER.interpret(
            case["query"], channel=case["channel"], language=case["language"]
        )
        assert sorted(result.target_types) == sorted(case["expected_target_types"])

    @pytest.mark.parametrize("case", _GOLD_CASES, ids=_ids(_GOLD_CASES))
    def test_required_concepts_matches_expectation(self, case: dict) -> None:
        result = _INTERPRETER.interpret(
            case["query"], channel=case["channel"], language=case["language"]
        )
        assert sorted(result.required_concepts) == sorted(case["expected_required_concepts"])

    @pytest.mark.parametrize("case", _GOLD_CASES, ids=_ids(_GOLD_CASES))
    def test_preferred_concepts_matches_expectation(self, case: dict) -> None:
        result = _INTERPRETER.interpret(
            case["query"], channel=case["channel"], language=case["language"]
        )
        assert sorted(result.preferred_concepts) == sorted(case["expected_preferred_concepts"])

    @pytest.mark.parametrize("case", _GOLD_CASES, ids=_ids(_GOLD_CASES))
    def test_excluded_concepts_matches_expectation(self, case: dict) -> None:
        result = _INTERPRETER.interpret(
            case["query"], channel=case["channel"], language=case["language"]
        )
        assert sorted(result.excluded_concepts) == sorted(case["expected_excluded_concepts"])

    @pytest.mark.parametrize("case", _GOLD_CASES, ids=_ids(_GOLD_CASES))
    def test_clarification_required_matches_expectation(self, case: dict) -> None:
        result = _INTERPRETER.interpret(
            case["query"], channel=case["channel"], language=case["language"]
        )
        assert result.clarification_required == case["expected_clarification_required"]
        if result.clarification_required:
            assert result.clarification, f"{case['id']}: UNKNOWN인데 clarification 문구가 없다"

    @pytest.mark.parametrize("case", _GOLD_CASES, ids=_ids(_GOLD_CASES))
    def test_concept_codes_is_union_of_the_three_buckets(self, case: dict) -> None:
        result = _INTERPRETER.interpret(
            case["query"], channel=case["channel"], language=case["language"]
        )
        expected_union = set(result.required_concepts) | set(result.preferred_concepts) | set(
            result.excluded_concepts
        )
        assert set(result.concept_codes) == expected_union

    @pytest.mark.parametrize("case", _GOLD_CASES, ids=_ids(_GOLD_CASES))
    def test_result_shape_is_well_formed(self, case: dict) -> None:
        result = _INTERPRETER.interpret(
            case["query"], channel=case["channel"], language=case["language"]
        )
        assert result.intent in INTENTS
        assert result.channel in CHANNELS
        assert all(t in TARGET_TYPES for t in result.target_types)
        assert 0.0 <= result.confidence <= 1.0
        assert result.raw_query == case["query"]


class TestNeverInventsCodesOutsideCatalog:
    """카탈로그에 없는 코드를 리턴하면 안 된다 - DECISION-004의 핵심 회귀 방지."""

    def _assert_all_codes_are_real(self, codes: tuple[str, ...]) -> None:
        for code in codes:
            assert code in _CATALOG.by_code, f"카탈로그에 없는 코드가 생성됨: {code!r}"

    @pytest.mark.parametrize("case", _GOLD_CASES, ids=_ids(_GOLD_CASES))
    def test_gold_set_codes_are_all_real(self, case: dict) -> None:
        result = _INTERPRETER.interpret(
            case["query"], channel=case["channel"], language=case["language"]
        )
        self._assert_all_codes_are_real(result.concept_codes)
        self._assert_all_codes_are_real(result.required_concepts)
        self._assert_all_codes_are_real(result.preferred_concepts)
        self._assert_all_codes_are_real(result.excluded_concepts)

    @pytest.mark.parametrize(
        "query",
        [
            "탁주 막걸리 증류주 맥주 와인 쌀 포도 서울 경기 부산 시음 상담 OEM PB 수출 온라인몰",
            "드라이하고 부드럽고 산뜻하고 진한 술 추천해줘 선물용으로 5만원대",
            "존재하지 않는 산업용 특수합금 부품 제조업체를 찾아줘 INDUSTRY.MANUFACTURING",
            "asdkjaslkdj alksjdlkasjd 123456 !@#$%^",
            "",
            "   ",
        ],
    )
    def test_adversarial_queries_never_invent_codes(self, query: str) -> None:
        result = _INTERPRETER.interpret(query, channel="WEB", language="ko")
        self._assert_all_codes_are_real(result.concept_codes)
        self._assert_all_codes_are_real(result.required_concepts)
        self._assert_all_codes_are_real(result.preferred_concepts)
        self._assert_all_codes_are_real(result.excluded_concepts)

    def test_redesign_doc_example_codes_are_never_produced(self) -> None:
        """docs/vibe-coding-master-spec-v1.md §30 예시 코드(INDUSTRY.*, TECH.* 등)는 DECISION-004로
        폐기됐다 - 문자 그대로 그 코드를 언급하는 질의를 줘도 그 코드를 리턴하면 안 된다."""

        result = _INTERPRETER.interpret(
            "INDUSTRY.TOURISM TECH.AI SERVICE.MULTILINGUAL_GUIDE 다국어 안내 업체",
            channel="WEB",
            language="ko",
        )
        forbidden = {"INDUSTRY.TOURISM", "TECH.AI", "SERVICE.MULTILINGUAL_GUIDE"}
        assert forbidden.isdisjoint(result.concept_codes)


class TestEmptyAndWhitespaceQueries:
    def test_empty_query_is_unknown_and_requests_clarification(self) -> None:
        result = _INTERPRETER.interpret("", channel="WEB", language="ko")
        assert result.intent == "UNKNOWN"
        assert result.clarification_required is True
        assert result.clarification
        assert result.concept_codes == ()

    def test_whitespace_only_query_is_unknown(self) -> None:
        result = _INTERPRETER.interpret("     ", channel="KIOSK", language="ko")
        assert result.intent == "UNKNOWN"
        assert result.clarification_required is True


class TestChannelHandling:
    def test_invalid_channel_falls_back_to_web(self) -> None:
        result = _INTERPRETER.interpret("탁주 파는 업체 알려주세요", channel="MOBILE_APP", language="ko")
        assert result.channel == "WEB"

    @pytest.mark.parametrize("channel", list(CHANNELS))
    def test_valid_channels_are_preserved(self, channel: str) -> None:
        result = _INTERPRETER.interpret("탁주 파는 업체 알려주세요", channel=channel, language="ko")
        assert result.channel == channel


class TestSynonymDictionaryIsActuallyUsed:
    """카탈로그 synonym 테이블(11개 항목)이 실제로 참조되는지, 근거(source)가 SYNONYM으로
    남는지 직접 확인한다(임무 지시: "동의어 사전(카탈로그의 synonym)" 단계가 실제로 동작해야
    한다)."""

    def test_synonym_source_recorded_for_matched_term(self) -> None:
        result = _INTERPRETER.interpret("막걸리 있나요", channel="WEB", language="ko")
        takju_terms = [t for t in result.matched_terms if t.concept_code == "ALCOHOL.TAKJU"]
        assert takju_terms, "동의어 '막걸리' -> ALCOHOL.TAKJU가 인식되지 않았다"
        assert takju_terms[0].source == "SYNONYM"
        assert takju_terms[0].matched_text == "막걸리"
