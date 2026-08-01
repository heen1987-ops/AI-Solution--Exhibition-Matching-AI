"""⑩ Diversity & Policy Controller - docs/05-ai-matching-engine-architecture.md 5.10절.

상위 점수만 반복 노출되는 문제를 방지한다. 이 컨트롤러는 실제로 동작해야 하는 로직으로
지시되어 있으므로(더미 금지) 다음을 전부 구현한다.

    - 동일 업체 노출 상한 (``exhibitor_id`` 당 ``MAX_PER_EXHIBITOR``)
    - 동일 최상위 카테고리 연속 추천 제한 (``MAX_CONSECUTIVE_SAME_CATEGORY``)
    - 추천 슬롯 배분: 상위 적합도 70% / 상황 최적 15% / 탐색·다양성 10% / 신규업체 5%
      (5.10절 "추천 슬롯 예시" 그대로. 정확한 비율은 운영 데이터로 조정하라고 문서가 명시함)
    - 데이터 완성도 미달 업체 감점 (``trust_score`` < ``LOW_TRUST_THRESHOLD``)

운영자 지정 제외·민원 업체 일시 제한은 그런 목록을 담을 테이블이 아직 없어 이번 구현에는
없다. TODO(운영 정책 테이블 설계 후 구현).

추천 대상과 추천 행동을 분리하는 05번 문서 7절 규칙에 따라, 최종 순위가 확정된 뒤에만
``recommended_action``을 배정한다.
"""

from __future__ import annotations

from datetime import UTC, datetime

from app.services.matching.ontology_support import get_catalog
from app.services.matching.types import MatchCandidate, ResolvedProfile

#: 05번 문서 5.10절에 정확한 값이 없어 합리적 기본값을 둔다. TODO(운영 데이터 확정 후 교체).
MAX_PER_EXHIBITOR = 2
MAX_CONSECUTIVE_SAME_CATEGORY = 2
TOP_SCORE_RATIO = 0.70
CONTEXT_OPTIMAL_RATIO = 0.15
EXPLORATION_RATIO = 0.10
NEW_EXHIBITOR_RATIO = 0.05
LOW_TRUST_THRESHOLD = 0.4
LOW_TRUST_PENALTY = 0.05

_MIN_DATETIME = datetime.min.replace(tzinfo=UTC)


def _top_level_category(candidate: MatchCandidate) -> str | None:
    payload = candidate.payload
    code = payload.get("category_code")
    if not code:
        codes = (
            payload.get("business_types")
            or (payload.get("supply_profile") or {}).get("business_types")
            or []
        )
        code = codes[0] if codes else None
    if not code:
        return None
    catalog = get_catalog()
    try:
        ancestors = catalog.ancestors(code)
    except KeyError:
        return code
    return ancestors[-1] if ancestors else code


def _effective_score(candidate: MatchCandidate) -> float:
    return candidate.final_score + candidate.diversity_adjustment


def _decide_action(candidate: MatchCandidate, profile: ResolvedProfile) -> str:
    if candidate.object_type == "PROGRAM":
        return "JOIN_PROGRAM"

    if (
        profile.user_type == "BUYER"
        and candidate.availability.get("meeting")
        and candidate.object_type
        in (
            "EXHIBITOR",
            "BOOTH",
        )
    ):
        return "REQUEST_MEETING"

    if candidate.object_type == "BOOTH":
        wait = candidate.estimated_wait_minutes or 0
        walk = candidate.estimated_walk_minutes or 0
        if candidate.payload.get("operating_status") != "OPEN":
            return "SAVE_FOR_LATER"
        if wait <= 5 and walk <= 10:
            return "VISIT_NOW"
        if candidate.payload.get("congestion_level") == "HIGH" or wait > 15:
            return "SAVE_FOR_LATER"
        return "ADD_TO_ROUTE"

    if candidate.object_type == "PRODUCT":
        if candidate.availability.get("purchase") or candidate.availability.get(
            "tasting"
        ):
            return "SAVE_FOR_LATER" if candidate.context_adjustment < 0 else "VISIT_NOW"
        return "REFINE_PROFILE"

    if candidate.object_type == "EXHIBITOR":
        return "REQUEST_MEETING" if profile.user_type == "BUYER" else "SAVE_FOR_LATER"

    return "SAVE_FOR_LATER"


def apply_diversity_policy(
    candidates: list[MatchCandidate],
    *,
    limit: int,
    profile: ResolvedProfile,
) -> list[MatchCandidate]:
    for candidate in candidates:
        trust = candidate.score_components.get("trust_score")
        if trust is not None and trust < LOW_TRUST_THRESHOLD:
            candidate.diversity_adjustment -= LOW_TRUST_PENALTY

    pool = sorted(candidates, key=_effective_score, reverse=True)

    selected: list[MatchCandidate] = []
    selected_keys: set[tuple[str, object]] = set()
    exhibitor_counts: dict[object, int] = {}

    def can_take(candidate: MatchCandidate) -> bool:
        if (
            candidate.exhibitor_id is not None
            and exhibitor_counts.get(candidate.exhibitor_id, 0) >= MAX_PER_EXHIBITOR
        ):
            return False
        if len(selected) >= MAX_CONSECUTIVE_SAME_CATEGORY:
            category = _top_level_category(candidate)
            if category is not None:
                recent = [
                    _top_level_category(item)
                    for item in selected[-MAX_CONSECUTIVE_SAME_CATEGORY:]
                ]
                if all(item == category for item in recent):
                    return False
        return True

    def take(candidate: MatchCandidate) -> None:
        selected.append(candidate)
        selected_keys.add((candidate.object_type, candidate.object_id))
        if candidate.exhibitor_id is not None:
            exhibitor_counts[candidate.exhibitor_id] = (
                exhibitor_counts.get(candidate.exhibitor_id, 0) + 1
            )

    def fill(
        target_count: int, ordered: list[MatchCandidate], *, relax_caps: bool = False
    ) -> None:
        taken = 0
        for candidate in ordered:
            if taken >= target_count or len(selected) >= limit:
                return
            key = (candidate.object_type, candidate.object_id)
            if key in selected_keys:
                continue
            if not relax_caps and not can_take(candidate):
                continue
            take(candidate)
            taken += 1

    top_slots = max(1, round(limit * TOP_SCORE_RATIO))
    context_slots = round(limit * CONTEXT_OPTIMAL_RATIO)
    exploration_slots = round(limit * EXPLORATION_RATIO)
    new_exhibitor_slots = max(0, limit - top_slots - context_slots - exploration_slots)

    fill(top_slots, pool)

    context_sorted = sorted(
        pool, key=lambda c: c.score_components.get("context_score") or 0.0, reverse=True
    )
    fill(context_slots, context_sorted)

    exploration_sorted = sorted(
        pool, key=lambda c: c.features.get("novelty_score", 0.0), reverse=True
    )
    fill(exploration_slots, exploration_sorted)

    new_exhibitor_sorted = sorted(
        pool, key=lambda c: c.payload.get("created_at") or _MIN_DATETIME, reverse=True
    )
    fill(new_exhibitor_slots, new_exhibitor_sorted)

    # 슬롯 배분 후에도 limit을 못 채웠다면(다양성 제약으로 후보가 부족한 경우) 제약을 풀고
    # 남은 상위 점수 후보로 채운다 - 05번 문서 10.5절 "필터를 무작정 해제하지 않는다"는
    # Hard Filter 단계 원칙이며, 다양성 보정은 정책이지 자격 조건이 아니므로 여기서는 완화가
    # 합리적이다.
    if len(selected) < min(limit, len(pool)):
        fill(limit - len(selected), pool, relax_caps=True)

    selected = selected[:limit]
    for index, candidate in enumerate(selected, start=1):
        candidate.rank = index
        candidate.final_score = min(
            max(candidate.final_score + candidate.diversity_adjustment, 0.0), 1.0
        )
        candidate.recommended_action = _decide_action(candidate, profile)

    return selected
