"""AI-BUYER-MATCH(WAVE 2C) canonical 패키지.

결정론적(비-LLM, 규칙기반) B2B 하드필터 + 점수화 엔진. 순수 Python 라이브러리이며 DB나
FastAPI에 의존하지 않는다 - BACKEND-BUYER-MATCH 트랙이 ORM 객체를 ``ai.buyer_matching.types``
의 dataclass로 매핑해 이 패키지의 함수를 호출한다.

공개 API:

- ``hard_filter(buyer_profile, exhibitor_candidates) -> list[HardFilterResult]``
- ``score_b2e(buyer, exhibitor) -> BuyerToExhibitorScore``
- ``score_e2b(buyer, exhibitor) -> ExhibitorToBuyerScore | None``
- ``mutual_score(b2e_score, e2b_score) -> float``
- ``grade_for_score(score) -> str``
- ``evaluate_candidates(buyer_profile, exhibitor_candidates) -> list[BuyerMatchResult]``
  (위 전부를 하나로 묶는 권장 진입점)
"""

from __future__ import annotations

from ai.buyer_matching.hard_filter import hard_filter
from ai.buyer_matching.pipeline import evaluate_candidates, primary_results
from ai.buyer_matching.scoring import (
    GRADE_THRESHOLDS,
    grade_for_score,
    harmonic_mean,
    mutual_score,
    score_b2e,
    score_e2b,
)
from ai.buyer_matching.types import (
    BuyerMatchResult,
    BuyerProfile,
    BuyerToExhibitorScore,
    ComponentScore,
    ExhibitorBuyerPreferenceSignal,
    ExhibitorCandidate,
    ExhibitorToBuyerScore,
    HardFilterResult,
)

__all__ = [
    "GRADE_THRESHOLDS",
    "BuyerMatchResult",
    "BuyerProfile",
    "BuyerToExhibitorScore",
    "ComponentScore",
    "ExhibitorBuyerPreferenceSignal",
    "ExhibitorCandidate",
    "ExhibitorToBuyerScore",
    "HardFilterResult",
    "evaluate_candidates",
    "grade_for_score",
    "hard_filter",
    "harmonic_mean",
    "mutual_score",
    "primary_results",
    "score_b2e",
    "score_e2b",
]
