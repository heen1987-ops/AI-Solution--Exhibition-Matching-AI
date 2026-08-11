"""indexing job.

Worker-side orchestration entry point for the four triggers the track GOAL
names: "On approve/publish/unpublish/visibility-change/document-delete:
create an indexing job, regenerate the relevant search document(s), and
invalidate the relevant caches."

Why this file has no SQLAlchemy import
-----------------------------------------
This module defines only the job payload shape, the trigger -> action mapping (pure,
independently testable), and a narrow `IndexingBackend` Protocol. The real DB-touching
regenerate/unpublish logic (querying `exhibition.*`/`document.*` and writing
`indexing.search_document`) lives in `apps/api/app/services/indexing/service.py`
(`regenerate_exhibitor_documents` / `unpublish_exhibitor_documents`). Since this worker
now imports `apps/api`'s `app` package directly for other jobs (see
`worker/jobs/notification_outbox.py`), the integrator's adapter implementing
`IndexingBackend` is free to call those service functions in-process; this module itself
stays a thin, dependency-free shim so its trigger -> action mapping remains testable with
zero setup, exactly as in the original standalone-worktree design.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Protocol, runtime_checkable


class IndexingTrigger(str, Enum):
    APPROVE = "APPROVE"
    PUBLISH = "PUBLISH"
    UNPUBLISH = "UNPUBLISH"
    VISIBILITY_CHANGE = "VISIBILITY_CHANGE"
    DOCUMENT_DELETE = "DOCUMENT_DELETE"
    MANUAL = "MANUAL"


#: Triggers that should regenerate the search documents - something may now
#: be visible that was not, or already-visible content changed.
_REGENERATE_TRIGGERS = frozenset(
    {
        IndexingTrigger.APPROVE,
        IndexingTrigger.PUBLISH,
        IndexingTrigger.VISIBILITY_CHANGE,
        IndexingTrigger.MANUAL,
    }
)
#: Triggers that should remove the search documents outright.
_UNPUBLISH_TRIGGERS = frozenset({IndexingTrigger.UNPUBLISH, IndexingTrigger.DOCUMENT_DELETE})


@dataclass(frozen=True)
class IndexingJobPayload:
    tenant_id: str
    event_id: str
    exhibitor_id: str
    trigger: IndexingTrigger
    requested_by_user_id: str | None = None


@dataclass(frozen=True)
class IndexingJobResult:
    indexing_job_id: str
    status: str
    action: str  # "REGENERATE" | "UNPUBLISH"


@runtime_checkable
class IndexingBackend(Protocol):
    """Structural boundary to the real DB-backed implementation.

    A conforming implementation adapts
    `apps/api/app/services/indexing/service.py`'s
    `regenerate_exhibitor_documents`/`unpublish_exhibitor_documents` to this
    dict-argument shape - see this module's own docstring for why that
    adaptation is left to the integrator rather than imported directly here.
    """

    async def regenerate(
        self,
        *,
        tenant_id: str,
        event_id: str,
        exhibitor_id: str,
        trigger: str,
        requested_by_user_id: str | None,
    ) -> IndexingJobResult: ...

    async def unpublish(
        self,
        *,
        tenant_id: str,
        event_id: str,
        exhibitor_id: str,
        trigger: str,
        requested_by_user_id: str | None,
    ) -> IndexingJobResult: ...


def action_for_trigger(trigger: IndexingTrigger) -> str:
    """Pure trigger -> action mapping, independently testable without a
    backend of any kind."""

    if trigger in _UNPUBLISH_TRIGGERS:
        return "UNPUBLISH"
    if trigger in _REGENERATE_TRIGGERS:
        return "REGENERATE"
    raise ValueError(f"unhandled indexing trigger: {trigger!r}")  # pragma: no cover - exhaustive enum


async def handle_indexing_job(
    payload: IndexingJobPayload, *, backend: IndexingBackend
) -> IndexingJobResult:
    """Job-shaped entry point (mirrors `document_parsing.py`'s
    `handle_parse_document_job` - the established pattern for this repo's
    worker jobs)."""

    action = action_for_trigger(payload.trigger)
    if action == "UNPUBLISH":
        return await backend.unpublish(
            tenant_id=payload.tenant_id,
            event_id=payload.event_id,
            exhibitor_id=payload.exhibitor_id,
            trigger=payload.trigger.value,
            requested_by_user_id=payload.requested_by_user_id,
        )
    return await backend.regenerate(
        tenant_id=payload.tenant_id,
        event_id=payload.event_id,
        exhibitor_id=payload.exhibitor_id,
        trigger=payload.trigger.value,
        requested_by_user_id=payload.requested_by_user_id,
    )


# ---------------------------------------------------------------------------
# Job registration hook (for the integrator - see document_parsing.py's
# identically-shaped hook for the established convention)
# ---------------------------------------------------------------------------


@runtime_checkable
class JobRegistry(Protocol):
    def register(self, name: str, handler: object) -> None: ...


def register_indexing_job(registry: JobRegistry) -> None:
    """Registration hook for the integrator - do not call this from within
    this track's own tests other than to check it does not raise; wiring a
    real registry/queue and a real IndexingBackend is out of this track's
    OWNED PATHS."""

    registry.register("indexing", handle_indexing_job)
