"""DRAFT -> PREVIEWED -> APPROVED -> SCHEDULED/PUBLISHED -> COMPLETED workflow (+ CANCELLED).

Pure functions only (no DB access) so both ``app/services/event_message/service.py`` and this
module's own tests can exercise the state machine without a session. The admin frontend mirrors
this exact transition table client-side for fast UX feedback
(``apps/admin/features/event-message/logic.ts``) - the backend copy here is the authoritative
one; any drift is a bug in the frontend copy, never the other way around.
"""

from __future__ import annotations

EVENT_MESSAGE_STATUSES: tuple[str, ...] = (
    "DRAFT",
    "PREVIEWED",
    "APPROVED",
    "SCHEDULED",
    "PUBLISHED",
    "COMPLETED",
    "CANCELLED",
)

#: Allowed status -> {allowed next statuses}. PUBLISHED/COMPLETED/CANCELLED are the only exits
#: without a way back (a published message cannot be un-published - it may already have
#: reached recipients).
ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    "DRAFT": frozenset({"PREVIEWED"}),
    "PREVIEWED": frozenset({"DRAFT", "APPROVED"}),
    "APPROVED": frozenset({"DRAFT", "SCHEDULED", "PUBLISHED", "CANCELLED"}),
    "SCHEDULED": frozenset({"PUBLISHED", "CANCELLED"}),
    "PUBLISHED": frozenset({"COMPLETED"}),
    "COMPLETED": frozenset(),
    "CANCELLED": frozenset(),
}

#: Editing title/body/channels/target_segment/target_role_code/destination_screen while in one
#: of these statuses invalidates the stale preview snapshot and drops the message back to DRAFT
#: (module docstring of app/models/event_message.py's EventMessage.preview_target_count).
STATUSES_RESET_TO_DRAFT_ON_EDIT: frozenset[str] = frozenset({"PREVIEWED", "APPROVED"})

#: Statuses a message may still be edited from at all. PUBLISHED/COMPLETED/CANCELLED are
#: terminal-ish for content (a published message's content is frozen - the audience already
#: saw it, or will very soon; SCHEDULED must be cancelled and recreated rather than mutated in
#: place, since its preview snapshot was already approved for a specific scheduled instant).
EDITABLE_STATUSES: frozenset[str] = frozenset({"DRAFT", "PREVIEWED", "APPROVED"})


class InvalidTransitionError(ValueError):
    def __init__(self, from_status: str, to_status: str) -> None:
        super().__init__(f"{from_status} -> {to_status} 전이는 허용되지 않습니다.")
        self.from_status = from_status
        self.to_status = to_status


class NotEditableError(ValueError):
    def __init__(self, status: str) -> None:
        super().__init__(f"{status} 상태의 메시지는 수정할 수 없습니다.")
        self.status = status


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in ALLOWED_TRANSITIONS.get(from_status, frozenset())


def require_transition(from_status: str, to_status: str) -> None:
    if not can_transition(from_status, to_status):
        raise InvalidTransitionError(from_status, to_status)


def require_editable(status: str) -> None:
    if status not in EDITABLE_STATUSES:
        raise NotEditableError(status)


def status_after_edit(current_status: str) -> str:
    """The new status a content/targeting edit produces. Raises if the message is not
    editable at all (PUBLISHED/COMPLETED/CANCELLED/SCHEDULED)."""

    require_editable(current_status)
    if current_status in STATUSES_RESET_TO_DRAFT_ON_EDIT:
        return "DRAFT"
    return current_status
