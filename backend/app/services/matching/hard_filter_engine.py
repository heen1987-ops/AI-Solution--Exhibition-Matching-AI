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
- 구체 규칙(rule_code별 evaluate 함수)은 가격 상한·필수 서비스 가능 여부·MOQ 상한에 더해
  생산·공급역량(15절)·유통채널(16절)·공급지역(17절)·OEM/PB/수출 가용상태(18~19절)까지
  추가했다 - exhibition.trade_condition이 이미 oem_status/private_label_status/
  export_status를 YES/NO/CONDITIONAL/NEGOTIABLE/UNKNOWN 5단계로 저장하므로(같은 값
  체계라 rule_availability_status 하나로 셋 다 만든다), 실제 컬럼이 있는 규칙부터
  구현했다. 여전히 남은 것: 상담 가능성(20절)·일정충돌(21절)·위치·거리(22절) 등 프로파일·
  일정 데이터가 아직 이 서비스 계층에 없는 규칙, 그리고 지역 계층 조회(서울↔수도권 같은
  상위 권역 판정)처럼 온톨로지 카탈로그가 선행되어야 하는 부분(rule_region_supported의
  match_type_of 콜백 docstring 참고).
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


def rule_capacity_min(
    *,
    rule_order: int,
    required_monthly_units: int,
    remaining_capacity_of: Callable[[uuid.UUID], int | None],
    capacity_available_after_days_of: Callable[[uuid.UUID], int | None] = lambda _: (
        None
    ),
) -> HardFilterRule:
    """10단계 15.2/15.3절: 생산·공급역량 필터.

    전체 생산량이 아니라 "신규계약에 쓸 수 있는 잔여" 생산능력만 비교한다(15.2절 예시) -
    호출자(orchestrator)가 이미 기존 계약물량을 뺀 값을 remaining_capacity_of로 넘겨야
    하고, 이 함수 자체는 그 차감을 수행하지 않는다. 잔여량이 부족해도 증설로 확보 가능한
    시점이 있으면(15.3절) rule_moq_max의 negotiable_of와 같은 패턴으로 CONDITIONAL_PASS로
    완화한다.
    """

    def evaluate(
        recommendable_id: uuid.UUID, context: FilterContext
    ) -> FilterOutcome | None:
        remaining = remaining_capacity_of(recommendable_id)
        if remaining is None:
            return FilterOutcome(
                rule_code="CAPACITY_INFORMATION_UNKNOWN",
                rule_type="HARD",
                result="UNKNOWN",
            )
        if remaining >= required_monthly_units:
            return FilterOutcome(
                rule_code="INSUFFICIENT_CAPACITY", rule_type="HARD", result="PASS"
            )
        available_after_days = capacity_available_after_days_of(recommendable_id)
        if available_after_days is not None:
            return FilterOutcome(
                rule_code="CAPACITY_AVAILABLE_AFTER_EXPANSION",
                rule_type="HARD",
                result="CONDITIONAL_PASS",
                user_value={"required_monthly_units": required_monthly_units},
                candidate_value={
                    "remaining_capacity": remaining,
                    "available_after_days": available_after_days,
                },
                reason_code="CAPACITY_AVAILABLE_AFTER_EXPANSION",
            )
        return FilterOutcome(
            rule_code="INSUFFICIENT_CAPACITY",
            rule_type="HARD",
            result="FAIL",
            user_value={"required_monthly_units": required_monthly_units},
            candidate_value={"remaining_capacity": remaining},
            reason_code="INSUFFICIENT_CAPACITY",
        )

    return HardFilterRule(
        rule_code="INSUFFICIENT_CAPACITY",
        rule_type="HARD",
        rule_order=rule_order,
        evaluate=evaluate,
        unknown_policy="MANUAL_REVIEW",
    )


#: 16단계 16.1절 표: ACTIVE/AVAILABLE/PREFERRED는 통과다. PREFERRED의 "가점"은 Hard
#: Filter 범위 밖(Soft Score 몫)이라 여기서는 PASS와 동일하게만 취급한다.
_CHANNEL_STATUS_PASS: frozenset[str] = frozenset({"ACTIVE", "AVAILABLE", "PREFERRED"})


def rule_channel_supported(
    *, rule_order: int, status_of: Callable[[uuid.UUID], str | None]
) -> HardFilterRule:
    """10단계 16.1절 유통채널 필터. 업체 지원상태(exhibition.trade_condition_term의
    term_type='CHANNEL'과 연결된 지원여부)를 6종 상태로 판정한다."""

    def evaluate(
        recommendable_id: uuid.UUID, context: FilterContext
    ) -> FilterOutcome | None:
        status = status_of(recommendable_id)
        if status is None or status == "UNKNOWN":
            return FilterOutcome(
                rule_code="CHANNEL_NOT_SUPPORTED", rule_type="HARD", result="UNKNOWN"
            )
        if status in _CHANNEL_STATUS_PASS:
            return FilterOutcome(
                rule_code="CHANNEL_NOT_SUPPORTED", rule_type="HARD", result="PASS"
            )
        if status == "CONDITIONAL":
            return FilterOutcome(
                rule_code="CHANNEL_NOT_SUPPORTED",
                rule_type="HARD",
                result="CONDITIONAL_PASS",
                candidate_value={"status": status},
                reason_code="CHANNEL_CONDITIONAL",
            )
        return FilterOutcome(
            rule_code="CHANNEL_NOT_SUPPORTED",
            rule_type="HARD",
            result="FAIL",
            candidate_value={"status": status},
            reason_code="CHANNEL_EXCLUDED_BY_EXHIBITOR",
        )

    return HardFilterRule(
        rule_code="CHANNEL_NOT_SUPPORTED",
        rule_type="HARD",
        rule_order=rule_order,
        evaluate=evaluate,
        unknown_policy="MANUAL_REVIEW",
    )


#: 17단계 17.1절 지역 관계 중 통과로 이어지는 것들.
_REGION_MATCH_PASS: frozenset[str] = frozenset({"EXACT", "PARENT_REGION", "NATIONWIDE"})


def rule_region_supported(
    *, rule_order: int, match_type_of: Callable[[uuid.UUID], str | None]
) -> HardFilterRule:
    """10단계 17.1절 공급지역 필터.

    지역 계층 조회(예: "서울"이 업체가 공급하는 "수도권"에 포함되는지)는 온톨로지
    카탈로그의 책임이다(9단계 6.3절 category_concept_ids 확장과 같은 이유로, 이 순수
    평가엔진은 DB나 카탈로그를 조회하지 않는다) - 그래서 이 함수는 이미 계산된 관계
    유형만 match_type_of로 받는다. match_type_of가 반환하는 값: "EXACT"/"PARENT_REGION"/
    "NATIONWIDE"(모두 통과) / "CONDITIONAL"(조건부 통과) / "NOT_SUPPORTED"(제거) /
    None(미확인).
    """

    def evaluate(
        recommendable_id: uuid.UUID, context: FilterContext
    ) -> FilterOutcome | None:
        match_type = match_type_of(recommendable_id)
        if match_type is None:
            return FilterOutcome(
                rule_code="REGION_NOT_SUPPORTED", rule_type="HARD", result="UNKNOWN"
            )
        if match_type in _REGION_MATCH_PASS:
            reason = (
                "NATIONWIDE_SUPPLY_AVAILABLE" if match_type == "NATIONWIDE" else None
            )
            return FilterOutcome(
                rule_code="REGION_NOT_SUPPORTED",
                rule_type="HARD",
                result="PASS",
                reason_code=reason,
            )
        if match_type == "CONDITIONAL":
            return FilterOutcome(
                rule_code="REGION_NOT_SUPPORTED",
                rule_type="HARD",
                result="CONDITIONAL_PASS",
                candidate_value={"match_type": match_type},
            )
        return FilterOutcome(
            rule_code="REGION_NOT_SUPPORTED",
            rule_type="HARD",
            result="FAIL",
            candidate_value={"match_type": match_type},
            reason_code="REGION_NOT_SUPPORTED",
        )

    return HardFilterRule(
        rule_code="REGION_NOT_SUPPORTED",
        rule_type="HARD",
        rule_order=rule_order,
        evaluate=evaluate,
        unknown_policy="MANUAL_REVIEW",
    )


def rule_availability_status(
    *,
    rule_order: int,
    rule_code: str,
    not_available_reason_code: str,
    status_of: Callable[[uuid.UUID], str | None],
) -> HardFilterRule:
    """18.1절 YES/NO/CONDITIONAL/NEGOTIABLE/UNKNOWN 5단계 가용상태의 공통 패턴.

    exhibition.trade_condition의 oem_status/private_label_status/export_status가
    이미 이 값 체계(TRADE_AVAILABILITY_STATUSES)를 쓰므로, 이 함수 하나로 OEM 필수조건
    (18.2절), PB 필수조건, 수출 가능 여부(19.1절 "수출 가능 여부" 항목)를 전부 만든다 -
    세 규칙 각각의 rule_code/reason_code만 다르고 판정 로직은 동일하다.
    NO -> FAIL, CONDITIONAL/NEGOTIABLE -> CONDITIONAL_PASS(18.2절 예시), YES -> PASS,
    UNKNOWN/정보없음 -> UNKNOWN(규칙별 unknown_policy가 최종 처리를 결정한다, 18.2절
    "UNKNOWN -> MANUAL_REVIEW 또는 FAIL"의 "또는"이 바로 unknown_policy 선택지다).
    """

    def evaluate(
        recommendable_id: uuid.UUID, context: FilterContext
    ) -> FilterOutcome | None:
        status = status_of(recommendable_id)
        if status is None or status == "UNKNOWN":
            return FilterOutcome(
                rule_code=rule_code, rule_type="HARD", result="UNKNOWN"
            )
        if status == "NO":
            return FilterOutcome(
                rule_code=rule_code,
                rule_type="HARD",
                result="FAIL",
                candidate_value={"status": status},
                reason_code=not_available_reason_code,
            )
        if status in ("CONDITIONAL", "NEGOTIABLE"):
            return FilterOutcome(
                rule_code=rule_code,
                rule_type="HARD",
                result="CONDITIONAL_PASS",
                candidate_value={"status": status},
                reason_code="COOPERATION_CONDITIONAL",
            )
        return FilterOutcome(rule_code=rule_code, rule_type="HARD", result="PASS")

    return HardFilterRule(
        rule_code=rule_code,
        rule_type="HARD",
        rule_order=rule_order,
        evaluate=evaluate,
        unknown_policy="MANUAL_REVIEW",
    )


def rule_oem_required(
    *, rule_order: int, status_of: Callable[[uuid.UUID], str | None]
) -> HardFilterRule:
    """10단계 18.2절 OEM 필수조건 - rule_availability_status의 OEM 특수화."""

    return rule_availability_status(
        rule_order=rule_order,
        rule_code="OEM_NOT_AVAILABLE",
        not_available_reason_code="OEM_NOT_AVAILABLE",
        status_of=status_of,
    )


def rule_private_label_required(
    *, rule_order: int, status_of: Callable[[uuid.UUID], str | None]
) -> HardFilterRule:
    """10단계 18.1절과 같은 5단계 상태를 PB(private label)에 적용한 특수화."""

    return rule_availability_status(
        rule_order=rule_order,
        rule_code="PB_NOT_AVAILABLE",
        not_available_reason_code="PB_NOT_AVAILABLE",
        status_of=status_of,
    )


def rule_export_required(
    *, rule_order: int, status_of: Callable[[uuid.UUID], str | None]
) -> HardFilterRule:
    """10단계 19.1절 "수출 가능 여부" 항목의 특수화. 19.2절 "수출 가능 문구만으로 수출
    적격 후보로 판단하지 않는다"에 따라, 대상국 인증·라벨 등 나머지 검증항목은 별도
    규칙(예: rule_availability_status를 대상국 인증 여부에 다시 적용)으로 추가해야 하며
    이 규칙 통과만으로 수출 적격을 확정하지 않는다."""

    return rule_availability_status(
        rule_order=rule_order,
        rule_code="EXPORT_NOT_AVAILABLE",
        not_available_reason_code="EXPORT_NOT_AVAILABLE",
        status_of=status_of,
    )
