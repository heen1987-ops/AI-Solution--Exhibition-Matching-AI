"""Per-item validation for client-reported UI events (WAVE 2E).

The batch contract keeps items as raw dicts (see ``ClientInteractionBatchRequest`` docstring)
so that one malformed item rejects only itself. This module owns that per-item validation:

- schema validation into ``ClientInteractionEventIn`` (best-effort ``client_event_id``
  recovery for error reporting),
- event-type allow-listing,
- occurred_at plausibility (stale / future clock skew),
- the kiosk identity-field hard ban.

Error text discipline: everything returned from here that can end up in a response body or in
the ``interaction.event_ingestion_failure`` ledger is an application-constructed summary -
field locations and error *types* only, never the offending client value (which could be an
unmasked free-text query or a smuggled identifier).
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import ValidationError

from app.schemas.interaction_event import (
    KIOSK_FORBIDDEN_CONTEXT_KEYS,
    ClientInteractionEventIn,
)

#: Offline kiosks/webapps are allowed to replay queued beacons for up to this long. Older
#: events are rejected (TIMESTAMP_OUT_OF_RANGE) - behaviour-learning jobs treat the event
#: stream as roughly time-ordered and a weeks-old replay would silently distort aggregates.
STALE_EVENT_MAX_AGE = timedelta(hours=72)

#: Tolerated client clock skew into the future. Anything further ahead is rejected.
FUTURE_EVENT_MAX_SKEW = timedelta(minutes=5)

_KEY_NORMALIZER = re.compile(r"[^a-z0-9]")

#: Normalized (lowercased, separator-stripped) forms of the forbidden kiosk identity keys, so
#: "user_id_hash", "userIdHash", "USER-ID-HASH" are all caught by the same entry.
_FORBIDDEN_KIOSK_KEYS_NORMALIZED = frozenset(
    _KEY_NORMALIZER.sub("", key.lower()) for key in KIOSK_FORBIDDEN_CONTEXT_KEYS
)


def _normalize_key(key: str) -> str:
    return _KEY_NORMALIZER.sub("", key.lower())


def find_forbidden_kiosk_keys(context: dict[str, Any] | None) -> list[str]:
    """Return context keys a KIOSK-sourced event is banned from carrying (any casing/style)."""

    if not context:
        return []
    return sorted(
        key for key in context if _normalize_key(key) in _FORBIDDEN_KIOSK_KEYS_NORMALIZED
    )


def recover_client_event_id(raw: dict[str, Any]) -> uuid.UUID | None:
    """Best-effort ``client_event_id`` extraction from a schema-invalid raw item."""

    value = raw.get("client_event_id")
    if isinstance(value, uuid.UUID):
        return value
    if isinstance(value, str):
        try:
            return uuid.UUID(value)
        except ValueError:
            return None
    return None


def safe_validation_summary(exc: ValidationError) -> str:
    """Field locations + pydantic error types only - never the client's input values."""

    parts = []
    for error in exc.errors(include_input=False, include_url=False)[:5]:
        location = ".".join(str(piece) for piece in error["loc"]) or "(root)"
        parts.append(f"{location}: {error['type']}")
    return "; ".join(parts)[:300]


def parse_client_event(
    raw: Any,
) -> tuple[ClientInteractionEventIn | None, uuid.UUID | None, str | None]:
    """Validate one raw batch item.

    Returns ``(event, client_event_id, error_summary)`` - exactly one of ``event`` /
    ``error_summary`` is non-None.
    """

    if not isinstance(raw, dict):
        return None, None, "(root): dict_type"
    try:
        event = ClientInteractionEventIn.model_validate(raw)
    except ValidationError as exc:
        return None, recover_client_event_id(raw), safe_validation_summary(exc)
    return event, event.client_event_id, None


def timestamp_out_of_range(occurred_at: datetime, *, now: datetime) -> str | None:
    """Return a safe reason summary when ``occurred_at`` is implausible, else ``None``."""

    reference = occurred_at
    if reference.tzinfo is None:
        # Naive timestamps are interpreted as UTC rather than rejected - offline kiosk
        # replays are the very traffic this endpoint exists for.
        reference = reference.replace(tzinfo=UTC)
    if reference < now - STALE_EVENT_MAX_AGE:
        return f"occurred_at older than {int(STALE_EVENT_MAX_AGE.total_seconds() // 3600)}h"
    if reference > now + FUTURE_EVENT_MAX_SKEW:
        return (
            "occurred_at more than "
            f"{int(FUTURE_EVENT_MAX_SKEW.total_seconds() // 60)}m in the future"
        )
    return None
