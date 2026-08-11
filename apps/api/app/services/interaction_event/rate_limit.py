"""Lightweight in-process rate limiting for the client event-beacon endpoints (WAVE 2E).

Task note: "basic rate-limit behavior (can be a lightweight in-process check, does not need
real infra)". This is a per-process sliding-window counter keyed by the reporting subject
(kiosk device, profile/user/guest session, or anonymous fallback). It deliberately does NOT
pretend to be a distributed limiter - once Redis-backed infra exists (app/services/kiosk.py's
store shows the intended pattern), this module's ``check_rate_limit`` is the single seam to
swap.

Thread-safety: FastAPI may run sync deps in a threadpool; a plain lock keeps the deque
bookkeeping consistent. Memory: buckets are pruned on every hit and the whole registry is
capped - an attacker rotating keys cannot grow it without bound.
"""

from __future__ import annotations

import threading
import time
from collections import deque

#: Max beacon requests per subject key within the window. Generous for legitimate UI batching
#: (clients are expected to batch up to 50 events per request anyway).
RATE_LIMIT_MAX_REQUESTS = 30
RATE_LIMIT_WINDOW_SECONDS = 10.0

#: Hard cap on distinct tracked keys (oldest-emptied pruned opportunistically).
_MAX_TRACKED_KEYS = 10_000

_lock = threading.Lock()
_buckets: dict[str, deque[float]] = {}


def check_rate_limit(key: str, *, now: float | None = None) -> bool:
    """Record a hit for ``key`` and return ``True`` when it is within the limit."""

    timestamp = time.monotonic() if now is None else now
    cutoff = timestamp - RATE_LIMIT_WINDOW_SECONDS
    with _lock:
        bucket = _buckets.get(key)
        if bucket is None:
            if len(_buckets) >= _MAX_TRACKED_KEYS:
                for existing_key in [k for k, v in _buckets.items() if not v][:1000]:
                    del _buckets[existing_key]
            bucket = deque()
            _buckets[key] = bucket
        while bucket and bucket[0] <= cutoff:
            bucket.popleft()
        if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
            return False
        bucket.append(timestamp)
        return True


def reset_rate_limiter() -> None:
    """Test hook: drop all recorded hits."""

    with _lock:
        _buckets.clear()
