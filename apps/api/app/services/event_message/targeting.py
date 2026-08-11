"""Target-audience resolution for event messages - coarse segments only.

Query builders here are pure functions returning a ``sqlalchemy.Select`` (never executed
themselves) so tests can compile them to text and assert the WHERE clause without a live
Postgres - the same pattern ``app/services/notification/service.py`` and
``app/services/exhibitor_preference/service.py`` already use in this repo.

Segment definitions (task spec: "targeting restricted to coarse, legitimate segments only")
----------------------------------------------------------------------------------------------
- ALL_REGISTERED_USERS  - every user_profile row for the event with a real user_id (not a
  guest_session_id - guests have no durable identity to message, PROJECT_SCOPE.md's kiosk
  anonymity exclusion).
- PROFILE_UNCONFIRMED   - user_profile.profile_status == 'DRAFT' for the event. Deliberately
  excludes 'INACTIVE' (a withdrawn/inactive profile is not "hasn't confirmed yet", it is opted
  out - see app/models/profile.py's profile_status CHECK).
- RECOMMENDATION_READY  - user_profile.profile_status == 'COMPLETE'. Note: this is a proxy, not
  a join into matching.slate_result/recommendation_session - those tables key off
  recommendation_session_id, not profile_id directly, and are still under active development by
  another track in this wave (RISK-005/DECISION-005 territory). Coupling this track's targeting
  query to that evolving internal schema was judged higher regression risk than this proxy
  (Blocker Score < 7 - documented here, not escalated). Re-evaluate once matching exposes a
  stable "has a current slate" read path.
- BUYERS                - user_profile.user_type == 'BUYER'.
- EXHIBITOR_STAFF       - profile.user_role with role_code == 'EXHIBITOR', currently valid.
- SPECIFIC_ROLE         - profile.user_role with role_code == the caller-supplied
  ``target_role_code`` (one of the same 5 profile.role codes app/models/identity.py's Role
  CHECK allows), currently valid.

Every segment additionally requires profile.user_account.account_status == 'ACTIVE' and
deleted_at IS NULL - a suspended or withdrawn account is never a legitimate message target
regardless of which segment matched it.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Select, and_, func, or_, select

from app.models.consent import ConsentPolicy, UserConsent
from app.models.identity import Role, UserAccount, UserRole
from app.models.profile import UserProfile

#: Same purpose string app/services/notification/service.py's
#: NOTIFICATION_EMAIL_CONSENT_PURPOSE uses - re-declared rather than imported (that module is
#: BACKEND-NOTIFICATION-owned, not this track's; repo convention is to re-list rather than
#: cross-import between tracks' service modules, mirrors the schema-layer convention documented
#: in app/schemas/notification.py). Kept identical on purpose: the underlying consent record an
#: operator-authored EMAIL notice relies on is the same one system-generated EMAIL notifications
#: already rely on - there is only one "may we email you" consent in this product, not one per
#: notification-producing track.
EMAIL_CONSENT_PURPOSE = "NOTIFICATION_EMAIL"

#: Below this many resolved targets, the API layer must suppress the exact count (repo-wide
#: small-group suppression rule - see app/models/event_message.py module docstring and
#: app/schemas/event_message.py's EventMessagePreview).
SMALL_AUDIENCE_THRESHOLD = 5


class TargetSegmentNotAllowedError(ValueError):
    """Raised for any target_segment/target_role_code combination outside the fixed allowlist -
    the runtime guard behind the task spec's "attempt a disallowed fine-grained target and
    assert it is rejected" requirement. Raised for both "not a known segment at all" (e.g. an
    attempted sensitive-attribute or behavioral filter) and "SPECIFIC_ROLE without a role /
    non-SPECIFIC_ROLE with a role"."""


def validate_target_segment(target_segment: str, target_role_code: str | None) -> None:
    from app.models.event_message import (
        EVENT_MESSAGE_TARGET_ROLE_CODES,
        EVENT_MESSAGE_TARGET_SEGMENTS,
    )

    if target_segment not in EVENT_MESSAGE_TARGET_SEGMENTS:
        raise TargetSegmentNotAllowedError(
            f"허용되지 않은 대상 세그먼트입니다: {target_segment!r}. 세밀한 행동/속성 기반 "
            "타겟팅은 지원하지 않습니다."
        )
    if target_segment == "SPECIFIC_ROLE":
        if target_role_code not in EVENT_MESSAGE_TARGET_ROLE_CODES:
            raise TargetSegmentNotAllowedError(
                f"SPECIFIC_ROLE에는 유효한 role_code가 필요합니다: {target_role_code!r}"
            )
    elif target_role_code is not None:
        raise TargetSegmentNotAllowedError(
            "SPECIFIC_ROLE이 아닌 세그먼트에는 target_role_code를 지정할 수 없습니다."
        )


def _active_account_filter():
    return and_(UserAccount.account_status == "ACTIVE", UserAccount.deleted_at.is_(None))


def target_user_ids_stmt(
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    target_segment: str,
    target_role_code: str | None,
) -> Select:
    """Distinct resolved recipient user_ids for one segment. Always scoped to
    (tenant_id, event_id) and an active, non-deleted account."""

    validate_target_segment(target_segment, target_role_code)

    if target_segment in (
        "ALL_REGISTERED_USERS",
        "PROFILE_UNCONFIRMED",
        "RECOMMENDATION_READY",
        "BUYERS",
    ):
        stmt = (
            select(UserProfile.user_id)
            .join(UserAccount, UserAccount.user_id == UserProfile.user_id)
            .where(
                UserProfile.tenant_id == tenant_id,
                UserProfile.event_id == event_id,
                UserProfile.user_id.is_not(None),
                UserProfile.deleted_at.is_(None),
                _active_account_filter(),
            )
        )
        if target_segment == "PROFILE_UNCONFIRMED":
            stmt = stmt.where(UserProfile.profile_status == "DRAFT")
        elif target_segment == "RECOMMENDATION_READY":
            stmt = stmt.where(UserProfile.profile_status == "COMPLETE")
        elif target_segment == "BUYERS":
            stmt = stmt.where(UserProfile.user_type == "BUYER")
        return stmt.distinct()

    # EXHIBITOR_STAFF / SPECIFIC_ROLE - both resolve through profile.user_role, scoped to
    # currently-valid assignments (valid_until IS NULL) and either this event or a global
    # (event_id IS NULL) role assignment.
    role_code = "EXHIBITOR" if target_segment == "EXHIBITOR_STAFF" else target_role_code
    return (
        select(UserRole.user_id)
        .join(Role, Role.role_id == UserRole.role_id)
        .join(UserAccount, UserAccount.user_id == UserRole.user_id)
        .where(
            UserRole.tenant_id == tenant_id,
            or_(UserRole.event_id == event_id, UserRole.event_id.is_(None)),
            UserRole.valid_until.is_(None),
            Role.role_code == role_code,
            _active_account_filter(),
        )
        .distinct()
    )


def target_count_stmt(
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    target_segment: str,
    target_role_code: str | None,
) -> Select:
    subquery = target_user_ids_stmt(
        tenant_id=tenant_id,
        event_id=event_id,
        target_segment=target_segment,
        target_role_code=target_role_code,
    ).subquery()
    return select(func.count()).select_from(subquery)


def email_consent_excluded_user_ids_stmt(
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    target_segment: str,
    target_role_code: str | None,
    now: datetime,
) -> Select:
    """Among the resolved target audience, which user_ids lack a currently-effective, accepted
    NOTIFICATION_EMAIL consent (latest UserConsent row wins - consent history is append-only,
    per app/models/consent.py, so a later withdrawal correctly overrides an earlier grant).
    Only meaningful when the message's channels include EMAIL - callers must gate on that
    themselves (a message with only IN_APP has zero consent-excluded recipients, see
    app/models/event_message.py's EventMessageRecipient docstring). This is the single source
    of truth both the preview count and the publish-time per-recipient flag are built from -
    never reimplement this join elsewhere."""

    targets = target_user_ids_stmt(
        tenant_id=tenant_id,
        event_id=event_id,
        target_segment=target_segment,
        target_role_code=target_role_code,
    ).subquery()

    latest_consent = (
        select(
            UserConsent.user_id.label("user_id"),
            UserConsent.accepted.label("accepted"),
            func.row_number()
            .over(partition_by=UserConsent.user_id, order_by=UserConsent.occurred_at.desc())
            .label("rn"),
        )
        .join(ConsentPolicy, UserConsent.consent_policy_id == ConsentPolicy.consent_policy_id)
        .where(
            UserConsent.tenant_id == tenant_id,
            ConsentPolicy.purpose == EMAIL_CONSENT_PURPOSE,
            ConsentPolicy.effective_from <= now,
            or_(ConsentPolicy.effective_until.is_(None), ConsentPolicy.effective_until >= now),
        )
        .subquery()
    )
    latest_accepted = select(latest_consent.c.user_id).where(
        latest_consent.c.rn == 1, latest_consent.c.accepted.is_(True)
    )

    return select(targets.c.user_id).where(targets.c.user_id.notin_(latest_accepted))


def email_consent_excluded_count_stmt(
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    target_segment: str,
    target_role_code: str | None,
    now: datetime,
) -> Select:
    """Count form of ``email_consent_excluded_user_ids_stmt`` - see that function's docstring."""

    excluded = email_consent_excluded_user_ids_stmt(
        tenant_id=tenant_id,
        event_id=event_id,
        target_segment=target_segment,
        target_role_code=target_role_code,
        now=now,
    )
    return select(func.count()).select_from(excluded.subquery())


def duplicate_message_count_stmt(
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    message_type: str,
    exclude_event_message_id: uuid.UUID | None,
) -> Select:
    """How many *other* not-yet-completed/cancelled messages of the same type already exist for
    this event - the signal behind the "duplicate-target warning" (task spec: preview must show
    it). A second APPROVED/SCHEDULED/PUBLISHED message of the same operational type for the same
    event is very likely about to reach an overlapping audience twice."""

    from app.models.event_message import EventMessage

    stmt = select(func.count(EventMessage.event_message_id)).where(
        EventMessage.tenant_id == tenant_id,
        EventMessage.event_id == event_id,
        EventMessage.message_type == message_type,
        EventMessage.status.in_(("APPROVED", "SCHEDULED", "PUBLISHED")),
    )
    if exclude_event_message_id is not None:
        stmt = stmt.where(EventMessage.event_message_id != exclude_event_message_id)
    return stmt


def display_target_count(target_count: int) -> tuple[int | None, str, bool]:
    """(exact_count_or_none, display_string, small_audience_warning) - the one place that
    implements the repo-wide small-group suppression rule for this track's preview numbers.
    Never format ``target_count`` for an API response any other way."""

    if target_count < SMALL_AUDIENCE_THRESHOLD:
        return None, f"{SMALL_AUDIENCE_THRESHOLD}명 미만", True
    return target_count, f"{target_count:,}명", False
