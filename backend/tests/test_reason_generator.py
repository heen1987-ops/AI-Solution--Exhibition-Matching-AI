from __future__ import annotations

from decimal import Decimal

from meet_ai.scoring import DirectionalScoreResult

from app.services.matching.reason_generator import generate_directional_reasons


def _result(contributions: dict[str, Decimal]) -> DirectionalScoreResult:
    return DirectionalScoreResult(
        policy_version="TEST_V1",
        audience="CONSUMER",
        eligibility_evaluation_id="eval-test",
        component_values=dict(contributions),
        effective_weights={key: Decimal(1) for key in contributions},
        contributions=contributions,
        missing_components=(),
        uncapped_score=Decimal("0.9"),
        final_score=Decimal("90.00"),
        grade=None,
        confidence=None,
        cap_rules=(),
        applied_cap_codes=(),
        calculation_fingerprint="fingerprint-test",
    )


def test_top_contributor_produces_first_reason() -> None:
    result = _result({"price": Decimal("0.5"), "sensory": Decimal("0.2")})

    reasons = generate_directional_reasons(result)

    assert reasons[0].reason_code == "PRICE_MATCH"
    assert reasons[0].display_order == 0


def test_reasons_are_ordered_by_contribution_descending() -> None:
    result = _result(
        {"category": Decimal("0.1"), "price": Decimal("0.6"), "sensory": Decimal("0.3")}
    )

    reasons = generate_directional_reasons(result)

    assert [reason.reason_code for reason in reasons] == [
        "PRICE_MATCH",
        "SENSORY_MATCH",
        "CATEGORY_MATCH",
    ]


def test_reason_text_never_mentions_internal_component_name() -> None:
    """05단계 5.11절 "금지 근거": 내부 구성요소 코드명을 문장에 그대로 노출하지 않는다."""

    result = _result({"sensory": Decimal("0.4")})

    reasons = generate_directional_reasons(result)

    assert "sensory" not in reasons[0].reason_text
    assert "SENSORY" not in reasons[0].reason_text


def test_max_reasons_caps_output() -> None:
    result = _result(
        {
            "price": Decimal("0.9"),
            "category": Decimal("0.8"),
            "sensory": Decimal("0.7"),
            "alcohol": Decimal("0.6"),
        }
    )

    reasons = generate_directional_reasons(result, max_reasons=2)

    assert len(reasons) == 2


def test_unmapped_component_is_skipped_not_fabricated() -> None:
    result = _result({"trust": Decimal("0.5"), "price": Decimal("0.1")})

    reasons = generate_directional_reasons(result)

    assert [reason.reason_code for reason in reasons] == ["PRICE_MATCH"]


def test_no_mapped_contributions_falls_back_to_general_reason() -> None:
    result = _result({"trust": Decimal("0.5")})

    reasons = generate_directional_reasons(result)

    assert len(reasons) == 1
    assert reasons[0].reason_code == "GENERAL_MATCH"
