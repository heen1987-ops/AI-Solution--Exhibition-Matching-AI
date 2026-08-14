"""AI-BUYER-MATCH(WAVE 2C) 트랙이 산출하는 매칭/정보 사유 코드의 유일한 진실 공급원.

이 모듈이 정의하는 값은 임무 지시가 명시한 닫힌 집합(MATCH.* 10개, INFO.* 4개) 그대로다.
``ai/buyer_matching`` 어디에서도 이 밖의 새 MATCH.*/INFO.* 코드를 만들어내지 않는다 - 이는
온톨로지 개념 코드(``src/meet_ai/ontology/catalog.v1.json``)와는 별개의, 이 매칭엔진 전용
설명가능성 코드 체계다.
"""

from __future__ import annotations

# --- 긍정 매칭 사유 -----------------------------------------------------
MATCH_PRODUCT = "MATCH.PRODUCT"
MATCH_TECHNOLOGY = "MATCH.TECHNOLOGY"
MATCH_BUSINESS_GOAL = "MATCH.BUSINESS_GOAL"
MATCH_CHANNEL = "MATCH.CHANNEL"
MATCH_ORDER_SCALE = "MATCH.ORDER_SCALE"
MATCH_MOQ = "MATCH.MOQ"
MATCH_REGION = "MATCH.REGION"
MATCH_COOPERATION = "MATCH.COOPERATION"
MATCH_TRADE_READINESS = "MATCH.TRADE_READINESS"
MATCH_MUTUAL_PREFERENCE = "MATCH.MUTUAL_PREFERENCE"

# --- 정보 필요(신호가 없거나 조건부임을 알리는) 사유 ---------------------
INFO_MOQ_UNKNOWN = "INFO.MOQ_UNKNOWN"
INFO_REGION_UNKNOWN = "INFO.REGION_UNKNOWN"
INFO_LEAD_TIME_UNKNOWN = "INFO.LEAD_TIME_UNKNOWN"
INFO_TRADE_CONDITION_CONDITIONAL = "INFO.TRADE_CONDITION_CONDITIONAL"

MATCH_REASON_CODES: frozenset[str] = frozenset(
    {
        MATCH_PRODUCT,
        MATCH_TECHNOLOGY,
        MATCH_BUSINESS_GOAL,
        MATCH_CHANNEL,
        MATCH_ORDER_SCALE,
        MATCH_MOQ,
        MATCH_REGION,
        MATCH_COOPERATION,
        MATCH_TRADE_READINESS,
        MATCH_MUTUAL_PREFERENCE,
    }
)

INFO_REASON_CODES: frozenset[str] = frozenset(
    {
        INFO_MOQ_UNKNOWN,
        INFO_REGION_UNKNOWN,
        INFO_LEAD_TIME_UNKNOWN,
        INFO_TRADE_CONDITION_CONDITIONAL,
    }
)

ALL_REASON_CODES: frozenset[str] = MATCH_REASON_CODES | INFO_REASON_CODES


def dedupe_preserve_order(codes: list[str]) -> tuple[str, ...]:
    """순서를 보존하며 중복을 제거한다 (set은 순서가 비결정적이라 쓰지 않는다)."""

    seen: set[str] = set()
    ordered: list[str] = []
    for code in codes:
        if code not in seen:
            seen.add(code)
            ordered.append(code)
    return tuple(ordered)
