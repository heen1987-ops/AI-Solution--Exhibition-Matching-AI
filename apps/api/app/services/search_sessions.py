"""Short-lived anonymous search-session persistence in Redis."""

from __future__ import annotations

import uuid
from functools import lru_cache

from pydantic import BaseModel
from redis.asyncio import Redis, from_url

from app.core.config import get_settings
from app.schemas.search import SearchResponse

SEARCH_KEY_PREFIX = "backju:search:session:"


class SearchSessionRecord(BaseModel):
    response: SearchResponse
    event_id: uuid.UUID
    query: str
    category_codes: list[str]


class SearchSessionStore:
    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def save(self, record: SearchSessionRecord, ttl_seconds: int) -> None:
        await self._redis.set(
            f"{SEARCH_KEY_PREFIX}{record.response.search_session_id}",
            record.model_dump_json(),
            ex=ttl_seconds,
        )

    async def get(self, search_session_id: uuid.UUID) -> SearchSessionRecord | None:
        value = await self._redis.get(f"{SEARCH_KEY_PREFIX}{search_session_id}")
        return SearchSessionRecord.model_validate_json(value) if value is not None else None


@lru_cache
def get_search_session_store() -> SearchSessionStore:
    settings = get_settings()
    redis = from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    return SearchSessionStore(redis)
