"""KeywordRetriever의 순수 스코어링 계층(``score_candidate``) 단위 테스트.

DB에 의존하는 ``retrieve()``의 SQL 조회 경로는 여기서 다루지 않는다(postgres_integration
마커 없이 실행되는 이 스위트는 라이브 Postgres가 없어도 항상 통과해야 한다 - 저장소 전반의
관례, apps/api/pyproject.toml의 ``postgres_integration`` 마커 참고).
"""

from __future__ import annotations

from meet_ai.ontology import load_catalog

from ai.keyword_retriever import score_candidate
from ai.query_interpreter import QueryInterpreter

_CATALOG = load_catalog()
_INTERPRETER = QueryInterpreter()


def test_required_concepts_across_different_types_are_and_ed() -> None:
    """서로 다른 개념유형의 required는 전부 만족해야 후보가 살아남는다."""

    query = _INTERPRETER.interpret("서울 지역 바틀샵 납품 정기 납품 탁주", channel="WEB", language="ko")
    assert set(query.required_concepts) == {
        "REGION.KR.SEOUL",
        "CHANNEL.BOTTLE_SHOP",
        "TRADE.REGULAR_SUPPLY",
        "ALCOHOL.TAKJU",
    }

    # 네 조건을 모두 만족하는 후보 -> 적격.
    full_match = score_candidate(
        _CATALOG,
        {"REGION.KR.SEOUL", "CHANNEL.BOTTLE_SHOP", "TRADE.REGULAR_SUPPLY", "ALCOHOL.TAKJU"},
        "탁주 서울 바틀샵 정기납품",
        query,
    )
    assert full_match.eligible is True
    assert full_match.required_hit_count == 4

    # 지역조건 하나만 빠져도 부적격(AND).
    missing_region = score_candidate(
        _CATALOG,
        {"CHANNEL.BOTTLE_SHOP", "TRADE.REGULAR_SUPPLY", "ALCOHOL.TAKJU"},
        "탁주 바틀샵 정기납품",
        query,
    )
    assert missing_region.eligible is False


def test_required_concepts_within_same_type_are_or_ed() -> None:
    """같은 개념유형 안의 여러 required 값은 하나만 겹쳐도(OR) 통과한다."""

    # required_concepts에 REGION 두 개를 직접 넣어 같은 유형 내 OR을 확인한다.
    query = _INTERPRETER.interpret("서울 부산 지역 탁주 업체", channel="WEB", language="ko")
    assert {"REGION.KR.SEOUL", "REGION.KR.BUSAN"}.issubset(set(query.required_concepts))

    seoul_only = score_candidate(
        _CATALOG, {"REGION.KR.SEOUL", "ALCOHOL.TAKJU"}, "서울 탁주", query
    )
    assert seoul_only.eligible is True

    neither_region = score_candidate(_CATALOG, {"ALCOHOL.TAKJU"}, "탁주만", query)
    assert neither_region.eligible is False


def test_excluded_concept_rejects_candidate() -> None:
    query = _INTERPRETER.interpret("탁주 말고 증류주로 만든 술 추천해줘", channel="WEB", language="ko")
    assert query.excluded_concepts == ("ALCOHOL.TAKJU",)
    assert query.required_concepts == ("ALCOHOL.DISTILLED",)

    rejected = score_candidate(_CATALOG, {"ALCOHOL.TAKJU"}, "탁주 제품", query)
    assert rejected.eligible is False

    accepted = score_candidate(_CATALOG, {"ALCOHOL.DISTILLED"}, "증류주 제품", query)
    assert accepted.eligible is True


def test_preferred_concepts_never_reject_but_boost_score() -> None:
    query = _INTERPRETER.interpret("선물하기 좋은 술 찾고 있어요", channel="WEB", language="ko")
    assert query.required_concepts == ()
    assert query.preferred_concepts == ("USE.GIFT",)

    without_preferred = score_candidate(_CATALOG, set(), "이름 모를 제품", query)
    assert without_preferred.eligible is True
    assert without_preferred.preferred_hit_count == 0

    with_preferred = score_candidate(_CATALOG, {"USE.GIFT"}, "선물용 제품", query)
    assert with_preferred.eligible is True
    assert with_preferred.preferred_hit_count == 1
    assert with_preferred.keyword_score > without_preferred.keyword_score


def test_no_required_or_preferred_concepts_is_always_eligible() -> None:
    query = _INTERPRETER.interpret("오늘 점심 뭐 먹지?", channel="WEB", language="ko")
    assert query.required_concepts == ()
    assert query.preferred_concepts == ()

    result = score_candidate(_CATALOG, set(), "아무 제품", query)
    assert result.eligible is True
    assert result.keyword_score == 0.0
