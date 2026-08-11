"""Typed errors for the extraction/review service layer.

Kept HTTP-agnostic so the service functions stay unit-testable without a FastAPI request
context (mirrors ``app/services/buyer_profile/errors.py``). The router
(``app/api/v1/routers/extraction.py``) is the only place these get mapped to HTTP responses.
"""

from __future__ import annotations


class ExtractionServiceError(Exception):
    """Base class for extraction/review service errors."""

    code = "EXTRACTION_ERROR"


class ExtractionNotFoundError(ExtractionServiceError):
    code = "EXTRACTION_NOT_FOUND"

    def __init__(self, extraction_id: object) -> None:
        self.extraction_id = extraction_id
        super().__init__(f"extraction not found: {extraction_id}")


class DocumentNotFoundError(ExtractionServiceError):
    code = "DOCUMENT_NOT_FOUND"

    def __init__(self, document_id: object) -> None:
        self.document_id = document_id
        super().__init__(f"document not found: {document_id}")


class ReviewRequestNotFoundError(ExtractionServiceError):
    code = "REVIEW_REQUEST_NOT_FOUND"

    def __init__(self, review_request_id: object) -> None:
        self.review_request_id = review_request_id
        super().__init__(f"review request not found: {review_request_id}")


class InvalidTransitionError(ExtractionServiceError):
    """Raised when a caller attempts a review-status transition not allowed by
    ``.harness/contracts/document-structuring.md`` §3's transition table."""

    code = "INVALID_REVIEW_TRANSITION"

    def __init__(self, *, current_status: str, attempted: str) -> None:
        self.current_status = current_status
        self.attempted = attempted
        super().__init__(f"cannot move {current_status!r} -> {attempted!r}")


class UnknownOntologyCodeError(ExtractionServiceError):
    code = "INVALID_ONTOLOGY_CODE"

    def __init__(self, concept_code: str) -> None:
        self.concept_code = concept_code
        super().__init__(f"unknown ontology concept code: {concept_code}")


class SubmitReviewValidationError(ExtractionServiceError):
    """Raised by ``submit_for_review`` when one or more attributes are not yet dispositioned,
    have unresolved conflicts, are missing required evidence, have no visibility set, or leave
    a critical trade-condition UNKNOWN unacknowledged (WAVE2D-CONTRACTS §9)."""

    code = "EXTRACTIONS_PENDING_REVIEW"

    def __init__(self, checks: list[dict]) -> None:
        self.checks = checks
        super().__init__(f"{len(checks)} attribute(s) failed submit-review validation")
