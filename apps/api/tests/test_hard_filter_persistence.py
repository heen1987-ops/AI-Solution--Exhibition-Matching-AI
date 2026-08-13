from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from app.models.filtering import FilterEvaluation
from app.services.matching.errors import RecommendationError
from app.services.matching.hard_filter import (
    evaluate_hard_filters,
    persist_hard_filter_evaluation,
)
from app.services.matching.types import (
    MatchCandidate,
    ResolvedContext,
    ResolvedProfile,
    SubjectContext,
)


def _subject() -> SubjectContext:
    return SubjectContext(
        tenant_id=uuid.uuid4(),
        event_id=uuid.uuid4(),
        profile_id=uuid.uuid4(),
        visit_session_id=None,
        user_id=None,
        guest_session_id=uuid.uuid4(),
        request_id="req-hard-filter-001",
        idempotency_key="idem-hard-filter-001",
        server_time=datetime(2026, 8, 1, 12, tzinfo=UTC),
    )


def _profile(subject: SubjectContext) -> ResolvedProfile:
    return ResolvedProfile(
        profile_id=subject.profile_id,
        profile_version=4,
        profile_version_id=uuid.uuid4(),
        user_type="GENERAL_VISITOR",
        completeness=0.9,
        goals=[],
        categories=[],
        channels=[],
        regions=[],
        taste=[],
        aroma=[],
        extra={},
        numeric_conditions={"retail_price_max": 20_000},
        raw_context={},
    )


def _context(subject: SubjectContext) -> ResolvedContext:
    return ResolvedContext(
        current_zone="A",
        current_zone_id=uuid.uuid4(),
        remaining_minutes=90,
        visited_booth_ids=set(),
        upcoming_meetings=[],
        upcoming_meeting_booth_ids=set(),
        operational_snapshot_version=7,
        exclude_visited=True,
        include_meetings=True,
        avoid_congestion=False,
        server_time=subject.server_time,
    )


def _product(*, price: int = 30_000) -> MatchCandidate:
    object_id = uuid.uuid4()
    return MatchCandidate(
        object_type="PRODUCT",
        object_id=object_id,
        recommendable_id=uuid.uuid4(),
        exhibitor_id=uuid.uuid4(),
        participation_id=uuid.uuid4(),
        public_object_id=str(object_id),
        payload={
            "category_code": "CATEGORY.TAKJU",
            "event_price_amount": price,
            "approval_status": "APPROVED",
            "master_approval_status": "APPROVED",
        },
    )


def test_evaluation_is_reproducible_and_order_independent() -> None:
    subject = _subject()
    profile = _profile(subject)
    context = _context(subject)
    eligible = _product()
    excluded = _product(price=10_000)
    excluded_ids = {excluded.recommendable_id}

    first = evaluate_hard_filters(
        candidates=[eligible, excluded],
        subject=subject,
        profile=profile,
        context=context,
        excluded_recommendable_ids=excluded_ids,
    )
    second = evaluate_hard_filters(
        candidates=[excluded, eligible],
        subject=subject,
        profile=profile,
        context=context,
        excluded_recommendable_ids=excluded_ids,
    )

    assert first.filter_evaluation_id != second.filter_evaluation_id
    assert first.input_fingerprint == second.input_fingerprint
    assert first.eligible_candidates == [eligible]
    assert first.rejected_count == 1
    assert eligible.filter_evaluation_id == str(second.filter_evaluation_id)
    rejected = next(outcome for outcome in first.outcomes if not outcome.passed)
    assert rejected.filter_code == "USER_EXCLUDED"
    assert rejected.evidence_refs == [
        f"candidate_payload_sha256:{rejected.candidate_fingerprint}"
    ]


def test_price_is_hard_constraint_only_when_user_requires_it() -> None:
    subject = _subject()
    profile = _profile(subject)
    context = _context(subject)
    candidate = _product()

    advisory = evaluate_hard_filters(
        candidates=[candidate],
        subject=subject,
        profile=profile,
        context=context,
        excluded_recommendable_ids=set(),
    )
    profile.raw_context["price_limit_required"] = True
    required = evaluate_hard_filters(
        candidates=[candidate],
        subject=subject,
        profile=profile,
        context=context,
        excluded_recommendable_ids=set(),
    )

    assert len(advisory.eligible_candidates) == 1
    assert required.eligible_candidates == []
    assert required.outcomes[0].filter_code == "PRICE_OVER_LIMIT"


class _FakeSession:
    def __init__(self) -> None:
        self.added: list[Any] = []
        self.flushed = False

    def add(self, row: Any) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        self.flushed = True


@pytest.mark.asyncio
async def test_persistence_stages_one_append_only_evaluation() -> None:
    subject = _subject()
    profile = _profile(subject)
    context = _context(subject)
    eligible = _product(price=10_000)
    rejected = _product(price=10_000)
    evaluation = evaluate_hard_filters(
        candidates=[eligible, rejected],
        subject=subject,
        profile=profile,
        context=context,
        excluded_recommendable_ids={rejected.recommendable_id},
    )
    session = _FakeSession()

    await persist_hard_filter_evaluation(
        session,  # type: ignore[arg-type]
        evaluation=evaluation,
        subject=subject,
        profile=profile,
        context=context,
    )

    assert session.flushed is True
    assert len(session.added) == 1
    row = session.added[0]
    assert isinstance(row, FilterEvaluation)
    assert row.filter_evaluation_id == evaluation.filter_evaluation_id
    assert row.candidate_count == 2
    assert row.eligible_count == 1
    assert row.rejected_count == 1
    assert len(row.results) == 2
    assert {result.passed for result in row.results} == {True, False}
    assert all(result.candidate_fingerprint for result in row.results)


@pytest.mark.asyncio
async def test_persistence_requires_profile_snapshot() -> None:
    subject = _subject()
    profile = _profile(subject)
    context = _context(subject)
    candidate = _product(price=10_000)
    evaluation = evaluate_hard_filters(
        candidates=[candidate],
        subject=subject,
        profile=profile,
        context=context,
        excluded_recommendable_ids=set(),
    )
    profile.profile_version_id = None

    with pytest.raises(RecommendationError) as raised:
        await persist_hard_filter_evaluation(
            _FakeSession(),  # type: ignore[arg-type]
            evaluation=evaluation,
            subject=subject,
            profile=profile,
            context=context,
        )

    assert raised.value.code == "PROFILE_INCOMPLETE"
