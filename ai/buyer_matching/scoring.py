"""결정론적 규칙기반 B2B 매칭 점수화: score_b2e / score_e2b / mutual(harmonic mean) / grade.

가중치는 임무 지시가 명시한 값 그대로다:

    score_b2e = 0.20*product_tech + 0.15*business_goal + 0.15*channel + 0.15*order_scale_moq
                + 0.10*region + 0.10*cooperation_type + 0.10*trade_readiness + 0.05*data_trust

    score_e2b = 0.20*buyer_type + 0.20*channel + 0.20*order_scale + 0.15*region
                + 0.15*cooperation_type + 0.10*verification_trust

신호가 없는 컴포넌트(value=None)는 가중합에서 빠지고 나머지 컴포넌트의 가중치 합으로
재정규화된다("graceful handling ... rather than zeroing blindly") - _combine() 참고.

결정성: 이 모듈은 난수·시각을 전혀 쓰지 않는다. 같은 입력은 항상 같은 출력을 낸다.
"""

from __future__ import annotations

from ai.buyer_matching import reason_codes as rc
from ai.buyer_matching.types import (
    _BUYER_VERIFICATION_TRUST,
    BuyerProfile,
    BuyerToExhibitorScore,
    ComponentScore,
    ExhibitorBuyerPreferenceSignal,
    ExhibitorCandidate,
    ExhibitorToBuyerScore,
)

# 연속형 적합도 신호(MOQ/물량/거래준비도)에서 "충분히 좋다"고 보고 MATCH.* 사유를 붙이는 기준.
_FIT_THRESHOLD = 0.999
_TRADE_READINESS_THRESHOLD = 0.7
# 이산형 선호 신호(REQUIRED=1.0/PREFERRED=0.8/EXCLUDED=0.0)에서 사유를 붙이는 기준
# (PREFERRED 이상이면 붙인다).
_PREFERENCE_THRESHOLD = 0.8

GRADE_THRESHOLDS: tuple[tuple[str, float], ...] = (
    ("HIGH", 80.0),
    ("MEDIUM", 65.0),
    ("POSSIBLE", 50.0),
)


def grade_for_score(score: float) -> str:
    for grade, threshold in GRADE_THRESHOLDS:
        if score >= threshold:
            return grade
    return "LOW"


def harmonic_mean(a: float, b: float) -> float:
    """두 0..100 점수의 조화평균. 한쪽이 0이면(진짜 일방적 불일치) 결과도 0이다."""

    if a <= 0 or b <= 0:
        return 0.0
    return round(2 * a * b / (a + b), 2)


def mutual_score(b2e_score: float, e2b_score: float | None) -> float:
    """e2b가 있으면 조화평균, 없으면 b2e를 그대로 최종점수로 쓴다(임무 지시)."""

    if e2b_score is None:
        return b2e_score
    return harmonic_mean(b2e_score, e2b_score)


def _combine(components: tuple[ComponentScore, ...]) -> float:
    available = [c for c in components if c.value is not None]
    total_weight = sum(c.weight for c in available)
    if total_weight <= 0:
        return 0.0
    weighted_sum = sum(c.weight * c.value for c in available)  # type: ignore[operator]
    score = (weighted_sum / total_weight) * 100
    return round(min(100.0, max(0.0, score)), 2)


def _set_overlap_fraction(wanted: frozenset[str], have: frozenset[str]) -> float | None:
    if not wanted:
        return None
    return len(wanted & have) / len(wanted)


def _moq_fit(ceiling: int | None, moq: int | None) -> float | None:
    if moq is None:
        return None
    if ceiling is None:
        return 1.0
    if moq <= ceiling:
        return 1.0
    return max(0.0, ceiling / moq)


def _range_fit(
    want_min: int | None,
    want_max: int | None,
    cap_min: int | None,
    cap_max: int | None,
) -> float | None:
    """want 구간이 cap 구간에 얼마나 들어맞는지 0..1로 반환한다. 양쪽 모두 정보가 있어야
    계산되고(호출측이 None 여부를 먼저 확인), want가 점값(min==max 또는 한쪽만 지정)이면
    그 값이 cap 구간 안에 있는지로 판정한다.
    """

    lo = want_min if want_min is not None else want_max
    hi = want_max if want_max is not None else want_min
    if lo is None and hi is None:
        return None
    if lo is None:
        lo = hi
    if hi is None:
        hi = lo
    if hi < lo:
        lo, hi = hi, lo

    cap_lo = cap_min if cap_min is not None else 0
    cap_hi = cap_max if cap_max is not None else float("inf")

    if hi == lo:
        return 1.0 if cap_lo <= lo <= cap_hi else 0.0

    overlap_lo = max(lo, cap_lo)
    overlap_hi = min(hi, cap_hi)
    overlap = max(0.0, overlap_hi - overlap_lo)
    width = hi - lo
    return round(min(1.0, overlap / width), 4)


def _preference_dimension_value(
    required: frozenset[str],
    preferred: frozenset[str],
    excluded: frozenset[str],
    buyer_values: frozenset[str],
) -> float | None:
    """exhibitor의 REQUIRED/PREFERRED/EXCLUDED 선호 3단계와 바이어 값을 비교한다.
    아무 선호도 선언되지 않았으면(세 집합 모두 빈 값) None(신호 없음)이다.
    """

    if not required and not preferred and not excluded:
        return None
    if buyer_values & excluded:
        return 0.0
    if required and buyer_values & required:
        return 1.0
    if preferred and buyer_values & preferred:
        return _PREFERENCE_THRESHOLD
    return 0.0


def score_b2e(buyer: BuyerProfile, exhibitor: ExhibitorCandidate) -> BuyerToExhibitorScore:
    """바이어 -> 업체 적합도. hard_filter를 통과한 후보에 대해서만 호출하는 것을 전제로
    하지만, 이 함수 자체는 하드필터 통과 여부를 검사하지 않는 순수 함수다(단위테스트 편의).
    """

    reasons: list[str] = []
    info: list[str] = []

    # product_tech (0.20)
    product_wanted = frozenset(buyer.required_product_codes) | frozenset(buyer.preferred_product_codes)
    tech_wanted = frozenset(buyer.required_technology_codes) | frozenset(buyer.preferred_technology_codes)
    combined_wanted = product_wanted | tech_wanted
    if combined_wanted:
        have = frozenset(exhibitor.product_codes) | frozenset(exhibitor.technology_codes)
        pt_value = len(combined_wanted & have) / len(combined_wanted)
        if product_wanted & frozenset(exhibitor.product_codes):
            reasons.append(rc.MATCH_PRODUCT)
        if tech_wanted & frozenset(exhibitor.technology_codes):
            reasons.append(rc.MATCH_TECHNOLOGY)
    else:
        pt_value = None

    # business_goal (0.15)
    goal_wanted = frozenset(buyer.business_goal_codes)
    bg_value = _set_overlap_fraction(goal_wanted, frozenset(exhibitor.business_goal_codes))
    if bg_value is not None and bg_value > 0:
        reasons.append(rc.MATCH_BUSINESS_GOAL)

    # channel (0.15)
    channel_wanted = frozenset(buyer.channel_codes)
    ch_value = _set_overlap_fraction(channel_wanted, frozenset(exhibitor.channel_codes))
    if ch_value is not None and ch_value > 0:
        reasons.append(rc.MATCH_CHANNEL)

    # order_scale_moq (0.15) - MOQ 상한 적합도 + 월 물량 적합도의 평균(가능한 것만)
    moq_fit = _moq_fit(buyer.moq_ceiling, exhibitor.moq)
    if exhibitor.moq is None:
        info.append(rc.INFO_MOQ_UNKNOWN)
    volume_fit: float | None = None
    if (buyer.monthly_order_min is not None or buyer.monthly_order_max is not None) and (
        exhibitor.monthly_capacity is not None
    ):
        volume_fit = _range_fit(
            buyer.monthly_order_min, buyer.monthly_order_max, 0, exhibitor.monthly_capacity
        )
    sub_fits = [v for v in (moq_fit, volume_fit) if v is not None]
    osm_value = sum(sub_fits) / len(sub_fits) if sub_fits else None
    if moq_fit is not None and moq_fit >= _FIT_THRESHOLD:
        reasons.append(rc.MATCH_MOQ)
    if volume_fit is not None and volume_fit >= _FIT_THRESHOLD:
        reasons.append(rc.MATCH_ORDER_SCALE)

    # region (0.10)
    region_wanted = frozenset(buyer.required_region_codes) | frozenset(buyer.preferred_region_codes)
    if region_wanted:
        have_region = frozenset(exhibitor.supply_region_codes)
        if not have_region:
            rg_value = None
            info.append(rc.INFO_REGION_UNKNOWN)
        else:
            rg_value = len(region_wanted & have_region) / len(region_wanted)
            if rg_value > 0:
                reasons.append(rc.MATCH_REGION)
    else:
        rg_value = None

    # cooperation_type (0.10)
    coop_wanted = frozenset(buyer.required_cooperation_type_codes) | frozenset(
        buyer.preferred_cooperation_type_codes
    )
    ct_value = _set_overlap_fraction(coop_wanted, frozenset(exhibitor.cooperation_type_codes))
    if ct_value is not None and ct_value > 0:
        reasons.append(rc.MATCH_COOPERATION)

    # trade_readiness (0.10)
    if exhibitor.trade_readiness_score is not None:
        tr_value = max(0.0, min(1.0, exhibitor.trade_readiness_score / 100))
        if tr_value >= _TRADE_READINESS_THRESHOLD:
            reasons.append(rc.MATCH_TRADE_READINESS)
    else:
        tr_value = None
        if exhibitor.lead_time_days is None:
            info.append(rc.INFO_LEAD_TIME_UNKNOWN)

    # data_trust (0.05) - 전용 사유 코드가 정의되어 있지 않으므로 점수에만 반영한다.
    if exhibitor.data_trust_score is not None:
        dt_value = max(0.0, min(1.0, exhibitor.data_trust_score / 100))
    else:
        dt_value = None

    components = (
        ComponentScore("product_tech", 0.20, pt_value),
        ComponentScore("business_goal", 0.15, bg_value),
        ComponentScore("channel", 0.15, ch_value),
        ComponentScore("order_scale_moq", 0.15, osm_value),
        ComponentScore("region", 0.10, rg_value),
        ComponentScore("cooperation_type", 0.10, ct_value),
        ComponentScore("trade_readiness", 0.10, tr_value),
        ComponentScore("data_trust", 0.05, dt_value),
    )

    return BuyerToExhibitorScore(
        exhibitor_id=exhibitor.exhibitor_id,
        score=_combine(components),
        components=components,
        reason_codes=rc.dedupe_preserve_order(reasons),
        info_codes=rc.dedupe_preserve_order(info),
    )


def score_e2b(buyer: BuyerProfile, exhibitor: ExhibitorCandidate) -> ExhibitorToBuyerScore | None:
    """업체 -> 바이어 적합도. exhibitor.buyer_preference가 선언되어 있을 때만 계산한다
    (임무 지시: "only computed if exhibitor declared buyer-preferences exist"). 선언이
    없으면 None을 반환하며, 이는 "0점"과 다르다(단순 미계산).
    """

    pref: ExhibitorBuyerPreferenceSignal | None = exhibitor.buyer_preference
    if pref is None:
        return None

    reasons: list[str] = []
    info: list[str] = []

    buyer_type_values = frozenset({buyer.buyer_type_code}) if buyer.buyer_type_code else frozenset()
    bt_value = _preference_dimension_value(
        frozenset(pref.required_buyer_type_codes),
        frozenset(pref.preferred_buyer_type_codes),
        frozenset(pref.excluded_buyer_type_codes),
        buyer_type_values,
    )
    # MATCH.BUYER_TYPE 전용 사유 코드는 정의되어 있지 않다(임무 지시 사유코드 목록에 없음).

    ch_value = _preference_dimension_value(
        frozenset(pref.required_channel_codes),
        frozenset(pref.preferred_channel_codes),
        frozenset(pref.excluded_channel_codes),
        frozenset(buyer.channel_codes),
    )
    if ch_value is not None and ch_value >= _PREFERENCE_THRESHOLD:
        reasons.append(rc.MATCH_CHANNEL)

    buyer_region_values = frozenset(buyer.required_region_codes) | frozenset(buyer.preferred_region_codes)
    rg_value = _preference_dimension_value(
        frozenset(pref.required_region_codes),
        frozenset(pref.preferred_region_codes),
        frozenset(pref.excluded_region_codes),
        buyer_region_values,
    )
    if rg_value is not None and rg_value >= _PREFERENCE_THRESHOLD:
        reasons.append(rc.MATCH_REGION)

    buyer_coop_values = frozenset(buyer.required_cooperation_type_codes) | frozenset(
        buyer.preferred_cooperation_type_codes
    )
    ct_value = _preference_dimension_value(
        frozenset(pref.required_cooperation_type_codes),
        frozenset(pref.preferred_cooperation_type_codes),
        frozenset(pref.excluded_cooperation_type_codes),
        buyer_coop_values,
    )
    if ct_value is not None and ct_value >= _PREFERENCE_THRESHOLD:
        reasons.append(rc.MATCH_COOPERATION)

    order_value: float | None = None
    if (pref.volume_min is not None or pref.volume_max is not None) and (
        buyer.monthly_order_min is not None or buyer.monthly_order_max is not None
    ):
        order_value = _range_fit(
            buyer.monthly_order_min, buyer.monthly_order_max, pref.volume_min, pref.volume_max
        )
        if order_value is not None and order_value >= _FIT_THRESHOLD:
            reasons.append(rc.MATCH_ORDER_SCALE)

    trust_value = _BUYER_VERIFICATION_TRUST.get(buyer.verification_status)
    # MATCH.* 목록에 검증신뢰 전용 사유 코드는 없다 - 점수에만 반영한다.

    components = (
        ComponentScore("buyer_type", 0.20, bt_value),
        ComponentScore("channel", 0.20, ch_value),
        ComponentScore("order_scale", 0.20, order_value),
        ComponentScore("region", 0.15, rg_value),
        ComponentScore("cooperation_type", 0.15, ct_value),
        ComponentScore("verification_trust", 0.10, trust_value),
    )

    return ExhibitorToBuyerScore(
        exhibitor_id=exhibitor.exhibitor_id,
        score=_combine(components),
        components=components,
        reason_codes=rc.dedupe_preserve_order(reasons),
        info_codes=rc.dedupe_preserve_order(info),
    )
