from __future__ import annotations

import base64
from types import SimpleNamespace
from uuid import uuid4

import pytest
from app.core.config import Settings
from app.services.auth_rate_limit import AuthLinkRateLimiter, AuthRateLimitUnavailable
from redis.exceptions import RedisError
from starlette.requests import Request


class _Pipeline:
    def __init__(self, counts: list[int] | None = None, error: bool = False) -> None:
        self.counts = counts or []
        self.error = error
        self.keys: list[str] = []

    def incr(self, key: str) -> None:
        self.keys.append(key)

    def expire(self, _key: str, _seconds: int) -> None:
        return None

    async def execute(self) -> list[object]:
        if self.error:
            raise RedisError("unavailable")
        result: list[object] = []
        for count in self.counts:
            result.extend([count, True])
        return result


def _settings() -> Settings:
    return Settings(
        SECRET_KEY="rate-limit-unit-test-secret",
        AUTH_TOKEN_PEPPER="rate-limit-independent-pepper",
        AUTH_ENCRYPTION_KEY_B64=base64.urlsafe_b64encode(b"r" * 32).decode(),
    )


def _request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/auth/magic-links/exchange",
            "headers": [],
            "client": ("203.0.113.10", 443),
        }
    )


@pytest.mark.asyncio
async def test_link_rate_limit_uses_only_derived_keys() -> None:
    pipeline = _Pipeline([1, 1])
    limiter = AuthLinkRateLimiter(
        SimpleNamespace(pipeline=lambda transaction: pipeline),  # type: ignore[arg-type]
        _settings(),
    )
    token_hmac = b"opaque-token-digest"

    assert await limiter.allow_initial(_request(), token_hmac) is True
    assert len(pipeline.keys) == 2
    assert all("203.0.113.10" not in key for key in pipeline.keys)
    assert all(token_hmac.hex() not in key for key in pipeline.keys)


@pytest.mark.asyncio
async def test_link_rate_limit_blocks_token_or_network_over_limit() -> None:
    settings = _settings()
    pipeline = _Pipeline([settings.AUTH_LINK_RATE_TOKEN_LIMIT + 1, 1])
    limiter = AuthLinkRateLimiter(
        SimpleNamespace(pipeline=lambda transaction: pipeline),  # type: ignore[arg-type]
        settings,
    )
    assert await limiter.allow_initial(_request(), b"digest") is False


@pytest.mark.asyncio
async def test_link_rate_limit_fails_closed_when_redis_is_unavailable() -> None:
    pipeline = _Pipeline(error=True)
    limiter = AuthLinkRateLimiter(
        SimpleNamespace(pipeline=lambda transaction: pipeline),  # type: ignore[arg-type]
        _settings(),
    )
    with pytest.raises(AuthRateLimitUnavailable):
        await limiter.allow_account(uuid4())
