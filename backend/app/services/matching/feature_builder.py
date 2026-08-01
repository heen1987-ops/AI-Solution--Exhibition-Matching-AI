"""Stage 6 normalized feature construction for the published score policies.

The builder never converts an absent input into a neutral score.  ``None`` means
the component is unavailable and lets the scoring core remove its weight; numeric
zero is reserved for a verified mismatch.  Location, congestion, and novelty are
kept as stage-14 context features and never blended into the base relevance score
here.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import EventZone
from app.services.matching.ontology_support import (
    get_catalog,
    max_match_strength,
    relation_weight,
)
from app.services.matching.types import (
    GoalItem,
    MatchCandidate,
    ResolvedContext,
    ResolvedProfile,
    TaxonomyItem,
)

NOVELTY_WINDOW_DAYS = 30
DISTANCE_NORMALIZATION_UNITS = 120.0

_CONGESTION_SCORE = {
    "LOW": 1.0,
    "MEDIUM": 0.6,
    "HIGH": 0.2,
    "UNKNOWN": 0.5,
}
_AVAILABILITY_STATUS_SCORE = {
    "YES": 1.0,
    "CONDITIONAL": 0.7,
    "NEGOTIABLE": 0.55,
    "UNKNOWN": None,
    "NO": 0.0,
}
_PREFERENCE_LEVEL_WEIGHT = {
    "HIGHEST": 1.0,
    "HIGH": 1.0,
    "PREFERRED": 0.85,
    "MEDIUM": 0.75,
    "ACCEPTABLE": 0.65,
    "LOW": 0.4,
    "CONDITIONAL": 0.4,
}
_GOAL_SERVICE = {
    "GOAL.TASTING": "SERVICE.TASTING",
    "GOAL.ON_SITE_PURCHASE": "SERVICE.PURCHASE",
    "GOAL.CULTURE_EXPERIENCE": "SERVICE.EXPERIENCE",
}
_GOAL_TRADE_STATUS = {
    "BIZ_GOAL.OEM": "oem_status",
    "BIZ_GOAL.PRIVATE_LABEL": "private_label_status",
    "BIZ_GOAL.EXPORT": "export_status",
}


def _combine_weighted(
    values: Sequence[tuple[float | None, float]],
) -> float | None:
    present = [(value, weight) for value, weight in values if value is not None]
    if not present:
        return None
    weight_total = sum(weight for _, weight in present)
    return sum(float(value) * weight for value, weight in present) / weight_total


def _weighted_code_match(
    catalog: Any,
    profile_codes: set[str],
    candidate_weights: Mapping[str, float],
) -> float | None:
    if not profile_codes or not candidate_weights:
        return None
    best = 0.0
    for code, weight in candidate_weights.items():
        for profile_code in profile_codes:
            try:
                strength = float(catalog.match_strength(profile_code, code))
            except KeyError:
                continue
            best = max(best, strength * min(max(weight, 0.0), 1.0))
    return best


def _set_match(catalog: Any, left: set[str], right: set[str]) -> float | None:
    if not left or not right:
        return None
    return max_match_strength(catalog, left, right)


def _price_score(price: int | None, price_max: Any) -> float | None:
    if price is None or price_max is None:
        return None
    try:
        maximum = float(price_max)
    except (TypeError, ValueError):
        return None
    if maximum <= 0:
        return None
    if price <= maximum:
        return 1.0
    return max(0.0, 1.0 - (price - maximum) / maximum)


def _candidate_price(candidate: MatchCandidate) -> int | None:
    return candidate.payload.get("event_price_amount") or candidate.payload.get(
        "retail_price_amount"
    )


def _is_recent(candidate: MatchCandidate, context: ResolvedContext) -> bool:
    created_at = candidate.payload.get("created_at")
    if created_at is None:
        return False
    return (context.server_time - created_at) <= timedelta(days=NOVELTY_WINDOW_DAYS)


def _data_trust(candidate: MatchCandidate) -> float | None:
    direct = candidate.payload.get("data_trust_score")
    supply_profile = candidate.payload.get("supply_profile") or {}
    value = direct if direct is not None else supply_profile.get("data_trust_score")
    if value is None:
        return None
    return min(max(float(value), 0.0), 1.0)


def _candidate_service_codes(candidate: MatchCandidate) -> set[str]:
    payload = candidate.payload
    codes = set(payload.get("service_codes") or [])
    if payload.get("tasting_status") == "AVAILABLE":
        codes.add("SERVICE.TASTING")
    if payload.get("purchase_status") in ("AVAILABLE", "LIMITED"):
        codes.add("SERVICE.PURCHASE")
    if payload.get("consultation_enabled") is True:
        codes.add("SERVICE.CONSULTATION")
    return codes


def _goal_match(
    catalog: Any,
    goals: Sequence[GoalItem],
    candidate_codes: set[str],
    service_codes: set[str],
) -> float | None:
    if not goals:
        return None
    if not candidate_codes and not service_codes:
        return None

    ordered = sorted(goals, key=lambda item: item.priority or 99)[:3]
    priority_weights = {
        1: (1.0,),
        2: (0.65, 0.35),
        3: (0.55, 0.30, 0.15),
    }[len(ordered)]
    scores: list[float] = []
    for goal in ordered:
        related = relation_weight(
            catalog,
            candidate_codes,
            "MATCHES_GOAL",
            {goal.code},
        )
        service_score = 1.0 if _GOAL_SERVICE.get(goal.code) in service_codes else 0.0
        scores.append(max(related, service_score))
    return sum(score * weight for score, weight in zip(scores, priority_weights))


def _service_match(
    catalog: Any,
    requested: Sequence[TaxonomyItem],
    candidate_codes: set[str],
) -> float | None:
    requested_codes = {item.code for item in requested}
    if not requested_codes:
        return None
    if not candidate_codes:
        return 0.0
    return max_match_strength(catalog, requested_codes, candidate_codes)


def _general_visitor_features(
    candidate: MatchCandidate,
    profile: ResolvedProfile,
    context: ResolvedContext,
    catalog: Any,
) -> dict[str, float | None]:
    payload = candidate.payload
    category_codes: dict[str, float] = {}
    if payload.get("category_code"):
        category_codes[payload["category_code"]] = 1.0
    for code in payload.get("business_types") or []:
        category_codes.setdefault(code, 1.0)

    taste_codes = {
        code: float(value) / 5.0
        for code, value in (payload.get("taste_json") or {}).items()
        if value is not None
    }
    aroma_codes = {
        code: float(value) / 5.0
        for code, value in (payload.get("aroma_json") or {}).items()
        if value is not None
    }
    taste_match = _weighted_code_match(
        catalog,
        profile.all_codes(profile.taste),
        taste_codes,
    )
    aroma_match = _weighted_code_match(
        catalog,
        profile.all_codes(profile.aroma),
        aroma_codes,
    )
    sensory_match = _combine_weighted(((taste_match, 0.70), (aroma_match, 0.30)))

    alcohol_match: float | None = None
    alcohol_preferences = profile.extra.get("alcohol_level", [])
    alcohol_percentage = payload.get("alcohol_percentage")
    if alcohol_preferences and alcohol_percentage is not None:
        try:
            band_code = catalog.derive_band("alcohol_percentage", alcohol_percentage)
            alcohol_match = max_match_strength(
                catalog,
                {item.code for item in alcohol_preferences},
                {band_code},
            )
        except (KeyError, ValueError):
            alcohol_match = None

    service_codes = _candidate_service_codes(candidate)
    usage_codes = set(payload.get("usage_json") or [])
    feature_codes = set(payload.get("feature_json") or [])
    candidate_goal_codes = usage_codes | feature_codes
    goal_match = _goal_match(
        catalog,
        profile.goals,
        candidate_goal_codes,
        service_codes,
    )
    usage_match = _set_match(
        catalog,
        profile.all_codes(profile.extra.get("use_case", [])),
        usage_codes,
    )
    feature_match = _set_match(
        catalog,
        profile.all_codes(profile.extra.get("product_feature", [])),
        feature_codes,
    )
    usage_feature_match = _combine_weighted(
        ((usage_match, 0.60), (feature_match, 0.40))
    )

    distance_score: float | None = None
    if candidate.object_type == "BOOTH" and "_distance_units" in payload:
        distance_score = 1.0 / (
            1.0 + payload["_distance_units"] / DISTANCE_NORMALIZATION_UNITS
        )
    congestion_score = (
        _CONGESTION_SCORE.get(payload.get("congestion_level"))
        if candidate.object_type == "BOOTH"
        else None
    )
    novelty_score = (
        1.0
        if "EXPLORATION" in candidate.source_channels
        else (0.7 if _is_recent(candidate, context) else 0.3)
    )

    return {
        "goal_match": goal_match,
        "category_match": _weighted_code_match(
            catalog,
            profile.all_codes(profile.categories),
            category_codes,
        ),
        "sensory_match": sensory_match,
        "taste_match": taste_match,
        "aroma_match": aroma_match,
        "alcohol_match": alcohol_match,
        "price_match": _price_score(
            _candidate_price(candidate),
            profile.numeric_conditions.get("retail_price_max"),
        ),
        "service_match": _service_match(
            catalog,
            profile.extra.get("booth_service", []),
            service_codes,
        ),
        "usage_feature_match": usage_feature_match,
        "distance_score": distance_score,
        "congestion_score": congestion_score,
        "novelty_score": novelty_score,
        "data_trust": _data_trust(candidate),
    }


def _goal_status_matches(
    goals: Sequence[GoalItem], trade_profile: Mapping[str, Any]
) -> list[tuple[float, int]]:
    matches: list[tuple[float, int]] = []
    for goal in goals:
        status_key = _GOAL_TRADE_STATUS.get(goal.code)
        if status_key is None:
            continue
        score = _AVAILABILITY_STATUS_SCORE.get(trade_profile.get(status_key))
        if score is not None:
            matches.append((score, goal.priority or 99))
    return matches


def _priority_goal_score(matches: Sequence[tuple[float, int]]) -> float | None:
    if not matches:
        return None
    ordered = sorted(matches, key=lambda item: item[1])[:3]
    weights = {
        1: (1.0,),
        2: (0.70, 0.30),
        3: (0.60, 0.30, 0.10),
    }[len(ordered)]
    return sum(value * weight for (value, _), weight in zip(ordered, weights))


def _preference_items(raw: Any, key: str) -> dict[str, float]:
    if not isinstance(raw, Mapping):
        return {}
    items = raw.get(key) or []
    result: dict[str, float] = {}
    if not isinstance(items, Iterable) or isinstance(items, (str, bytes, Mapping)):
        return result
    for item in items:
        if isinstance(item, str):
            result[item] = 1.0
            continue
        if not isinstance(item, Mapping) or not item.get("code"):
            continue
        level = str(
            item.get("preference_level") or item.get("level") or "PREFERRED"
        ).upper()
        result[str(item["code"])] = _PREFERENCE_LEVEL_WEIGHT.get(level, 0.65)
    return result


def _preferred_order_volume(raw: Any, profile: ResolvedProfile) -> float | None:
    if not isinstance(raw, Mapping):
        return None
    order = raw.get("order_volume")
    if not isinstance(order, Mapping):
        return None
    buyer_units = profile.numeric_conditions.get("monthly_units_max") or (
        profile.numeric_conditions.get("monthly_units_min")
    )
    if buyer_units is None:
        return None
    preferred_min = order.get("preferred_min")
    preferred_max = order.get("preferred_max")
    if preferred_min is not None and buyer_units < preferred_min:
        return max(0.0, float(buyer_units) / float(preferred_min))
    if preferred_max is not None and buyer_units > preferred_max:
        return 0.9
    return 1.0


def _decision_timing_match(raw: Any, profile: ResolvedProfile) -> float | None:
    if not isinstance(raw, Mapping):
        return None
    buyer_timing = profile.raw_context.get("decision_timeline")
    preferred = raw.get("preferred_decision_timelines") or raw.get("decision_timelines")
    if buyer_timing is None or not isinstance(preferred, Sequence) or not preferred:
        return None
    preferred_codes = {
        item.get("code") if isinstance(item, Mapping) else item for item in preferred
    }
    preferred_codes.discard(None)
    if buyer_timing in preferred_codes:
        return 1.0

    order = {
        "IMMEDIATE": 0,
        "SHORT_TERM": 1,
        "MID_TERM": 2,
        "LONG_TERM": 3,
        "RESEARCH_ONLY": 4,
    }
    buyer_index = order.get(str(buyer_timing))
    candidate_indexes = [order[code] for code in preferred_codes if code in order]
    if buyer_index is None or not candidate_indexes:
        return None
    difference = min(abs(buyer_index - index) for index in candidate_indexes)
    if difference == 1:
        return 0.8
    if difference == 2:
        return 0.5
    return 0.3


def _buyer_features(
    candidate: MatchCandidate,
    profile: ResolvedProfile,
    catalog: Any,
) -> dict[str, float | None]:
    payload = candidate.payload
    supply_profile = payload.get("supply_profile") or {}
    trade_profile = supply_profile.get("trade_profile") or {}
    preference_profile = supply_profile.get("preferred_buyers") or {}

    category_codes: dict[str, float] = {}
    if payload.get("category_code"):
        category_codes[payload["category_code"]] = 1.0
    for code in (
        supply_profile.get("business_types") or payload.get("business_types") or []
    ):
        category_codes.setdefault(code, 1.0)
    product_match = _weighted_code_match(
        catalog,
        profile.all_codes(profile.categories),
        category_codes,
    )

    channel_match = _set_match(
        catalog,
        profile.all_codes(profile.channels),
        set(trade_profile.get("channels") or []),
    )
    region_match = _set_match(
        catalog,
        profile.all_codes(profile.regions),
        set(trade_profile.get("regions") or []),
    )

    buyer_units = profile.numeric_conditions.get("monthly_units_max") or (
        profile.numeric_conditions.get("monthly_units_min")
    )
    exhibitor_min = trade_profile.get("min_order_quantity")
    moq_match: float | None = None
    if buyer_units is not None and exhibitor_min is not None:
        moq_match = (
            1.0
            if exhibitor_min <= buyer_units
            else max(0.0, float(buyer_units) / float(exhibitor_min))
        )

    available = trade_profile.get("monthly_available_capacity")
    capacity_match: float | None = None
    if buyer_units is not None and available is not None and buyer_units > 0:
        ratio = float(available) / float(buyer_units)
        if ratio >= 1.5:
            capacity_match = 1.0
        elif ratio >= 1.0:
            capacity_match = 0.9
        elif ratio >= 0.8:
            capacity_match = 0.6
        elif ratio >= 0.5:
            capacity_match = 0.3
        else:
            capacity_match = 0.0

    price_target = profile.numeric_conditions.get("wholesale_price_max") or (
        profile.numeric_conditions.get("retail_price_max")
    )
    goal_matches = _goal_status_matches(profile.goals, trade_profile)
    business_goal_match = _priority_goal_score(goal_matches)

    trade_readiness = supply_profile.get("trade_readiness_score")
    if trade_readiness is not None:
        trade_readiness = min(max(float(trade_readiness) / 100.0, 0.0), 1.0)
    trade_trust = _combine_weighted(
        ((trade_readiness, 0.60), (_data_trust(candidate), 0.40))
    )

    meeting_match = (
        1.0
        if payload.get("consultation_enabled") is True
        else (0.0 if payload.get("consultation_enabled") is False else None)
    )
    acceptance_capacity = _combine_weighted(
        ((capacity_match, 0.70), (meeting_match, 0.30))
    )

    preferred_buyer_types = _preference_items(
        preference_profile, "preferred_buyer_types"
    )
    preferred_channels = _preference_items(preference_profile, "preferred_channels")
    preferred_regions = _preference_items(preference_profile, "preferred_regions")
    preferred_trade_types = _preference_items(preference_profile, "trade_types")

    buyer_type_match = _weighted_code_match(
        catalog,
        profile.all_codes(profile.extra.get("buyer_type", [])),
        preferred_buyer_types,
    )
    preferred_channel_match = _weighted_code_match(
        catalog,
        profile.all_codes(profile.channels),
        preferred_channels,
    )
    preferred_region_match = _weighted_code_match(
        catalog,
        profile.all_codes(profile.regions),
        preferred_regions,
    )
    trade_type_match = _weighted_code_match(
        catalog,
        profile.all_codes(profile.extra.get("trade_type", [])),
        preferred_trade_types,
    )

    raw_context = profile.raw_context
    buyer_verification = raw_context.get("buyer_verification")
    meeting_readiness = raw_context.get("meeting_readiness")
    decision_timing_match = _decision_timing_match(preference_profile, profile)

    return {
        # Stage 12: buyer -> exhibitor.
        "business_goal_match": business_goal_match,
        "product_match": product_match,
        "channel_match": channel_match,
        "price_match": _price_score(_candidate_price(candidate), price_target),
        "moq_match": moq_match,
        "capacity_match": capacity_match,
        "region_match": region_match,
        "cooperation_match": business_goal_match,
        "meeting_match": meeting_match,
        "trade_trust": trade_trust,
        # Stage 13: exhibitor -> buyer.
        "buyer_type_match": buyer_type_match,
        "preferred_channel_match": preferred_channel_match,
        "order_volume_match": _preferred_order_volume(preference_profile, profile),
        "preferred_region_match": preferred_region_match,
        "trade_type_match": trade_type_match,
        "portfolio_match": product_match,
        "decision_timing_match": decision_timing_match,
        "buyer_verification": buyer_verification,
        "meeting_readiness": meeting_readiness,
        "exhibitor_preference_available": (1.0 if bool(preference_profile) else 0.0),
        "acceptance_capacity": acceptance_capacity,
    }


async def build_features(
    db: AsyncSession,
    candidates: list[MatchCandidate],
    *,
    profile: ResolvedProfile,
    context: ResolvedContext,
) -> None:
    """Populate normalized, missing-aware features on each candidate."""

    catalog = get_catalog()
    current_zone_xy: tuple[float, float] | None = None
    if context.current_zone_id is not None:
        row = (
            await db.execute(
                select(EventZone.coordinate_x, EventZone.coordinate_y).where(
                    EventZone.event_zone_id == context.current_zone_id
                )
            )
        ).first()
        if row is not None and row[0] is not None and row[1] is not None:
            current_zone_xy = (float(row[0]), float(row[1]))

    for candidate in candidates:
        if current_zone_xy is not None and candidate.object_type == "BOOTH":
            map_x = candidate.payload.get("map_x")
            map_y = candidate.payload.get("map_y")
            if map_x is not None and map_y is not None:
                dx = float(map_x) - current_zone_xy[0]
                dy = float(map_y) - current_zone_xy[1]
                candidate.payload["_distance_units"] = math.hypot(dx, dy)

        if profile.user_type == "BUYER":
            candidate.features = _buyer_features(candidate, profile, catalog)
        else:
            candidate.features = _general_visitor_features(
                candidate,
                profile,
                context,
                catalog,
            )
