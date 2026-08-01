"""⑨ Context Re-ranker - docs/05-ai-matching-engine-architecture.md 5.9절.

기본 적합도에 행사 현장 상황을 반영해 순위를 재조정한다. 재정렬 요소(5.9절):
현재 위치와 거리, 남은 체류시간, 부스 대기시간, 상담 가능시간, 확정 일정과의 이동 가능성,
제품 품절 임박, 프로그램 시작시간, 최근 방문·조회 이력, 긴급 운영변경.

"기본 적합도와 '지금 방문할 가치'는 분리해 저장한다"(5.9절 마지막 문장)는 원칙에 따라,
이 단계는 ⑦~⑧ 단계가 만든 preference/goal/trade/behavior/trust 점수(``normalized_score``)를
건드리지 않고 ``score_components["context_score"]``만 새로 채운다. 그 다음
``normalized_score``(기본 적합도+양면 적합도+행동 적합도+데이터 신뢰도의 평균)와
``context_score``를 3:1 비율로 섞어 "지금 방문할 가치"를 반영한 ``final_score``를 만든다
(정확한 배합비는 11/12단계 확정 전까지의 잠정값 - 아래 ``CONTEXT_BLEND_WEIGHT`` 참고).
``raw_score``/``normalized_score`` 자체는 순수 기본 적합도로 남겨 두어야 재현·비교가
쉬우므로 여기서 덮어쓰지 않는다.

"긴급 운영변경"은 booth.operating_status/event_product.inventory_status의 최신 값을 이미
후보 payload가 담고 있으므로(준실시간 처리 - 05번 문서 8.3절) 이 단계가 그 최신 값을 그대로
읽는 것 자체가 곧 긴급 운영변경 반영이다. 별도 이벤트 스트림 처리는 이번 MVP 범위 밖이다.
"""

from __future__ import annotations

from sqlalchemy import bindparam, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.services.matching.types import MatchCandidate, ResolvedContext, ResolvedProfile

#: 05번 문서에 정확한 값이 없어 합리적 기본값을 둔다. TODO(11/12단계 정책·실측 후 교체).
#: candidate_generator/feature_builder가 쓰는 지도 좌표 단위를 실제 미터로 환산하는 임시 축척.
DISTANCE_UNIT_TO_METERS = 5.0
WALK_SPEED_METERS_PER_MINUTE = 60.0  # 도보 약 3.6km/h 가정.
#: normalized_score(기본 적합도) 대 context_score(상황 보정) 배합비.
CONTEXT_BLEND_WEIGHT = 0.3


async def _open_slot_participation_ids(
    db: AsyncSession, participation_ids: set, server_time
) -> set:
    if not participation_ids:
        return set()
    table_available = (
        await db.execute(
            text("SELECT to_regclass('interaction.availability_slot') IS NOT NULL")
        )
    ).scalar_one()
    if not table_available:
        return set()
    statement = text(
        "SELECT participation_id FROM interaction.availability_slot "
        "WHERE participation_id IN :participation_ids AND status = 'OPEN' "
        "AND reserved_count < capacity AND end_at >= :server_time"
    ).bindparams(bindparam("participation_ids", expanding=True))
    rows = await db.execute(
        statement,
        {
            "participation_ids": tuple(participation_ids),
            "server_time": server_time,
        },
    )
    return {row.participation_id for row in rows}


def _booth_adjustment(
    candidate: MatchCandidate,
    profile: ResolvedProfile,
    context: ResolvedContext,
    meeting_open: bool,
) -> tuple[float, dict[str, bool]]:
    payload = candidate.payload
    adjustment = 0.0
    availability: dict[str, bool] = {"open": payload.get("operating_status") == "OPEN"}

    if (
        candidate.distance_meters is not None
        and candidate.estimated_walk_minutes is not None
    ):
        total_needed = candidate.estimated_walk_minutes + (
            candidate.estimated_wait_minutes or 0
        )
        if (
            context.remaining_minutes is not None
            and total_needed > context.remaining_minutes
        ):
            adjustment -= 0.3
        elif total_needed <= 5:
            adjustment += 0.15

    if context.avoid_congestion and payload.get("congestion_level") == "HIGH":
        adjustment -= 0.15

    if candidate.object_id in context.visited_booth_ids:
        # exclude_visited=True인 경우는 이미 ⑤ Hard Filter Engine이 제외했으므로, 여기 도달한
        # 방문 이력은 "다시 봐도 무방하지만 우선순위는 낮추는" 신호로만 반영한다.
        adjustment -= 0.1

    if (
        profile.user_type == "BUYER"
        and payload.get("consultation_enabled")
        and meeting_open
    ):
        availability["meeting"] = True
        adjustment += 0.2

    return adjustment, availability


def _product_adjustment(candidate: MatchCandidate) -> tuple[float, dict[str, bool]]:
    payload = candidate.payload
    adjustment = 0.0
    availability = {
        "purchase": payload.get("purchase_status") in ("AVAILABLE", "LIMITED"),
        "tasting": payload.get("tasting_status") == "AVAILABLE",
    }
    if payload.get("inventory_status") == "LOW":
        adjustment -= 0.1
    return adjustment, availability


def _exhibitor_adjustment(
    candidate: MatchCandidate, profile: ResolvedProfile, meeting_open: bool
) -> tuple[float, dict[str, bool]]:
    adjustment = 0.0
    availability: dict[str, bool] = {}
    if profile.user_type == "BUYER" and meeting_open:
        availability["meeting"] = True
        adjustment += 0.2
    return adjustment, availability


def _program_adjustment(candidate: MatchCandidate, context: ResolvedContext) -> float:
    payload = candidate.payload
    start_at = payload.get("start_at")
    adjustment = 0.0
    if start_at is None:
        return adjustment
    minutes_until = (start_at - context.server_time).total_seconds() / 60.0
    if minutes_until < 0:
        adjustment -= 0.5  # 이미 시작·종료된 프로그램.
    elif (
        context.remaining_minutes is not None
        and minutes_until <= context.remaining_minutes
    ):
        adjustment += 0.15
    return adjustment


async def rerank_by_context(
    db: AsyncSession,
    candidates: list[MatchCandidate],
    *,
    profile: ResolvedProfile,
    context: ResolvedContext,
) -> None:
    participation_ids = {
        c.participation_id for c in candidates if c.participation_id is not None
    }
    open_slot_ids = (
        await _open_slot_participation_ids(db, participation_ids, context.server_time)
        if profile.user_type == "BUYER"
        else set()
    )

    for candidate in candidates:
        if "_distance_units" in candidate.payload:
            distance_meters = (
                candidate.payload["_distance_units"] * DISTANCE_UNIT_TO_METERS
            )
            candidate.distance_meters = distance_meters
            candidate.estimated_walk_minutes = max(
                1, round(distance_meters / WALK_SPEED_METERS_PER_MINUTE)
            )
        if candidate.object_type == "BOOTH":
            candidate.estimated_wait_minutes = candidate.payload.get(
                "estimated_wait_minutes"
            )

        meeting_open = candidate.participation_id in open_slot_ids
        adjustment = 0.0
        availability: dict[str, bool] = {}

        if candidate.object_type == "BOOTH":
            adjustment, availability = _booth_adjustment(
                candidate, profile, context, meeting_open
            )
        elif candidate.object_type == "PRODUCT":
            candidate.status_observed_at = candidate.payload.get("status_observed_at")
            adjustment, availability = _product_adjustment(candidate)
        elif candidate.object_type == "EXHIBITOR":
            adjustment, availability = _exhibitor_adjustment(
                candidate, profile, meeting_open
            )
        elif candidate.object_type == "PROGRAM":
            adjustment = _program_adjustment(candidate, context)

        if candidate.object_id in context.upcoming_meeting_booth_ids:
            availability["meeting"] = True
            adjustment += 0.1  # 이미 확정된 상담이 걸린 대상은 우선순위를 높인다.

        candidate.context_adjustment = adjustment
        candidate.availability = availability
        context_score = min(max(0.5 + adjustment, 0.0), 1.0)
        candidate.score_components["context_score"] = context_score
        # normalized_score(기본 적합도)와 context_score(상황 보정)를 섞어 "지금 방문할
        # 가치"를 반영한 최종 순위 기준값을 만든다 (05번 문서 5.9절 마지막 문장:
        # "기본 적합도와 '지금 방문할 가치'는 분리해 저장한다" - 그래서 normalized_score
        # 자체는 그대로 두고 final_score에만 반영한다).
        candidate.final_score = min(
            max(
                candidate.normalized_score * (1 - CONTEXT_BLEND_WEIGHT)
                + context_score * CONTEXT_BLEND_WEIGHT,
                0.0,
            ),
            1.0,
        )
