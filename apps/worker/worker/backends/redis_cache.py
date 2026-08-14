"""Redis-backed `CacheBackend` (see `worker/jobs/cache_invalidation.py`'s Protocol).

Follows the exact `redis.asyncio.from_url(settings.REDIS_URL, ...)` pattern already used
in three places in `apps/api` (`app/api/v1/routers/kiosk.py`,
`app/services/search_sessions.py`, `app/services/auth_rate_limit.py`) - this is not a new
integration, just the fourth consumer of the same `REDIS_URL` setting the API has shipped
with since before this port (the standalone-worktree original's docstring claiming
"nothing consumes REDIS_URL" was already false against main at the time of the merge).
"""

from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from redis.asyncio import Redis, from_url

#: Namespaced so a cache flush of this prefix never collides with the search-session /
#: rate-limit keys the same Redis instance already holds (see search_sessions.py's
#: SEARCH_KEY_PREFIX / auth_rate_limit.py for the same "backju:<domain>:" convention).
CACHE_KEY_PREFIX = "backju:cache:"

#: No TTL is set on invalidation entries themselves (there is nothing to expire - deleting
#: a key IS the operation); this constant exists only for a future `RedisCacheBackend.set`
#: convenience method that a real cache-populating caller (not this worker) would use.
DEFAULT_TTL_SECONDS = 300


class RedisCacheBackend:
    """Real `CacheBackend` implementation: `invalidate` deletes the namespaced key."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def invalidate(self, *, scope: str, key: str) -> None:
        await self._redis.delete(f"{CACHE_KEY_PREFIX}{scope}:{key}")


@lru_cache
def get_redis_cache_backend() -> RedisCacheBackend:
    """Process-wide singleton, mirroring `search_sessions.get_search_session_store` and
    `auth_rate_limit`'s own `from_url(...)`-per-process convention."""

    settings = get_settings()
    redis = from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    return RedisCacheBackend(redis)
