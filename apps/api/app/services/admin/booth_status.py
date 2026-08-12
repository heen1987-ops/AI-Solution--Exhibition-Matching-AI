"""Booth operating-status change - BACKEND-007.

Updates ``exhibition.booth.operating_status`` (and optionally ``congestion_level``/
``estimated_wait_minutes``) using the row's own ``row_version`` column
(``app/models/exhibitor.py::Booth`` - "row_version으로 낙관적 동시성을 제어한다") as the
optimistic-concurrency guard, and appends exactly one ``exhibition.booth_status_history`` row
per successful change (append-only audit trail - ``app/models/exhibitor.py::BoothStatusHistory``,
already defined by the model layer; this module does not invent a second mechanism).

Concurrency: a single conditional ``UPDATE ... WHERE row_version = <caller-supplied>`` - the
same "condition lives inside the UPDATE, never SELECT-then-blind-UPDATE" technique
``app/api/v1/routers/meetings.py::_reserve_slot`` already uses for availability-slot occupation.
A caller whose ``row_version`` no longer matches the current row gets a typed conflict, never a
silent overwrite of someone else's more recent change.
"""

from __future__ import annotations

import uuid

from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exhibitor import Booth, BoothStatusHistory


class BoothStatusError(Exception):
    """Base class for this module's typed errors."""


class BoothVersionConflictError(BoothStatusError):
    """The caller's row_version does not match the booth's current row_version."""


async def update_booth_status(
    db: AsyncSession,
    booth: Booth,
    *,
    operating_status: str,
    congestion_level: str | None,
    estimated_wait_minutes: int | None,
    expected_row_version: int,
    actor_user_id: uuid.UUID | None,
    reason_code: str | None,
) -> Booth:
    previous_status = booth.operating_status

    values: dict[str, object] = {
        "operating_status": operating_status,
        "row_version": Booth.row_version + 1,
        "status_observed_at": func.now(),
    }
    # Omitted (None) fields mean "leave unchanged" - a PATCH is a partial update, not a full
    # replace (schema docstring). Only an explicitly-supplied value overwrites the column.
    if congestion_level is not None:
        values["congestion_level"] = congestion_level
    if estimated_wait_minutes is not None:
        values["estimated_wait_minutes"] = estimated_wait_minutes

    stmt = (
        update(Booth)
        .where(
            Booth.booth_id == booth.booth_id,
            Booth.row_version == expected_row_version,
        )
        .values(**values)
        .returning(Booth)
    )
    result = await db.execute(stmt)
    updated = result.scalar_one_or_none()
    if updated is None:
        raise BoothVersionConflictError(
            f"booth {booth.booth_id} row_version conflict: expected={expected_row_version}"
        )

    db.add(
        BoothStatusHistory(
            booth_id=updated.booth_id,
            previous_status=previous_status,
            new_status=operating_status,
            changed_by_user_id=actor_user_id,
            reason_code=reason_code,
        )
    )
    return updated
