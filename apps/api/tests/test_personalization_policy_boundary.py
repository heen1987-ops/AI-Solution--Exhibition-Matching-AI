"""Regression guard for the AISEARCH-003 personalization-policy decision."""

from __future__ import annotations

from decimal import Decimal

from meet_ai.scoring import CONSUMER_SCORE_V1

from app.schemas.recommendation import RecommendationRequest
from app.services.matching.context_policy import (
    BASE_SCORE_WEIGHT,
    CONTEXT_COMPONENT_WEIGHTS,
    CONTEXT_POLICY_VERSION,
)


def test_published_consumer_v1_keeps_explainable_interest_dimensions() -> None:
    assert CONSUMER_SCORE_V1.version == "consumer-score-v1.0"
    assert dict(CONSUMER_SCORE_V1.weights) == {
        "alcohol": Decimal("0.08"),
        "behavior": Decimal("0.04"),
        "category": Decimal("0.18"),
        "goal": Decimal("0.20"),
        "price": Decimal("0.12"),
        "sensory": Decimal("0.18"),
        "service": Decimal("0.09"),
        "trust": Decimal("0.05"),
        "usage": Decimal("0.06"),
    }
    assert "current_query" not in CONSUMER_SCORE_V1.weights
    assert "booth_availability" not in CONSUMER_SCORE_V1.weights


def test_section_34_inputs_cannot_be_inferred_from_the_current_api_contract() -> None:
    assert set(RecommendationRequest.model_fields) == {
        "recommendation_type",
        "context",
        "limit",
    }
    assert "query" not in RecommendationRequest.model_fields
    assert "current_query" not in RecommendationRequest.model_fields


def test_runtime_availability_remains_a_separate_context_rerank_signal() -> None:
    assert CONTEXT_POLICY_VERSION == "context-rerank-v1.0"
    assert BASE_SCORE_WEIGHT == 0.85
    assert "operational_availability" in CONTEXT_COMPONENT_WEIGHTS
    assert "recent_behavior" in CONTEXT_COMPONENT_WEIGHTS
    assert sum(CONTEXT_COMPONENT_WEIGHTS.values()) == 1.0
