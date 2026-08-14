"""Tests for apps/worker/app/jobs/indexing.py and cache_invalidation.py
(WAVE 2D / BACKEND-INDEXING - worker-side shims).

The DB-touching regenerate/unpublish/query logic is tested in
apps/api/tests/test_indexing.py against the service layer; these tests cover
the pure worker-side pieces: trigger -> action mapping, job dispatch through
the Protocol boundary, deterministic cache-key construction, and the
registration hooks.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field

from worker.jobs.cache_invalidation import (
    ALL_CACHE_SCOPES,
    CacheInvalidationPayload,
    CacheScope,
    InMemoryCacheBackend,
    cache_key_for,
    handle_cache_invalidation_job,
    register_cache_invalidation_job,
)
from worker.jobs.indexing import (
    IndexingJobPayload,
    IndexingJobResult,
    IndexingTrigger,
    action_for_trigger,
    handle_indexing_job,
    register_indexing_job,
)

# ---------------------------------------------------------------------------
# indexing job: trigger -> action mapping
# ---------------------------------------------------------------------------


def test_regenerate_triggers_map_to_regenerate() -> None:
    for trigger in (
        IndexingTrigger.APPROVE,
        IndexingTrigger.PUBLISH,
        IndexingTrigger.VISIBILITY_CHANGE,
        IndexingTrigger.MANUAL,
    ):
        assert action_for_trigger(trigger) == "REGENERATE"


def test_unpublish_and_delete_triggers_map_to_unpublish() -> None:
    """unpublish/document-delete must remove content, never regenerate it -
    the 'content MUST actually disappear from search' requirement starts at
    this mapping."""

    for trigger in (IndexingTrigger.UNPUBLISH, IndexingTrigger.DOCUMENT_DELETE):
        assert action_for_trigger(trigger) == "UNPUBLISH"


def test_every_trigger_has_an_action() -> None:
    for trigger in IndexingTrigger:
        assert action_for_trigger(trigger) in {"REGENERATE", "UNPUBLISH"}


# ---------------------------------------------------------------------------
# indexing job: dispatch through the IndexingBackend Protocol
# ---------------------------------------------------------------------------


@dataclass
class _RecordingBackend:
    calls: list[tuple[str, dict]] = field(default_factory=list)

    async def regenerate(self, **kwargs: object) -> IndexingJobResult:
        self.calls.append(("regenerate", dict(kwargs)))
        return IndexingJobResult(indexing_job_id="job-1", status="COMPLETED", action="REGENERATE")

    async def unpublish(self, **kwargs: object) -> IndexingJobResult:
        self.calls.append(("unpublish", dict(kwargs)))
        return IndexingJobResult(indexing_job_id="job-2", status="COMPLETED", action="UNPUBLISH")


def test_handle_indexing_job_dispatches_approve_to_regenerate() -> None:
    backend = _RecordingBackend()
    payload = IndexingJobPayload(
        tenant_id="t1", event_id="e1", exhibitor_id="x1", trigger=IndexingTrigger.APPROVE
    )
    result = asyncio.run(handle_indexing_job(payload, backend=backend))
    assert result.action == "REGENERATE"
    assert backend.calls == [
        (
            "regenerate",
            {
                "tenant_id": "t1",
                "event_id": "e1",
                "exhibitor_id": "x1",
                "trigger": "APPROVE",
                "requested_by_user_id": None,
            },
        )
    ]


def test_handle_indexing_job_dispatches_unpublish_to_unpublish() -> None:
    backend = _RecordingBackend()
    payload = IndexingJobPayload(
        tenant_id="t1", event_id="e1", exhibitor_id="x1", trigger=IndexingTrigger.UNPUBLISH
    )
    result = asyncio.run(handle_indexing_job(payload, backend=backend))
    assert result.action == "UNPUBLISH"
    assert backend.calls[0][0] == "unpublish"
    # An unpublish dispatch must never fall through to regenerate.
    assert all(name != "regenerate" for name, _ in backend.calls)


def test_handle_indexing_job_dispatches_document_delete_to_unpublish() -> None:
    backend = _RecordingBackend()
    payload = IndexingJobPayload(
        tenant_id="t1",
        event_id="e1",
        exhibitor_id="x1",
        trigger=IndexingTrigger.DOCUMENT_DELETE,
    )
    result = asyncio.run(handle_indexing_job(payload, backend=backend))
    assert result.action == "UNPUBLISH"
    assert backend.calls[0][1]["trigger"] == "DOCUMENT_DELETE"


# ---------------------------------------------------------------------------
# cache_invalidation job
# ---------------------------------------------------------------------------


def test_cache_key_for_is_deterministic_per_scope() -> None:
    assert (
        cache_key_for(CacheScope.EXHIBITOR_DETAIL, event_id="e1", exhibitor_id="x1")
        == "exhibitor-detail:x1"
    )
    assert cache_key_for(CacheScope.SEARCH, event_id="e1", exhibitor_id="x1") == "search:event:e1"
    assert (
        cache_key_for(CacheScope.RECOMMENDATION, event_id="e1", exhibitor_id="x1")
        == "recommendation:event:e1"
    )
    assert (
        cache_key_for(CacheScope.BUYER_MATCH, event_id="e1", exhibitor_id="x1")
        == "buyer-match:event:e1"
    )


def test_cache_key_for_missing_ids_falls_back_to_wildcard() -> None:
    """A trigger without an event/exhibitor id must invalidate conservatively
    (the 'all' segment), never silently skip invalidation."""

    assert (
        cache_key_for(CacheScope.EXHIBITOR_DETAIL, event_id=None, exhibitor_id=None)
        == "exhibitor-detail:all"
    )
    assert cache_key_for(CacheScope.SEARCH, event_id=None, exhibitor_id=None) == "search:event:all"


def test_handle_cache_invalidation_job_drops_all_four_scopes_by_default() -> None:
    backend = InMemoryCacheBackend(
        entries={
            "exhibitor-detail:x1": "cached-detail",
            "search:event:e1": "cached-search",
            "recommendation:event:e1": "cached-reco",
            "buyer-match:event:e1": "cached-match",
            "search:event:other": "untouched",
        }
    )
    payload = CacheInvalidationPayload(
        tenant_id="t1", event_id="e1", exhibitor_id="x1", reason="UNPUBLISH"
    )
    result = asyncio.run(handle_cache_invalidation_job(payload, backend=backend))

    assert len(result.invalidated_keys) == len(ALL_CACHE_SCOPES) == 4
    assert result.reason == "UNPUBLISH"
    # The four affected regions are gone; unrelated keys survive.
    assert backend.entries == {"search:event:other": "untouched"}
    assert {scope for scope, _ in backend.invalidated} == {s.value for s in CacheScope}


def test_handle_cache_invalidation_job_is_idempotent() -> None:
    backend = InMemoryCacheBackend()
    payload = CacheInvalidationPayload(
        tenant_id="t1", event_id="e1", exhibitor_id="x1", reason="APPROVE"
    )
    first = asyncio.run(handle_cache_invalidation_job(payload, backend=backend))
    second = asyncio.run(handle_cache_invalidation_job(payload, backend=backend))
    assert first.invalidated_keys == second.invalidated_keys


def test_handle_cache_invalidation_job_respects_explicit_scope_subset() -> None:
    backend = InMemoryCacheBackend()
    payload = CacheInvalidationPayload(
        tenant_id="t1",
        event_id="e1",
        exhibitor_id="x1",
        reason="VISIBILITY_CHANGE",
        scopes=(CacheScope.SEARCH,),
    )
    result = asyncio.run(handle_cache_invalidation_job(payload, backend=backend))
    assert result.invalidated_keys == ("search:event:e1",)


# ---------------------------------------------------------------------------
# registration hooks
# ---------------------------------------------------------------------------


class _FakeRegistry:
    def __init__(self) -> None:
        self.registered: dict[str, object] = {}

    def register(self, name: str, handler: object) -> None:
        self.registered[name] = handler


def test_register_hooks_register_both_jobs() -> None:
    registry = _FakeRegistry()
    register_indexing_job(registry)
    register_cache_invalidation_job(registry)
    assert registry.registered["indexing"] is handle_indexing_job
    assert registry.registered["cache_invalidation"] is handle_cache_invalidation_job
