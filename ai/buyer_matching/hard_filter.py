"""B2B 하드필터: 바이어-업체 후보 쌍이 "매칭 후보로 고려될 자격이 있는가"만 판정한다.

점수화(scoring.py)는 이 필터를 통과한 후보에만 적용된다 - 하드필터를 통과하지 못한 후보는
어떤 이유로도 점수가 매겨지지 않는다(파이프라인 계층인 pipeline.py가 이를 강제한다).

핵심 원칙(임무 지시 그대로): UNKNOWN은 필수 조건을 통과시키지 않는다. 다만 "정보가 없어서
탈락"과 "명시적으로 조건을 만족하지 않아서 탈락"은 구분해 반환한다(``HardFilterResult.
info_codes``/``unknown_required_codes``) - 신호 없이 조용히 버려지지 않는다.
"""

from __future__ import annotations

from collections.abc import Sequence

from ai.buyer_matching import reason_codes as rc
from ai.buyer_matching.types import (
    _BUYER_VERIFICATION_ALLOWED,
    _EXHIBITOR_APPROVAL_ALLOWED,
    _PARTICIPATION_ACTIVE_ALLOWED,
    _VISIBILITY_ALLOWED_PRE_MEETING,
    BuyerProfile,
    ExhibitorCandidate,
    HardFilterResult,
)


def _check_required_codes(
    required: frozenset[str],
    have: frozenset[str],
    declared: frozenset[str],
) -> tuple[bool, tuple[str, ...]]:
    """required가 have의 부분집합인지 확인한다. 만족하지 못한 코드 중 declared에 없는
    것(=UNKNOWN, 아직 업체가 답하지 않음)만 별도로 반환한다(declared에는 있지만 have에는
    없는 코드는 "명시적으로 NO"로, 정보 필요 신호를 추가하지 않는다).
    """

    missing = required - have
    if not missing:
        return True, ()
    unknown = tuple(sorted(code for code in missing if code not in declared))
    return False, unknown


def hard_filter(
    buyer_profile: BuyerProfile,
    exhibitor_candidates: Sequence[ExhibitorCandidate],
) -> list[HardFilterResult]:
    """각 후보에 대해 하드필터를 평가한다. 입력 순서를 그대로 보존해 반환한다(결정적)."""

    results: list[HardFilterResult] = []

    buyer_verification_ok = buyer_profile.verification_status in _BUYER_VERIFICATION_ALLOWED

    required_product_tech = frozenset(buyer_profile.required_product_codes) | frozenset(
        buyer_profile.required_technology_codes
    )
    required_region = frozenset(buyer_profile.required_region_codes)
    required_cooperation = frozenset(buyer_profile.required_cooperation_type_codes)

    for candidate in exhibitor_candidates:
        failed: list[str] = []
        info: list[str] = []
        unknown_required: list[str] = []

        if not buyer_verification_ok:
            failed.append("BUYER_VERIFICATION")

        if candidate.approval_status not in _EXHIBITOR_APPROVAL_ALLOWED:
            failed.append("EXHIBITOR_APPROVAL")

        if candidate.participation_status not in _PARTICIPATION_ACTIVE_ALLOWED:
            failed.append("PARTICIPATION_ACTIVE")

        if candidate.visibility_scope not in _VISIBILITY_ALLOWED_PRE_MEETING:
            failed.append("VISIBILITY_SCOPE")

        if required_product_tech:
            have = frozenset(candidate.product_codes) | frozenset(candidate.technology_codes)
            declared = frozenset(candidate.declared_capability_codes)
            ok, unknown = _check_required_codes(required_product_tech, have, declared)
            if not ok:
                failed.append("REQUIRED_PRODUCT_TECH")
                unknown_required.extend(unknown)

        if required_region:
            have_region = frozenset(candidate.supply_region_codes)
            if not have_region:
                failed.append("REQUIRED_REGION")
                info.append(rc.INFO_REGION_UNKNOWN)
            elif not required_region.issubset(have_region):
                failed.append("REQUIRED_REGION")

        if buyer_profile.moq_ceiling is not None:
            if candidate.moq is None:
                failed.append("MOQ_CEILING")
                info.append(rc.INFO_MOQ_UNKNOWN)
            elif candidate.moq > buyer_profile.moq_ceiling:
                failed.append("MOQ_CEILING")

        if required_cooperation:
            have_coop = frozenset(candidate.cooperation_type_codes)
            declared = frozenset(candidate.declared_capability_codes)
            ok, unknown = _check_required_codes(required_cooperation, have_coop, declared)
            if not ok:
                failed.append("REQUIRED_COOPERATION_TYPE")
                unknown_required.extend(unknown)

        if buyer_profile.require_new_trade_available:
            status = candidate.new_trade_available
            if status in ("UNKNOWN", "NO"):
                failed.append("NEW_TRADE_AVAILABLE")
            elif status == "CONDITIONAL":
                info.append(rc.INFO_TRADE_CONDITION_CONDITIONAL)
            # YES / NEGOTIABLE -> 그대로 통과

        if buyer_profile.require_meeting_available and candidate.meeting_available is not True:
            failed.append("MEETING_AVAILABLE")

        results.append(
            HardFilterResult(
                exhibitor_id=candidate.exhibitor_id,
                passed=not failed,
                failed_filters=tuple(failed),
                info_codes=rc.dedupe_preserve_order(info),
                unknown_required_codes=tuple(sorted(set(unknown_required))),
            )
        )

    return results
