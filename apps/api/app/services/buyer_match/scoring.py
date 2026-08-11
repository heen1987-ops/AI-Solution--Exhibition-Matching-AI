"""하드필터를 통과한 바이어 매칭 후보의 점수·등급·근거코드·unknown_fields 계산.

등급 임계값은 ``app.services.matching.types.score_to_match_level``을 그대로 재사용한다
(VERY_HIGH/HIGH/MEDIUM/LOW 4단계 임계값을 이 트랙이 중복 정의하면 두 매칭 경로의 등급
기준이 몰래 어긋날 수 있어, 순수 함수 하나를 공유하는 쪽을 택했다 - 이 파일이
``app/services/matching/**``의 다른 어떤 상태도 가져오지 않고 이 함수 하나만 참조한다는
점에서 트랙 경계를 침범하지 않는다).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.services.buyer_match.eligibility import BuyerCriteria, CandidateRow
from app.services.matching.types import score_to_match_level

_CATEGORY_WEIGHT = 0.4
_REGION_WEIGHT = 0.2
_PRICE_WEIGHT = 0.2
_DEFAULT_NEUTRAL_SCORE = 0.5
_POSITIVE_TRADE_STATUSES = frozenset({"YES", "NEGOTIABLE"})


@dataclass(frozen=True)
class ScoredCandidate:
    exhibitor_id: uuid.UUID
    participation_id: uuid.UUID
    score: float
    grade: str
    reason_codes: list[str]
    unknown_fields: list[str]


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(values))


def score_candidate(candidate: CandidateRow, criteria: BuyerCriteria) -> ScoredCandidate:
    reason_codes: list[str] = []
    unknown_fields: list[str] = []
    weighted_sum = 0.0
    weight_total = 0.0

    if criteria.categories:
        overlap = len(candidate.category_codes & criteria.categories) / len(
            criteria.categories
        )
        weighted_sum += overlap * _CATEGORY_WEIGHT
        weight_total += _CATEGORY_WEIGHT
        if overlap > 0:
            reason_codes.append("CATEGORY_MATCH")
    elif candidate.category_codes:
        weighted_sum += _DEFAULT_NEUTRAL_SCORE * _CATEGORY_WEIGHT
        weight_total += _CATEGORY_WEIGHT

    if criteria.regions:
        matched = candidate.region_code in criteria.regions
        weighted_sum += (1.0 if matched else 0.0) * _REGION_WEIGHT
        weight_total += _REGION_WEIGHT
        if matched:
            reason_codes.append("REGION_MATCH")
    elif candidate.region_code is None:
        unknown_fields.append("REGION_UNKNOWN")

    if not candidate.has_trade_condition:
        unknown_fields.extend(
            [
                "PRICE_UNKNOWN",
                "OEM_STATUS_UNKNOWN",
                "PRIVATE_LABEL_STATUS_UNKNOWN",
                "EXPORT_STATUS_UNKNOWN",
            ]
        )
    else:
        if candidate.oem_status == "UNKNOWN":
            unknown_fields.append("OEM_STATUS_UNKNOWN")
        elif candidate.oem_status in _POSITIVE_TRADE_STATUSES:
            reason_codes.append("OEM_AVAILABLE")

        if candidate.private_label_status == "UNKNOWN":
            unknown_fields.append("PRIVATE_LABEL_STATUS_UNKNOWN")
        elif candidate.private_label_status in _POSITIVE_TRADE_STATUSES:
            reason_codes.append("PRIVATE_LABEL_AVAILABLE")

        if candidate.export_status == "UNKNOWN":
            unknown_fields.append("EXPORT_STATUS_UNKNOWN")
        elif candidate.export_status in _POSITIVE_TRADE_STATUSES:
            reason_codes.append("EXPORT_AVAILABLE")

        if candidate.wholesale_price_min is None and candidate.wholesale_price_max is None:
            unknown_fields.append("PRICE_UNKNOWN")

    if (criteria.price_min is not None or criteria.price_max is not None) and (
        candidate.wholesale_price_min is not None
        or candidate.wholesale_price_max is not None
    ):
        weighted_sum += 1.0 * _PRICE_WEIGHT
        weight_total += _PRICE_WEIGHT
        reason_codes.append("PRICE_RANGE_FIT")

    if not candidate.profile_approved:
        unknown_fields.append("SUPPLY_PROFILE_UNAPPROVED")

    score = (weighted_sum / weight_total) if weight_total > 0 else _DEFAULT_NEUTRAL_SCORE
    score = max(0.0, min(1.0, score))
    grade = score_to_match_level(score)

    return ScoredCandidate(
        exhibitor_id=candidate.exhibitor_id,
        participation_id=candidate.participation_id,
        score=score,
        grade=grade,
        reason_codes=_dedupe(reason_codes),
        unknown_fields=_dedupe(unknown_fields),
    )
