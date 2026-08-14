"""Operator-only verification_status mutation path.

The buyer-facing router (``app/api/v1/routers/buyer_profile.py``) never imports this module and
its request schema (``app/schemas/buyer_profile.py``'s ``BuyerProfilePatchRequest``) has no
``verification_status`` field at all, so a buyer has no way to reach this function through
``/me/buyer-profile``. This is the intended integration point for the ADMIN-BUYER track: call
``set_verification_status`` from its own operator-authenticated router after loading the row
(ideally with ``SELECT ... FOR UPDATE`` to serialize concurrent operator decisions, the same
pattern ``app/api/v1/routers/meetings.py`` uses for ``meeting`` state transitions) and commit the
session there - this function does not commit.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from app.models.buyer_profile import VERIFICATION_STATUSES, BuyerProfile
from app.services.buyer_profile.errors import InvalidVerificationStatusError


def set_verification_status(
    buyer_profile: BuyerProfile,
    *,
    new_status: str,
    operator_user_id: uuid.UUID,
    reason: str | None = None,
) -> BuyerProfile:
    """Mutate ``buyer_profile.verification_status`` and its operator-attribution columns.

    Any status in ``VERIFICATION_STATUSES`` is accepted as a target (the task spec does not
    define a restricted transition graph beyond "buyer cannot change this themselves, only an
    operator-only mutation path can"); the ADMIN-BUYER track's own router is the place to layer
    a stricter state machine if its design calls for one. Does not flush/commit - caller's
    responsibility, matching every other write helper in ``app/services/matching/*``.
    """

    if new_status not in VERIFICATION_STATUSES:
        raise InvalidVerificationStatusError(new_status)

    buyer_profile.verification_status = new_status
    buyer_profile.verification_reason = reason
    buyer_profile.verification_reviewed_by_user_id = operator_user_id
    buyer_profile.verification_reviewed_at = datetime.now(UTC)
    buyer_profile.version += 1
    return buyer_profile
