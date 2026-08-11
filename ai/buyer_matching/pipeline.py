"""hard_filter + score_b2e/score_e2b + 등급 + 사유코드를 하나로 묶는 오케스트레이션 계층.

BACKEND-BUYER-MATCH 트랙이 실제로 호출할 진입점은 이 모듈의 ``evaluate_candidates()``다
(hard_filter/scoring 개별 함수는 단위테스트·세부제어용으로 계속 공개돼 있다).

불변식(평가 하네스가 검증한다): 이 함수가 반환하는 결과 중 ``hard_filter.passed is False``인
항목은 ``b2e``/``e2b``/``final_score``/``grade``가 전부 None이다 - 하드필터를 통과하지 못한
후보는 어떤 경우에도 점수화되지 않는다("hard-filter violation" 0건 불변식의 근거).
"""

from __future__ import annotations

from collections.abc import Sequence

from ai.buyer_matching import reason_codes as rc
from ai.buyer_matching.hard_filter import hard_filter
from ai.buyer_matching.scoring import (
    grade_for_score,
    mutual_score,
    score_b2e,
    score_e2b,
)
from ai.buyer_matching.types import BuyerMatchResult, BuyerProfile, ExhibitorCandidate

#: e2b 점수가 이 값 이상이면 "상호 선호가 확인됐다"는 신호로 MATCH.MUTUAL_PREFERENCE를 붙인다.
#: scoring.GRADE_THRESHOLDS의 POSSIBLE 기준(50)과 맞춘다 - "의미 있는 신호"의 최소선.
_MUTUAL_PREFERENCE_THRESHOLD = 50.0


def evaluate_candidates(
    buyer_profile: BuyerProfile,
    exhibitor_candidates: Sequence[ExhibitorCandidate],
) -> list[BuyerMatchResult]:
    """hard_filter -> (통과분만) score_b2e/score_e2b -> mutual -> grade 전체 파이프라인.

    반환 순서는 final_score 내림차순, 동점이면 exhibitor_id 문자열 오름차순(결정적 정렬 -
    입력 순서나 딕셔너리 순회 순서에 기대지 않는다). hard_filter를 통과하지 못한 후보는
    final_score가 없으므로(None) 정렬 키에서 -1로 취급해 항상 뒤로 보낸다.
    """

    filter_results = hard_filter(buyer_profile, exhibitor_candidates)
    candidates_by_id = {c.exhibitor_id: c for c in exhibitor_candidates}

    results: list[BuyerMatchResult] = []
    for filter_result in filter_results:
        candidate = candidates_by_id[filter_result.exhibitor_id]

        if not filter_result.passed:
            results.append(
                BuyerMatchResult(
                    exhibitor_id=filter_result.exhibitor_id,
                    hard_filter=filter_result,
                    b2e=None,
                    e2b=None,
                    final_score=None,
                    grade=None,
                    reason_codes=(),
                    info_codes=filter_result.info_codes,
                    included_in_primary=False,
                )
            )
            continue

        b2e = score_b2e(buyer_profile, candidate)
        e2b = score_e2b(buyer_profile, candidate)
        final = mutual_score(b2e.score, e2b.score if e2b is not None else None)
        grade = grade_for_score(final)

        reasons = list(b2e.reason_codes)
        info = list(filter_result.info_codes) + list(b2e.info_codes)
        if e2b is not None:
            reasons.extend(e2b.reason_codes)
            info.extend(e2b.info_codes)
            if e2b.score >= _MUTUAL_PREFERENCE_THRESHOLD:
                reasons.append(rc.MATCH_MUTUAL_PREFERENCE)

        results.append(
            BuyerMatchResult(
                exhibitor_id=filter_result.exhibitor_id,
                hard_filter=filter_result,
                b2e=b2e,
                e2b=e2b,
                final_score=final,
                grade=grade,
                reason_codes=rc.dedupe_preserve_order(reasons),
                info_codes=rc.dedupe_preserve_order(info),
                included_in_primary=grade != "LOW",
            )
        )

    results.sort(key=lambda r: (-(r.final_score if r.final_score is not None else -1), str(r.exhibitor_id)))
    return results


def primary_results(results: Sequence[BuyerMatchResult]) -> list[BuyerMatchResult]:
    """LOW 등급과 하드필터 탈락분을 제외한, 노출용 1차 결과만 걸러낸다."""

    return [r for r in results if r.included_in_primary]
