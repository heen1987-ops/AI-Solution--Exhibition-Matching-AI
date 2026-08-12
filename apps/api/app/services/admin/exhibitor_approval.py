"""Exhibitor master-approval decision (approve/reject) - BACKEND-007.

Transitions ``exhibition.exhibitor.master_approval_status`` (``app/models/exhibitor.py``
``MASTER_APPROVAL_STATUSES`` = DRAFT/APPROVED/REJECTED - that model's own docstring: "업체
마스터 버전"의 검수상태). ``app/api/v1/routers/partner.py``'s submit flow
(``POST /partner/exhibitors/{id}/submit``) only ever writes ``ExhibitorProfile.approval_status``
(a separate, more granular 4-state field on the *profile*, not the master record) and that
router's own module docstring explicitly declines to own this operator-side decision ("28.7절
... 운영자(admin) 라우터 담당 에이전트의 몫이다"). This module is that missing counterpart.

No pre-existing state-transition helper or DB constraint governs which prior status may reach
which target (grepped every ``master_approval_status`` write site in the codebase: only this
exhibitor's own column default of ``DRAFT`` and this module write it; every other reference
found is a read-only ``== 'APPROVED'`` gate for public visibility, e.g.
``app/services/exhibition_public_repository.py``). The rule below is this module's own minimal,
defensible design, not a pre-existing contract:

* ``approve_exhibitor``: DRAFT or REJECTED -> APPROVED. A previously-rejected exhibitor that
  fixes the flagged problem can be approved directly on re-review, without a DB-level
  workaround forcing it back through DRAFT first.
* ``reject_exhibitor``: DRAFT or APPROVED -> REJECTED. An operator may also revoke a prior
  approval (e.g. a compliance problem surfaces after the fact).
* A call whose current status already equals its own target (approve-while-APPROVED,
  reject-while-REJECTED) is a conflict, not a silent no-op success - callers must not be able to
  double-decide undetected.

Concurrency: ``Exhibitor`` carries no ``row_version`` column (unlike ``Booth`` - see
``app/services/admin/booth_status.py``), so this module uses the *previously observed* status
itself as the optimistic-concurrency guard inside a single conditional
``UPDATE ... WHERE master_approval_status = <observed>``* - the same "condition lives inside the
UPDATE, never SELECT-then-blind-UPDATE" technique
``app/api/v1/routers/meetings.py::_reserve_slot`` already uses for availability-slot occupation.

Audit: every decision writes one ``audit.audit_log`` row (``app/models/consent.py::AuditLog`` -
the existing generic append-only audit table this repo already reuses for
``interaction.meeting`` decisions, see ``app/services/meeting/buyer_matching.py::_record_audit``;
no new audit table is introduced, per the task's own preference to reuse one if it exists).
``action_type`` is constrained by that table's CHECK constraint to
``('VIEW','CREATE','UPDATE','DELETE','EXPORT','APPROVE')``: approve uses the literal
``'APPROVE'``; reject (not a member of that enum) uses ``'UPDATE'`` and always carries the
required ``reason_code``, so the decision itself is still fully reconstructable from the row.
"""

from __future__ import annotations

import uuid

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consent import AuditLog
from app.models.exhibitor import Exhibitor

#: See module docstring - this module's own minimal transition rule, not a pre-existing one.
APPROVE_FROM_STATUSES: tuple[str, ...] = ("DRAFT", "REJECTED")
REJECT_FROM_STATUSES: tuple[str, ...] = ("DRAFT", "APPROVED")


class ExhibitorApprovalError(Exception):
    """Base class for this module's typed errors."""


class InvalidApprovalTransitionError(ExhibitorApprovalError):
    """The observed status cannot reach the requested target (includes already-decided)."""

    def __init__(self, *, current_status: str, target_status: str) -> None:
        self.current_status = current_status
        self.target_status = target_status
        super().__init__(
            f"cannot transition master_approval_status from {current_status} to {target_status}"
        )


class ApprovalRaceLostError(ExhibitorApprovalError):
    """Another request changed the row between this caller's read and its conditional UPDATE."""


async def _apply_transition(
    db: AsyncSession,
    exhibitor: Exhibitor,
    *,
    target_status: str,
    allowed_from: tuple[str, ...],
    actor_user_id: uuid.UUID,
    action_type: str,
    reason_code: str | None,
) -> Exhibitor:
    observed_status = exhibitor.master_approval_status
    if observed_status not in allowed_from:
        raise InvalidApprovalTransitionError(
            current_status=observed_status, target_status=target_status
        )

    stmt = (
        update(Exhibitor)
        .where(
            Exhibitor.exhibitor_id == exhibitor.exhibitor_id,
            Exhibitor.master_approval_status == observed_status,
        )
        .values(master_approval_status=target_status)
        .returning(Exhibitor)
    )
    result = await db.execute(stmt)
    updated = result.scalar_one_or_none()
    if updated is None:
        raise ApprovalRaceLostError(
            f"exhibitor {exhibitor.exhibitor_id} master_approval_status changed concurrently"
        )

    db.add(
        AuditLog(
            tenant_id=updated.tenant_id,
            actor_user_id=actor_user_id,
            actor_role="ADMIN",
            action_type=action_type,
            resource_type="exhibition.exhibitor",
            resource_id=updated.exhibitor_id,
            reason_code=reason_code,
        )
    )
    return updated


async def approve_exhibitor(
    db: AsyncSession,
    exhibitor: Exhibitor,
    *,
    actor_user_id: uuid.UUID,
    reason_code: str | None,
) -> Exhibitor:
    return await _apply_transition(
        db,
        exhibitor,
        target_status="APPROVED",
        allowed_from=APPROVE_FROM_STATUSES,
        actor_user_id=actor_user_id,
        action_type="APPROVE",
        reason_code=reason_code,
    )


async def reject_exhibitor(
    db: AsyncSession,
    exhibitor: Exhibitor,
    *,
    actor_user_id: uuid.UUID,
    reason_code: str,
) -> Exhibitor:
    return await _apply_transition(
        db,
        exhibitor,
        target_status="REJECTED",
        allowed_from=REJECT_FROM_STATUSES,
        actor_user_id=actor_user_id,
        action_type="UPDATE",
        reason_code=reason_code,
    )
