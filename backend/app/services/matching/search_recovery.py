"""No-result and low-confidence recovery policy for WEB_ONLY search."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

SearchRecoveryAction = Literal[
    "NONE",
    "CLARIFY",
    "BROADEN_CONCEPTS",
    "POPULAR_FALLBACK",
    "CATEGORY_FALLBACK",
]
SearchRecoveryChannel = Literal["REGISTERED_WEB", "GUEST_WEB", "BUYER_WEB"]
SearchQueryType = Literal["FREE_TEXT", "CATEGORY"]

LOW_CONFIDENCE_THRESHOLD = 0.35
MIN_HEALTHY_RESULT_COUNT = 3


@dataclass(frozen=True)
class SearchRecoveryInput:
    channel: SearchRecoveryChannel
    query_type: SearchQueryType
    result_count: int
    confidence: float | None = None
    required_concept_count: int = 0
    preferred_concept_count: int = 0
    excluded_concept_count: int = 0
    unmapped_term_count: int = 0
    has_raw_text: bool = False


@dataclass(frozen=True)
class SearchRecoveryDecision:
    action: SearchRecoveryAction
    reason_codes: tuple[str, ...] = ()
    meta_code: str | None = None
    clarification_question: str | None = None


def _low_confidence(confidence: float | None) -> bool:
    return confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD


def decide_search_recovery(
    recovery_input: SearchRecoveryInput,
) -> SearchRecoveryDecision:
    """Choose the least surprising recovery step for a search response.

    The function is deliberately pure so BAC-008 can call it before persisting
    `matching.search_query.fallback_reason`. It never invents ontology concepts
    and never asks for PII.
    """

    if recovery_input.result_count < 0:
        raise ValueError("result_count must be >= 0")
    if recovery_input.confidence is not None and not 0 <= recovery_input.confidence <= 1:
        raise ValueError("confidence must be between 0 and 1")

    if (
        recovery_input.result_count >= MIN_HEALTHY_RESULT_COUNT
        and not _low_confidence(recovery_input.confidence)
    ):
        return SearchRecoveryDecision(action="NONE")

    if recovery_input.query_type == "CATEGORY" and recovery_input.result_count == 0:
        return SearchRecoveryDecision(
            action="CATEGORY_FALLBACK",
            reason_codes=("CATEGORY_NO_RESULT",),
            meta_code="SEARCH_NO_RESULT",
        )

    if _low_confidence(recovery_input.confidence):
        return SearchRecoveryDecision(
            action="CLARIFY",
            reason_codes=("LOW_CONFIDENCE_INTENT",),
            meta_code="SEARCH_NO_RESULT" if recovery_input.result_count == 0 else None,
            clarification_question="찾으시는 조건을 조금 더 구체적으로 알려주시겠어요?",
        )

    if recovery_input.required_concept_count > 0 and recovery_input.result_count == 0:
        return SearchRecoveryDecision(
            action="BROADEN_CONCEPTS",
            reason_codes=("STRICT_CONCEPTS_NO_RESULT",),
            meta_code="SEARCH_NO_RESULT",
        )

    if recovery_input.unmapped_term_count > 0 and recovery_input.has_raw_text:
        return SearchRecoveryDecision(
            action="POPULAR_FALLBACK",
            reason_codes=("ONTOLOGY_GAP_KEYWORD_FALLBACK",),
            meta_code="SEARCH_NO_RESULT" if recovery_input.result_count == 0 else None,
        )

    if recovery_input.result_count == 0:
        return SearchRecoveryDecision(
            action="POPULAR_FALLBACK",
            reason_codes=("EMPTY_RESULT_SET",),
            meta_code="SEARCH_NO_RESULT",
        )

    return SearchRecoveryDecision(
        action="BROADEN_CONCEPTS",
        reason_codes=("LOW_RECALL_RESULT_SET",),
    )
