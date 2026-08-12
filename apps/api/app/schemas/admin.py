"""Admin exhibitor-approval + booth operating-status API contract - BACKEND-007.

Model reference: ``app/models/exhibitor.py`` (``Exhibitor.master_approval_status`` /
``Booth.operating_status``/``congestion_level``/``estimated_wait_minutes``/``row_version``).
Literal value lists are re-declared here rather than imported from the model module, following
this repo's established "schema layer re-lists values instead of importing another layer's
module" convention (see ``app/schemas/event_message.py``'s own docstring for the identical
choice) - ``tests/test_admin_api.py`` asserts these stay in sync with the model's tuples.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

MasterApprovalStatus = Literal["DRAFT", "APPROVED", "REJECTED"]

#: Bounded reason codes for a REJECT decision. This repo's own precedent for a negative-decision
#: reason is a short bounded code, not open free text (see ``app/models/meeting.py``
#: ``MEETING_REJECT_REASON_CODES`` / ``PartnerDecisionRequest.reason_code``). This set is
#: exhibitor-approval-specific - the meeting one is about consultation slots, not applicable
#: here - and is stored as-is in ``audit.audit_log.reason_code`` (``VARCHAR(50)``, see
#: ``app/services/admin/exhibitor_approval.py``).
EXHIBITOR_REJECT_REASON_CODES: tuple[str, ...] = (
    "INCOMPLETE_INFORMATION",
    "DUPLICATE_REGISTRATION",
    "BUSINESS_VERIFICATION_FAILED",
    "POLICY_VIOLATION",
    "DATA_QUALITY_ISSUE",
    "OTHER",
)

ExhibitorRejectReasonCode = Literal[
    "INCOMPLETE_INFORMATION",
    "DUPLICATE_REGISTRATION",
    "BUSINESS_VERIFICATION_FAILED",
    "POLICY_VIOLATION",
    "DATA_QUALITY_ISSUE",
    "OTHER",
]


# ---------------------------------------------------------------------------
# POST /admin/exhibitors/{exhibitor_id}/approve
# ---------------------------------------------------------------------------


class ExhibitorApproveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Optional operator note - unlike REJECT, a positive decision does not require one.
    reason_code: str | None = Field(default=None, max_length=50)


# ---------------------------------------------------------------------------
# POST /admin/exhibitors/{exhibitor_id}/reject
# ---------------------------------------------------------------------------


class ExhibitorRejectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    #: Required - rejecting a business with no stated reason is a real ops problem (task spec).
    reason_code: ExhibitorRejectReasonCode


class ExhibitorApprovalDecisionResponse(BaseModel):
    exhibitor_id: UUID
    previous_status: MasterApprovalStatus
    master_approval_status: MasterApprovalStatus
    decided_by_user_id: UUID
    decided_at: datetime


# ---------------------------------------------------------------------------
# PATCH /admin/booths/{booth_id}/status
# ---------------------------------------------------------------------------

BoothOperatingStatus = Literal["OPEN", "PAUSED", "CLOSED"]
BoothCongestionLevel = Literal["LOW", "MEDIUM", "HIGH", "UNKNOWN"]


class BoothStatusUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operating_status: BoothOperatingStatus
    #: Omitted (None) means "leave unchanged" - only an explicit value overwrites the row.
    congestion_level: BoothCongestionLevel | None = None
    estimated_wait_minutes: int | None = Field(default=None, ge=0)
    #: Optimistic-concurrency guard - the caller's last-known row_version (model docstring:
    #: "row_version으로 낙관적 동시성을 제어한다"). A mismatch is a 409, never a blind overwrite.
    row_version: int = Field(ge=1)
    reason_code: str | None = Field(default=None, max_length=50)


class BoothStatusResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    booth_id: UUID
    operating_status: BoothOperatingStatus
    congestion_level: BoothCongestionLevel
    estimated_wait_minutes: int | None
    status_observed_at: datetime | None
    row_version: int
    updated_at: datetime
