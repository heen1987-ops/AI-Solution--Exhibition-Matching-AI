"""Shared persistence helpers for domain models."""

from __future__ import annotations

import secrets
import time
import uuid


def new_uuid7() -> uuid.UUID:
    """Return an RFC 9562 UUIDv7 using Unix milliseconds and secure randomness."""

    unix_ms = time.time_ns() // 1_000_000
    if unix_ms >= 1 << 48:
        raise OverflowError("Unix timestamp does not fit in a UUIDv7")

    value = unix_ms << 80
    value |= 0x7 << 76
    value |= secrets.randbits(12) << 64
    value |= 0b10 << 62
    value |= secrets.randbits(62)
    return uuid.UUID(int=value)
