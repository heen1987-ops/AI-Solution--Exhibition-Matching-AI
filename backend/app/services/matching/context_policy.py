"""Immutable deterministic policy for stage-14 context-aware re-ranking.

The base score answers "is this a good match?" while this policy answers "is
this worth doing now?".  Missing observations are never replaced with a
fabricated neutral value: only present components are reweighted.  This keeps
the module portable to host sites that expose only a subset of location,
inventory, congestion, and meeting overlays.
"""

from __future__ import annotations

import hashlib
import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.services.matching.types import MatchCandidate, ResolvedContext, ResolvedProfile

CONTEXT_POLICY_VERSION = "context-rerank-v1.0"
BASE_SCORE_WEIGHT = 0.85
CONTEXT_SCORE_WEIGHT = 0.15
DISTANCE_UNIT_TO_METERS = 5.0
WALK_SPEED_METERS_PER_MINUTE = 60.0
DEFAULT_VISIT_MINUTES = 10

CONTEXT_COMPONENT_WEIGHTS: dict[str, float] = {
    "proximity": 0.20,
    "time_feasibility": 0.20,
    "wait_congestion": 0.15,
    "operational_availability": 0.15,
    "meeting_availability": 0.10,
    "schedule_feasibility": 0.10,
    "inventory_urgency": 0.05,
    "recent_behavior": 0.05,
}

CONTEXT_POLICY_CONFIG: dict[str, Any] = {
    "base_score_weight": BASE_SCORE_WEIGHT,
    "context_score_weight": CONTEXT_SCORE_WEIGHT,
    "component_weights": CONTEXT_COMPONENT_WEIGHTS,
    "missing_value_strategy": "REWEIGHT_PRESENT_ONLY",
    "distance_unit_to_meters": DISTANCE_UNIT_TO_METERS,
    "walk_speed_meters_per_minute": WALK_SPEED_METERS_PER_MINUTE,
    "default_visit_minutes": DEFAULT_VISIT_MINUTES,
    "score_range": [0.0, 1.0],
}


@dataclass(frozen=True)
class ContextEvaluation:
    """One reproducible, policy-versioned context calculation."""

    policy_version: str
    components: dict[str, float | None]
    effective_weights: dict[str, float]
    contributions: dict[str, float]
    missing_components: tuple[str, ...]
    context_score: float | None
    final_score: float
    input_fingerprint: str
    score_fingerprint: str


def _clamp(value: float) -> float:
    return min(max(float(value), 0.0), 1.0)


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, set | frozenset | tuple):
        return sorted((_json_ready(item) for item in value), key=str)
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if hasattr(value, "as_tuple"):  # Decimal without coupling this module to it.
        return str(value)
    return value


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        _json_ready(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _candidate_coordinates(candidate: MatchCandidate) -> tuple[float, float] | None:
    x = candidate.payload.get("map_x")
    y = candidate.payload.get("map_y")
    if x is None or y is None:
        return None
    return float(x), float(y)


def _proximity(candidate: MatchCandidate) -> float | None:
    if candidate.distance_meters is None:
        return None
    # 300m is a gentle decay scale for an exhibition hall, not a hard cutoff.
    return _clamp(1.0 / (1.0 + candidate.distance_meters / 300.0))


def _time_feasibility(
    candidate: MatchCandidate, context: ResolvedContext
) -> float | None:
    if candidate.object_type == "PROGRAM":
        start_at = candidate.payload.get("start_at")
        end_at = candidate.payload.get("end_at")
        if end_at is not None and end_at <= context.server_time:
            return 0.0
        if start_at is None or context.remaining_minutes is None:
            return None
        minutes_until = (start_at - context.server_time).total_seconds() / 60.0
        if minutes_until < 0:
            return 0.6  # already running, but still actionable until end_at.
        return 1.0 if minutes_until <= context.remaining_minutes else 0.0

    if context.remaining_minutes is None:
        return None
    if context.current_zone is not None and candidate.estimated_walk_minutes is None:
        return None
    required = float(candidate.estimated_walk_minutes or 0)
    if candidate.object_type == "BOOTH":
        required += float(candidate.estimated_wait_minutes or 0)
        required += DEFAULT_VISIT_MINUTES
    elif candidate.object_type in ("PRODUCT", "EXHIBITOR"):
        required += DEFAULT_VISIT_MINUTES
    else:
        return None
    if required > context.remaining_minutes:
        return 0.0
    spare_ratio = (context.remaining_minutes - required) / max(
        context.remaining_minutes, 1
    )
    return _clamp(0.5 + 0.5 * spare_ratio)


def _wait_congestion(candidate: MatchCandidate, avoid_congestion: bool) -> float | None:
    if candidate.object_type != "BOOTH":
        return None
    values: list[float] = []
    if candidate.estimated_wait_minutes is not None:
        values.append(_clamp(1.0 - candidate.estimated_wait_minutes / 30.0))
    level = candidate.payload.get("congestion_level")
    if level in {"LOW", "MEDIUM", "HIGH"}:
        score = {"LOW": 1.0, "MEDIUM": 0.6, "HIGH": 0.2}[level]
        if avoid_congestion and level == "HIGH":
            score = 0.0
        values.append(score)
    return sum(values) / len(values) if values else None


def _operational_availability(candidate: MatchCandidate) -> float | None:
    payload = candidate.payload
    if candidate.object_type == "BOOTH":
        status = payload.get("operating_status")
        return {"OPEN": 1.0, "PAUSED": 0.2, "CLOSED": 0.0}.get(status)
    if candidate.object_type == "PRODUCT":
        if payload.get("inventory_status") == "SOLD_OUT":
            return 0.0
        purchase = payload.get("purchase_status")
        tasting = payload.get("tasting_status")
        if purchase in {"AVAILABLE", "LIMITED"} or tasting == "AVAILABLE":
            return 1.0
        if purchase is not None or tasting is not None:
            return 0.2
        return None
    if candidate.object_type == "EXHIBITOR":
        status = payload.get("participation_status")
        return {"APPROVED": 1.0, "CANCELLED": 0.0}.get(status)
    if candidate.object_type == "PROGRAM":
        status = payload.get("status")
        return {
            "PLANNED": 1.0,
            "OPEN": 1.0,
            "IN_PROGRESS": 0.8,
            "CANCELLED": 0.0,
            "CLOSED": 0.0,
            "ENDED": 0.0,
        }.get(status)
    return None


def _meeting_availability(
    candidate: MatchCandidate,
    profile: ResolvedProfile,
    context: ResolvedContext,
    meeting_open: bool | None,
) -> float | None:
    if profile.user_type != "BUYER" or candidate.participation_id is None:
        return None
    booth_id = candidate.payload.get("booth_id")
    if candidate.object_type == "BOOTH":
        booth_id = candidate.object_id
    if booth_id in context.upcoming_meeting_booth_ids:
        return 1.0
    if meeting_open is True:
        return 1.0
    if meeting_open is False and candidate.payload.get("consultation_enabled") is True:
        return 0.0  # enabled, but the current slot overlay verified no open slot.
    return None


def _schedule_feasibility(
    candidate: MatchCandidate, context: ResolvedContext
) -> float | None:
    if candidate.object_type == "PROGRAM":
        return _time_feasibility(candidate, context)
    if not context.upcoming_meetings:
        return None

    booth_id = candidate.payload.get("booth_id")
    if candidate.object_type == "BOOTH":
        booth_id = candidate.object_id
    if booth_id in context.upcoming_meeting_booth_ids:
        return 1.0

    next_meeting = context.upcoming_meetings[0]
    start_at = next_meeting.get("start_at")
    if start_at is None:
        return None
    minutes_until = (start_at - context.server_time).total_seconds() / 60.0
    if minutes_until <= 0:
        return 0.0

    coordinates = _candidate_coordinates(candidate)
    meeting_x = next_meeting.get("map_x")
    meeting_y = next_meeting.get("map_y")
    if (
        candidate.estimated_walk_minutes is None
        or coordinates is None
        or meeting_x is None
        or meeting_y is None
    ):
        return None
    required = float(candidate.estimated_walk_minutes)
    required += float(candidate.estimated_wait_minutes or 0)
    required += DEFAULT_VISIT_MINUTES
    distance_units = math.dist(coordinates, (float(meeting_x), float(meeting_y)))
    required += distance_units * DISTANCE_UNIT_TO_METERS / WALK_SPEED_METERS_PER_MINUTE
    return 1.0 if required <= minutes_until else 0.0


def _inventory_urgency(candidate: MatchCandidate) -> float | None:
    if candidate.object_type != "PRODUCT":
        return None
    return {"AVAILABLE": 0.4, "LOW": 1.0, "SOLD_OUT": 0.0}.get(
        candidate.payload.get("inventory_status")
    )


def _recent_behavior(
    candidate: MatchCandidate, context: ResolvedContext
) -> float | None:
    if (
        candidate.recommendable_id is not None
        and candidate.recommendable_id in context.recently_viewed_recommendable_ids
    ):
        return 0.0
    booth_id = candidate.payload.get("booth_id")
    if candidate.object_type == "BOOTH":
        booth_id = candidate.object_id
    if booth_id in context.visited_booth_ids:
        return 0.0
    return None


def evaluate_context(
    candidate: MatchCandidate,
    *,
    profile: ResolvedProfile,
    context: ResolvedContext,
    meeting_open: bool | None,
) -> ContextEvaluation:
    """Evaluate one candidate without mutating it or calling an AI provider."""

    components: dict[str, float | None] = {
        "proximity": _proximity(candidate),
        "time_feasibility": _time_feasibility(candidate, context),
        "wait_congestion": _wait_congestion(candidate, context.avoid_congestion),
        "operational_availability": _operational_availability(candidate),
        "meeting_availability": _meeting_availability(
            candidate, profile, context, meeting_open
        ),
        "schedule_feasibility": _schedule_feasibility(candidate, context),
        "inventory_urgency": _inventory_urgency(candidate),
        "recent_behavior": _recent_behavior(candidate, context),
    }
    present = {name: value for name, value in components.items() if value is not None}
    present_weight = sum(CONTEXT_COMPONENT_WEIGHTS[name] for name in present)
    effective_weights = (
        {name: CONTEXT_COMPONENT_WEIGHTS[name] / present_weight for name in present}
        if present_weight
        else {}
    )
    contributions = {
        name: float(value) * effective_weights[name] for name, value in present.items()
    }
    context_score = sum(contributions.values()) if contributions else None
    final_score = (
        candidate.normalized_score
        if context_score is None
        else candidate.normalized_score * BASE_SCORE_WEIGHT
        + context_score * CONTEXT_SCORE_WEIGHT
    )
    input_payload = {
        "policy": CONTEXT_POLICY_VERSION,
        "policy_config": CONTEXT_POLICY_CONFIG,
        "candidate": {
            "object_type": candidate.object_type,
            "object_id": candidate.object_id,
            "recommendable_id": candidate.recommendable_id,
            "participation_id": candidate.participation_id,
            "distance_meters": candidate.distance_meters,
            "estimated_walk_minutes": candidate.estimated_walk_minutes,
            "estimated_wait_minutes": candidate.estimated_wait_minutes,
            "operating_status": candidate.payload.get("operating_status"),
            "congestion_level": candidate.payload.get("congestion_level"),
            "inventory_status": candidate.payload.get("inventory_status"),
            "purchase_status": candidate.payload.get("purchase_status"),
            "tasting_status": candidate.payload.get("tasting_status"),
            "program_status": candidate.payload.get("status"),
            "start_at": candidate.payload.get("start_at"),
            "end_at": candidate.payload.get("end_at"),
            "status_observed_at": candidate.status_observed_at,
            "map_x": candidate.payload.get("map_x"),
            "map_y": candidate.payload.get("map_y"),
            "meeting_open": meeting_open,
        },
        "context": {
            "user_type": profile.user_type,
            "current_zone": context.current_zone,
            "current_zone_id": context.current_zone_id,
            "remaining_minutes": context.remaining_minutes,
            "operational_snapshot_version": context.operational_snapshot_version,
            "visited_booth_ids": context.visited_booth_ids,
            "recently_viewed_recommendable_ids": (
                context.recently_viewed_recommendable_ids
            ),
            "upcoming_meetings": context.upcoming_meetings,
            "avoid_congestion": context.avoid_congestion,
            "server_time": context.server_time,
        },
    }
    input_fingerprint = _fingerprint(input_payload)
    score_fingerprint = _fingerprint(
        {
            "input_fingerprint": input_fingerprint,
            "components": components,
            "effective_weights": effective_weights,
            "contributions": contributions,
            "context_score": context_score,
            "base_score": candidate.normalized_score,
            "final_score": final_score,
        }
    )
    return ContextEvaluation(
        policy_version=CONTEXT_POLICY_VERSION,
        components=components,
        effective_weights=effective_weights,
        contributions=contributions,
        missing_components=tuple(
            name for name, value in components.items() if value is None
        ),
        context_score=context_score,
        final_score=_clamp(final_score),
        input_fingerprint=input_fingerprint,
        score_fingerprint=score_fingerprint,
    )
