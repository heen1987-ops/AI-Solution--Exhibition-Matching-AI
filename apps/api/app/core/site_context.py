"""Signed subject-context contract for portable exhibition-site adapters.

The browser never receives the signing secret.  A trusted Backju/PHP, Netlify,
or other event-site BFF derives the current subject from its authenticated
session, signs these headers, and forwards them to the matching API.
"""

from __future__ import annotations

import hashlib
import hmac
import time
from collections.abc import Mapping
from dataclasses import dataclass

SIGNATURE_SCHEME = "v1"
SIGNATURE_TOLERANCE_SECONDS = 300
SIGNED_SUBJECT_HEADERS = (
    "x-tenant-id",
    "x-event-id",
    "x-profile-id",
    "x-visit-session-id",
    "x-user-id",
    "x-guest-session-id",
)


@dataclass(frozen=True)
class SiteContextVerification:
    valid: bool
    reason: str | None = None


def _canonical_payload(headers: Mapping[str, str], timestamp: str) -> bytes:
    lines = [timestamp]
    lines.extend(
        f"{name}:{headers.get(name, '').strip()}" for name in SIGNED_SUBJECT_HEADERS
    )
    return "\n".join(lines).encode("utf-8")


def sign_site_context(
    headers: Mapping[str, str], *, timestamp: int | str, secret: str
) -> str:
    """Create the value for ``X-Site-Context-Signature`` in a trusted BFF."""

    timestamp_text = str(timestamp)
    digest = hmac.new(
        secret.encode("utf-8"),
        _canonical_payload(headers, timestamp_text),
        hashlib.sha256,
    ).hexdigest()
    return f"{SIGNATURE_SCHEME}={digest}"


def verify_site_context(
    headers: Mapping[str, str],
    *,
    secret: str,
    now: float | None = None,
    tolerance_seconds: int = SIGNATURE_TOLERANCE_SECONDS,
) -> SiteContextVerification:
    timestamp = headers.get("x-site-context-timestamp")
    signature = headers.get("x-site-context-signature")
    if not timestamp:
        return SiteContextVerification(False, "MISSING_CONTEXT_TIMESTAMP")
    if not signature:
        return SiteContextVerification(False, "MISSING_CONTEXT_SIGNATURE")
    try:
        sent_at = int(timestamp)
    except ValueError:
        return SiteContextVerification(False, "INVALID_CONTEXT_TIMESTAMP")
    current = time.time() if now is None else now
    if abs(current - sent_at) > tolerance_seconds:
        return SiteContextVerification(False, "STALE_CONTEXT_SIGNATURE")
    expected = sign_site_context(headers, timestamp=timestamp, secret=secret)
    if not hmac.compare_digest(signature, expected):
        return SiteContextVerification(False, "CONTEXT_SIGNATURE_MISMATCH")
    return SiteContextVerification(True)
