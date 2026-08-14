from __future__ import annotations

from app.services.conversation_policy import (
    CONVERSATION_POLICY_VERSION,
    interpret_message,
    mask_sensitive_text,
)


def test_general_request_is_structured_without_auto_confirmation() -> None:
    decision = interpret_message(
        "부모님 선물용으로 5만 원 이하의 드라이한 증류주를 찾고 있어요.",
        user_type="GENERAL_VISITOR",
    )

    entities = {item.attribute_code: item for item in decision.entities}
    assert {
        "GOAL.GIFT_SEARCH",
        "ALCOHOL.DISTILLED",
        "TASTE.DRY",
        "PRICE_BAND.K20_TO_K50",
    } <= entities.keys()
    assert entities["PRICE_BAND.K20_TO_K50"].value == {
        "max": 50_000,
        "currency": "KRW",
    }
    assert all(item.status == "PROPOSED" for item in decision.entities)
    assert decision.next_action == "CONFIRM_PROFILE_UPDATE"
    assert decision.recommendation_ready
    assert decision.policy_version == CONVERSATION_POLICY_VERSION
    assert len(decision.input_fingerprint) == 64


def test_required_and_excluded_conditions_are_distinguished() -> None:
    decision = interpret_message(
        "서울 공급은 반드시 가능해야 하고 단맛 강한 건 빼줘.",
        user_type="BUYER",
    )

    entities = {item.attribute_code: item for item in decision.entities}
    assert entities["REGION.KR.SEOUL"].requirement_level == "REQUIRED"
    assert entities["TASTE.SWEET"].requirement_level == "EXCLUDED"
    assert entities["TASTE.SWEET"].operator == "NOT_IN"


def test_ambiguous_small_quantity_is_not_invented() -> None:
    decision = interpret_message(
        "소량으로 먼저 거래하고 싶어요.",
        user_type="BUYER",
    )

    assert decision.entities == ()
    assert decision.ambiguities == ("SMALL_QUANTITY",)
    assert decision.next_action == "ASK_CLARIFICATION"
    assert decision.next_question is not None
    assert "발주수량" in decision.next_question.text


def test_exact_bottle_quantity_is_preserved_with_unit() -> None:
    decision = interpret_message(
        "서울 바틀샵에 증류주 200병 정도 납품할 업체를 찾아줘.",
        user_type="BUYER",
    )

    quantity = next(
        item
        for item in decision.entities
        if item.attribute_code == "ORDER.INITIAL_QUANTITY"
    )
    assert quantity.value == {"count": 200}
    assert quantity.unit == "BOTTLE"
    assert quantity.operator == "APPROXIMATE"
    assert decision.recommendation_ready


def test_direct_identifiers_are_masked_before_policy_processing() -> None:
    text = "010-1234-5678 또는 buyer@example.com으로 연락해 주세요."

    assert mask_sensitive_text(text) == (
        "[PHONE] 또는 [EMAIL]으로 연락해 주세요."
    )
    decision = interpret_message(text, user_type="BUYER")
    assert "010-1234-5678" not in decision.assistant_message
    assert "buyer@example.com" not in decision.assistant_message
