"""Typed errors for the buyer-profile service layer.

Kept separate from the router (``app/api/v1/routers/buyer_profile.py``) so the service
functions stay HTTP-agnostic and unit-testable on their own (mirrors
``app/services/matching/errors.py``'s ``RecommendationError`` split from its router).
"""

from __future__ import annotations


class BuyerProfileServiceError(Exception):
    """Base class for buyer-profile service errors."""


class UnknownOntologyCodeError(BuyerProfileServiceError):
    """Raised when a code in one of the ontology-validated list fields isn't in the catalog."""

    def __init__(self, field: str, code: str) -> None:
        self.field = field
        self.code = code
        super().__init__(f"unknown ontology code for {field}: {code}")


class VersionConflictError(BuyerProfileServiceError):
    """Raised when the caller's ``version`` doesn't match the current row (optimistic lock)."""

    def __init__(self, expected: int, actual: int) -> None:
        self.expected = expected
        self.actual = actual
        super().__init__(f"version conflict: request had {expected}, current is {actual}")


class InvalidVerificationStatusError(BuyerProfileServiceError):
    """Raised by the operator-only verification path for an unknown target status."""

    def __init__(self, status_value: str) -> None:
        self.status_value = status_value
        super().__init__(f"unknown verification_status: {status_value}")
