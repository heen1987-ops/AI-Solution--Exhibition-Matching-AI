from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.services.matching.context_reranker import (
    ContextSignals,
    compute_context_score,
    rerank,
)


def test_no_signals_scores_full_context() -> None:
    score, penalties = compute_context_score(ContextSignals())

    assert score == Decimal(1)
    assert penalties == ()


def test_no_remaining_time_scores_zero_context() -> None:
    score, penalties = compute_context_score(ContextSignals(remaining_minutes=0))

    assert score == Decimal(0)
    assert "NO_TIME_REMAINING" in penalties


def test_insufficient_remaining_time_lowers_score_but_stays_positive() -> None:
    score, penalties = compute_context_score(ContextSignals(remaining_minutes=5))

    assert Decimal(0) < score < Decimal(1)
    assert "INSUFFICIENT_REMAINING_TIME" in penalties


def test_upcoming_schedule_conflict_lowers_score() -> None:
    now = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)
    signals = ContextSignals(
        now=now, next_schedule_at=now + timedelta(minutes=3), remaining_minutes=60
    )

    score, penalties = compute_context_score(signals)

    assert score < Decimal(1)
    assert "UPCOMING_SCHEDULE_CONFLICT" in penalties


def test_rerank_keeps_high_base_score_candidate_ahead_when_context_is_equal() -> None:
    high, low = uuid.uuid4(), uuid.uuid4()
    candidates = [(high, Decimal(90)), (low, Decimal(50))]

    reranked = rerank(candidates, signals_of=lambda _rid: ContextSignals())

    assert [item.recommendable_id for item in reranked] == [high, low]


def test_rerank_can_flip_order_when_context_penalizes_the_higher_base_score() -> None:
    """05단계 5.9절 예시: 기본점수가 높아도 상황이 나쁘면 순위가 밀린다."""

    congested_candidate, immediate_candidate = uuid.uuid4(), uuid.uuid4()
    candidates = [
        (congested_candidate, Decimal(92)),
        (immediate_candidate, Decimal(84)),
    ]

    def signals_of(recommendable_id: uuid.UUID) -> ContextSignals:
        if recommendable_id == congested_candidate:
            return ContextSignals(remaining_minutes=1)
        return ContextSignals(remaining_minutes=60)

    reranked = rerank(candidates, signals_of=signals_of)

    assert reranked[0].recommendable_id == immediate_candidate


def test_rerank_never_zeroes_out_a_candidate_entirely() -> None:
    """재정렬은 배제가 아니다(모듈 docstring) - context_score가 0이어도 기본점수의
    최소 비율은 남아야 한다."""

    recommendable_id = uuid.uuid4()
    reranked = rerank(
        [(recommendable_id, Decimal(100))],
        signals_of=lambda _rid: ContextSignals(remaining_minutes=0),
    )

    assert reranked[0].rerank_score > Decimal(0)
