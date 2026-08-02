from __future__ import annotations

import uuid

from app.services.matching.engine_adapter import (
    execute_catalog_search_score,
    execute_directional_score,
)
from app.services.matching.explanation_generator import generate_explanations
from app.services.matching.types import MatchCandidate, ResolvedProfile

from meet_ai.engine import CatalogSearchSignals, MatchingMode
from meet_ai.scoring import EligibilityDecision


def test_backend_catalog_adapter_uses_common_facade_policy() -> None:
    result = execute_catalog_search_score(
        CatalogSearchSignals(0.8, 0.7, 0.6, 0.5, 0.4),
        reason_evidence={
            "SEMANTIC_MATCH": ("query:structured", "candidate:approved_summary"),
            "KEYWORD_MATCH": ("query:tokens", "candidate:approved_document"),
        },
        model_version="embedding-v1",
    )

    assert float(result.normalized_score) == 0.705
    assert result.policy_versions == {"catalog_search": "catalog-search-score-v1.0"}
    assert result.catalog_search_result is not None
    assert [claim.code for claim in result.reason_claims] == [
        "SEMANTIC_MATCH",
        "KEYWORD_MATCH",
    ]


def test_backend_recommendation_adapter_preserves_eligibility_provenance() -> None:
    result = execute_directional_score(
        candidate_id="candidate-a",
        exhibitor_id="exhibitor-a",
        mode=MatchingMode.GENERAL_VISITOR,
        components={"goal": 1.0, "category": 0.8},
        eligibility=EligibilityDecision(True, "filter-evaluation-a"),
        confidence=0.9,
        reason_evidence={
            "GOAL_MATCH": ("profile:goal", "candidate:usage"),
            "CATEGORY_MATCH": ("profile:category", "candidate:category"),
        },
    )

    assert result.eligibility_evaluation_id == "filter-evaluation-a"
    assert result.policy_versions == {"consumer": "consumer-score-v1.0"}
    assert result.directional_result is not None
    assert result.calculation_fingerprint
    assert {claim.code for claim in result.reason_claims} == {
        "GOAL_MATCH",
        "CATEGORY_MATCH",
    }


def test_runtime_explanation_projects_facade_claims_not_raw_feature_rank() -> None:
    profile = ResolvedProfile(
        profile_id=uuid.uuid4(),
        profile_version=1,
        profile_version_id=uuid.uuid4(),
        user_type="GENERAL_VISITOR",
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
    candidate = MatchCandidate(
        object_type="PRODUCT",
        object_id=uuid.uuid4(),
        recommendable_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        participation_id=uuid.uuid4(),
        public_object_id="product-runtime-reason",
        features={"taste_match": 1.0, "category_match": 0.8},
        directional_policy_version="consumer-score-v1.0",
        directional_contributions={"category": 0.2},
    )

    generate_explanations([candidate], profile=profile)

    assert [reason.code for reason in candidate.reasons] == ["CATEGORY_MATCH"]
    assert set(candidate.reasons[0].evidence_refs) == {
        f"profile:{profile.profile_id}:v1",
        f"product:{candidate.object_id}:category_match",
    }
