"""14단계 상황 인지 재정렬 (Context Re-ranker).

근거 문서: docs/05-ai-matching-engine-architecture.md 5.9절 Context Re-ranker,
docs/11-13-scoring-implementation.md "14단계 재정렬은 기본 적합도와 분리해 구현한다".

5.9절은 재정렬 요소(현재 위치와 거리, 남은 체류시간, 부스 대기시간, 상담 가능시간,
확정 일정과의 이동 가능성, 품절 임박, 프로그램 시작시간, 최근 이력, 긴급 운영변경)와
정성적 예시(기본 92점이어도 이동 15분+대기 30분 > 남은 25분이면 순위 하락)만 제시하고
수치 공식은 정의하지 않는다. 이 모듈은 그 원칙("기본 적합도와 '지금 방문할 가치'는
분리해 저장한다")을 지키는 최소 구현이다:

- 기본 적합도(raw/normalized_score)는 절대 수정하지 않는다. context_score([0,1])를
  별도로 계산해 matching.match_result.context_score 컬럼(db-erd 15.3절)에 저장하고,
  최종 순위만 (normalized_score x context_score 반영치)로 다시 매긴다.
- 재정렬 요소 중 context_resolver.py가 실제로 제공하는 데이터(remaining_minutes,
  next_schedule_at, captured_at)로 판단 가능한 것만 구현한다: 남은 체류시간 대비 방문
  소요시간, 확정 일정까지 남은 여유. 부스 대기시간·품절 임박·프로그램 시작시간·긴급
  운영변경은 부스 혼잡도 스트림·재고 이벤트가 아직 없어 훅(ContextSignals의 해당
  필드)만 남겨두었다 - 데이터가 생기면 판정 함수만 추가하면 된다.
- 순위 결합은 5.9절 예시의 성질(상황 페널티가 크면 기본점수가 높아도 뒤로 밀린다)을
  만족하는 가장 단순한 형태를 쓴다: rerank_score = normalized_score x (기본 바닥
  _CONTEXT_FLOOR + (1-_CONTEXT_FLOOR) x context_score). context_score가 1이면 기본
  순위 그대로, 0이어도 기본점수의 _CONTEXT_FLOOR 배는 남는다 - 상황이 나빠도 적합도가
  압도적인 후보가 목록에서 사라지지는 않게 한다(5.9절은 "제외"가 아니라 "재정렬"이다).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal

#: context_score가 0이어도 남는 기본점수 비율. 재정렬은 배제가 아니므로 0이 아니다.
_CONTEXT_FLOOR = Decimal("0.5")

#: 5.9절 예시가 든 "이동 + 대기" 소요시간을 아직 계산할 수 없어(위치·혼잡 데이터 없음),
#: 후보 1곳 방문에 필요한 최소 시간을 보수적 상수로 둔다. TODO(부스 위치·혼잡 데이터
#: 연결 후): 실제 이동시간 + 대기시간 추정으로 교체.
_ASSUMED_VISIT_MINUTES = 10


@dataclass(frozen=True)
class ContextSignals:
    """후보 1개에 대한 상황 신호. 지금은 전 후보 공통 신호(남은 체류시간, 다음 일정)만
    있지만, 부스별 신호(대기시간·품절 임박)가 생기면 후보별로 다른 값을 담게 된다."""

    remaining_minutes: int | None = None
    next_schedule_at: datetime | None = None
    now: datetime | None = None
    #: 훅: 부스 대기시간(분). 혼잡도 스트림이 연결되면 채운다.
    expected_wait_minutes: int | None = None
    #: 훅: 품절 임박 여부. 재고 이벤트가 연결되면 채운다.
    stock_running_out: bool | None = None


@dataclass(frozen=True)
class RerankedCandidate:
    recommendable_id: uuid.UUID
    base_normalized_score: Decimal
    context_score: Decimal
    rerank_score: Decimal
    penalty_codes: tuple[str, ...] = field(default_factory=tuple)


def compute_context_score(signals: ContextSignals) -> tuple[Decimal, tuple[str, ...]]:
    """상황 신호를 [0,1] 점수와 페널티 코드 목록으로 요약한다.

    신호가 하나도 없으면(방문 세션 없음 등) 1을 반환한다 - "상황 정보 없음"은 페널티
    사유가 아니다(10단계 2.3절 "정보 없음과 조건 불충족 분리"와 같은 원칙).
    """

    score = Decimal(1)
    penalties: list[str] = []

    visit_minutes = (
        signals.expected_wait_minutes
        if signals.expected_wait_minutes is not None
        else _ASSUMED_VISIT_MINUTES
    )

    if signals.remaining_minutes is not None:
        if signals.remaining_minutes <= 0:
            score = Decimal(0)
            penalties.append("NO_TIME_REMAINING")
        elif signals.remaining_minutes < visit_minutes:
            # 남은 시간이 방문 소요시간보다 짧다 - 5.9절 예시의 핵심 상황.
            score = min(
                score,
                Decimal(signals.remaining_minutes) / Decimal(visit_minutes),
            )
            penalties.append("INSUFFICIENT_REMAINING_TIME")

    if signals.next_schedule_at is not None and signals.now is not None:
        minutes_to_schedule = (
            signals.next_schedule_at - signals.now
        ).total_seconds() / 60
        if 0 <= minutes_to_schedule < visit_minutes:
            score = min(
                score, Decimal(int(minutes_to_schedule)) / Decimal(visit_minutes)
            )
            penalties.append("UPCOMING_SCHEDULE_CONFLICT")

    if signals.stock_running_out:
        # 품절 임박은 페널티가 아니라 "지금 방문할 가치" 상승 요인이지만(5.9절), 기본
        # 점수를 넘어서는 부양은 하지 않는다 - 페널티가 없는 상태(1.0) 유지가 최대다.
        penalties.append("STOCK_RUNNING_OUT")

    return max(score, Decimal(0)), tuple(penalties)


def rerank(
    candidates: Sequence[tuple[uuid.UUID, Decimal]],
    *,
    signals_of: Callable[[uuid.UUID], ContextSignals],
) -> list[RerankedCandidate]:
    """(recommendable_id, normalized_score) 목록을 상황 반영 순서로 재정렬한다.

    반환 목록은 rerank_score 내림차순이다. 기본 적합도는 수정하지 않고 별도 필드로
    유지한다(모듈 docstring 참고).
    """

    reranked = []
    for recommendable_id, normalized_score in candidates:
        context_score, penalty_codes = compute_context_score(
            signals_of(recommendable_id)
        )
        rerank_score = normalized_score * (
            _CONTEXT_FLOOR + (Decimal(1) - _CONTEXT_FLOOR) * context_score
        )
        reranked.append(
            RerankedCandidate(
                recommendable_id=recommendable_id,
                base_normalized_score=normalized_score,
                context_score=context_score,
                rerank_score=rerank_score,
                penalty_codes=penalty_codes,
            )
        )
    reranked.sort(key=lambda item: item.rerank_score, reverse=True)
    return reranked
