"""추출 속성(attribute_code)별 기본 공개등급(visibility) 정책 - 단일 진실 공급원.

왜 이 모듈이 필요한가 (통합 MERGE STEP 16 (a))
------------------------------------------------
통합 전 ``services/extraction/ingestion.py``는 ``default_visibility: str = "PUBLIC"``을
**모든** 추출 속성에 그대로 찍었다. 그 결과 ``ai/schemas/extraction/attribute_schema.json``의
``trade_condition: true`` 아홉 개 코드(도매 결제조건·MOQ·리드타임 등)와 ``product.price_krw``
까지 PUBLIC 등급으로 저장됐고, ``document.published_content_version``의 visibility='PUBLIC'
행만 필터하는 공개 검색문서 파이프라인이 그것을 그대로 익명 공개면(웹/키오스크)에 실었다.

제품 불변식("거래조건·연락처는 세 게이트를 통과하기 전에는 공개되지 않는다")을 지키려면
거래조건 계열과 가격은 기본값이 PUBLIC이 아니라 VERIFIED_BUYER여야 한다.

fail-loud 원칙
---------------
이 정책의 근거 데이터는 ``ai/schemas/extraction/attribute_schema.json``이다. 그 파일을
읽지 못하면 조용히 "제한 없음"으로 떨어지지 않고 :class:`AttributeSchemaUnavailableError`
를 던진다 - 스키마를 못 읽는 상황에서 기본값 PUBLIC으로 폴백하는 것이 정확히 이 결함의
원인이었기 때문이다(같은 저장소 ``app/services/extraction/attribute_schema.py``의 관대한
``{}`` 폴백은 submit-review 보조 신호용이라 그대로 두되, 공개등급 결정에는 쓰지 않는다).
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

__all__ = [
    "PUBLIC_TIER",
    "VERIFIED_BUYER_TIER",
    "AttributeSchemaUnavailableError",
    "forbidden_public_attribute_codes",
    "resolve_default_visibility",
    "restricted_attribute_codes",
]

PUBLIC_TIER = "PUBLIC"
VERIFIED_BUYER_TIER = "VERIFIED_BUYER"

# apps/api/app/services/extraction/visibility.py 기준 5단계 위가 저장소 루트다
# (extraction -> services -> app -> api -> apps -> root).
_REPO_ROOT = Path(__file__).resolve().parents[5]
_SCHEMA_PATH = _REPO_ROOT / "ai" / "schemas" / "extraction" / "attribute_schema.json"

#: 스키마의 trade_condition 플래그와 무관하게 항상 제한되는 코드.
#: 가격은 trade_condition:false지만 "비공개 가격은 PUBLIC 문서에서 제외"가 트랙 GOAL에
#: 명시돼 있다(app/services/indexing/document_builder.py 모듈 docstring).
_ALWAYS_RESTRICTED: frozenset[str] = frozenset({"product.price_krw"})


class AttributeSchemaUnavailableError(RuntimeError):
    """공개등급 판정의 근거 스키마를 읽을 수 없다 - 공개 쪽으로 폴백하지 않는다."""


@lru_cache(maxsize=1)
def restricted_attribute_codes() -> frozenset[str]:
    """PUBLIC 등급을 기본값으로 가질 수 없는 attribute_code 집합.

    = 스키마의 ``trade_condition: true`` 전부 + :data:`_ALWAYS_RESTRICTED`.
    """

    try:
        payload = json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:  # pragma: no cover - 방어적
        raise AttributeSchemaUnavailableError(str(_SCHEMA_PATH)) from exc

    attributes = payload.get("attributes")
    if not attributes:
        raise AttributeSchemaUnavailableError(
            f"{_SCHEMA_PATH}: 'attributes' is empty or missing"
        )

    codes = {
        item["attribute_code"]
        for item in attributes
        if item.get("attribute_code") and item.get("trade_condition")
    }
    return frozenset(codes | _ALWAYS_RESTRICTED)


def resolve_default_visibility(
    attribute_code: str, *, default_visibility: str = PUBLIC_TIER
) -> str:
    """``attribute_code``에 적용할 기본 공개등급을 돌려준다.

    제한 대상 코드는 호출자가 무엇을 요청했든 최소 VERIFIED_BUYER로 좁힌다 - 호출자가
    이미 더 엄격한 등급(예: OPERATOR_ONLY)을 지정했다면 그 값을 그대로 존중한다.
    """

    if attribute_code not in restricted_attribute_codes():
        return default_visibility
    if default_visibility in (PUBLIC_TIER, "REGISTERED_USER"):
        return VERIFIED_BUYER_TIER
    return default_visibility


def forbidden_public_attribute_codes() -> frozenset[str]:
    """PUBLIC 티어 문서에 실리면 안 되는 attribute_code 집합(거부목록)."""

    return restricted_attribute_codes()
