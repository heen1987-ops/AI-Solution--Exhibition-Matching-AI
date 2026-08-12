"""Explicit, tested bridge between the two independent ``notification_type`` vocabularies.

Two live CHECK-constrained enums name overlapping real-world occurrences differently:

    - ``app.models.integration.NOTIFICATION_TYPES`` (schema ``integration``, the OUTBOUND
      Alimtalk -> SMS -> EMAIL provider fan-out driven by ``notification_delivery.py``)
    - ``app.models.notification.NOTIFICATION_TYPES`` (schema ``notification``, the INBOX
      in-app notification center driven by ``services/notification/service.py``)

Renaming either CHECK-constrained column's allowed values to force a shared vocabulary would
require a new migration on both already-migrated tables for no functional benefit (see
NOTIFY-002 in ``.harness/backlog.yaml`` and DECISION-024 in ``.harness/decisions.md``). Instead,
this module is the single documented translation table between them, imported by both
``services/notification/`` and ``notification_delivery.py`` so neither side has to guess at the
other's vocabulary.

This module transcribes (and is the executable, test-enforced version of) the mapping table that
previously lived only as prose in ``app/services/notification/__init__.py``'s module docstring.

Design rules
------------
1. ``OUTBOUND_TO_INBOX`` only contains a key when a genuine real-world correspondence exists.
   The value is a tuple because one outbound type can legitimately correspond to more than one
   inbox type (see MEETING_STATUS_CHANGED below) - callers must not assume a 1:1 mapping.
2. Every outbound type absent from ``OUTBOUND_TO_INBOX`` MUST appear in ``OUTBOUND_ONLY`` with a
   one-line reason - never silently omitted.
3. Every inbox type absent from the derived ``INBOX_TO_OUTBOUND`` MUST appear in ``INBOX_ONLY``
   with a one-line reason - never silently omitted.
4. ``test_notification_type_mapping.py`` asserts every value in both
   ``app.models.integration.NOTIFICATION_TYPES`` and ``app.models.notification.NOTIFICATION_TYPES``
   is accounted for by rule 2/3 - that test is the actual acceptance criterion ("a canonical
   type name across both pipelines, or an explicit documented translation table exists").
"""

from __future__ import annotations

from app.models.integration import NOTIFICATION_TYPES as OUTBOUND_NOTIFICATION_TYPES
from app.models.notification import NOTIFICATION_TYPES as INBOX_NOTIFICATION_TYPES

#: Outbound (integration.py) type -> tuple of corresponding inbox (notification.py) type(s).
#: Only listed here when a real-world correspondence exists; see module docstring rule 1.
OUTBOUND_TO_INBOX: dict[str, tuple[str, ...]] = {
    # Same occurrence, same name on both sides.
    "RECOMMENDATION_READY": ("RECOMMENDATION_READY",),
    # Same real-world occurrence (an event-starting-soon reminder), different anchor point in
    # the two designs (eve-of vs day-of) and different names. Not a coincidence - both fire off
    # the same "event is about to start" business trigger.
    "EVENT_EVE_REMINDER": ("EVENT_DAY_REMINDER",),
    # Granularity mismatch, not a lossy 1:1 synonym: the outbound side collapses every meeting
    # state transition into one generic type (distinguishing them only by template_code), while
    # the inbox side splits them into specific sub-events so a recipient's notification list
    # reads clearly. A single outbound MEETING_STATUS_CHANGED firing could correspond to either
    # inbox type - the caller must disambiguate by the actual sub-event that fired (mirrors
    # ``app/services/notification/__init__.py``'s documented bridge: both
    # ``notify_meeting_accepted`` and ``notify_meeting_time_proposed`` stamp
    # ``business_event_code="MEETING_STATUS_CHANGED"``, which is the outbound value). This
    # module intentionally does NOT force a lossy 1:1 rename here - both candidates are listed.
    "MEETING_STATUS_CHANGED": ("MEETING_ACCEPTED", "MEETING_TIME_PROPOSED"),
}

#: Outbound types with no inbox counterpart, and why. Rule 2.
OUTBOUND_ONLY: dict[str, str] = {
    "REGISTRATION_COMPLETED": (
        "Sent immediately at registration, before any in-app inbox session exists to hold a "
        "row for it; the inbox has no pre-registration recipient to address."
    ),
    "MEETING_IMMINENT": (
        "A last-minute 'starting very soon' nudge is only useful as an off-platform channel "
        "(Alimtalk/SMS/email) since the recipient is not assumed to have the app open; no "
        "inbox design exists for this occurrence."
    ),
    "POST_EVENT_SUMMARY": (
        "Sent after the event has already ended as a wrap-up email; the inbox surface has no "
        "design for post-event content."
    ),
}

#: Inbox types with no outbound counterpart, and why. Rule 3.
INBOX_ONLY: dict[str, str] = {
    "CONTENT_REVIEW_REQUESTED": (
        "Internal AI-extraction moderation workflow state, never sent off-platform."
    ),
    "CONTENT_REVIEW_RESULT": (
        "Internal AI-extraction moderation workflow state, never sent off-platform."
    ),
    "OPERATOR_NOTICE": (
        "Operator broadcast notices are in-app only in the current design; no off-platform "
        "channel/template is wired for them."
    ),
}


def _build_inbox_to_outbound(
    outbound_to_inbox: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    reverse: dict[str, list[str]] = {}
    for outbound_type, inbox_types in outbound_to_inbox.items():
        for inbox_type in inbox_types:
            reverse.setdefault(inbox_type, []).append(outbound_type)
    return {inbox_type: tuple(values) for inbox_type, values in reverse.items()}


#: Inbox (notification.py) type -> tuple of corresponding outbound (integration.py) type(s).
#: Derived from ``OUTBOUND_TO_INBOX`` so the two directions can never drift apart from each other.
INBOX_TO_OUTBOUND: dict[str, tuple[str, ...]] = _build_inbox_to_outbound(OUTBOUND_TO_INBOX)


def outbound_to_inbox_types(outbound_type: str) -> tuple[str, ...]:
    """Return the inbox type(s) corresponding to an outbound type, or ``()`` if one-sided."""

    return OUTBOUND_TO_INBOX.get(outbound_type, ())


def inbox_to_outbound_types(inbox_type: str) -> tuple[str, ...]:
    """Return the outbound type(s) corresponding to an inbox type, or ``()`` if one-sided."""

    return INBOX_TO_OUTBOUND.get(inbox_type, ())


def unmapped_outbound_types() -> frozenset[str]:
    """Outbound types accounted for by neither ``OUTBOUND_TO_INBOX`` nor ``OUTBOUND_ONLY``.

    Empty in a correct build - test_notification_type_mapping.py asserts this. Exposed as a
    function (rather than only a test) so callers/tooling can self-check at import/CI time too.
    """

    accounted_for = set(OUTBOUND_TO_INBOX) | set(OUTBOUND_ONLY)
    return frozenset(set(OUTBOUND_NOTIFICATION_TYPES) - accounted_for)


def unmapped_inbox_types() -> frozenset[str]:
    """Inbox types accounted for by neither ``INBOX_TO_OUTBOUND`` nor ``INBOX_ONLY``."""

    accounted_for = set(INBOX_TO_OUTBOUND) | set(INBOX_ONLY)
    return frozenset(set(INBOX_NOTIFICATION_TYPES) - accounted_for)


__all__ = [
    "INBOX_ONLY",
    "INBOX_TO_OUTBOUND",
    "OUTBOUND_ONLY",
    "OUTBOUND_TO_INBOX",
    "inbox_to_outbound_types",
    "outbound_to_inbox_types",
    "unmapped_inbox_types",
    "unmapped_outbound_types",
]
