"""Pure stage-15 slate construction policy.

Relevance remains a stage-11~14 concern.  This module only composes candidates
that already passed the hard filter and relevance floor.  Sponsor metadata and
company size are deliberately absent from every score input.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from app.services.matching.types import MatchCandidate, ResolvedProfile

SLATE_POLICY_VERSION = "slate-policy-v1.0"
RELEVANCE_FLOOR = 0.45
CONDITIONAL_FLOOR = 0.55
CORE_FLOOR = 0.70
GENERAL_MMR_LAMBDA = 0.80
BUYER_MMR_LAMBDA = 0.85
EXPLORATION_MMR_LAMBDA = 0.65
NEW_MMR_LAMBDA = 0.70
MAX_FAIRNESS_ADJUSTMENT = 0.05
MAX_DIVERSITY_ADJUSTMENT = 0.05
MAX_EXPLORATION_ADJUSTMENT = 0.04
MAX_REPEAT_PENALTY = 0.10
MAX_CONCENTRATION_PENALTY = 0.05
EXPOSURE_SHARE_WARNING = 0.15
NEW_WINDOW_DAYS = 30

SLATE_POLICY_CONFIG: dict[str, Any] = {
    "relevance_floors": {
        "core": CORE_FLOOR,
        "conditional": CONDITIONAL_FLOOR,
        "exploration": RELEVANCE_FLOOR,
    },
    "mmr_lambda": {
        "general": GENERAL_MMR_LAMBDA,
        "buyer": BUYER_MMR_LAMBDA,
        "exploration": EXPLORATION_MMR_LAMBDA,
        "new": NEW_MMR_LAMBDA,
    },
    "exhibitor_caps": {
        "general_top5": 1,
        "general_top10": 2,
        "general_top20": 3,
        "buyer": 1,
    },
    "category_caps": {"top5": 3, "top10": 5},
    "region_cap_top10": 4,
    "max_exploration_top10": 1,
    "repeat_penalty": {"two": 0.03, "three": 0.07, "five_exclude": True},
    "repeat_scope": {
        "booth": "VISIT_SESSION",
        "product": "P1D",
        "program": "EVENT_LIFETIME",
        "exhibitor": "EVENT_LIFETIME",
    },
    "user_preferences": {
        "balanced": "DEFAULT",
        "accuracy_first": "MMR_LAMBDA_PLUS_0.10",
        "diverse": "MMR_LAMBDA_MINUS_0.15",
        "nearby_first": {"relevance": 0.80, "proximity": 0.20},
        "new_discovery": "NEW_MMR_LAMBDA",
    },
    "adjustment_limits": {
        "diversity": [-MAX_DIVERSITY_ADJUSTMENT, MAX_DIVERSITY_ADJUSTMENT],
        "fairness": [-MAX_FAIRNESS_ADJUSTMENT, MAX_FAIRNESS_ADJUSTMENT],
        "exploration": [0.0, MAX_EXPLORATION_ADJUSTMENT],
        "repeat": [0.0, MAX_REPEAT_PENALTY],
        "concentration": [0.0, MAX_CONCENTRATION_PENALTY],
    },
    "relevance_loss_limits": {"top5": 0.03, "top10": 0.05},
    "sponsored_content_separated": True,
    "company_size_scoring": False,
    "missing_value_strategy": "DO_NOT_INFER",
}


@dataclass(frozen=True)
class ExposureOverlay:
    """Observed exposure facts resolved outside the pure policy."""

    user_impressions: dict[uuid.UUID, int] = field(default_factory=dict)
    user_positive_actions: dict[uuid.UUID, int] = field(default_factory=dict)
    event_exhibitor_impressions: dict[uuid.UUID, int] = field(default_factory=dict)
    event_total_impressions: int = 0


@dataclass(frozen=True)
class SlateBuildResult:
    items: list[MatchCandidate]
    policy_version: str
    input_fingerprint: str
    score_fingerprint: str
    metrics: dict[str, Any]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return min(max(float(value), low), high)


def _json_ready(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, set | frozenset | tuple):
        return sorted((_json_ready(item) for item in value), key=str)
    if isinstance(value, list):
        return [_json_ready(item) for item in value]
    if hasattr(value, "as_tuple"):
        return str(value)
    return value


def _fingerprint(value: Any) -> str:
    payload = json.dumps(
        _json_ready(value), ensure_ascii=False, separators=(",", ":"), sort_keys=True
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _base_score(candidate: MatchCandidate) -> float:
    value = (
        candidate.context_blended_score
        if candidate.context_blended_score is not None
        else candidate.final_score
    )
    return _clamp(value)


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
    # The supplied canonical code is the display-level product kind.  Walking
    # to the final ancestor would collapse every alcohol category into the same
    # PRODUCT.ALL root and silently disable the category cap.
    return str(code)


def _regions(candidate: MatchCandidate) -> set[str]:
    payload = candidate.payload
    regions = set(payload.get("region_codes") or [])
    supply_profile = payload.get("supply_profile") or {}
    trade_profile = supply_profile.get("trade_profile") or {}
    regions.update(trade_profile.get("regions") or [])
    return regions


def _price_band(candidate: MatchCandidate) -> str | None:
    value = candidate.payload.get("event_price_amount")
    if value is None:
        value = candidate.payload.get("retail_price_amount")
    if value is None:
        return None
    price = float(value)
    if price <= 20_000:
        return "PRICE.UNDER_20K"
    if price <= 50_000:
        return "PRICE.20K_50K"
    if price <= 100_000:
        return "PRICE.50K_100K"
    return "PRICE.OVER_100K"


def _taste_codes(candidate: MatchCandidate) -> set[str]:
    return set((candidate.payload.get("taste_json") or {}).keys())


def _jaccard(left: set[str], right: set[str]) -> float:
    if not left and not right:
        return 0.0
    return len(left & right) / len(left | right)


def candidate_similarity(left: MatchCandidate, right: MatchCandidate) -> float:
    """Weighted observable similarity used by MMR and ILD."""

    score = 0.0
    if left.exhibitor_id is not None and left.exhibitor_id == right.exhibitor_id:
        score += 0.35
    left_category = _top_level_category(left)
    right_category = _top_level_category(right)
    if left_category is not None and left_category == right_category:
        score += 0.25
    left_regions = _regions(left)
    right_regions = _regions(right)
    score += 0.10 * _jaccard(left_regions, right_regions)
    left_price = _price_band(left)
    if left_price is not None and left_price == _price_band(right):
        score += 0.10
    score += 0.10 * _jaccard(_taste_codes(left), _taste_codes(right))
    if left.object_type == right.object_type:
        score += 0.10
    return _clamp(score)


def _is_personalized(candidate: MatchCandidate) -> bool:
    content_type = candidate.payload.get("content_type", "PERSONALIZED_RECOMMENDATION")
    return (
        content_type == "PERSONALIZED_RECOMMENDATION"
        and candidate.payload.get("is_sponsored") is not True
    )


def _is_exploration(candidate: MatchCandidate, *, server_time: datetime) -> bool:
    if "EXPLORATION" in candidate.source_channels:
        return True
    created_at = candidate.payload.get("created_at")
    age = server_time - created_at if created_at is not None else None
    return bool(
        age is not None and timedelta(0) <= age <= timedelta(days=NEW_WINDOW_DAYS)
    )


def _repeat_penalty(candidate: MatchCandidate, overlay: ExposureOverlay) -> float:
    if candidate.recommendable_id is None:
        return 0.0
    if overlay.user_positive_actions.get(candidate.recommendable_id, 0) > 0:
        return 0.0
    count = overlay.user_impressions.get(candidate.recommendable_id, 0)
    if count >= 5:
        return MAX_REPEAT_PENALTY
    if count >= 3:
        return 0.07
    if count >= 2:
        return 0.03
    return 0.0


def _eligible_exhibitor_shares(
    candidates: list[MatchCandidate],
) -> dict[uuid.UUID, float]:
    counts = Counter(
        candidate.exhibitor_id
        for candidate in candidates
        if candidate.exhibitor_id is not None
    )
    total = sum(counts.values())
    return {key: value / total for key, value in counts.items()} if total else {}


def _actual_exhibitor_share(
    exhibitor_id: uuid.UUID | None, overlay: ExposureOverlay
) -> float:
    if exhibitor_id is None or overlay.event_total_impressions <= 0:
        return 0.0
    return (
        overlay.event_exhibitor_impressions.get(exhibitor_id, 0)
        / overlay.event_total_impressions
    )


def _fairness_adjustment(
    candidate: MatchCandidate,
    *,
    eligible_shares: dict[uuid.UUID, float],
    overlay: ExposureOverlay,
) -> float:
    if candidate.exhibitor_id is None or overlay.event_total_impressions <= 0:
        return 0.0
    deficit = eligible_shares.get(candidate.exhibitor_id, 0.0) - (
        _actual_exhibitor_share(candidate.exhibitor_id, overlay)
    )
    return _clamp(deficit, -MAX_FAIRNESS_ADJUSTMENT, MAX_FAIRNESS_ADJUSTMENT)


def _concentration_penalty(
    candidate: MatchCandidate, overlay: ExposureOverlay
) -> float:
    share = _actual_exhibitor_share(candidate.exhibitor_id, overlay)
    if share <= EXPOSURE_SHARE_WARNING:
        return 0.0
    scaled = (share - EXPOSURE_SHARE_WARNING) / (1.0 - EXPOSURE_SHARE_WARNING)
    return _clamp(scaled * MAX_CONCENTRATION_PENALTY, 0.0, MAX_CONCENTRATION_PENALTY)


def _lambda_for(
    profile: ResolvedProfile, slot_type: str, user_preference: str
) -> float:
    if slot_type == "EXPLORATION":
        value = EXPLORATION_MMR_LAMBDA
    else:
        value = BUYER_MMR_LAMBDA if profile.user_type == "BUYER" else GENERAL_MMR_LAMBDA
    if user_preference == "ACCURACY_FIRST":
        value += 0.10
    elif user_preference == "DIVERSE":
        value -= 0.15
    elif user_preference == "NEW_DISCOVERY" and slot_type == "EXPLORATION":
        value = NEW_MMR_LAMBDA
    return _clamp(value, 0.55, 0.95)


def _exploration_score(candidate: MatchCandidate) -> float:
    trust = candidate.score_components.get("trust_score")
    novelty = candidate.features.get("novelty_score")
    deficit = max(candidate.fairness_adjustment, 0.0) / MAX_FAIRNESS_ADJUSTMENT
    return _clamp(
        0.55 * _base_score(candidate)
        + 0.20 * (float(trust) if trust is not None else 0.0)
        + 0.15 * (float(novelty) if novelty is not None else 0.0)
        + 0.10 * deficit
    )


def _preference_utility(
    candidate: MatchCandidate, utility: float, user_preference: str
) -> float:
    if user_preference != "NEARBY_FIRST" or candidate.distance_meters is None:
        return utility
    proximity = 1.0 - _clamp(candidate.distance_meters / 1_000.0)
    return 0.80 * utility + 0.20 * proximity


def _slot_plan(limit: int, exploration_ratio: float | None = None) -> list[str]:
    if exploration_ratio is not None:
        exploration = min(3, max(0, round(limit * _clamp(exploration_ratio))))
        if limit >= 5 and exploration_ratio > 0:
            exploration = max(1, exploration)
        conditional = 1 if limit >= 4 else 0
        diversity = 1 if limit >= 6 else 0
        core = max(0, limit - exploration - conditional - diversity)
        return (
            ["CORE"] * core
            + ["CONDITIONAL"] * conditional
            + ["DIVERSITY"] * diversity
            + ["EXPLORATION"] * exploration
        )
    if limit >= 10:
        return (
            ["CORE"] * 6
            + ["CONDITIONAL"] * 2
            + ["DIVERSITY", "EXPLORATION"]
            + ["CORE"] * (limit - 10)
        )
    if limit <= 2:
        return ["CORE"] * limit
    exploration = 1 if limit >= 5 else 0
    conditional = 1 if limit >= 4 else 0
    diversity = 1 if limit >= 6 else 0
    core = limit - exploration - conditional - diversity
    return (
        ["CORE"] * core
        + ["CONDITIONAL"] * conditional
        + ["DIVERSITY"] * diversity
        + ["EXPLORATION"] * exploration
    )


def _passes_slot(
    candidate: MatchCandidate, slot_type: str, *, server_time: datetime
) -> bool:
    score = _base_score(candidate)
    if slot_type == "CORE":
        return score >= CORE_FLOOR
    if slot_type == "CONDITIONAL":
        return score >= CONDITIONAL_FLOOR
    if slot_type == "EXPLORATION":
        trust = candidate.score_components.get("trust_score")
        return (
            score >= RELEVANCE_FLOOR
            and _is_exploration(candidate, server_time=server_time)
            and (trust is None or trust >= 0.4)
        )
    return score >= RELEVANCE_FLOOR


def _can_take(
    candidate: MatchCandidate,
    *,
    selected: list[MatchCandidate],
    profile: ResolvedProfile,
    required_categories: set[str],
    required_regions: set[str],
    relax_soft_caps: bool,
) -> bool:
    position = len(selected) + 1
    if (
        position <= 10
        and "COLD_START_QUALITY" in candidate.source_channels
        and any("COLD_START_QUALITY" in item.source_channels for item in selected)
    ):
        return False
    if candidate.exhibitor_id is not None:
        exhibitor_count = sum(
            item.exhibitor_id == candidate.exhibitor_id for item in selected
        )
        if profile.user_type == "BUYER" and exhibitor_count >= 1:
            return False
        exhibitor_cap = 1 if position <= 5 else (2 if position <= 10 else 3)
        if exhibitor_count >= exhibitor_cap:
            return False

    if not relax_soft_caps:
        category = _top_level_category(candidate)
        if category is not None and category not in required_categories:
            category_count = sum(
                _top_level_category(item) == category for item in selected
            )
            category_cap = 3 if position <= 5 else 5
            if position <= 10 and category_count >= category_cap:
                return False

    if not relax_soft_caps and position <= 10:
        regions = _regions(candidate)
        for region in regions:
            if region in required_regions:
                continue
            if sum(region in _regions(item) for item in selected) >= 4:
                return False
    return True


def _maximum_similarity(
    candidate: MatchCandidate, selected: list[MatchCandidate]
) -> float:
    if not selected:
        return 0.0
    return max(candidate_similarity(candidate, item) for item in selected)


def _gini(values: list[int]) -> float:
    values = sorted(value for value in values if value >= 0)
    if not values or sum(values) == 0:
        return 0.0
    count = len(values)
    weighted = sum((index + 1) * value for index, value in enumerate(values))
    return _clamp((2 * weighted) / (count * sum(values)) - (count + 1) / count)


def _hhi(values: list[int]) -> float:
    total = sum(values)
    if total <= 0:
        return 0.0
    return sum((value / total) ** 2 for value in values)


def _intra_list_diversity(items: list[MatchCandidate]) -> float:
    if len(items) < 2:
        return 0.0
    distances = [
        1.0 - candidate_similarity(left, right)
        for index, left in enumerate(items)
        for right in items[index + 1 :]
    ]
    return sum(distances) / len(distances)


def _relevance_loss(
    baseline: list[MatchCandidate], selected: list[MatchCandidate], k: int
) -> float:
    size = min(k, len(baseline), len(selected))
    if size == 0:
        return 0.0
    baseline_mean = sum(_base_score(item) for item in baseline[:size]) / size
    selected_mean = sum(_base_score(item) for item in selected[:size]) / size
    return max(0.0, baseline_mean - selected_mean)


def build_slate(
    candidates: list[MatchCandidate],
    *,
    limit: int,
    profile: ResolvedProfile,
    server_time: datetime,
    exposure: ExposureOverlay | None = None,
    user_preference: str = "BALANCED",
    exploration_ratio: float | None = None,
) -> SlateBuildResult:
    """Construct and mutate a deterministic final slate."""

    overlay = exposure or ExposureOverlay()
    baseline = sorted(
        candidates, key=lambda item: (-_base_score(item), str(item.object_id))
    )
    for index, candidate in enumerate(baseline, start=1):
        candidate.slate_base_rank = index

    eligible = [
        candidate
        for candidate in baseline
        if _base_score(candidate) >= RELEVANCE_FLOOR
        and _is_personalized(candidate)
        and not (
            candidate.recommendable_id is not None
            and overlay.user_impressions.get(candidate.recommendable_id, 0) >= 5
            and overlay.user_positive_actions.get(candidate.recommendable_id, 0) == 0
        )
    ]
    eligible_shares = _eligible_exhibitor_shares(eligible)
    required_categories = profile.required_codes(profile.categories)
    required_regions = profile.required_codes(profile.regions)

    for candidate in eligible:
        candidate.fairness_adjustment = _fairness_adjustment(
            candidate, eligible_shares=eligible_shares, overlay=overlay
        )
        candidate.repeat_penalty = _repeat_penalty(candidate, overlay)
        candidate.concentration_penalty = _concentration_penalty(candidate, overlay)

    input_payload = {
        "policy_version": SLATE_POLICY_VERSION,
        "policy_config": SLATE_POLICY_CONFIG,
        "user_type": profile.user_type,
        "user_preference": user_preference,
        "exploration_ratio": exploration_ratio,
        "required_categories": required_categories,
        "required_regions": required_regions,
        "limit": limit,
        "server_time": server_time,
        "exposure": {
            "user_impressions": overlay.user_impressions,
            "user_positive_actions": overlay.user_positive_actions,
            "event_exhibitor_impressions": overlay.event_exhibitor_impressions,
            "event_total_impressions": overlay.event_total_impressions,
        },
        "candidates": [
            {
                "object_type": item.object_type,
                "object_id": item.object_id,
                "recommendable_id": item.recommendable_id,
                "exhibitor_id": item.exhibitor_id,
                "base_score": _base_score(item),
                "category": _top_level_category(item),
                "regions": _regions(item),
                "price_band": _price_band(item),
                "taste_codes": _taste_codes(item),
                "source_channels": item.source_channels,
                "trust_score": item.score_components.get("trust_score"),
                "novelty_score": item.features.get("novelty_score"),
                "distance_meters": item.distance_meters,
                "created_at": item.payload.get("created_at"),
                "content_type": item.payload.get(
                    "content_type", "PERSONALIZED_RECOMMENDATION"
                ),
                "is_sponsored": item.payload.get("is_sponsored", False),
            }
            for item in baseline
        ],
    }
    input_fingerprint = _fingerprint(input_payload)

    selected: list[MatchCandidate] = []
    slot_types: list[str] = []
    mmr_values: list[float] = []
    slot_plan = _slot_plan(min(limit, len(eligible)), exploration_ratio)
    max_exploration = slot_plan.count("EXPLORATION")
    for slot_index, requested_slot in enumerate(slot_plan):
        selected_ids = {id(candidate) for candidate in selected}
        available = [
            candidate for candidate in eligible if id(candidate) not in selected_ids
        ]
        slot_pool = [
            candidate
            for candidate in available
            if _passes_slot(candidate, requested_slot, server_time=server_time)
            and _can_take(
                candidate,
                selected=selected,
                profile=profile,
                required_categories=required_categories,
                required_regions=required_regions,
                relax_soft_caps=False,
            )
        ]
        actual_slot = requested_slot
        used_slot_fallback = False
        if not slot_pool:
            slot_pool = [
                candidate
                for candidate in available
                if _passes_slot(candidate, requested_slot, server_time=server_time)
                and _can_take(
                    candidate,
                    selected=selected,
                    profile=profile,
                    required_categories=required_categories,
                    required_regions=required_regions,
                    relax_soft_caps=True,
                )
            ]
        if not slot_pool:
            actual_slot = "DIVERSITY"
            used_slot_fallback = True
            slot_pool = [
                candidate
                for candidate in available
                if _base_score(candidate) >= RELEVANCE_FLOOR
                and _can_take(
                    candidate,
                    selected=selected,
                    profile=profile,
                    required_categories=required_categories,
                    required_regions=required_regions,
                    relax_soft_caps=False,
                )
            ]
        if not slot_pool:
            slot_pool = [
                candidate
                for candidate in available
                if _can_take(
                    candidate,
                    selected=selected,
                    profile=profile,
                    required_categories=required_categories,
                    required_regions=required_regions,
                    relax_soft_caps=True,
                )
            ]
        exploration_is_reserved = (
            requested_slot != "EXPLORATION"
            and "EXPLORATION" in slot_plan[slot_index + 1 :]
        )
        if exploration_is_reserved:
            regular_pool = [
                candidate
                for candidate in slot_pool
                if not _is_exploration(candidate, server_time=server_time)
            ]
            slot_pool = regular_pool
        if max_exploration > 0 and len(selected) < 10 and sum(
            _is_exploration(candidate, server_time=server_time)
            for candidate in selected
        ) >= max_exploration:
            slot_pool = [
                candidate
                for candidate in slot_pool
                if not _is_exploration(candidate, server_time=server_time)
            ]
        if not slot_pool:
            if exploration_is_reserved:
                continue
            break

        mmr_lambda = _lambda_for(profile, actual_slot, user_preference)

        def mmr_value(
            candidate: MatchCandidate,
            *,
            weight: float = mmr_lambda,
            slot: str = actual_slot,
        ) -> float:
            if slot == "EXPLORATION":
                provisional = _exploration_score(candidate)
            else:
                provisional = _base_score(candidate) + candidate.fairness_adjustment
            provisional = _preference_utility(candidate, provisional, user_preference)
            provisional -= candidate.repeat_penalty
            provisional -= candidate.concentration_penalty
            return weight * provisional - (1.0 - weight) * _maximum_similarity(
                candidate, selected
            )

        chosen = max(
            slot_pool,
            key=lambda item: (mmr_value(item), _base_score(item), str(item.object_id)),
        )
        if used_slot_fallback:
            actual_slot = (
                "CORE"
                if _base_score(chosen) >= CORE_FLOOR
                else "CONDITIONAL"
                if _base_score(chosen) >= CONDITIONAL_FLOOR
                else "DIVERSITY"
            )
        similarity = _maximum_similarity(chosen, selected)
        chosen.diversity_adjustment = (
            0.0
            if not selected
            else min(
                MAX_DIVERSITY_ADJUSTMENT,
                (1.0 - mmr_lambda) * (1.0 - similarity) * 0.05,
            )
        )
        if actual_slot == "EXPLORATION":
            chosen.exploration_adjustment = min(
                MAX_EXPLORATION_ADJUSTMENT,
                MAX_EXPLORATION_ADJUSTMENT * _exploration_score(chosen),
            )
        selected.append(chosen)
        slot_types.append(actual_slot)
        mmr_values.append(mmr_value(chosen))

    loss5 = _relevance_loss(eligible, selected, 5)
    loss10 = _relevance_loss(eligible, selected, 10)
    quality_guard_fallback = loss5 > 0.03 or loss10 > 0.05
    if quality_guard_fallback:
        relevance_first: list[MatchCandidate] = []
        for candidate in eligible:
            if len(relevance_first) >= limit:
                break
            if (
                len(relevance_first) < 10
                and _is_exploration(candidate, server_time=server_time)
                and sum(
                    _is_exploration(item, server_time=server_time)
                    for item in relevance_first
                ) >= max_exploration
            ):
                continue
            if _can_take(
                candidate,
                selected=relevance_first,
                profile=profile,
                required_categories=required_categories,
                required_regions=required_regions,
                relax_soft_caps=False,
            ):
                relevance_first.append(candidate)
        if len(relevance_first) < limit:
            selected_ids = {id(candidate) for candidate in relevance_first}
            for candidate in eligible:
                if len(relevance_first) >= limit:
                    break
                if id(candidate) in selected_ids:
                    continue
                if (
                    len(relevance_first) < 10
                    and _is_exploration(candidate, server_time=server_time)
                    and sum(
                        _is_exploration(item, server_time=server_time)
                        for item in relevance_first
                    ) >= max_exploration
                ):
                    continue
                if _can_take(
                    candidate,
                    selected=relevance_first,
                    profile=profile,
                    required_categories=required_categories,
                    required_regions=required_regions,
                    relax_soft_caps=True,
                ):
                    relevance_first.append(candidate)
                    selected_ids.add(id(candidate))
        selected = relevance_first
        exploration_item_ids = {
            id(item)
            for item in selected
            if _is_exploration(item, server_time=server_time)
        }
        slot_types = [
            (
                "EXPLORATION"
                if id(item) in exploration_item_ids
                else "CORE"
                if _base_score(item) >= CORE_FLOOR
                else "CONDITIONAL"
            )
            for item in selected
        ]
        mmr_values = [_base_score(item) for item in selected]
        for item in selected:
            item.diversity_adjustment = 0.0
            item.exploration_adjustment = 0.0
        loss5 = _relevance_loss(eligible, selected, 5)
        loss10 = _relevance_loss(eligible, selected, 10)

    selected_set = {id(item) for item in selected}
    for rank, (candidate, slot_type, mmr_score) in enumerate(
        zip(selected, slot_types, mmr_values), start=1
    ):
        candidate.slate_policy_version = SLATE_POLICY_VERSION
        candidate.rank = rank
        candidate.slot_type = slot_type
        candidate.mmr_score = mmr_score
        candidate.slate_reason_codes = tuple(
            code
            for code, applies in (
                ("CORE_RELEVANCE", slot_type == "CORE"),
                ("CONDITIONAL_RELEVANCE", slot_type == "CONDITIONAL"),
                ("DIVERSITY_MMR", slot_type == "DIVERSITY"),
                ("EXPLORATION_SLOT", slot_type == "EXPLORATION"),
                ("EXPOSURE_DEFICIT", candidate.fairness_adjustment > 0),
                ("REPEAT_PENALTY", candidate.repeat_penalty > 0),
                ("CONCENTRATION_PENALTY", candidate.concentration_penalty > 0),
            )
            if applies
        )
        candidate.slate_score = _clamp(
            _base_score(candidate)
            + candidate.diversity_adjustment
            + candidate.fairness_adjustment
            + candidate.exploration_adjustment
            - candidate.repeat_penalty
            - candidate.concentration_penalty
        )
        candidate.slate_input_fingerprint = _fingerprint(
            {
                "slate_input_fingerprint": input_fingerprint,
                "object_id": candidate.object_id,
                "base_rank": candidate.slate_base_rank,
                "base_score": _base_score(candidate),
            }
        )
        candidate.slate_score_fingerprint = _fingerprint(
            {
                "input_fingerprint": candidate.slate_input_fingerprint,
                "rank": rank,
                "slot_type": slot_type,
                "mmr_score": mmr_score,
                "diversity_adjustment": candidate.diversity_adjustment,
                "fairness_adjustment": candidate.fairness_adjustment,
                "exploration_adjustment": candidate.exploration_adjustment,
                "repeat_penalty": candidate.repeat_penalty,
                "concentration_penalty": candidate.concentration_penalty,
                "slate_score": candidate.slate_score,
            }
        )

    omitted = [item for item in eligible if id(item) not in selected_set]
    for candidate in selected:
        if candidate.object_type != "PRODUCT" or candidate.exhibitor_id is None:
            continue
        candidate.related_object_ids = tuple(
            item.public_object_id
            for item in omitted
            if item.object_type == "PRODUCT"
            and item.exhibitor_id == candidate.exhibitor_id
        )[:3]

    selected_categories = {
        category for item in selected if (category := _top_level_category(item))
    }
    eligible_categories = {
        category for item in eligible if (category := _top_level_category(item))
    }
    selected_exhibitors = {item.exhibitor_id for item in selected if item.exhibitor_id}
    eligible_exhibitors = {item.exhibitor_id for item in eligible if item.exhibitor_id}
    event_exposures = list(overlay.event_exhibitor_impressions.values())
    fairness_gaps = [
        abs(
            eligible_shares.get(exhibitor_id, 0.0)
            - _actual_exhibitor_share(exhibitor_id, overlay)
        )
        for exhibitor_id in eligible_exhibitors
    ]
    exposure_opportunity_ratio = {
        str(exhibitor_id): (
            _actual_exhibitor_share(exhibitor_id, overlay)
            / eligible_shares[exhibitor_id]
        )
        for exhibitor_id in eligible_exhibitors
        if overlay.event_total_impressions > 0
        and eligible_shares.get(exhibitor_id, 0.0) > 0
    }
    metrics: dict[str, Any] = {
        "eligible_count": len(eligible),
        "selected_count": len(selected),
        "diversity_score": _intra_list_diversity(selected),
        "category_coverage": (
            len(selected_categories) / len(eligible_categories)
            if eligible_categories
            else 0.0
        ),
        "supplier_coverage": (
            len(selected_exhibitors) / len(eligible_exhibitors)
            if eligible_exhibitors
            else 0.0
        ),
        "exposure_fairness_score": (
            _clamp(1.0 - sum(fairness_gaps) / len(fairness_gaps))
            if fairness_gaps and overlay.event_total_impressions > 0
            else None
        ),
        "exposure_opportunity_ratio": exposure_opportunity_ratio,
        "relevance_loss_top5": loss5,
        "relevance_loss_top10": loss10,
        "quality_guard_fallback": quality_guard_fallback,
        "quality_guard_unresolved": loss5 > 0.03 or loss10 > 0.05,
        "gini": _gini(event_exposures),
        "hhi": _hhi(event_exposures),
        "exploration_count": sum(item.slot_type == "EXPLORATION" for item in selected),
        "sponsored_separated_count": sum(
            not _is_personalized(item) for item in baseline
        ),
        "repeat_excluded_count": sum(
            item.recommendable_id is not None
            and overlay.user_impressions.get(item.recommendable_id, 0) >= 5
            and overlay.user_positive_actions.get(item.recommendable_id, 0) == 0
            for item in baseline
        ),
    }
    score_payload = {
        "input_fingerprint": input_fingerprint,
        "metrics": metrics,
        "items": [
            {
                "object_id": item.object_id,
                "rank": item.rank,
                "slot_type": item.slot_type,
                "score_fingerprint": item.slate_score_fingerprint,
            }
            for item in selected
        ],
    }
    return SlateBuildResult(
        items=selected,
        policy_version=SLATE_POLICY_VERSION,
        input_fingerprint=input_fingerprint,
        score_fingerprint=_fingerprint(score_payload),
        metrics=metrics,
    )
