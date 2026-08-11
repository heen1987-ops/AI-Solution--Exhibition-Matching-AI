"""Notification domain services - the IN-APP INBOX half of the notification surface.

See ``app/models/notification.py`` for the schema/design rationale and
``app/services/notification/service.py`` for the creation/dedup/frequency-cap/delivery pipeline.

Two notification pipelines exist in this repository, and they are COMPLEMENTARY
=============================================================================
This package (schema ``notification``) is the INBOUND, user-facing inbox: one row per
recipient per business event, with read state, a nulls-not-distinct dedup key, per-recipient
daily frequency caps, and an EMAIL channel gated on BOTH a per-type preference AND a
currently-effective ``NOTIFICATION_EMAIL`` consent.

``app/services/notification_delivery.py`` (schema ``integration``) is the OUTBOUND provider
fan-out: KAKAO_ALIMTALK -> SMS -> EMAIL, one row bound 1:1 to an
``identity.personal_access_link``, an AESGCM-encrypted access URL, a
``message_class = 'INFORMATIONAL'`` CHECK, and a SKIP LOCKED outbox drain with leases and
backoff. It has no inbox, no read state and no preferences; this package has no off-platform
channel. Neither replaces the other and neither shares a table with the other.

Reconciling the two notification_type vocabularies (CONTRACTS: do not let these drift)
--------------------------------------------------------------------------------------
The two halves name the same real-world occurrences differently. Until a single shared
vocabulary module exists (deliberately a FOLLOW-UP, not part of this port - renaming either
side today would break a live DB CHECK constraint on both
``integration.notification_delivery.notification_type`` and
``notification.notifications.notification_type``), this table IS the mapping. Any new value
added to either side must be added here at the same time.

    business occurrence          | INBOX notification_type   | OUTBOUND notification_type
                                 | (models/notification.py)  | (models/integration.py)
    -----------------------------+---------------------------+-----------------------------
    registration completed       | -- (no inbox row)         | REGISTRATION_COMPLETED
    recommendation batch ready   | RECOMMENDATION_READY      | RECOMMENDATION_READY   [same]
    reminder before/on event day | EVENT_DAY_REMINDER        | EVENT_EVE_REMINDER     [*1]
    meeting accepted             | MEETING_ACCEPTED          | MEETING_STATUS_CHANGED [*2]
    meeting time proposed        | MEETING_TIME_PROPOSED     | MEETING_STATUS_CHANGED [*2]
    meeting starting soon        | -- (no inbox row)         | MEETING_IMMINENT
    post-event summary           | -- (no inbox row)         | POST_EVENT_SUMMARY
    AI extraction awaiting review| CONTENT_REVIEW_REQUESTED  | -- (never sent off-platform)
    AI extraction decided        | CONTENT_REVIEW_RESULT     | -- (never sent off-platform)
    operator notice published    | OPERATOR_NOTICE           | -- (never sent off-platform)

    [*1] Same occurrence, different anchor point in the two designs (eve-of vs day-of). The
         inbox row is created by ``triggers.notify_event_day_reminder`` and versioned by the
         calendar date, so an eve-of and a day-of firing are distinct rows by construction.
    [*2] The outbound side collapses every meeting transition into one type and distinguishes
         them by template_code; the inbox side splits them so the recipient's list is
         readable. ``BusinessEvent.business_event_code`` is the bridge: both
         ``notify_meeting_accepted`` and ``notify_meeting_time_proposed`` stamp
         ``business_event_code='MEETING_STATUS_CHANGED'``, which is exactly the outbound
         value. ``source_business_event_code`` on the inbox row is therefore the join key for
         "was the user told about X?" across both pipelines - no translation table needed.

Two further contract rules that follow from CR-012 and apply to BOTH halves:
  - ``notification.notification_templates`` is INFORMATIONAL-only and must never carry raw
    contact values, exactly as ``integration.notification_delivery``'s
    ``message_class = 'INFORMATIONAL'`` CHECK enforces on the outbound side.
  - The outbound EMAIL channel must consult the same ``NOTIFICATION_EMAIL`` consent purpose
    this package already checks (``service.email_processing_basis_stmt``), or a user who
    withdrew consent keeps receiving mail on the outbound path.
"""

from __future__ import annotations

from app.services.notification.service import (
    BusinessEvent,
    InMemoryNotificationRepository,
    NotificationOutcome,
    NotificationService,
    SqlAlchemyNotificationRepository,
)

__all__ = [
    "BusinessEvent",
    "InMemoryNotificationRepository",
    "NotificationOutcome",
    "NotificationService",
    "SqlAlchemyNotificationRepository",
]
