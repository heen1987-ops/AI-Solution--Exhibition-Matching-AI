from __future__ import annotations

import uuid

from app.services.matching.hard_filter_engine import (
    FilterContext,
    FilterOutcome,
    HardFilterRule,
    evaluate_candidate,
    rule_capacity_min,
    rule_channel_supported,
    rule_export_required,
    rule_moq_max,
    rule_oem_required,
    rule_price_max,
    rule_private_label_required,
    rule_region_supported,
    rule_required_service,
    to_filter_result_rows,
)


def _context() -> FilterContext:
    return FilterContext(candidate_values={}, user_requirements={})


def test_price_rule_fails_above_maximum() -> None:
    recommendable_id = uuid.uuid4()
    rule = rule_price_max(rule_order=1, max_price=50_000, price_of=lambda _rid: 65_000)

    result = evaluate_candidate(
        recommendable_id, rules=[rule], context=_context(), evaluation_id="eval-1"
    )

    assert result.passed is False
    assert result.reason_codes == ("PRICE_ABOVE_MAXIMUM",)


def test_price_rule_passes_within_range() -> None:
    recommendable_id = uuid.uuid4()
    rule = rule_price_max(rule_order=1, max_price=50_000, price_of=lambda _rid: 45_000)

    result = evaluate_candidate(
        recommendable_id, rules=[rule], context=_context(), evaluation_id="eval-2"
    )

    assert result.passed is True


def test_moq_rule_allows_conditional_pass_when_negotiable() -> None:
    recommendable_id = uuid.uuid4()
    rule = rule_moq_max(
        rule_order=1,
        buyer_max_quantity=100,
        moq_of=lambda _rid: 300,
        negotiable_of=lambda _rid: True,
    )

    result = evaluate_candidate(
        recommendable_id, rules=[rule], context=_context(), evaluation_id="eval-3"
    )

    # CONDITIONAL_PASS는 배제 결과가 아니므로 전체 평가는 통과로 남는다 (10단계 4절).
    assert result.passed is True
    assert result.outcomes[0].result == "CONDITIONAL_PASS"


def test_moq_rule_fails_when_not_negotiable() -> None:
    recommendable_id = uuid.uuid4()
    rule = rule_moq_max(rule_order=1, buyer_max_quantity=100, moq_of=lambda _rid: 300)

    result = evaluate_candidate(
        recommendable_id, rules=[rule], context=_context(), evaluation_id="eval-4"
    )

    assert result.passed is False


def test_production_mode_short_circuits_after_first_hard_failure() -> None:
    recommendable_id = uuid.uuid4()
    calls: list[str] = []

    def failing_evaluate(_rid: uuid.UUID, _ctx: FilterContext) -> FilterOutcome:
        calls.append("first")
        return FilterOutcome(rule_code="FIRST", rule_type="HARD", result="FAIL")

    def second_evaluate(_rid: uuid.UUID, _ctx: FilterContext) -> FilterOutcome:
        calls.append("second")
        return FilterOutcome(rule_code="SECOND", rule_type="HARD", result="PASS")

    rules = [
        HardFilterRule(
            rule_code="FIRST", rule_type="HARD", rule_order=1, evaluate=failing_evaluate
        ),
        HardFilterRule(
            rule_code="SECOND",
            rule_type="HARD",
            rule_order=2,
            evaluate=second_evaluate,
        ),
    ]

    evaluate_candidate(
        recommendable_id, rules=rules, context=_context(), evaluation_id="eval-5"
    )

    assert calls == ["first"]


def test_explain_mode_evaluates_every_rule_even_after_failure() -> None:
    recommendable_id = uuid.uuid4()
    calls: list[str] = []

    def failing_evaluate(_rid: uuid.UUID, _ctx: FilterContext) -> FilterOutcome:
        calls.append("first")
        return FilterOutcome(rule_code="FIRST", rule_type="HARD", result="FAIL")

    def second_evaluate(_rid: uuid.UUID, _ctx: FilterContext) -> FilterOutcome:
        calls.append("second")
        return FilterOutcome(rule_code="SECOND", rule_type="HARD", result="PASS")

    rules = [
        HardFilterRule(
            rule_code="FIRST", rule_type="HARD", rule_order=1, evaluate=failing_evaluate
        ),
        HardFilterRule(
            rule_code="SECOND",
            rule_type="HARD",
            rule_order=2,
            evaluate=second_evaluate,
        ),
    ]

    evaluate_candidate(
        recommendable_id,
        rules=rules,
        context=_context(),
        evaluation_id="eval-6",
        mode="EXPLAIN",
    )

    assert calls == ["first", "second"]


def test_unknown_result_respects_unknown_policy_exclude() -> None:
    recommendable_id = uuid.uuid4()
    rule = rule_required_service(
        rule_order=1,
        rule_code="TASTING_UNAVAILABLE",
        fail_reason_code="TASTING_UNAVAILABLE",
        status_of=lambda _rid: None,
    )

    result = evaluate_candidate(
        recommendable_id, rules=[rule], context=_context(), evaluation_id="eval-7"
    )

    assert result.passed is False
    assert result.outcomes[0].result == "FAIL"


def test_capacity_rule_conditional_pass_when_expansion_available() -> None:
    recommendable_id = uuid.uuid4()
    rule = rule_capacity_min(
        rule_order=1,
        required_monthly_units=1_000,
        remaining_capacity_of=lambda _rid: 500,
        capacity_available_after_days_of=lambda _rid: 60,
    )

    result = evaluate_candidate(
        recommendable_id, rules=[rule], context=_context(), evaluation_id="eval-9"
    )

    assert result.passed is True
    assert result.outcomes[0].result == "CONDITIONAL_PASS"


def test_capacity_rule_fails_when_no_expansion_available() -> None:
    recommendable_id = uuid.uuid4()
    rule = rule_capacity_min(
        rule_order=1,
        required_monthly_units=1_000,
        remaining_capacity_of=lambda _rid: 500,
    )

    result = evaluate_candidate(
        recommendable_id, rules=[rule], context=_context(), evaluation_id="eval-10"
    )

    assert result.passed is False
    assert result.reason_codes == ("INSUFFICIENT_CAPACITY",)


def test_channel_rule_fails_when_not_supported() -> None:
    recommendable_id = uuid.uuid4()
    rule = rule_channel_supported(rule_order=1, status_of=lambda _rid: "NOT_AVAILABLE")

    result = evaluate_candidate(
        recommendable_id, rules=[rule], context=_context(), evaluation_id="eval-11"
    )

    assert result.passed is False
    assert result.reason_codes == ("CHANNEL_EXCLUDED_BY_EXHIBITOR",)


def test_channel_rule_passes_for_active_and_preferred() -> None:
    recommendable_id = uuid.uuid4()
    for status in ("ACTIVE", "AVAILABLE", "PREFERRED"):
        rule = rule_channel_supported(
            rule_order=1, status_of=lambda _rid, status=status: status
        )
        result = evaluate_candidate(
            recommendable_id, rules=[rule], context=_context(), evaluation_id="eval-12"
        )
        assert result.passed is True


def test_region_rule_passes_on_nationwide_and_fails_on_not_supported() -> None:
    recommendable_id = uuid.uuid4()

    nationwide_rule = rule_region_supported(
        rule_order=1, match_type_of=lambda _rid: "NATIONWIDE"
    )
    passed = evaluate_candidate(
        recommendable_id,
        rules=[nationwide_rule],
        context=_context(),
        evaluation_id="eval-13",
    )
    assert passed.passed is True

    not_supported_rule = rule_region_supported(
        rule_order=1, match_type_of=lambda _rid: "NOT_SUPPORTED"
    )
    failed = evaluate_candidate(
        recommendable_id,
        rules=[not_supported_rule],
        context=_context(),
        evaluation_id="eval-14",
    )
    assert failed.passed is False
    assert failed.reason_codes == ("REGION_NOT_SUPPORTED",)


def test_availability_status_rules_share_no_conditional_yes_semantics() -> None:
    recommendable_id = uuid.uuid4()
    context = _context()

    for factory, rule_code in (
        (rule_oem_required, "OEM_NOT_AVAILABLE"),
        (rule_private_label_required, "PB_NOT_AVAILABLE"),
        (rule_export_required, "EXPORT_NOT_AVAILABLE"),
    ):
        fail_result = evaluate_candidate(
            recommendable_id,
            rules=[factory(rule_order=1, status_of=lambda _rid: "NO")],
            context=context,
            evaluation_id=f"eval-{rule_code}-no",
        )
        assert fail_result.passed is False
        assert fail_result.reason_codes == (rule_code,)

        conditional_result = evaluate_candidate(
            recommendable_id,
            rules=[factory(rule_order=1, status_of=lambda _rid: "NEGOTIABLE")],
            context=context,
            evaluation_id=f"eval-{rule_code}-negotiable",
        )
        assert conditional_result.passed is True
        assert conditional_result.outcomes[0].result == "CONDITIONAL_PASS"

        pass_result = evaluate_candidate(
            recommendable_id,
            rules=[factory(rule_order=1, status_of=lambda _rid: "YES")],
            context=context,
            evaluation_id=f"eval-{rule_code}-yes",
        )
        assert pass_result.passed is True
        assert pass_result.outcomes[0].result == "PASS"


def test_to_filter_result_rows_only_includes_excluding_outcomes() -> None:
    recommendable_id = uuid.uuid4()
    rule = rule_price_max(rule_order=1, max_price=1, price_of=lambda _rid: 2)

    result = evaluate_candidate(
        recommendable_id, rules=[rule], context=_context(), evaluation_id="eval-8"
    )
    rows = to_filter_result_rows(
        [result],
        recommendation_session_id=uuid.uuid4(),
        policy_version_id=uuid.uuid4(),
    )

    assert len(rows) == 1
    assert rows[0]["rule_code"] == "PRICE_ABOVE_MAXIMUM"
    assert rows[0]["result"] == "FAIL"
