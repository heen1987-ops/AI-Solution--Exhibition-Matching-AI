"""Buyer-profile domain services (WAVE2C BACKEND-BUYER-PROFILE).

Public surface other tracks are expected to import:
    - ``eligibility.is_meeting_eligible`` - BACKEND-MEETING gates meeting-request actions on this.
    - ``verification.set_verification_status`` - ADMIN-BUYER's operator-only mutation path.

``service`` holds the buyer-facing CRUD/validation logic used by
``app/api/v1/routers/buyer_profile.py`` and is exported here mainly so tests can
``monkeypatch.setattr(service, "...")`` the way ``tests/test_exhibition_public_api.py`` does for
its own ``service`` module.
"""

from __future__ import annotations

from app.services.buyer_profile import eligibility, service, verification
from app.services.buyer_profile.eligibility import is_meeting_eligible
from app.services.buyer_profile.verification import set_verification_status

__all__ = [
    "eligibility",
    "is_meeting_eligible",
    "service",
    "set_verification_status",
    "verification",
]
