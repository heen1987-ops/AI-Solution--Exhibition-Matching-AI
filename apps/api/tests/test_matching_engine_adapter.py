from __future__ import annotations

from app.services.matching.engine_adapter import (
    execute_catalog_search_score,
    execute_directional_score,
)

from meet_ai.engine import CatalogSearchSignals, MatchingMode
from meet_ai.scoring import EligibilityDecision


def test_backend_catalog_adapter_uses_common_facade_policy() -> None:
    result = execute_catalog_search_score(
        CatalogSearchSignals(0.8, 0.7, 0.6, 0.5, 0.4),
        model_version="embedding-v1",
    )

    assert float(result.normalized_score) == 0.705
    assert result.policy_versions == {"catalog_search": "catalog-search-score-v1.0"}
    assert result.catalog_search_result is not None


def test_backend_recommendation_adapter_preserves_eligibility_provenance() -> None:
    result = execute_directional_score(
        candidate_id="candidate-a",
        exhibitor_id="exhibitor-a",
        mode=MatchingMode.GENERAL_VISITOR,
        components={"goal": 1.0, "category": 0.8},
        eligibility=EligibilityDecision(True, "filter-evaluation-a"),
        confidence=0.9,
    )

    assert result.eligibility_evaluation_id == "filter-evaluation-a"
    assert result.policy_versions == {"consumer": "consumer-score-v1.0"}
    assert result.directional_result is not None
    assert result.calculation_fingerprint
