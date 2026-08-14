from __future__ import annotations

import uuid

from app.services.matching.explanation_generator import (
    EXPLANATION_POLICY_VERSION,
    generate_explanations,
)
from app.services.matching.types import MatchCandidate, ResolvedProfile


def _profile(*, user_type: str = "GENERAL_VISITOR") -> ResolvedProfile:
    return ResolvedProfile(
        profile_id=uuid.uuid4(),
        profile_version=4,
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


def _candidate(**overrides: object) -> MatchCandidate:
    values: dict[str, object] = {
        "object_type": "PRODUCT",
        "object_id": uuid.uuid4(),
        "recommendable_id": uuid.uuid4(),
        "exhibitor_id": uuid.uuid4(),
        "participation_id": uuid.uuid4(),
        "public_object_id": "product-001",
    }
    values.update(overrides)
    return MatchCandidate(**values)  # type: ignore[arg-type]


def test_feature_reason_has_profile_and_target_evidence_with_lineage() -> None:
    profile = _profile()
    candidate = _candidate(features={"taste_match": 0.91})

    generate_explanations([candidate], profile=profile)

    assert len(candidate.reasons) == 1
    reason = candidate.reasons[0]
    assert reason.code == "TASTE_MATCH"
    assert reason.evidence_refs == [
        f"profile:{profile.profile_id}:v4",
        f"product:{candidate.object_id}:taste_match",
    ]
    assert reason.explanation_policy_version == EXPLANATION_POLICY_VERSION
    assert reason.input_fingerprint is not None
    assert len(reason.input_fingerprint) == 64


def test_unapproved_or_sensitive_features_are_not_exposed() -> None:
    profile = _profile()
    candidate = _candidate(
        features={
            "gender_match": 1.0,
            "age_match": 1.0,
            "sponsor_score": 1.0,
        }
    )

    generate_explanations([candidate], profile=profile)

    assert [reason.code for reason in candidate.reasons] == [
        "EXPLORATION_CANDIDATE"
    ]
    assert candidate.reasons[0].text == (
        "직접 일치하는 정보가 부족해 탐색 후보로 제안합니다."
    )


def test_reasons_are_sorted_by_contribution_and_limited_to_three() -> None:
    profile = _profile()
    candidate = _candidate(
        features={
            "taste_match": 0.7,
            "aroma_match": 0.95,
            "category_match": 0.8,
            "price_match": 0.6,
        },
        availability={"meeting": True},
        estimated_walk_minutes=5,
        score_components={"context_score": 0.1},
    )

    generate_explanations([candidate], profile=profile)

    assert [reason.code for reason in candidate.reasons] == [
        "AROMA_MATCH",
        "CATEGORY_MATCH",
        "TASTE_MATCH",
    ]
    assert [reason.display_order for reason in candidate.reasons] == [0, 1, 2]
    assert all("None" not in ref for reason in candidate.reasons for ref in reason.evidence_refs)


def test_buyer_uses_trade_templates_instead_of_consumer_templates() -> None:
    profile = _profile(user_type="BUYER")
    candidate = _candidate(
        features={
            "channel_match": 0.9,
            "taste_match": 1.0,
        }
    )

    generate_explanations([candidate], profile=profile)

    assert [reason.code for reason in candidate.reasons] == ["CHANNEL_MATCH"]
