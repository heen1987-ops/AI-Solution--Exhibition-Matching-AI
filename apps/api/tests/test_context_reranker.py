from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from app.services.matching.context_policy import (
    BASE_SCORE_WEIGHT,
    CONTEXT_COMPONENT_WEIGHTS,
    CONTEXT_POLICY_VERSION,
    CONTEXT_SCORE_WEIGHT,
    evaluate_context,
)
from app.services.matching.types import (
    MatchCandidate,
    ResolvedContext,
    ResolvedProfile,
)


def _profile(user_type: str = "GENERAL_VISITOR") -> ResolvedProfile:
    return ResolvedProfile(
        profile_id=uuid.uuid4(),
        profile_version=1,
        profile_version_id=uuid.uuid4(),
        user_type=user_type,
        completeness=80,
        goals=[],
        categories=[],
        channels=[],
        regions=[],
        taste=[],
        aroma=[],
        extra={},
        numeric_conditions={},
        raw_context={},
    )


def _context(*, remaining_minutes: int | None = 60) -> ResolvedContext:
    now = datetime(2026, 8, 1, 12, tzinfo=UTC)
    return ResolvedContext(
        current_zone="A",
        current_zone_id=uuid.uuid4(),
        remaining_minutes=remaining_minutes,
        visited_booth_ids=set(),
        upcoming_meetings=[],
        upcoming_meeting_booth_ids=set(),
        operational_snapshot_version=42,
        exclude_visited=False,
        include_meetings=True,
        avoid_congestion=False,
        server_time=now,
    )


def _booth(*, wait: int = 0, status: str = "OPEN") -> MatchCandidate:
    booth_id = uuid.uuid4()
    return MatchCandidate(
        object_type="BOOTH",
        object_id=booth_id,
        recommendable_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        participation_id=uuid.uuid4(),
        public_object_id=str(booth_id),
        normalized_score=0.8,
        distance_meters=120,
        estimated_walk_minutes=2,
        estimated_wait_minutes=wait,
        payload={
            "operating_status": status,
            "congestion_level": "LOW" if wait <= 5 else "HIGH",
            "estimated_wait_minutes": wait,
            "consultation_enabled": True,
            "map_x": 10,
            "map_y": 20,
        },
    )


def test_policy_weights_and_blend_are_published_contract() -> None:
    assert sum(CONTEXT_COMPONENT_WEIGHTS.values()) == 1.0
    assert BASE_SCORE_WEIGHT == 0.85
    assert CONTEXT_SCORE_WEIGHT == 0.15


def test_impossible_visit_is_ranked_below_actionable_visit() -> None:
    context = _context(remaining_minutes=25)
    near = _booth(wait=2)
    far = _booth(wait=30)
    far.distance_meters = 900
    far.estimated_walk_minutes = 15

    near_result = evaluate_context(
        near, profile=_profile(), context=context, meeting_open=False
    )
    far_result = evaluate_context(
        far, profile=_profile(), context=context, meeting_open=False
    )

    assert near_result.policy_version == CONTEXT_POLICY_VERSION
    assert near_result.context_score is not None
    assert far_result.components["time_feasibility"] == 0.0
    assert near_result.final_score > far_result.final_score


def test_missing_observations_are_reweighted_not_neutral_filled() -> None:
    candidate = MatchCandidate(
        object_type="PRODUCT",
        object_id=uuid.uuid4(),
        recommendable_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        participation_id=uuid.uuid4(),
        public_object_id="product-1",
        normalized_score=0.75,
        payload={"inventory_status": "LOW", "purchase_status": "AVAILABLE"},
    )
    result = evaluate_context(
        candidate,
        profile=_profile(),
        context=_context(remaining_minutes=None),
        meeting_open=False,
    )

    assert result.components["proximity"] is None
    assert "proximity" not in result.effective_weights
    assert sum(result.effective_weights.values()) == pytest.approx(1.0)
    assert result.components["inventory_urgency"] == 1.0


def test_optional_meeting_module_absence_does_not_become_a_verified_zero() -> None:
    candidate = _booth(wait=1)
    result = evaluate_context(
        candidate,
        profile=_profile("BUYER"),
        context=_context(),
        meeting_open=None,
    )

    assert result.components["meeting_availability"] is None


def test_no_observations_preserve_the_base_score() -> None:
    candidate = MatchCandidate(
        object_type="PRODUCT",
        object_id=uuid.uuid4(),
        recommendable_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        participation_id=uuid.uuid4(),
        public_object_id="unobserved-product",
        normalized_score=0.73,
    )
    context = _context(remaining_minutes=None)
    context.current_zone = None
    result = evaluate_context(
        candidate, profile=_profile(), context=context, meeting_open=None
    )

    assert result.context_score is None
    assert result.effective_weights == {}
    assert result.final_score == 0.73


def test_same_input_is_reproducible_and_context_change_rotates_fingerprint() -> None:
    candidate = _booth(wait=4)
    context = _context()
    first = evaluate_context(
        candidate, profile=_profile(), context=context, meeting_open=False
    )
    second = evaluate_context(
        candidate, profile=_profile(), context=context, meeting_open=False
    )
    changed = _context(remaining_minutes=10)
    changed.server_time = context.server_time + timedelta(minutes=1)
    third = evaluate_context(
        candidate, profile=_profile(), context=changed, meeting_open=False
    )

    assert first.input_fingerprint == second.input_fingerprint
    assert first.score_fingerprint == second.score_fingerprint
    assert first.input_fingerprint != third.input_fingerprint


def test_confirmed_meeting_route_can_make_candidate_infeasible() -> None:
    candidate = _booth(wait=10)
    context = _context()
    meeting_booth_id = uuid.uuid4()
    context.upcoming_meeting_booth_ids.add(meeting_booth_id)
    context.upcoming_meetings.append(
        {
            "booth_id": meeting_booth_id,
            "start_at": context.server_time + timedelta(minutes=5),
            "map_x": 100,
            "map_y": 100,
        }
    )

    result = evaluate_context(
        candidate, profile=_profile("BUYER"), context=context, meeting_open=True
    )
    assert result.components["meeting_availability"] == 1.0
    assert result.components["schedule_feasibility"] == 0.0
