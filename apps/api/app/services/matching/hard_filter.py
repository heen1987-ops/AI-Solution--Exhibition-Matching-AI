"""⑤ Hard Filter Engine - docs/05-ai-matching-engine-architecture.md 5.5절.

점수와 무관하게 추천이 불가능한 후보를 제거한다. 통과 여부는 점수 항이 아니라 "노출 자격"
(06절 Eligibility Gate)이다. 한 번의 평가와 후보별 최종 판정을 불변 감사 레코드로 저장하고,
통과한 후보에 같은 평가 ID를 붙여 이후 점수 계산이 자격 판정과 분리되지 않게 한다.

외부 사이트의 세션·DB를 직접 조회하지 않는다. 사용자 제외 목록 같은 상호작용 오버레이는
연동 계층에서 명시적인 입력으로 해석해 전달하므로 PHP 관리자 사이트와 독립적으로 이식할 수 있다.

구현 범위 (05번 문서 5.5절 목록 기준):
    공통  : 관리자 미승인, 참가 취소, 부스 운영 종료(부스 후보), 제품 판매·시음 종료(제품
            후보), 사용자 명시적 제외, 추천 대상 정보 부족.
    일반  : 가격 상한 절대조건 초과, 남은 시간 안에 방문 불가능.
            (연령확인은 ① Request Validator가 요청 단위로 이미 처리했으므로 여기서
            중복하지 않는다 - request_validator.py 모듈 docstring 참고.)
    바이어: MOQ 불일치, 공급지역 불일치, 유통채널 불일치, OEM·PB 필수조건 불일치,
            생산역량 부족, 상담 가능시간 없음(consultation_enabled), 수출 대상국 불일치.

"접근성 필수조건 불일치"는 부스·제품 모델에 접근성 데이터 컬럼이 아직 없어 구현하지 않는다.
TODO(접근성 데이터 소스 확정 후 구현).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.common import new_uuid7
from app.models.filtering import FilterEvaluation, FilterResult
from app.services.matching import errors
from app.services.matching.constraint_shadow import evaluate_runtime_constraint_shadow
from app.services.matching.ontology_support import get_catalog, max_match_strength
from app.services.matching.types import (
    FilterOutcome,
    HardFilterEvaluation,
    MatchCandidate,
    ResolvedContext,
    ResolvedProfile,
    SubjectContext,
)

#: 05번 문서에 정확한 값이 없어 합리적 기본값을 둔다. TODO(11/12단계 정책 확정 후 교체).
ASSUMED_VISIT_MINUTES = 10
FILTER_POLICY_VERSION = "hard-filter-v1.0"

#: 인터페이스 명세 16.2절 표준 이벤트 이름 중 "사용자 명시적 제외"에 대응.
_FilterFn = Callable[
    [MatchCandidate, ResolvedProfile, ResolvedContext],
    "tuple[str, dict[str, Any]] | None",
]


# ---------------------------------------------------------------------------
# 공통 필터
# ---------------------------------------------------------------------------


def _admin_not_approved(
    candidate: MatchCandidate, *_: Any
) -> tuple[str, dict[str, Any]] | None:
    payload = candidate.payload
    if candidate.object_type == "BOOTH":
        status = payload.get("exhibitor_master_approval_status")
    elif candidate.object_type == "PRODUCT":
        status = payload.get("master_approval_status")
        event_product_status = payload.get("approval_status")
        if event_product_status not in (None, "APPROVED"):
            return "ADMIN_NOT_APPROVED", {"approval_status": event_product_status}
    elif candidate.object_type == "EXHIBITOR":
        status = payload.get("master_approval_status")
    else:
        return None
    if status not in (None, "APPROVED"):
        return "ADMIN_NOT_APPROVED", {"master_approval_status": status}
    return None


def _participation_cancelled(
    candidate: MatchCandidate, *_: Any
) -> tuple[str, dict[str, Any]] | None:
    if candidate.object_type not in ("BOOTH", "PRODUCT", "EXHIBITOR"):
        return None
    if candidate.payload.get("participation_status") == "CANCELLED":
        return "PARTICIPATION_CANCELLED", {}
    return None


def _booth_operation_ended(
    candidate: MatchCandidate, *_: Any
) -> tuple[str, dict[str, Any]] | None:
    if candidate.object_type != "BOOTH":
        return None
    if candidate.payload.get("operating_status") == "CLOSED":
        return "BOOTH_CLOSED", {"operating_status": "CLOSED"}
    return None


def _product_unavailable(
    candidate: MatchCandidate, *_: Any
) -> tuple[str, dict[str, Any]] | None:
    if candidate.object_type != "PRODUCT":
        return None
    payload = candidate.payload
    tasting_ended = payload.get("tasting_status") == "ENDED"
    purchase_ended = payload.get("purchase_status") == "ENDED"
    sold_out = payload.get("inventory_status") == "SOLD_OUT"
    if sold_out and purchase_ended:
        return "PRODUCT_SOLD_OUT", {"inventory_status": "SOLD_OUT"}
    if tasting_ended and purchase_ended:
        return "PRODUCT_UNAVAILABLE", {
            "tasting_status": "ENDED",
            "purchase_status": "ENDED",
        }
    return None


def _program_cancelled(
    candidate: MatchCandidate, *_: Any
) -> tuple[str, dict[str, Any]] | None:
    if candidate.object_type != "PROGRAM":
        return None
    if candidate.payload.get("status") == "CANCELLED":
        return "PROGRAM_CANCELLED", {}
    return None


def _insufficient_data(
    candidate: MatchCandidate, profile: ResolvedProfile, _context: ResolvedContext
) -> tuple[str, dict[str, Any]] | None:
    # 05번 문서 5.5절은 "추천 대상 정보 부족"을 공통 필수 필터로 둔다 - 모든 사용자 유형에
    # 적용한다. 제품이 카테고리·맛·향 속성을 하나도 갖지 못하면 취향/카테고리 기반 특성이
    # 전부 0이 되어 사실상 무의미한 추천이 되므로 배제한다.
    payload = candidate.payload
    if (
        candidate.object_type == "PRODUCT"
        and not payload.get("category_code")
        and not payload.get("taste_json")
        and not payload.get("aroma_json")
    ):
        return "INSUFFICIENT_DATA", {"reason": "no_product_attributes"}
    # 바이어 매칭은 거래조건·공급역량이 반드시 필요하므로 추가로 검사한다(일반 관람객
    # 추천은 공급 프로파일 없이도 부스·제품 정보만으로 의미가 있어 요구하지 않는다).
    if (
        profile.user_type == "BUYER"
        and candidate.exhibitor_id is not None
        and "supply_profile" not in payload
    ):
        return "INSUFFICIENT_DATA", {"reason": "no_supply_profile"}
    return None


_COMMON_FILTERS: tuple[_FilterFn, ...] = (
    _admin_not_approved,
    _participation_cancelled,
    _booth_operation_ended,
    _product_unavailable,
    _program_cancelled,
    _insufficient_data,
)


# ---------------------------------------------------------------------------
# 일반 관람객 필터
# ---------------------------------------------------------------------------


def _price_over_limit(
    candidate: MatchCandidate, profile: ResolvedProfile, _context: ResolvedContext
) -> tuple[str, dict[str, Any]] | None:
    if candidate.object_type != "PRODUCT":
        return None
    if not profile.raw_context.get("price_limit_required", False):
        return None
    price_max = profile.numeric_conditions.get("retail_price_max")
    if price_max is None:
        return None
    price = candidate.payload.get("event_price_amount")
    if price is None:
        price = candidate.payload.get("retail_price_amount")
    if price is None:
        return None
    if price > price_max:
        return "PRICE_OVER_LIMIT", {"price_max": price_max, "price": price}
    return None


def _time_insufficient(
    candidate: MatchCandidate, _profile: ResolvedProfile, context: ResolvedContext
) -> tuple[str, dict[str, Any]] | None:
    if candidate.object_type != "BOOTH":
        return None
    if context.remaining_minutes is None:
        return None
    wait = candidate.payload.get("estimated_wait_minutes") or 0
    required = wait + ASSUMED_VISIT_MINUTES
    if required > context.remaining_minutes:
        return "TIME_INSUFFICIENT", {
            "remaining_minutes": context.remaining_minutes,
            "required_minutes": required,
        }
    return None


def _already_visited(
    candidate: MatchCandidate, _profile: ResolvedProfile, context: ResolvedContext
) -> tuple[str, dict[str, Any]] | None:
    # 05번 문서 5.5절에는 명시되지 않지만, 인터페이스 명세 9.1절 요청 예시의
    # "exclude_visited": true는 사용자가 이미 방문한 부스를 이번 추천에서 빼 달라는
    # 명시적 조건이다. §5.5의 "사용자 명시적 제외"를 개별 항목 제외뿐 아니라 요청 수준
    # 조건까지 포함하는 것으로 해석해 여기서 적용한다.
    if candidate.object_type != "BOOTH" or not context.exclude_visited:
        return None
    if candidate.object_id in context.visited_booth_ids:
        return "ALREADY_VISITED", {}
    return None


_GENERAL_VISITOR_FILTERS: tuple[_FilterFn, ...] = (
    _price_over_limit,
    _time_insufficient,
    _already_visited,
)


# ---------------------------------------------------------------------------
# 바이어 필터
# ---------------------------------------------------------------------------


def _trade_profile(candidate: MatchCandidate) -> dict[str, Any] | None:
    supply_profile = candidate.payload.get("supply_profile")
    if not supply_profile:
        return None
    return supply_profile.get("trade_profile")


def _moq_mismatch(
    candidate: MatchCandidate, profile: ResolvedProfile, _context: ResolvedContext
) -> tuple[str, dict[str, Any]] | None:
    trade_profile = _trade_profile(candidate)
    if trade_profile is None:
        return None
    buyer_max = profile.numeric_conditions.get("monthly_units_max")
    exhibitor_min = trade_profile.get("min_order_quantity")
    if buyer_max is None or exhibitor_min is None:
        return None
    if buyer_max < exhibitor_min:
        return "MOQ_MISMATCH", {"buyer_max": buyer_max, "exhibitor_min": exhibitor_min}
    return None


def _capacity_insufficient(
    candidate: MatchCandidate, profile: ResolvedProfile, _context: ResolvedContext
) -> tuple[str, dict[str, Any]] | None:
    trade_profile = _trade_profile(candidate)
    if trade_profile is None:
        return None
    buyer_min = profile.numeric_conditions.get("monthly_units_min")
    available = trade_profile.get("monthly_available_capacity")
    if buyer_min is None or available is None:
        return None
    if buyer_min > available:
        return "CAPACITY_INSUFFICIENT", {
            "buyer_min": buyer_min,
            "available_capacity": available,
        }
    return None


def _region_mismatch(
    candidate: MatchCandidate, profile: ResolvedProfile, _context: ResolvedContext
) -> tuple[str, dict[str, Any]] | None:
    required = profile.required_codes(profile.regions)
    if not required:
        return None
    trade_profile = _trade_profile(candidate)
    if trade_profile is None:
        return None
    offered = trade_profile.get("regions") or []
    if not offered:
        return None
    catalog = get_catalog()
    if max_match_strength(catalog, required, offered) <= 0:
        return "REGION_MISMATCH", {
            "required": sorted(required),
            "offered": sorted(offered),
        }
    return None


def _channel_mismatch(
    candidate: MatchCandidate, profile: ResolvedProfile, _context: ResolvedContext
) -> tuple[str, dict[str, Any]] | None:
    required = profile.required_codes(profile.channels)
    if not required:
        return None
    trade_profile = _trade_profile(candidate)
    if trade_profile is None:
        return None
    offered = trade_profile.get("channels") or []
    if not offered:
        return None
    catalog = get_catalog()
    if max_match_strength(catalog, required, offered) <= 0:
        return "CHANNEL_MISMATCH", {
            "required": sorted(required),
            "offered": sorted(offered),
        }
    return None


def _goal_requires(profile: ResolvedProfile, code: str) -> bool:
    return any(
        goal.code == code and goal.requirement_level == "REQUIRED"
        for goal in profile.goals
    )


def _oem_private_label_mismatch(
    candidate: MatchCandidate, profile: ResolvedProfile, _context: ResolvedContext
) -> tuple[str, dict[str, Any]] | None:
    trade_profile = _trade_profile(candidate)
    if trade_profile is None:
        return None
    if (
        _goal_requires(profile, "BIZ_GOAL.OEM")
        and trade_profile.get("oem_status") == "NO"
    ):
        return "OEM_MISMATCH", {"oem_status": "NO"}
    if (
        _goal_requires(profile, "BIZ_GOAL.PRIVATE_LABEL")
        and trade_profile.get("private_label_status") == "NO"
    ):
        return "PRIVATE_LABEL_MISMATCH", {"private_label_status": "NO"}
    return None


def _export_mismatch(
    candidate: MatchCandidate, profile: ResolvedProfile, _context: ResolvedContext
) -> tuple[str, dict[str, Any]] | None:
    trade_profile = _trade_profile(candidate)
    if trade_profile is None:
        return None
    if (
        _goal_requires(profile, "BIZ_GOAL.EXPORT")
        and trade_profile.get("export_status") == "NO"
    ):
        return "EXPORT_MISMATCH", {"export_status": "NO"}
    return None


def _meeting_unavailable(
    candidate: MatchCandidate, profile: ResolvedProfile, _context: ResolvedContext
) -> tuple[str, dict[str, Any]] | None:
    if candidate.object_type not in ("EXHIBITOR", "BOOTH"):
        return None
    if not profile.raw_context.get("meeting_required", False):
        return None
    if candidate.payload.get("consultation_enabled") is False:
        return "MEETING_UNAVAILABLE", {"consultation_enabled": False}
    return None


_BUYER_FILTERS: tuple[_FilterFn, ...] = (
    _moq_mismatch,
    _capacity_insufficient,
    _region_mismatch,
    _channel_mismatch,
    _oem_private_label_mismatch,
    _export_mismatch,
    _meeting_unavailable,
)


def _json_ready(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _json_ready(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, set):
        return sorted(_json_ready(item) for item in value)
    if isinstance(value, (UUID, Decimal)):
        return str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    return str(value)


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        _json_ready(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _context_snapshot(context: ResolvedContext) -> dict[str, Any]:
    return {
        "current_zone": context.current_zone,
        "current_zone_id": context.current_zone_id,
        "remaining_minutes": context.remaining_minutes,
        "visited_booth_ids": context.visited_booth_ids,
        "upcoming_meeting_booth_ids": context.upcoming_meeting_booth_ids,
        "operational_snapshot_version": context.operational_snapshot_version,
        "exclude_visited": context.exclude_visited,
        "include_meetings": context.include_meetings,
        "avoid_congestion": context.avoid_congestion,
        "server_time": context.server_time,
    }


def evaluate_hard_filters(
    *,
    candidates: list[MatchCandidate],
    subject: SubjectContext,
    profile: ResolvedProfile,
    context: ResolvedContext,
    excluded_recommendable_ids: set[UUID],
    policy_version: str = FILTER_POLICY_VERSION,
) -> HardFilterEvaluation:
    """Evaluate hard constraints without performing a database write."""

    started_at = datetime.now(UTC)
    evaluation_id = new_uuid7()
    filters: list[_FilterFn] = list(_COMMON_FILTERS)
    filters.extend(
        _GENERAL_VISITOR_FILTERS
        if profile.user_type == "GENERAL_VISITOR"
        else _BUYER_FILTERS
    )

    eligible: list[MatchCandidate] = []
    outcomes: list[FilterOutcome] = []
    for candidate in candidates:
        candidate_fingerprint = _fingerprint(
            {
                "object_type": candidate.object_type,
                "object_id": candidate.object_id,
                "recommendable_id": candidate.recommendable_id,
                "payload": candidate.payload,
            }
        )
        failure: tuple[str, dict[str, Any]] | None = None
        if (
            candidate.recommendable_id is not None
            and candidate.recommendable_id in excluded_recommendable_ids
        ):
            failure = ("USER_EXCLUDED", {})
        else:
            for filter_fn in filters:
                failure = filter_fn(candidate, profile, context)
                if failure is not None:
                    break

        if failure is None:
            passed = True
            code = None
            details: dict[str, Any] = {}
            eligible.append(candidate)
            candidate.filter_evaluation_id = str(evaluation_id)
        else:
            passed = False
            code, details = failure

        outcomes.append(
            FilterOutcome(
                filter_evaluation_id=evaluation_id,
                object_id=candidate.object_id,
                object_type=candidate.object_type,
                recommendable_id=candidate.recommendable_id,
                passed=passed,
                filter_code=code,
                details=details,
                evidence_refs=[f"candidate_payload_sha256:{candidate_fingerprint}"],
                candidate_fingerprint=candidate_fingerprint,
            )
        )

    fingerprint_candidates = sorted(
        (
            {
                "object_type": outcome.object_type,
                "object_id": outcome.object_id,
                "candidate_fingerprint": outcome.candidate_fingerprint,
            }
            for outcome in outcomes
        ),
        key=lambda item: (item["object_type"], str(item["object_id"])),
    )
    input_fingerprint = _fingerprint(
        {
            "tenant_id": subject.tenant_id,
            "event_id": subject.event_id,
            "profile_id": profile.profile_id,
            "profile_version_id": profile.profile_version_id,
            "policy_version": policy_version,
            "context": _context_snapshot(context),
            "excluded_recommendable_ids": excluded_recommendable_ids,
            "candidates": fingerprint_candidates,
        }
    )
    return HardFilterEvaluation(
        filter_evaluation_id=evaluation_id,
        policy_version=policy_version,
        input_fingerprint=input_fingerprint,
        started_at=started_at,
        completed_at=datetime.now(UTC),
        eligible_candidates=eligible,
        outcomes=outcomes,
        constraint_shadow=evaluate_runtime_constraint_shadow(
            profile=profile,
            candidates=candidates,
            legacy_outcomes=outcomes,
        ),
    )


async def persist_hard_filter_evaluation(
    db: AsyncSession,
    *,
    evaluation: HardFilterEvaluation,
    subject: SubjectContext,
    profile: ResolvedProfile,
    context: ResolvedContext,
) -> None:
    """Stage an append-only evaluation and all candidate decisions."""

    if profile.profile_version_id is None:
        raise errors.profile_incomplete(
            "하드필터 평가에는 고정된 프로파일 버전이 필요합니다."
        )

    row = FilterEvaluation(
        filter_evaluation_id=evaluation.filter_evaluation_id,
        tenant_id=subject.tenant_id,
        event_id=subject.event_id,
        profile_id=profile.profile_id,
        profile_version_id=profile.profile_version_id,
        request_id=subject.request_id,
        idempotency_key=subject.idempotency_key,
        filter_policy_version=evaluation.policy_version,
        input_fingerprint=evaluation.input_fingerprint,
        context_snapshot=_json_ready(_context_snapshot(context)),
        candidate_count=len(evaluation.outcomes),
        eligible_count=len(evaluation.eligible_candidates),
        rejected_count=evaluation.rejected_count,
        evaluation_status="COMPLETED",
        started_at=evaluation.started_at,
        completed_at=evaluation.completed_at,
    )
    row.results = [
        FilterResult(
            filter_evaluation_id=evaluation.filter_evaluation_id,
            object_type=outcome.object_type,
            object_id=outcome.object_id,
            recommendable_id=outcome.recommendable_id,
            passed=outcome.passed,
            filter_code=outcome.filter_code,
            details_json=_json_ready(outcome.details),
            evidence_refs=outcome.evidence_refs,
            candidate_fingerprint=outcome.candidate_fingerprint,
            evaluated_at=evaluation.completed_at,
        )
        for outcome in evaluation.outcomes
    ]
    db.add(row)
    await db.flush()


async def apply_hard_filters(
    db: AsyncSession,
    *,
    candidates: list[MatchCandidate],
    subject: SubjectContext,
    profile: ResolvedProfile,
    context: ResolvedContext,
    excluded_recommendable_ids: set[UUID],
) -> HardFilterEvaluation:
    """Evaluate and stage one reproducible hard-filter run."""

    evaluation = evaluate_hard_filters(
        candidates=candidates,
        subject=subject,
        profile=profile,
        context=context,
        excluded_recommendable_ids=excluded_recommendable_ids,
    )
    await persist_hard_filter_evaluation(
        db,
        evaluation=evaluation,
        subject=subject,
        profile=profile,
        context=context,
    )
    return evaluation
