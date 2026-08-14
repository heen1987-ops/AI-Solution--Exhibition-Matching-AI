"""``ai/schemas/extraction/attribute_schema.json``의 critical/trade_condition 플래그를
Python 코드 import 없이 읽는 얇은 로더.

왜 ``ai.extraction.attribute_schema.load_attribute_schema()``를 직접 import하지 않는가
-----------------------------------------------------------------------------------------
``ai/`` 최상위 패키지는 저장소 루트 바로 아래에 있고, ``apps/api``의 pytest 설정
(``apps/api/pyproject.toml``의 ``pythonpath = [".", "../src"]``)은 저장소 루트를 포함하지
않는다 - 실제로 ``apps/api/tests/test_ai_buyer_matching.py``가 ``from ai.buyer_matching import
reason_codes``를 시도하다가 ``ModuleNotFoundError: No module named 'ai'``로 이미 깨져 있는
것으로 확인했다(이 트랙 시작 전부터 있던 기존 상태 - 내가 만든 회귀가 아니다). 같은 함정을
반복하지 않기 위해 이 모듈은 **데이터 파일**(``attribute_schema.json``, JSON이라 패키지
경계와 무관)만 읽고 ``ai/extraction/**``의 어떤 ``.py``도 import하지 않는다.

``ai/extraction/types.py``가 정확히 같은 이유로 WORKER-PARSING의 ``TextSegment``를 import
대신 duck-typing으로 재구현한 선례를 그대로 따른 것이다.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

# apps/api/app/services/extraction/attribute_schema.py 기준 5단계 위가 저장소 루트다
# (.harness/decisions.md DECISION-006이 경고한 "parents[N] 하드코딩" 함정을 피하기 위해
# 마이그레이션 뒤의 실제 깊이로 다시 계산했다: extraction -> services -> app -> api -> apps -> root).
_REPO_ROOT = Path(__file__).resolve().parents[5]
_SCHEMA_PATH = _REPO_ROOT / "ai" / "schemas" / "extraction" / "attribute_schema.json"


@dataclass(frozen=True)
class AttributeFlags:
    attribute_code: str
    critical: bool
    trade_condition: bool
    applies_to: tuple[str, ...]


@lru_cache(maxsize=1)
def load_attribute_flags(path: str | Path | None = None) -> dict[str, AttributeFlags]:
    """``attribute_code -> AttributeFlags`` 맵. 파일이 없거나 읽을 수 없으면 빈 맵을 반환한다
    (이 정보는 submit-review의 "critical trade-condition UNKNOWN 확인" 검증을 더 정확하게
    만드는 보조 신호일 뿐, 이 파일이 없다고 해서 라우터 전체가 죽어서는 안 된다 - AI-EXTRACTION
    트랙이 스키마 파일 경로를 바꾸더라도 이 트랙이 그 이유만으로 500을 내지 않게 한다)."""

    target = Path(path) if path is not None else _SCHEMA_PATH
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}

    result: dict[str, AttributeFlags] = {}
    for item in payload.get("attributes", ()):
        code = item.get("attribute_code")
        if not code:
            continue
        result[code] = AttributeFlags(
            attribute_code=code,
            critical=bool(item.get("critical", False)),
            trade_condition=bool(item.get("trade_condition", False)),
            applies_to=tuple(item.get("applies_to", ())),
        )
    return result


def is_critical_trade_condition(attribute_code: str) -> bool:
    flags = load_attribute_flags().get(attribute_code)
    return bool(flags and flags.critical and flags.trade_condition)
