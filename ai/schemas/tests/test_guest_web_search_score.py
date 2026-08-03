"""AIS-007 tests for the GUEST_WEB search scoring policy."""

from __future__ import annotations

import sys
from decimal import Decimal
from pathlib import Path

_SRC_DIR = Path(__file__).resolve().parents[3] / "src"
sys.path.insert(0, str(_SRC_DIR))

from meet_ai.scoring import (
    GUEST_WEB_SEARCH_SCORE_V1,
    EligibilityDecision,
    calculate_directional_score,
)


def test_guest_web_search_policy_weights_are_cr001_shape() -> None:
    assert GUEST_WEB_SEARCH_SCORE_V1.audience == "GUEST_WEB_SEARCH"
    assert GUEST_WEB_SEARCH_SCORE_V1.weights == {
        "availability": Decimal("0.05"),
        "data_quality": Decimal("0.05"),
        "keyword": Decimal("0.30"),
        "semantic": Decimal("0.45"),
        "structured": Decimal("0.15"),
    }


def test_guest_web_search_policy_renormalizes_missing_signals() -> None:
    result = calculate_directional_score(
        GUEST_WEB_SEARCH_SCORE_V1,
        {
            "semantic": None,
            "keyword": Decimal("0.80"),
            "structured": Decimal("0.60"),
            "data_quality": Decimal(1),
            "availability": Decimal(1),
        },
        eligibility=EligibilityDecision(
            passed=True,
            evaluation_id="guest-web-search-test",
        ),
    )

    assert result.missing_components == ("semantic",)
    assert result.effective_weights["keyword"] > GUEST_WEB_SEARCH_SCORE_V1.weights["keyword"]
    assert result.final_score.quantize(Decimal("0.01")) == Decimal("78.18")
    assert result.grade == "S4"
