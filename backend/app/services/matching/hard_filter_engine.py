"""10단계 필수조건 필터: Hard Filter/Soft Constraint 평가 엔진.

근거 문서: docs/10-hard-filter-exclusion-rules.md (2·3·4·5·28·29·30·33절), db-erd-table-spec.md
15.1/15.5절(matching.filter_rule/filter_result). meet_ai.scoring.EligibilityDecision과의
경계는 docs/11-13-scoring-implementation.md의 "클로드 구현과의 연결 경계"절을 따른다: 이
모듈이 만든 EligibilityResult가 그 EligibilityDecision의 원천이며, 순수 점수 계산 코어는
이 모듈이 이미 통과시킨 후보만 받는다(10단계 Hard Filter를 통과한 후보만 점수 계산을
허용한다는 계약).

구현 범위와 남은 작업
----------------------
- 평가 엔진 자체(실행순서, 단락회로, UNKNOWN 정책, 평가모드 3종, 결과 저장 행 변환)는
  완전히 구현했다.
- 구체 규칙(rule_code별 evaluate 함수)은 10단계 문서가 나열한 40여 개 필터 코드 전체가
  아니라 대표 유형 몇 개(가격 상한, 필수 서비스 가능 여부, MOQ 상한)만 예시로 제공한다.
  나머지 규칙(공급지역, 유통채널, OEM/PB, 수출조건, 상담시간, 접근성 등)은 실제 프로파일·
  거래조건 필드가 정의된 이후 같은 HardFilterRule 계약으로 추가하면 된다.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Literal

#: 10단계 4절 필터 결과 유형 8종. app/models/matching.py의 FILTER_RESULT_TYPES와 동일해야
#: 한다 (이 모듈은 순수 로직이라 모델을 import하지 않고 리터럴로 다시 선언한다).
FilterResultType = Literal[
    "PASS",
    "FAIL",
    "UNKNOWN",
    "CONDITIONAL_PASS",
    "MANUAL_REVIEW",
    "TEMPORARY_BLOCK",
    "POLICY_BLOCK",
    "USER_EXCLUDED",
]

#: 결과 우선순위 - 어느 결과가 "후보 제거"로 이어지는지. 10단계 2.1/28절.
_EXCLUDING_RESULTS: frozenset[str] = frozenset(
    {"FAIL", "POLICY_BLOCK", "USER_EXCLUDED"}
)


@dataclass(frozen=True)
class FilterOutcome:
    """규칙 1개를 후보 1개에 적용한 결과 (10단계 5절 필터 공통 데이터 구조)."""

    rule_code: str
    rule_type: Literal["HARD", "SOFT", "WARNING"]
    result: FilterResultType
    user_value: dict[str, Any] | None = None
    candidate_value: dict[str, Any] | None = None
    reason_code: str | None = None
    details: dict[str, Any] | None = None


@dataclass(frozen=True)
class HardFilterRule:
    """평가 가능한 필터 규칙 1개 (10단계 30절 필터 규칙 정의 구조).

    evaluate는 (recommendable_id, context) -> FilterOutcome | None을 받는다. None을
    반환하면 이 규칙이 해당 후보에 적용되지 않는다는 뜻이다(예: 가격 조건 미입력).
    """

    rule_code: str
    rule_type: Literal["HARD", "SOFT", "WARNING"]
    rule_order: int
    evaluate: Callable[[uuid.UUID, FilterContext], FilterOutcome | None]
    unknown_policy: Literal[
        "EXCLUDE", "MANUAL_REVIEW", "TREAT_AS_PASS", "TREAT_AS_FAIL"
    ] = "MANUAL_REVIEW"
    failure_action: Literal["EXCLUDE", "SCORE_PENALTY", "MANUAL_REVIEW"] = "EXCLUDE"


@dataclass(frozen=True)
class FilterContext:
    """규칙 evaluate 함수에 전달하는 조회 헬퍼 모음.

    실제 값 조회(가격, MOQ, 서비스 가능여부 등)는 orchestrator/feature_builder가 이미
    적재해 둔 dict를 이 컨텍스트에 실어 보낸다 - 이 엔진 자체는 DB를 조회하지 않는다
    (10단계 2.5절 "실시간 상황과 상시 조건 분리"를 지키려면 조회 시점과 평가 시점을
    분리해야 하고, 평가 엔진은 순수 함수로 남는 편이 재현성(2.4절)에 유리하다).
    """

    candidate_values: dict[uuid.UUID, dict[str, Any]]
    user_requirements: dict[str, Any]


@dataclass(frozen=True)
class EligibilityResult:
    """후보 1개에 대한 전체 필터 평가 결과."""

    recommendable_id: uuid.UUID
    evaluation_id: str
    passed: bool
    outcomes: tuple[FilterOutcome, ...]

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(
            outcome.reason_code or outcome.rule_code
            for outcome in self.outcomes
            if outcome.result in _EXCLUDING_RESULTS
        )


EvaluationMode = Literal["PRODUCTION", "EXPLAIN", "AUDIT", "TEST"]


def evaluate_candidate(
    recommendable_id: uuid.UUID,
    *,
    rules: Sequence[HardFilterRule],
    context: FilterContext,
    evaluation_id: str,
    mode: EvaluationMode = "PRODUCTION",
) -> EligibilityResult:
    """10단계 28/29절: 실행순서대로 규칙을 평가하고, PRODUCTION 모드에서는 배제가 확정되면
    단락회로로 나머지 규칙을 생략한다. EXPLAIN/AUDIT/TEST 모드는 모든 규칙을 끝까지
    평가한다(디버깅·감사 목적, 29절).
    """

    ordered_rules = sorted(rules, key=lambda rule: rule.rule_order)
    outcomes: list[FilterOutcome] = []
    excluded = False

    for rule in ordered_rules:
        if excluded and mode == "PRODUCTION":
            break

        raw_outcome = rule.evaluate(recommendable_id, context)
        if raw_outcome is None:
            continue

        outcome = raw_outcome
        if outcome.result == "UNKNOWN":
            outcome = _apply_unknown_policy(outcome, rule)

        outcomes.append(outcome)
        if rule.rule_type == "HARD" and outcome.result in _EXCLUDING_RESULTS:
            excluded = True

    return EligibilityResult(
        recommendable_id=recommendable_id,
        evaluation_id=evaluation_id,
        passed=not excluded,
        outcomes=tuple(outcomes),
    )


def _apply_unknown_policy(
    outcome: FilterOutcome, rule: HardFilterRule
) -> FilterOutcome:
    """10단계 2.3절: UNKNOWN을 NO나 YES로 임의 간주하지 않고, 규칙별 unknown_policy를
    명시적으로 적용한다."""

    if rule.unknown_policy == "TREAT_AS_PASS":
        return _replace_result(outcome, "PASS")
    if rule.unknown_policy == "TREAT_AS_FAIL":
        return _replace_result(outcome, "FAIL")
    if rule.unknown_policy == "EXCLUDE":
        return _replace_result(outcome, "FAIL")
    return _replace_result(outcome, "MANUAL_REVIEW")


def _replace_result(outcome: FilterOutcome, result: FilterResultType) -> FilterOutcome:
    return FilterOutcome(
        rule_code=outcome.rule_code,
        rule_type=outcome.rule_type,
        result=result,
        user_value=outcome.user_value,
        candidate_value=outcome.candidate_value,
        reason_code=outcome.reason_code,
        details=outcome.details,
    )


def evaluate_candidates(
    recommendable_ids: Sequence[uuid.UUID],
    *,
    rules: Sequence[HardFilterRule],
    context: FilterContext,
    evaluation_id_of: Callable[[uuid.UUID], str],
    mode: EvaluationMode = "PRODUCTION",
) -> list[EligibilityResult]:
    return [
        evaluate_candidate(
            recommendable_id,
            rules=rules,
            context=context,
            evaluation_id=evaluation_id_of(recommendable_id),
            mode=mode,
        )
        for recommendable_id in recommendable_ids
    ]


def to_filter_result_rows(
    results: Sequence[EligibilityResult],
    *,
    recommendation_session_id: uuid.UUID,
    policy_version_id: uuid.UUID,
) -> list[dict[str, Any]]:
    """db-erd 15.5절: "실패한 후보의 rule code ... 최소 details_json을 저장한다 ...
    통과한 모든 규칙을 모든 후보에 기록하면 폭증하므로 최종 후보의 trace 또는 표본만
    저장한다". 그래서 여기서는 배제로 이어진(_EXCLUDING_RESULTS) outcome만 행으로
    변환한다. PASS/CONDITIONAL_PASS/WARNING 결과는 저장하지 않는다.
    """

    rows: list[dict[str, Any]] = []
    for result in results:
        for outcome in result.outcomes:
            if outcome.result not in _EXCLUDING_RESULTS:
                continue
            rows.append(
                {
                    "recommendation_session_id": recommendation_session_id,
                    "recommendable_id": result.recommendable_id,
                    "rule_code": outcome.rule_code,
                    "policy_version_id": policy_version_id,
                    "result": outcome.result,
                    "reason_code": outcome.reason_code,
                    "user_value_json": outcome.user_value,
                    "candidate_value_json": outcome.candidate_value,
                    "details_json": outcome.details,
                }
            )
    return rows


# ---------------------------------------------------------------------------
# 대표 규칙 예시 (10단계 13·10·14절) - 나머지 규칙은 같은 계약으로 추가한다.
# ---------------------------------------------------------------------------


def rule_price_max(
    *, rule_order: int, max_price: int, price_of: Callable[[uuid.UUID], int | None]
) -> HardFilterRule:
    """10단계 13.2/13.4절: 가격 상한이 필수조건인 경우의 Hard Filter."""

    def evaluate(
        recommendable_id: uuid.UUID, context: FilterContext
    ) -> FilterOutcome | None:
        price = price_of(recommendable_id)
        if price is None:
            return FilterOutcome(
                rule_code="PRICE_INFORMATION_UNKNOWN",
                rule_type="HARD",
                result="UNKNOWN",
            )
        if price > max_price:
            return FilterOutcome(
                rule_code="PRICE_ABOVE_MAXIMUM",
                rule_type="HARD",
                result="FAIL",
                user_value={"max_price": max_price},
                candidate_value={"price": price},
                reason_code="PRICE_ABOVE_MAXIMUM",
            )
        return FilterOutcome(
            rule_code="PRICE_ABOVE_MAXIMUM", rule_type="HARD", result="PASS"
        )

    return HardFilterRule(
        rule_code="PRICE_ABOVE_MAXIMUM",
        rule_type="HARD",
        rule_order=rule_order,
        evaluate=evaluate,
        unknown_policy="MANUAL_REVIEW",
    )


def rule_required_service(
    *,
    rule_order: int,
    rule_code: str,
    fail_reason_code: str,
    status_of: Callable[[uuid.UUID], str | None],
    available_status: str = "AVAILABLE",
) -> HardFilterRule:
    """10단계 10.2절: 시음·구매 등 필수 서비스가 현재 가능한지 검증하는 Hard Filter."""

    def evaluate(
        recommendable_id: uuid.UUID, context: FilterContext
    ) -> FilterOutcome | None:
        status = status_of(recommendable_id)
        if status is None:
            return FilterOutcome(
                rule_code=rule_code, rule_type="HARD", result="UNKNOWN"
            )
        if status != available_status:
            return FilterOutcome(
                rule_code=rule_code,
                rule_type="HARD",
                result="FAIL",
                candidate_value={"status": status},
                reason_code=fail_reason_code,
            )
        return FilterOutcome(rule_code=rule_code, rule_type="HARD", result="PASS")

    return HardFilterRule(
        rule_code=rule_code,
        rule_type="HARD",
        rule_order=rule_order,
        evaluate=evaluate,
        unknown_policy="EXCLUDE",
    )


def rule_moq_max(
    *,
    rule_order: int,
    buyer_max_quantity: int,
    moq_of: Callable[[uuid.UUID], int | None],
    negotiable_of: Callable[[uuid.UUID], bool] = lambda _: False,
) -> HardFilterRule:
    """10단계 14절: MOQ 필터. 협의 가능(negotiable)이면 CONDITIONAL_PASS로 완화한다."""

    def evaluate(
        recommendable_id: uuid.UUID, context: FilterContext
    ) -> FilterOutcome | None:
        moq = moq_of(recommendable_id)
        if moq is None:
            return FilterOutcome(
                rule_code="MOQ_INFORMATION_UNKNOWN", rule_type="HARD", result="UNKNOWN"
            )
        if moq <= buyer_max_quantity:
            return FilterOutcome(
                rule_code="MOQ_EXCEEDS_BUYER_LIMIT", rule_type="HARD", result="PASS"
            )
        if negotiable_of(recommendable_id):
            return FilterOutcome(
                rule_code="MOQ_NEGOTIABLE",
                rule_type="HARD",
                result="CONDITIONAL_PASS",
                user_value={"buyer_max_quantity": buyer_max_quantity},
                candidate_value={"moq": moq, "negotiable": True},
                reason_code="MOQ_CONDITIONAL_MATCH",
            )
        return FilterOutcome(
            rule_code="MOQ_EXCEEDS_BUYER_LIMIT",
            rule_type="HARD",
            result="FAIL",
            user_value={"buyer_max_quantity": buyer_max_quantity},
            candidate_value={"moq": moq},
            reason_code="MOQ_EXCEEDS_BUYER_LIMIT",
        )

    return HardFilterRule(
        rule_code="MOQ_EXCEEDS_BUYER_LIMIT",
        rule_type="HARD",
        rule_order=rule_order,
        evaluate=evaluate,
        unknown_policy="MANUAL_REVIEW",
    )
