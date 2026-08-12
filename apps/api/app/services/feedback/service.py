"""``POST /feedback`` service layer (BACKEND-017).

Scope: this package owns everything behind ``app/api/v1/routers/feedback.py``. The model
(``app/models/feedback.py`` - read its module docstring first) and this file were built
together in the same task; see that module's "Scope note" for why.

Identity resolution reuses checkin.py's exact pattern, it does not reinvent one
--------------------------------------------------------------------------------------------
Per this task's spec: "visit_session-scoped, same as check-in - reuse whatever identity/
visit_session resolution pattern checkin.py already established". :func:`submit_feedback` below
imports and calls ``app.services.checkin.service.resolve_active_visit_session_id`` directly
(same owner-derived-ACTIVE-preferred-over-PLANNED lookup) and re-raises the exact same
``VisitSessionNotFoundError`` type that module defines, rather than declaring a second,
near-identical exception class - a caller (the router) already knows how to translate that one
error into a 404.

Target resolution reuses favorites' exact helper, it does not reinvent one either
--------------------------------------------------------------------------------------------
Per this task's spec: "find and reuse whichever of those two tracks' resolution helper is
cleanest to reuse or mirror". ``app.services.favorite.service.resolve_recommendable_id`` is the
cleaner of the two candidates (BACKEND-016's own ``verify_booth_qr`` resolves a *QR token* to a
booth, an unrelated concept; the favorites helper's ``(object_type, object_id) ->
recommendable_id`` signature is exactly what this endpoint's ``FeedbackRequest`` needs) and is
imported directly rather than copy-pasted a third time.

match_result_id is soft-validated - unresolvable never blocks the write
--------------------------------------------------------------------------------------------
Identical rationale to ``app.services.checkin.service.submit_check_in``: the feedback record
itself is the important side effect. Contrast
``app.services.favorite.service.create_favorite``, which hard-rejects an unresolvable
match_result_id - favorites are meant to be precisely re-derivable from a specific
recommendation click, whereas feedback's own wire contract only carries match_result_id as
optional lineage.

comment encryption reuses app/core/auth.py's AEAD envelope, mirroring
app/services/meeting/buyer_matching.py's thin-wrapper shape
--------------------------------------------------------------------------------------------
See ``app/models/feedback.py``'s "comment is stored encrypted" section for the full rationale.
:func:`encrypt_comment`/:func:`decrypt_comment` below are the same shape as
``encrypt_meeting_text``/``decrypt_meeting_text`` (fail-closed: a decrypt of corrupt/foreign-
purpose/legacy-plaintext data returns ``None`` rather than raising or leaking bytes). No route in
this task's scope calls :func:`decrypt_comment` - there is no GET/read endpoint for feedback yet
- but it is exercised directly by ``tests/test_feedback_model.py`` to prove the round-trip and
that a comment is genuinely never persisted as plaintext.

Idempotency-Key: reuses integration.idempotency_record, mirrors checkin.py's mechanism
--------------------------------------------------------------------------------------------
docs/frontend-backend-ai-interface-spec.md §11: check-in and feedback both support offline-queue
resend. This mirrors ``app.services.checkin.service.submit_check_in``'s
``principal_fingerprint`` + fixed ``route="/feedback"`` + caller-supplied key lookup exactly. One
deliberate simplification versus check-in: ``FeedbackResponse`` (unlike ``CheckInResponse``) has
no ``duplicate`` boolean to reconstruct on replay, so every ``IdempotencyRecord`` this module
writes uses a single fixed ``response_status`` (``_STATUS_CREATED``) - there is no second status
value to distinguish, unlike check-in's 200-vs-201 split.

``client_event_id``'s own partial-unique index (see the model's docstring) is a second,
independent safety net for the race window where two concurrent requests share the same
``client_event_id`` but arrive without (or with different) Idempotency-Key values - see
:func:`submit_feedback`'s ``except IntegrityError`` branch, which mirrors
``app.services.favorite.service.create_favorite``'s "pre-check, then re-query on the
race-window IntegrityError" shape.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime

from cryptography.exceptions import InvalidTag
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import decrypt_secret, encrypt_secret
from app.core.config import Settings
from app.core.security import compute_principal_fingerprint
from app.models.feedback import Feedback
from app.models.integration import IdempotencyRecord
from app.models.matching import MatchResult
from app.services.checkin.service import (
    VisitSessionNotFoundError,
    resolve_active_visit_session_id,
)
from app.services.favorite.service import FavoriteObjectType, resolve_recommendable_id

__all__ = [
    "COMMENT_ENCRYPTION_PURPOSE",
    "FeedbackTargetNotFoundError",
    "VisitSessionNotFoundError",
    "decrypt_comment",
    "encrypt_comment",
    "find_feedback_by_client_event_id",
    "resolve_active_visit_session_id",
    "resolve_recommendable_id",
    "submit_feedback",
]

#: AEAD purpose tag for the encrypted comment column - see app/models/feedback.py's docstring
#: for why a distinct purpose tag is required (never shared with meeting/identity purposes).
COMMENT_ENCRYPTION_PURPOSE = "feedback-comment"

#: integration.idempotency_record scoping for this route (mirrors checkin.py's own constants).
IDEMPOTENCY_METHOD = "POST"
IDEMPOTENCY_ROUTE = "/feedback"

#: Single fixed response_status - see module docstring "deliberate simplification" note.
_STATUS_CREATED = 201


class FeedbackTargetNotFoundError(Exception):
    """The caller-supplied (object_type, object_id) does not resolve to a recommendable target
    in this tenant/event."""


@dataclass(frozen=True)
class SubmittedFeedback:
    feedback: Feedback
    #: True only when an Idempotency-Key replay returned a prior row instead of inserting a new
    #: one - the router does not currently surface this (FeedbackResponse has no field for it),
    #: but the service layer still reports it accurately for tests/observability.
    replayed: bool


def encrypt_comment(value: str | None, *, settings: Settings) -> bytes | None:
    if value is None:
        return None
    return encrypt_secret(value, purpose=COMMENT_ENCRYPTION_PURPOSE, settings=settings)


def decrypt_comment(value: bytes | None, *, settings: Settings) -> str | None:
    if value is None:
        return None
    try:
        return decrypt_secret(
            value, purpose=COMMENT_ENCRYPTION_PURPOSE, settings=settings
        ).decode("utf-8")
    except (InvalidTag, ValueError, UnicodeDecodeError):
        # Fail closed: legacy/plaintext/corrupt/wrong-purpose data must never be echoed.
        return None


async def find_feedback_by_client_event_id(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    client_event_id: uuid.UUID,
) -> Feedback | None:
    return await db.scalar(
        select(Feedback).where(
            Feedback.tenant_id == tenant_id,
            Feedback.event_id == event_id,
            Feedback.client_event_id == client_event_id,
        )
    )


async def _find_idempotency_record(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    principal_fingerprint: bytes,
    idempotency_key: str,
) -> IdempotencyRecord | None:
    return await db.scalar(
        select(IdempotencyRecord).where(
            IdempotencyRecord.tenant_id == tenant_id,
            IdempotencyRecord.principal_fingerprint == principal_fingerprint,
            IdempotencyRecord.method == IDEMPOTENCY_METHOD,
            IdempotencyRecord.route == IDEMPOTENCY_ROUTE,
            IdempotencyRecord.idempotency_key == idempotency_key,
        )
    )


async def _replay_from_record(
    db: AsyncSession, record: IdempotencyRecord | None
) -> Feedback | None:
    if record is None or record.response_reference is None:
        return None
    return await db.get(Feedback, record.response_reference)


async def submit_feedback(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    user_id: uuid.UUID | None,
    guest_session_id: uuid.UUID | None,
    object_type: FavoriteObjectType,
    object_id: uuid.UUID,
    match_result_id: uuid.UUID | None,
    rating: str,
    positive_reasons: list[str],
    negative_reasons: list[str],
    comment: str | None,
    client_event_id: uuid.UUID | None,
    idempotency_key: str | None,
    settings: Settings,
    now: datetime,
) -> SubmittedFeedback:
    """Full ``POST /feedback`` orchestration.

    Raises :class:`VisitSessionNotFoundError` or :class:`FeedbackTargetNotFoundError` for the
    router to translate into the matching HTTP response - see that module. The write itself is a
    single, fast, append-only insert (docs/frontend-backend-ai-interface-spec.md §13.2: "온라인
    행동 하나로 영구 가중치를 즉시 변경하지 않는다" - this function never mutates any scoring/
    profile state, only durably records the feedback row).
    """

    principal_fingerprint = compute_principal_fingerprint(
        str(user_id) if user_id is not None else str(guest_session_id)
    )

    if idempotency_key:
        replay = await _replay_from_record(
            db,
            await _find_idempotency_record(
                db,
                tenant_id=tenant_id,
                principal_fingerprint=principal_fingerprint,
                idempotency_key=idempotency_key,
            ),
        )
        if replay is not None:
            return SubmittedFeedback(feedback=replay, replayed=True)

    visit_session_id = await resolve_active_visit_session_id(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        user_id=user_id,
        guest_session_id=guest_session_id,
    )
    if visit_session_id is None:
        raise VisitSessionNotFoundError()

    recommendable_id = await resolve_recommendable_id(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        object_type=object_type,
        object_id=object_id,
    )
    if recommendable_id is None:
        raise FeedbackTargetNotFoundError(f"{object_type}:{object_id}")

    resolved_match_result_id: uuid.UUID | None = None
    if match_result_id is not None:
        # Soft validation: an unresolvable match_result_id must never block a feedback submit -
        # see module docstring (same precedent as submit_check_in's own match_result_id).
        resolved_match_result_id = await db.scalar(
            select(MatchResult.match_result_id).where(
                MatchResult.match_result_id == match_result_id,
                MatchResult.tenant_id == tenant_id,
                MatchResult.event_id == event_id,
            )
        )

    feedback = Feedback(
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        recommendable_id=recommendable_id,
        match_result_id=resolved_match_result_id,
        rating=rating,
        positive_reasons=list(positive_reasons),
        negative_reasons=list(negative_reasons),
        comment_enc=encrypt_comment(comment, settings=settings),
        client_event_id=client_event_id,
        created_at=now,
    )
    db.add(feedback)
    try:
        await db.flush()  # populate feedback.feedback_id for the idempotency_record FK value
        if idempotency_key:
            db.add(
                IdempotencyRecord(
                    tenant_id=tenant_id,
                    principal_fingerprint=principal_fingerprint,
                    method=IDEMPOTENCY_METHOD,
                    route=IDEMPOTENCY_ROUTE,
                    idempotency_key=idempotency_key,
                    response_status=_STATUS_CREATED,
                    response_reference=feedback.feedback_id,
                )
            )
        await db.commit()
    except IntegrityError:
        # Race window: a concurrent request for the same idempotency key, or the same
        # client_event_id, committed first. Never let the raw constraint violation reach the
        # caller as a 500 - resolve to whichever row won.
        await db.rollback()
        if idempotency_key:
            replay = await _replay_from_record(
                db,
                await _find_idempotency_record(
                    db,
                    tenant_id=tenant_id,
                    principal_fingerprint=principal_fingerprint,
                    idempotency_key=idempotency_key,
                ),
            )
            if replay is not None:
                return SubmittedFeedback(feedback=replay, replayed=True)
        if client_event_id is not None:
            existing = await find_feedback_by_client_event_id(
                db,
                tenant_id=tenant_id,
                event_id=event_id,
                client_event_id=client_event_id,
            )
            if existing is not None:
                return SubmittedFeedback(feedback=existing, replayed=True)
        raise
    await db.refresh(feedback)
    return SubmittedFeedback(feedback=feedback, replayed=False)
