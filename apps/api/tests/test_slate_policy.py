from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from app.services.matching.slate_policy import (
    MAX_FAIRNESS_ADJUSTMENT,
    SLATE_POLICY_VERSION,
    ExposureOverlay,
    build_slate,
)
from app.services.matching.types import (
    MatchCandidate,
    ResolvedProfile,
    TaxonomyItem,
)

NOW = datetime(2026, 8, 1, 12, tzinfo=UTC)


def _profile(
    user_type: str = "GENERAL_VISITOR", *, required_category: str | None = None
) -> ResolvedProfile:
    categories = (
        [TaxonomyItem(code=required_category, level="REQUIRED", confidence=1.0)]
        if required_category
        else []
    )
    return ResolvedProfile(
        profile_id=uuid.uuid4(),
        profile_version=1,
        profile_version_id=uuid.uuid4(),
        user_type=user_type,
        completeness=90,
        goals=[],
        categories=categories,
        channels=[],
        regions=[],
        taste=[],
        aroma=[],
        extra={},
        numeric_conditions={},
        raw_context={},
    )


def _candidate(
    score: float,
    *,
    exhibitor_id: uuid.UUID | None = None,
    category: str = "CATEGORY.DISTILLED",
    region: str = "REGION.GYEONGBUK",
    exploration: bool = False,
    sponsored: bool = False,
    suffix: str | None = None,
) -> MatchCandidate:
    object_id = uuid.uuid4()
    candidate = MatchCandidate(
        object_type="PRODUCT",
        object_id=object_id,
        recommendable_id=uuid.uuid4(),
        exhibitor_id=exhibitor_id or uuid.uuid4(),
        participation_id=uuid.uuid4(),
        public_object_id=suffix or str(object_id),
        context_blended_score=score,
        final_score=score,
        score_components={"trust_score": 0.9},
        features={"novelty_score": 0.9 if exploration else 0.2},
        payload={
            "category_code": category,
            "region_codes": [region],
            "event_price_amount": 30_000,
            "taste_json": {"TASTE.DRY": 4},
            "created_at": NOW - timedelta(days=2 if exploration else 90),
            "is_sponsored": sponsored,
        },
    )
    if exploration:
        candidate.source_channels.add("EXPLORATION")
    return candidate


def test_top_five_prevents_one_exhibitor_from_dominating() -> None:
    exhibitor_a = uuid.uuid4()
    candidates = [
        _candidate(0.95 - index * 0.002, exhibitor_id=exhibitor_a, suffix=f"a-{index}")
        for index in range(5)
    ]
    candidates.extend(
        _candidate(0.945 - index * 0.003, suffix=f"other-{index}") for index in range(5)
    )

    result = build_slate(candidates, limit=10, profile=_profile(), server_time=NOW)

    top_five = result.items[:5]
    assert sum(item.exhibitor_id == exhibitor_a for item in top_five) == 1
    assert (
        max(
            sum(item.exhibitor_id == exhibitor for item in result.items)
            for exhibitor in {item.exhibitor_id for item in result.items}
        )
        <= 2
    )
    representative = next(
        item for item in result.items if item.exhibitor_id == exhibitor_a
    )
    assert len(representative.related_object_ids) == 3


def test_category_and_region_caps_hold_when_alternatives_exist() -> None:
    concentrated = [
        _candidate(
            0.95 - index * 0.005,
            category="CATEGORY.CONCENTRATED",
            region="REGION.CONCENTRATED",
            suffix=f"concentrated-{index}",
        )
        for index in range(6)
    ]
    alternatives = [
        _candidate(
            0.90 - index * 0.005,
            category=f"CATEGORY.ALTERNATIVE.{index % 3}",
            region=f"REGION.ALTERNATIVE.{index}",
            suffix=f"alternative-{index}",
        )
        for index in range(6)
    ]

    result = build_slate(
        [*concentrated, *alternatives],
        limit=10,
        profile=_profile(),
        server_time=NOW,
    )

    assert (
        sum(
            item.payload["category_code"] == "CATEGORY.CONCENTRATED"
            for item in result.items[:5]
        )
        <= 3
    )
    assert (
        sum(
            "REGION.CONCENTRATED" in item.payload["region_codes"]
            for item in result.items[:10]
        )
        <= 4
    )


def test_relevance_floor_and_sponsor_separation_are_never_relaxed() -> None:
    low = _candidate(0.44, exploration=True, suffix="low-new")
    sponsor = _candidate(0.99, sponsored=True, suffix="sponsor")
    valid = [
        _candidate(0.80 - index * 0.01, suffix=f"valid-{index}") for index in range(5)
    ]

    result = build_slate(
        [low, sponsor, *valid], limit=7, profile=_profile(), server_time=NOW
    )
    ids = {item.public_object_id for item in result.items}

    assert "low-new" not in ids
    assert "sponsor" not in ids
    assert result.metrics["sponsored_separated_count"] == 1


def test_fallback_slot_label_never_claims_a_higher_relevance_tier() -> None:
    conditional = _candidate(0.60, suffix="conditional")
    diversity = _candidate(0.50, suffix="diversity")

    result = build_slate(
        [conditional, diversity],
        limit=2,
        profile=_profile(),
        server_time=NOW,
    )

    assert [item.slot_type for item in result.items] == ["CONDITIONAL", "DIVERSITY"]


def test_exploration_slot_is_optional_and_requires_relevance() -> None:
    new = _candidate(0.72, exploration=True, suffix="new-qualified")
    candidates = [new] + [
        _candidate(0.90 - index * 0.015, suffix=f"core-{index}") for index in range(9)
    ]

    result = build_slate(candidates, limit=10, profile=_profile(), server_time=NOW)

    selected_new = next(
        item for item in result.items if item.public_object_id == "new-qualified"
    )
    assert selected_new.slot_type == "EXPLORATION"
    assert selected_new.exploration_adjustment <= 0.04
    assert result.metrics["exploration_count"] == 1


def test_top_ten_never_contains_more_than_one_exploration_candidate() -> None:
    candidates = [
        _candidate(0.90 - index * 0.01, exploration=True, suffix=f"new-{index}")
        for index in range(6)
    ]
    candidates.extend(
        _candidate(0.82 - index * 0.01, suffix=f"established-{index}")
        for index in range(6)
    )

    result = build_slate(candidates, limit=10, profile=_profile(), server_time=NOW)

    assert (
        sum(item.public_object_id.startswith("new-") for item in result.items[:10]) == 1
    )


def test_exploration_slot_uses_quality_and_novelty_formula() -> None:
    higher_relevance = _candidate(0.70, exploration=True, suffix="higher-relevance")
    higher_relevance.score_components["trust_score"] = 0.4
    higher_relevance.features["novelty_score"] = 0.1
    higher_quality = _candidate(0.60, exploration=True, suffix="higher-quality")
    higher_quality.score_components["trust_score"] = 1.0
    higher_quality.features["novelty_score"] = 1.0
    established = [
        _candidate(0.90 - index * 0.01, suffix=f"core-{index}") for index in range(9)
    ]

    result = build_slate(
        [higher_relevance, higher_quality, *established],
        limit=10,
        profile=_profile(),
        server_time=NOW,
    )

    exploration = next(item for item in result.items if item.slot_type == "EXPLORATION")
    assert exploration.public_object_id == "higher-quality"


def test_nearby_preference_uses_observed_distance_without_penalizing_missing() -> None:
    farther = _candidate(0.80, suffix="farther")
    farther.distance_meters = 1_000
    nearer = _candidate(0.79, suffix="nearer")
    nearer.distance_meters = 100
    missing = _candidate(0.78, suffix="missing")

    result = build_slate(
        [farther, nearer, missing],
        limit=3,
        profile=_profile(),
        server_time=NOW,
        user_preference="NEARBY_FIRST",
    )

    assert result.items[0].public_object_id == "nearer"
    assert {item.public_object_id for item in result.items} == {
        "farther",
        "nearer",
        "missing",
    }


def test_five_ignored_impressions_exclude_until_positive_action() -> None:
    repeated = _candidate(0.95, suffix="repeated")
    alternatives = [
        _candidate(0.80 - index * 0.01, suffix=f"alt-{index}") for index in range(5)
    ]
    exposure = ExposureOverlay(
        user_impressions={repeated.recommendable_id: 5},
    )

    excluded = build_slate(
        [repeated, *alternatives],
        limit=5,
        profile=_profile(),
        server_time=NOW,
        exposure=exposure,
    )
    assert "repeated" not in {item.public_object_id for item in excluded.items}

    restored = build_slate(
        [repeated, *alternatives],
        limit=5,
        profile=_profile(),
        server_time=NOW,
        exposure=ExposureOverlay(
            user_impressions={repeated.recommendable_id: 5},
            user_positive_actions={repeated.recommendable_id: 1},
        ),
    )
    assert "repeated" in {item.public_object_id for item in restored.items}


def test_buyer_slate_has_one_card_per_exhibitor() -> None:
    exhibitor = uuid.uuid4()
    candidates = [
        _candidate(0.95 - index * 0.01, exhibitor_id=exhibitor, suffix=f"same-{index}")
        for index in range(5)
    ]
    candidates.extend(
        _candidate(0.88 - index * 0.01, suffix=f"different-{index}")
        for index in range(5)
    )

    result = build_slate(
        candidates, limit=10, profile=_profile("BUYER"), server_time=NOW
    )
    assert sum(item.exhibitor_id == exhibitor for item in result.items) == 1


def test_opportunity_adjustment_is_bounded_and_reproducible() -> None:
    underexposed = uuid.uuid4()
    overexposed = uuid.uuid4()
    candidates = [
        _candidate(0.8, exhibitor_id=underexposed, suffix="under"),
        _candidate(0.8, exhibitor_id=overexposed, suffix="over"),
    ]
    exposure = ExposureOverlay(
        event_exhibitor_impressions={underexposed: 1, overexposed: 99},
        event_total_impressions=100,
    )

    first = build_slate(
        candidates,
        limit=2,
        profile=_profile(),
        server_time=NOW,
        exposure=exposure,
    )
    second = build_slate(
        candidates,
        limit=2,
        profile=_profile(),
        server_time=NOW,
        exposure=exposure,
    )

    under = next(item for item in first.items if item.exhibitor_id == underexposed)
    over = next(item for item in first.items if item.exhibitor_id == overexposed)
    assert under.fairness_adjustment == MAX_FAIRNESS_ADJUSTMENT
    assert over.fairness_adjustment == -MAX_FAIRNESS_ADJUSTMENT
    assert over.concentration_penalty <= 0.05
    assert under.final_score == pytest.approx(0.8)
    assert under.slate_score != under.final_score
    eor = first.metrics["exposure_opportunity_ratio"]
    assert eor[str(underexposed)] == pytest.approx(0.02)
    assert eor[str(overexposed)] == pytest.approx(1.98)
    assert first.policy_version == SLATE_POLICY_VERSION
    assert first.input_fingerprint == second.input_fingerprint
    assert first.score_fingerprint == second.score_fingerprint


def test_quality_guard_caps_relevance_loss() -> None:
    dominant = uuid.uuid4()
    candidates = [
        _candidate(0.99 - index * 0.005, exhibitor_id=dominant, suffix=f"top-{index}")
        for index in range(5)
    ]
    candidates.extend(
        _candidate(0.50 - index * 0.005, suffix=f"tail-{index}") for index in range(5)
    )

    result = build_slate(candidates, limit=10, profile=_profile(), server_time=NOW)

    assert result.metrics["quality_guard_fallback"] is True
    assert result.metrics["quality_guard_unresolved"] is True
    assert len(result.items) == 6
    assert sum(item.exhibitor_id == dominant for item in result.items) == 1
    assert result.metrics["relevance_loss_top10"] == pytest.approx(0.3266666667)
