"""cache_invalidation job.

Track GOAL (verbatim): "On approve/publish/unpublish/visibility-change/
document-delete: create an indexing job, regenerate the relevant search
document(s), and invalidate the relevant caches (exhibitor detail, search,
recommendation, buyer-match)."

Division of labour with the rest of this track
------------------------------------------------
`apps/api/app/services/indexing/service.py` (same track) durably records the
*intent* to invalidate as `indexing.cache_invalidation_event` rows (its
`_record_cache_invalidations`). This worker job is the consume side: given
one of those recorded events (or a direct trigger payload), it computes the
deterministic cache keys for each affected scope and asks a `CacheBackend`
to drop them.

CacheBackend is now backed by real Redis (unified-repo port note)
--------------------------------------------------------------------
Unlike the standalone-worktree original of this module - which had no Redis client
wiring anywhere and deliberately kept `CacheBackend` unimplemented pending a future
integration pass - this repo already wires `redis.asyncio` in three places
(`app/api/v1/routers/kiosk.py`, `app/services/search_sessions.py`,
`app/services/auth_rate_limit.py`, all consuming `Settings.REDIS_URL`).
`worker/backends/redis_cache.py::RedisCacheBackend` is the real implementation of the
`CacheBackend` Protocol below, following that same `redis.asyncio.from_url` pattern.
`InMemoryCacheBackend` remains the reference implementation this module's own tests use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable


class CacheScope(str, Enum):
    """The four cache regions the track GOAL names. Values match
    `indexing.cache_invalidation_event.cache_scope`'s CHECK constraint
    (apps/api/app/models/indexing.py `CACHE_SCOPES`) so a consumed event row
    maps 1:1 onto this enum."""

    EXHIBITOR_DETAIL = "EXHIBITOR_DETAIL"
    SEARCH = "SEARCH"
    RECOMMENDATION = "RECOMMENDATION"
    BUYER_MATCH = "BUYER_MATCH"


ALL_CACHE_SCOPES: tuple[CacheScope, ...] = tuple(CacheScope)


def cache_key_for(scope: CacheScope, *, event_id: str | None, exhibitor_id: str | None) -> str:
    """Deterministic cache key per scope.

    - EXHIBITOR_DETAIL is keyed per exhibitor (a detail page cache).
    - SEARCH / RECOMMENDATION / BUYER_MATCH are keyed per event: any change
      to one exhibitor can change ranked/filtered result sets for every
      query in that event, so the whole event-scoped region is dropped
      rather than guessing which result lists contained the exhibitor.
    - A missing id falls back to the "all" wildcard segment so an
      event-less trigger (e.g. master-data delete) still invalidates
      conservatively rather than not at all.
    """

    if scope is CacheScope.EXHIBITOR_DETAIL:
        return f"exhibitor-detail:{exhibitor_id or 'all'}"
    prefix = {
        CacheScope.SEARCH: "search",
        CacheScope.RECOMMENDATION: "recommendation",
        CacheScope.BUYER_MATCH: "buyer-match",
    }[scope]
    return f"{prefix}:event:{event_id or 'all'}"


@dataclass(frozen=True)
class CacheInvalidationPayload:
    """One consumed `indexing.cache_invalidation_event` row (or an
    equivalent direct trigger). `scopes` defaults to all four regions -
    matching `_record_cache_invalidations`, which always records all four."""

    tenant_id: str
    event_id: str | None
    exhibitor_id: str | None
    reason: str  # one of app/models/indexing.py INDEXING_JOB_TRIGGERS
    scopes: tuple[CacheScope, ...] = ALL_CACHE_SCOPES


@dataclass(frozen=True)
class CacheInvalidationResult:
    invalidated_keys: tuple[str, ...]
    reason: str


@runtime_checkable
class CacheBackend(Protocol):
    """Structural boundary to the real cache. See module docstring for the real Redis
    implementation (`worker/backends/redis_cache.py`)."""

    async def invalidate(self, *, scope: str, key: str) -> None: ...


@dataclass
class InMemoryCacheBackend:
    """Reference CacheBackend for tests and local/dev use (same precedent as
    `document_parsing.py`'s InMemorySegmentStore)."""

    entries: dict[str, object] = field(default_factory=dict)
    invalidated: list[tuple[str, str]] = field(default_factory=list)

    async def invalidate(self, *, scope: str, key: str) -> None:
        self.entries.pop(key, None)
        self.invalidated.append((scope, key))


async def handle_cache_invalidation_job(
    payload: CacheInvalidationPayload, *, backend: CacheBackend
) -> CacheInvalidationResult:
    """Job-shaped entry point (mirrors `indexing.py`'s
    `handle_indexing_job`). Idempotent by construction: invalidating an
    already-absent key is a no-op, so re-consuming the same
    cache_invalidation_event row is safe."""

    keys: list[str] = []
    for scope in payload.scopes:
        key = cache_key_for(
            scope, event_id=payload.event_id, exhibitor_id=payload.exhibitor_id
        )
        await backend.invalidate(scope=scope.value, key=key)
        keys.append(key)
    return CacheInvalidationResult(invalidated_keys=tuple(keys), reason=payload.reason)


# ---------------------------------------------------------------------------
# Job registration hook (for the integrator - same shape as
# document_parsing.py / indexing.py)
# ---------------------------------------------------------------------------


@runtime_checkable
class JobRegistry(Protocol):
    def register(self, name: str, handler: object) -> None: ...


def register_cache_invalidation_job(registry: JobRegistry) -> None:
    """Registration hook for the integrator - wiring a real registry/queue
    is out of this track's OWNED PATHS; the CacheBackend itself is now real
    (see module docstring)."""

    registry.register("cache_invalidation", handle_cache_invalidation_job)
