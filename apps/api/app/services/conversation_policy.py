"""Deterministic stage-19 conversation interpretation boundary.

The policy extracts only a small, published set of ontology-backed conditions.
It never ranks recommendations and never writes directly to a profile.  A user
must confirm every proposed extraction through the conversation API first.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from typing import Any

CONVERSATION_POLICY_VERSION = "conversation-policy-v1.0-deterministic"

_EMAIL = re.compile(r"(?i)[a-z0-9._%+-]+@[a-z0-9.-]+\.[a-z]{2,}")
_PHONE = re.compile(r"(?<!\d)01[016789][ -]?\d{3,4}[ -]?\d{4}(?!\d)")
_RESIDENT_ID = re.compile(r"(?<!\d)\d{6}[ -]?[1-4]\d{6}(?!\d)")
_PRICE = re.compile(
    r"(?P<amount>\d+(?:\.\d+)?)\s*만\s*원?\s*"
    r"(?P<qualifier>이하|미만|안쪽|정도|대|까지)?"
)
_BOTTLES = re.compile(r"(?<!\d)(?P<count>\d{1,6})\s*병")

_CODE_RULES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("GOAL.GIFT_SEARCH", ("선물",)),
    ("GOAL.TASTING", ("시음", "맛보고")),
    ("GOAL.ON_SITE_PURCHASE", ("현장구매", "구매")),
    ("BIZ_GOAL.NEW_SUPPLIER", ("공급업체", "거래처 발굴")),
    ("BIZ_GOAL.DISTRIBUTION", ("입점", "납품", "유통")),
    ("BIZ_GOAL.OEM", ("oem",)),
    ("BIZ_GOAL.PRIVATE_LABEL", ("pb", "자체 브랜드", "자체브랜드")),
    ("BIZ_GOAL.EXPORT", ("수출",)),
    ("ALCOHOL.SOJU_DISTILLED", ("전통소주", "증류식 소주")),
    ("ALCOHOL.DISTILLED", ("증류주",)),
    ("ALCOHOL.TAKJU", ("막걸리", "탁주")),
    ("ALCOHOL.YAKJU", ("약주",)),
    ("ALCOHOL.CHEONGJU", ("청주",)),
    ("ALCOHOL.FRUIT_WINE", ("과실주",)),
    ("TASTE.DRY", ("드라이", "깔끔한")),
    ("TASTE.SMOOTH", ("부드러운", "부드럽게")),
    ("TASTE.FRESH", ("산뜻한", "상큼한")),
    ("CHANNEL.BOTTLE_SHOP", ("바틀샵", "주류 전문점")),
    ("CHANNEL.ONLINE_MALL", ("온라인몰", "온라인 몰")),
    ("REGION.KR.SEOUL", ("서울",)),
    ("REGION.KR.GYEONGGI", ("경기", "경기도")),
)

_GOAL_PREFIXES = ("GOAL.", "BIZ_GOAL.")
_PREFERENCE_PREFIXES = ("ALCOHOL.", "TASTE.", "CHANNEL.", "REGION.", "PRICE_BAND.")
_REQUIRED_MARKERS = ("반드시", "무조건", "꼭", "필수")
_EXCLUDE_MARKERS = ("빼줘", "제외", "싫", "안 돼", "안돼")


@dataclass(frozen=True)
class ExtractedCondition:
    attribute_code: str
    operator: str
    value: dict[str, Any]
    unit: str | None
    requirement_level: str
    source_text: str
    confidence: float
    status: str = "PROPOSED"


@dataclass(frozen=True)
class ClarificationQuestion:
    code: str
    text: str
    options: tuple[str, ...]


@dataclass(frozen=True)
class ConversationDecision:
    intent_code: str
    intent_confidence: float
    entities: tuple[ExtractedCondition, ...]
    ambiguities: tuple[str, ...]
    next_action: str
    next_question: ClarificationQuestion | None
    recommendation_ready: bool
    assistant_message: str
    policy_version: str
    input_fingerprint: str


def mask_sensitive_text(text: str) -> str:
    """Remove direct identifiers before persistence or any future model call."""

    masked = _EMAIL.sub("[EMAIL]", text)
    masked = _PHONE.sub("[PHONE]", masked)
    return _RESIDENT_ID.sub("[RESIDENT_ID]", masked)


def content_fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _requirement(text: str, *, excluded: bool = False) -> str:
    if excluded:
        return "EXCLUDED"
    if any(marker in text for marker in _REQUIRED_MARKERS):
        return "REQUIRED"
    return "PREFERRED"


def _price_band(max_amount: int) -> str:
    if max_amount <= 20_000:
        return "PRICE_BAND.UNDER_20K"
    if max_amount <= 50_000:
        return "PRICE_BAND.K20_TO_K50"
    if max_amount <= 100_000:
        return "PRICE_BAND.K50_TO_K100"
    return "PRICE_BAND.OVER_100K"


def _extract_conditions(text: str) -> tuple[ExtractedCondition, ...]:
    lowered = text.lower()
    entities: list[ExtractedCondition] = []
    seen: set[str] = set()

    sweet_excluded = "달지 않" in lowered or (
        "단맛" in lowered and any(marker in lowered for marker in _EXCLUDE_MARKERS)
    )
    if sweet_excluded:
        entities.append(
            ExtractedCondition(
                attribute_code="TASTE.SWEET",
                operator="NOT_IN",
                value={"selected": True},
                unit=None,
                requirement_level="EXCLUDED",
                source_text="달지 않은",
                confidence=0.98,
            )
        )
        seen.add("TASTE.SWEET")
    elif "달콤" in lowered or "단맛" in lowered:
        entities.append(
            ExtractedCondition(
                attribute_code="TASTE.SWEET",
                operator="IN",
                value={"selected": True},
                unit=None,
                requirement_level=_requirement(lowered),
                source_text="달콤함",
                confidence=0.96,
            )
        )
        seen.add("TASTE.SWEET")

    for code, phrases in _CODE_RULES:
        phrase = next((item for item in phrases if item in lowered), None)
        if phrase is None or code in seen:
            continue
        if code == "ALCOHOL.DISTILLED" and (
            "전통소주" in lowered or "증류식 소주" in lowered
        ):
            continue
        entities.append(
            ExtractedCondition(
                attribute_code=code,
                operator="IN",
                value={"selected": True},
                unit=None,
                requirement_level=_requirement(lowered),
                source_text=phrase,
                confidence=0.96,
            )
        )
        seen.add(code)

    price = _PRICE.search(lowered)
    if price is not None:
        amount = int(float(price.group("amount")) * 10_000)
        qualifier = price.group("qualifier") or "정도"
        code = _price_band(amount)
        entities.append(
            ExtractedCondition(
                attribute_code=code,
                operator=("LESS_THAN" if qualifier == "미만" else "LESS_THAN_OR_EQUAL"),
                value={"max": amount, "currency": "KRW"},
                unit="KRW",
                requirement_level=_requirement(lowered),
                source_text=price.group(0).strip(),
                confidence=0.99,
            )
        )

    quantity = _BOTTLES.search(lowered)
    if quantity is not None:
        entities.append(
            ExtractedCondition(
                attribute_code="ORDER.INITIAL_QUANTITY",
                operator="APPROXIMATE" if "정도" in lowered else "EQUAL",
                value={"count": int(quantity.group("count"))},
                unit="BOTTLE",
                requirement_level=_requirement(lowered),
                source_text=quantity.group(0),
                confidence=0.98,
            )
        )

    return tuple(entities)


def _ambiguities(text: str) -> tuple[str, ...]:
    lowered = text.lower()
    found: list[str] = []
    if "가벼운" in lowered or "가볍게" in lowered:
        found.append("LIGHT_MEANING")
    if "독하지 않" in lowered:
        found.append("LOW_ALCOHOL_MEANING")
    if "소량" in lowered and _BOTTLES.search(lowered) is None:
        found.append("SMALL_QUANTITY")
    return tuple(found)


def _clarification(ambiguities: tuple[str, ...]) -> ClarificationQuestion | None:
    if "LIGHT_MEANING" in ambiguities:
        return ClarificationQuestion(
            code="CLARIFY.LIGHT_MEANING",
            text="‘가벼운 술’에서 어떤 조건을 더 중요하게 볼까요?",
            options=("낮은 도수", "산뜻한 맛", "둘 다"),
        )
    if "LOW_ALCOHOL_MEANING" in ambiguities:
        return ClarificationQuestion(
            code="CLARIFY.LOW_ALCOHOL_MEANING",
            text="‘독하지 않은 술’은 낮은 도수와 부드러운 맛 중 어느 쪽인가요?",
            options=("낮은 도수", "부드러운 맛", "둘 다"),
        )
    if "SMALL_QUANTITY" in ambiguities:
        return ClarificationQuestion(
            code="CLARIFY.SMALL_QUANTITY",
            text="초기 발주수량을 어느 정도로 예상하나요?",
            options=("50병 이하", "51~100병", "101~300병", "직접 입력"),
        )
    return None


def _intent(text: str, entities: tuple[ExtractedCondition, ...]) -> tuple[str, float]:
    lowered = text.lower()
    if any(marker in lowered for marker in ("왜 추천", "추천 이유")):
        return "INTENT.ASK_REASON", 0.99
    if "비교" in lowered:
        return "INTENT.COMPARE", 0.98
    if any(marker in lowered for marker in ("빼줘", "삭제", "제외해")):
        return "INTENT.REMOVE", 0.96
    if any(marker in lowered for marker in ("추천", "찾고", "보여줘")):
        return "INTENT.REQUEST_RECOMMENDATION", 0.94
    if any(item.attribute_code.startswith(_GOAL_PREFIXES) for item in entities):
        return "INTENT.SET_GOAL", 0.93
    if entities:
        return "INTENT.SET_CONSTRAINT", 0.91
    return "INTENT.UNKNOWN", 0.35


def _ready(
    *,
    user_type: str,
    entities: tuple[ExtractedCondition, ...],
    existing_codes: frozenset[str],
) -> bool:
    codes = existing_codes | frozenset(item.attribute_code for item in entities)
    has_goal = any(code.startswith(_GOAL_PREFIXES) for code in codes)
    has_preference = any(code.startswith(_PREFERENCE_PREFIXES) for code in codes)
    if user_type == "BUYER":
        return (
            any(code.startswith("BIZ_GOAL.") for code in codes)
            and any(code.startswith("ALCOHOL.") for code in codes)
            and any(code.startswith("CHANNEL.") for code in codes)
        )
    return has_goal and has_preference


def interpret_message(
    text: str,
    *,
    user_type: str,
    existing_codes: frozenset[str] = frozenset(),
) -> ConversationDecision:
    """Interpret one turn without mutating the user's confirmed profile."""

    masked = mask_sensitive_text(text.strip())
    entities = _extract_conditions(masked)
    ambiguities = _ambiguities(masked)
    intent_code, intent_confidence = _intent(masked, entities)
    question = _clarification(ambiguities)
    ready = _ready(user_type=user_type, entities=entities, existing_codes=existing_codes)

    if question is not None:
        next_action = "ASK_CLARIFICATION"
        assistant_message = question.text
    elif entities:
        next_action = "CONFIRM_PROFILE_UPDATE"
        assistant_message = (
            "이해한 조건을 확인해 주세요. 확인된 조건만 추천 프로파일에 반영합니다."
        )
    elif ready:
        next_action = "GENERATE_RECOMMENDATION"
        assistant_message = "확인된 조건으로 추천을 생성할 수 있습니다."
    else:
        next_action = "ASK_GOAL"
        assistant_message = "이번 방문에서 가장 중요한 목적을 알려주세요."

    fingerprint_input = {
        "policy_version": CONVERSATION_POLICY_VERSION,
        "masked_text": masked,
        "user_type": user_type,
        "existing_codes": sorted(existing_codes),
        "intent": intent_code,
        "entities": [asdict(item) for item in entities],
        "ambiguities": ambiguities,
        "next_action": next_action,
    }
    fingerprint = content_fingerprint(
        json.dumps(
            fingerprint_input,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
    )
    return ConversationDecision(
        intent_code=intent_code,
        intent_confidence=intent_confidence,
        entities=entities,
        ambiguities=ambiguities,
        next_action=next_action,
        next_question=question,
        recommendation_ready=ready,
        assistant_message=assistant_message,
        policy_version=CONVERSATION_POLICY_VERSION,
        input_fingerprint=fingerprint,
    )
