"""Tests for the NOTIFY-002 outbound<->inbox notification_type translation table.

Acceptance criterion (see .harness/backlog.yaml NOTIFY-002 / .harness/decisions.md
DECISION-024): "RECOMMENDATION_READY and other shared events map to one canonical type name
across both pipelines, or an explicit documented translation table exists". This module's
completeness checks (every value in both live CHECK-constrained NOTIFICATION_TYPES tuples is
either mapped or explicitly listed as one-sided with a reason) are the executable form of that
translation table living up to its own claim.
"""

from __future__ import annotations

from app.models.integration import NOTIFICATION_TYPES as OUTBOUND_NOTIFICATION_TYPES
from app.models.notification import NOTIFICATION_TYPES as INBOX_NOTIFICATION_TYPES
from app.services.notification.type_mapping import (
    INBOX_ONLY,
    INBOX_TO_OUTBOUND,
    OUTBOUND_ONLY,
    OUTBOUND_TO_INBOX,
    inbox_to_outbound_types,
    outbound_to_inbox_types,
    unmapped_inbox_types,
    unmapped_outbound_types,
)


def test_every_outbound_type_is_mapped_or_explicitly_one_sided() -> None:
    assert unmapped_outbound_types() == frozenset()
    for outbound_type in OUTBOUND_NOTIFICATION_TYPES:
        in_mapping = outbound_type in OUTBOUND_TO_INBOX
        in_one_sided = outbound_type in OUTBOUND_ONLY
        assert in_mapping or in_one_sided, outbound_type
        # Never both - a type is either translated or explicitly one-sided, not ambiguous.
        assert not (in_mapping and in_one_sided), outbound_type


def test_every_inbox_type_is_mapped_or_explicitly_one_sided() -> None:
    assert unmapped_inbox_types() == frozenset()
    for inbox_type in INBOX_NOTIFICATION_TYPES:
        in_mapping = inbox_type in INBOX_TO_OUTBOUND
        in_one_sided = inbox_type in INBOX_ONLY
        assert in_mapping or in_one_sided, inbox_type
        assert not (in_mapping and in_one_sided), inbox_type


def test_one_sided_reasons_are_non_empty_strings() -> None:
    for reason in OUTBOUND_ONLY.values():
        assert isinstance(reason, str) and reason.strip()
    for reason in INBOX_ONLY.values():
        assert isinstance(reason, str) and reason.strip()


def test_mapping_targets_reference_only_real_enum_values() -> None:
    for outbound_type, inbox_types in OUTBOUND_TO_INBOX.items():
        assert outbound_type in OUTBOUND_NOTIFICATION_TYPES
        for inbox_type in inbox_types:
            assert inbox_type in INBOX_NOTIFICATION_TYPES
    for inbox_type, outbound_types in INBOX_TO_OUTBOUND.items():
        assert inbox_type in INBOX_NOTIFICATION_TYPES
        for outbound_type in outbound_types:
            assert outbound_type in OUTBOUND_NOTIFICATION_TYPES


def test_recommendation_ready_maps_to_itself() -> None:
    assert outbound_to_inbox_types("RECOMMENDATION_READY") == ("RECOMMENDATION_READY",)
    assert inbox_to_outbound_types("RECOMMENDATION_READY") == ("RECOMMENDATION_READY",)


def test_event_reminder_pair_is_mapped_despite_different_names() -> None:
    assert outbound_to_inbox_types("EVENT_EVE_REMINDER") == ("EVENT_DAY_REMINDER",)
    assert inbox_to_outbound_types("EVENT_DAY_REMINDER") == ("EVENT_EVE_REMINDER",)


def test_meeting_status_changed_maps_to_both_specific_sub_events() -> None:
    """Granularity mismatch, not a lossy 1:1 rename - the outbound generic type could
    correspond to either specific inbox sub-event; both are listed, neither is guessed at."""

    mapped = outbound_to_inbox_types("MEETING_STATUS_CHANGED")
    assert set(mapped) == {"MEETING_ACCEPTED", "MEETING_TIME_PROPOSED"}
    assert inbox_to_outbound_types("MEETING_ACCEPTED") == ("MEETING_STATUS_CHANGED",)
    assert inbox_to_outbound_types("MEETING_TIME_PROPOSED") == ("MEETING_STATUS_CHANGED",)


def test_unmapped_lookup_returns_empty_tuple() -> None:
    assert outbound_to_inbox_types("REGISTRATION_COMPLETED") == ()
    assert inbox_to_outbound_types("OPERATOR_NOTICE") == ()


def test_one_sided_types_match_expected_sets() -> None:
    assert set(OUTBOUND_ONLY) == {
        "REGISTRATION_COMPLETED",
        "MEETING_IMMINENT",
        "POST_EVENT_SUMMARY",
    }
    assert set(INBOX_ONLY) == {
        "CONTENT_REVIEW_REQUESTED",
        "CONTENT_REVIEW_RESULT",
        "OPERATOR_NOTICE",
    }
