"""Small-group suppression + defensive PII redaction for analytics output.

CONTRACTS-OPERATIONS' small-group/minority-group suppression rule (see this
track's worker prompt and PROJECT_SCOPE.md-adjacent operations contract):
"any aggregate with fewer than 5 underlying users must be suppressed or
shown as 'fewer than 5' rather than an exact number." This module is the
single place that rule is enforced, so every endpoint in
``app/api/v1/routers/analytics.py`` applies it the same way - server-side,
never delegated to the client.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Iterable
from typing import TypeVar

from app.schemas.analytics import SMALL_GROUP_SUPPRESSION_THRESHOLD, Metric

T = TypeVar("T")


def suppress_metric(
    value: float | None,
    underlying_count: int | None,
    *,
    threshold: int = SMALL_GROUP_SUPPRESSION_THRESHOLD,
) -> Metric:
    """Build a :class:`Metric`, masking ``value`` when the group behind it is
    small but nonzero.

    A *true* zero (``underlying_count in (0, None)``) is never suppressed -
    reporting "0 searches happened" does not re-identify anyone. Only
    ``0 < underlying_count < threshold`` triggers masking, per the rule's
    wording ("fewer than 5 underlying users").
    """

    count = underlying_count or 0
    if 0 < count < threshold:
        return Metric(value=None, suppressed=True)
    return Metric(value=value if value is not None else 0, suppressed=False)


def suppress_rate(
    numerator_value: float | None,
    numerator_underlying_count: int | None,
    denominator_value: float | None,
    denominator_underlying_count: int | None,
    *,
    threshold: int = SMALL_GROUP_SUPPRESSION_THRESHOLD,
) -> Metric:
    """Suppress a rate (e.g. no-result rate) whenever *either* side of the
    ratio is backed by a small group - a rate computed from a masked
    numerator or denominator would otherwise leak the masked figure back out
    (e.g. "no-result rate = 100%" with 1 search is as identifying as showing
    the raw count).
    """

    num_count = numerator_underlying_count or 0
    den_count = denominator_underlying_count or 0
    if 0 < num_count < threshold or 0 < den_count < threshold:
        return Metric(value=None, suppressed=True)
    if not denominator_value:
        return Metric(value=0, suppressed=False)
    return Metric(value=(numerator_value or 0) / denominator_value, suppressed=False)


def combine_rate(numerator: Metric, denominator: Metric) -> Metric:
    """Build a rate ``Metric`` from two already-aggregated ``Metric`` values
    (e.g. period totals rolled up from several ``analytics.daily_metric`` /
    ``analytics.funnel_metric`` rows in ``app/services/analytics/queries.py``).

    Unlike :func:`suppress_rate` (which derives suppression from raw
    underlying counts), this operates on values that are already suppressed
    or not - masking the rate whenever *either* side is masked, for the same
    "a rate computed from a masked figure re-derives the masked figure" reason
    ``suppress_rate`` documents. A zero, unsuppressed denominator yields a
    zero rate rather than a division error (no activity happened, which is a
    real, non-identifying zero - not a masked one).
    """

    if numerator.suppressed or denominator.suppressed:
        return Metric(value=None, suppressed=True)
    if not denominator.value:
        return Metric(value=0, suppressed=False)
    return Metric(value=(numerator.value or 0) / denominator.value, suppressed=False)


def drop_small_groups(
    rows: Iterable[T],
    *,
    underlying_count_of: Callable[[T], int | None],
    threshold: int = SMALL_GROUP_SUPPRESSION_THRESHOLD,
) -> list[T]:
    """Filter out list rows (e.g. top search queries, no-result queries) whose
    underlying distinct-user count is below the threshold.

    Row-level suppression drops the row entirely rather than nulling a field,
    because for a list of queries the *presence* of a rare, low-volume query
    text is itself the re-identifying signal - there is no non-identifying
    "masked row" to show in its place, unlike a single scalar KPI.
    """

    kept: list[T] = []
    for row in rows:
        count = underlying_count_of(row) or 0
        if count >= threshold:
            kept.append(row)
    return kept


# ---------------------------------------------------------------------------
# Defensive query-text redaction
# ---------------------------------------------------------------------------
#
# search_query_daily.query_masked is documented (tables.py) as already
# PII-masked upstream by whichever service writes search interaction events
# into the aggregate table. This is a *second*, independent redaction pass
# applied here regardless, so a regression in that upstream masking step
# cannot turn into a PII leak through this read-only reporting API - this
# track's prompt: "raw search text only shown when already PII-masked
# upstream, never raw."

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")
_PHONE_RE = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{2,4}\)?[-.\s]?\d{3,4}[-.\s]?\d{4}")
_KR_RRN_RE = re.compile(r"\d{6}[-\s]?[1-4]\d{6}")
_REDACTED = "[masked]"


def redact_query_text(text: str) -> str:
    """Defensively re-mask obvious PII patterns in an already-upstream-masked
    query string. Never raises; unmatched text passes through unchanged."""

    if not text:
        return text
    redacted = _KR_RRN_RE.sub(_REDACTED, text)
    redacted = _EMAIL_RE.sub(_REDACTED, redacted)
    redacted = _PHONE_RE.sub(_REDACTED, redacted)
    return redacted
