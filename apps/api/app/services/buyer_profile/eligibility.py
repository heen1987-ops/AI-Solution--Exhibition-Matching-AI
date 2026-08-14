"""Shared eligibility helper for other tracks (e.g. BACKEND-MEETING) to import.

Task spec: "verification_status permission matrix ... only VERIFIED (and LIMITED per policy)
can use full matching/meetings" / "UNVERIFIED blocked from meeting-eligible actions".
"""

from __future__ import annotations

from app.models.buyer_profile import (
    MEETING_ELIGIBLE_VERIFICATION_STATUSES,
    BuyerProfile,
)


def is_meeting_eligible(profile: BuyerProfile | None) -> bool:
    """Whether ``profile`` may use full matching/meeting-request features.

    ``None`` (no buyer profile on file yet, i.e. effectively UNVERIFIED) is not eligible.
    """

    if profile is None:
        return False
    return profile.verification_status in MEETING_ELIGIBLE_VERIFICATION_STATUSES
