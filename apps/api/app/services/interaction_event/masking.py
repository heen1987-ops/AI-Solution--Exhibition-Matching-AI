"""Free-text and context sanitization for client-reported UI events (WAVE 2E).

Task requirement: before persisting any client free-text search query, mask phone numbers,
emails, resident-registration-number-shaped strings, and account-number-shaped strings;
enforce a length cap; strip control characters. The raw text must never touch storage - the
router/service only ever persists the output of :func:`mask_search_query`.

Masking is deliberately shape-based (regex), not validity-based: a string that merely *looks*
like an RRN or account number is masked even if its check digit would be invalid. False
positives cost a few masked search tokens; false negatives leak PII into an append-only,
partition-replicated analytics table. AGENTS.md: "Never write personal data into logs,
fixtures, or snapshots."

Ordering matters and is fixed inside :func:`mask_search_query`:
RRN (13-digit shaped) -> email -> phone -> grouped account numbers -> long bare digit runs.
Running phone before RRN would let "900101-1234567"'s tail be half-eaten by the phone rule and
leave the birthdate half exposed.
"""

from __future__ import annotations

import re
from typing import Any

#: Persisted length cap for the (already masked) search query. Shorter than the request-side
#: input cap (app/schemas/interaction_event.py: MAX_SEARCH_QUERY_INPUT_LENGTH = 500) so a
#: masked token expansion can never grow the stored value past this.
MASKED_SEARCH_QUERY_MAX_LENGTH = 200

MASK_RRN = "[RRN]"
MASK_EMAIL = "[EMAIL]"
MASK_PHONE = "[PHONE]"
MASK_ACCOUNT = "[ACCOUNT]"

#: C0 control chars + DEL. Tabs/newlines are control chars too - all collapse to a space.
_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]+")

#: Korean resident registration number shape: YYMMDD + optional separator + 7 digits whose
#: first digit is the century/sex marker 1-4. Covers both "900101-1234567" and bare
#: "9001011234567".
_RRN = re.compile(r"(?<!\d)\d{6}[-\s]?[1-4]\d{6}(?!\d)")

_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")

#: Korean phone shapes: optional +82 country prefix, mobile (010/011/016/017/018/019) and
#: area-code landlines (02, 031, ...), with -, ., or space separators or none.
_PHONE = re.compile(r"(?<!\d)(?:\+?82[-.\s]?)?0\d{1,2}[-.\s]?\d{3,4}[-.\s]?\d{4}(?!\d)")

#: Separator-grouped digit runs (bank account shaped, e.g. "110-234-567890"). Only masked when
#: the total digit count is >= _ACCOUNT_MIN_DIGITS (see _mask_grouped_account), so short
#: benign groups like dates ("2026-08-02", 8 digits) survive.
_GROUPED_DIGITS = re.compile(r"(?<!\d)\d{2,6}(?:[-\s]\d{2,6}){2,5}(?!\d)")
_ACCOUNT_MIN_DIGITS = 10

#: Bare unseparated digit run of 10+ (account/card shaped). RRN-shaped 13-digit runs were
#: already consumed by _RRN before this rule fires.
_LONG_DIGITS = re.compile(r"(?<!\d)\d{10,}(?!\d)")

_WHITESPACE = re.compile(r"\s+")


def _mask_grouped_account(match: re.Match[str]) -> str:
    digit_count = sum(ch.isdigit() for ch in match.group(0))
    return MASK_ACCOUNT if digit_count >= _ACCOUNT_MIN_DIGITS else match.group(0)


def mask_search_query(raw: str | None) -> str | None:
    """Return a persistence-safe version of a client free-text query (or ``None``)."""

    if raw is None:
        return None
    text = _CONTROL_CHARS.sub(" ", raw)
    text = _RRN.sub(MASK_RRN, text)
    text = _EMAIL.sub(MASK_EMAIL, text)
    text = _PHONE.sub(MASK_PHONE, text)
    text = _GROUPED_DIGITS.sub(_mask_grouped_account, text)
    text = _LONG_DIGITS.sub(MASK_ACCOUNT, text)
    text = _WHITESPACE.sub(" ", text).strip()
    text = text[:MASKED_SEARCH_QUERY_MAX_LENGTH].strip()
    return text or None


# ---------------------------------------------------------------------------
# Context allow-listing (same convention as recommendations.py::_sanitize_context - unknown
# keys are dropped, never rejected; only scalar values survive).
# ---------------------------------------------------------------------------

MAX_CONTEXT_VALUE_LENGTH = 200

#: Keys a client may report in ``context`` and have persisted. Everything else is dropped.
#: Deliberately contains no identity-shaped key (those are additionally hard-rejected for
#: kiosk traffic - app/services/interaction_event/validation.py).
ALLOWED_CONTEXT_KEYS = frozenset(
    {
        "source",
        "component",
        "variant",
        "reason_code",
        "network_state",
        "offline_replay",
        "position",
        "rank",
        "list_size",
        "result_count",
        "dwell_ms",
        "visible_ratio",
        "zone",
        "page",
        "filter_code",
        "sort_code",
        "referrer_screen",
    }
)


def sanitize_context(
    context: dict[str, Any] | None, *, extra: dict[str, Any] | None = None
) -> dict[str, Any] | None:
    """Allow-list client context and merge server-derived ``extra`` keys on top.

    ``extra`` is trusted (constructed by our own service - e.g. the masked search query,
    source, kiosk_id) and therefore wins over any client-supplied key of the same name.
    """

    sanitized: dict[str, Any] = {}
    for key, value in (context or {}).items():
        if key not in ALLOWED_CONTEXT_KEYS:
            continue
        if isinstance(value, str):
            if len(value) > MAX_CONTEXT_VALUE_LENGTH:
                continue
        elif not isinstance(value, bool | int | float) and value is not None:
            continue
        sanitized[key] = value
    for key, value in (extra or {}).items():
        if value is not None:
            sanitized[key] = value
    return sanitized or None
