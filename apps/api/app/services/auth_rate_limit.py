"""Distributed, privacy-minimized personal-link exchange rate limits."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Request
from redis.asyncio import Redis, from_url
from redis.exceptions import RedisError

from app.core.auth import digest_secret
from app.core.config import Settings, get_settings

KEY_PREFIX = "meet-ai:auth-link-rate:v1"


class AuthRateLimitUnavailable(RuntimeError):
    """The distributed limiter could not make a reliable decision."""


class AuthLinkRateLimiter:
    def __init__(self, redis: Redis, settings: Settings) -> None:
        self._redis = redis
        self._settings = settings

    def _key(self, dimension: str, value: str | bytes) -> str:
        digest = digest_secret(
            value, purpose=f"auth-link-rate-{dimension}", settings=self._settings
        ).hex()
        return f"{KEY_PREFIX}:{dimension}:{digest}"

    async def _allow(self, limits: list[tuple[str, int]]) -> bool:
        pipeline = self._redis.pipeline(transaction=True)
        for key, _limit in limits:
            pipeline.incr(key)
            pipeline.expire(key, self._settings.AUTH_LINK_RATE_WINDOW_SECONDS)
        try:
            results = await pipeline.execute()
        except RedisError as exc:
            raise AuthRateLimitUnavailable from exc
        counts = [int(results[index]) for index in range(0, len(results), 2)]
        return all(count <= limit for count, (_key, limit) in zip(counts, limits))

    async def allow_initial(self, request: Request, token_hmac: bytes) -> bool:
        network = request.client.host if request.client else "unknown"
        return await self._allow(
            [
                (
                    self._key("token", token_hmac),
                    self._settings.AUTH_LINK_RATE_TOKEN_LIMIT,
                ),
                (
                    self._key("network", network),
                    self._settings.AUTH_LINK_RATE_NETWORK_LIMIT,
                ),
            ]
        )

    async def allow_account(self, user_id: UUID) -> bool:
        return await self._allow(
            [
                (
                    self._key("account", user_id.bytes),
                    self._settings.AUTH_LINK_RATE_ACCOUNT_LIMIT,
                )
            ]
        )


async def get_auth_link_rate_limiter(
    settings: Annotated[Settings, Depends(get_settings)],
) -> AsyncIterator[AuthLinkRateLimiter]:
    redis = from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    try:
        yield AuthLinkRateLimiter(redis, settings)
    finally:
        await redis.aclose()
