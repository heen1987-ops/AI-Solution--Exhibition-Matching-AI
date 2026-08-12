"""``POST /check-ins`` service layer (BACKEND-016).

Scope: this package owns everything behind ``app/api/v1/routers/checkin.py`` - QR
verification, active visit-session resolution, the 5-minute advisory-lock dedupe window, and
Idempotency-Key replay. The model (``app/models/checkin.py`` - read its module docstring
first) and this file were built together in the same task; see that module's "Scope note" for
why.

QR verification reuses the established HMAC-lookup pattern, it does not hand-roll new crypto
--------------------------------------------------------------------------------------------
``app/core/auth.py::digest_secret`` already implements "client holds the raw opaque token,
server stores/looks up only its HMAC digest" for browser sessions (``purpose="browser-session"``),
guest sessions (``purpose="guest-session"``), and personal access links
(``purpose="personal-link"``). :func:`verify_booth_qr` below reuses that exact function with a
new ``purpose="booth-qr"`` tag (a distinct purpose tag always derives a distinct key - see that
module's docstring) rather than inventing a second signing scheme.

The QR token's "부스·행사·만료시간을 서명" claim (docs/user-ia-wireframes.md §7 U-16 - "signs
booth, event, and expiry") is realized via the ``exhibition.booth_qr`` row the token's HMAC
resolves to, not by decoding a self-describing payload out of the opaque token string itself.
``BoothQr`` already carries ``booth_id``, ``valid_from``/``valid_until``, and ``status``
(``app/models/exhibitor.py``); ``event_id``/``tenant_id`` are re-derived one hop further through
``booth_id -> Booth.tenant_id/event_id`` and re-checked against the caller's own session
boundary on every single verification - "미리보기용 검증 API를 제공하더라도 등록 시 모든 조건을
다시 검사한다" (docs/frontend-backend-ai-interface-spec.md §13.1) is satisfied by construction
here: there is no separate preview code path to fall out of sync, :func:`verify_booth_qr` is the
only QR-checking code and it always runs at actual registration time.

Every failure mode below (unknown token, wrong tenant/event, revoked, outside
valid_from/valid_until) collapses to the same ``InvalidQrError`` / ``INVALID_QR`` response the
frontend already branches on (``apps/user-web/app/check-in/[qrToken]/page.tsx``:
``err.code === "INVALID_QR"``) - never a distinguishing error, so a caller cannot use response
differences to enumerate which booths/events/QR states exist.

Active visit-session resolution
--------------------------------------------------------------------------------------------
``CurrentSubject`` (``app/api/v1/routers/profile.py::get_current_subject``, reused by this
router exactly as ``app/api/v1/routers/favorites.py`` reuses it) carries tenant/event/owner but
not a ``visit_session_id`` - unlike the heavier ``resolve_subject_context``/``SubjectContext``
flow in ``app/api/v1/routers/recommendations.py`` (which requires a signed site-context header
from an external site adapter and an explicit ``X-Visit-Session-Id`` header), this endpoint is
called directly by REGISTERED_WEB/GUEST_WEB browsers exactly like ``/me/favorites``, so it
derives the caller's current visit session server-side instead of trusting a caller-supplied
id. :func:`resolve_active_visit_session_id` picks the owner's most recently updated
non-terminal (``ACTIVE`` preferred over ``PLANNED``, never ``COMPLETED``/``CANCELLED``)
``profile.visit_session`` row - a visitor mid-event always has exactly one such row (created at
``POST /sessions`` - see ``app/api/v1/routers/sessions.py``), and the check-in cannot be
attributed to a session that has already ended or been cancelled.

5-minute duplicate window: advisory lock, then a bounded range query
--------------------------------------------------------------------------------------------
docs/db-erd-table-spec.md §16.2: "5분 중복방지는 트랜잭션 내 visit_session_id + booth_id
advisory lock 후 최근 체크인을 조회한다". :func:`_check_in_lock_stmt` mirrors the
``pg_advisory_xact_lock(hashtextextended(...))`` pattern already established by
``app/services/object_embeddings.py`` (``_embedding_stage_lock_stmt`` /
``_catalog_source_lock_stmt``) rather than inventing a new locking primitive - the lock is
session/transaction-scoped (``_xact_lock``) so it releases automatically on commit or rollback,
never needs an explicit unlock call, and serializes only requests that share the same
``visit_session_id``+``booth_id`` pair (unrelated check-ins never block each other).

After the lock is held, :func:`find_recent_check_in` looks for an existing row within +/-5
minutes of the *new* request's ``occurred_at`` (the client-declared event time, which matters
for offline-queued resends whose ``occurred_at`` can be well before the moment the request
finally reaches the server) for the same ``(tenant, event, visit_session, booth)`` tuple - db-erd
§16.2's "event_id + booth_id + visit_session_id + dedupe_window" duplicate key. If found, the
caller gets that row back with ``duplicate=True`` and no new row is inserted - "중복이면 오류만
반환하지 않고 기존 체크인 ID와 시각을 제공한다" (§13.1). The response always reflects the
*existing* row's own id/time/activities, never a merge with the new request's activities.

Idempotency-Key: reuses integration.idempotency_record, no parallel mechanism
--------------------------------------------------------------------------------------------
"Idempotency-Key는 integration.idempotency_record에 별도 저장한다" (§16.2). This mirrors
``app/api/v1/routers/webhooks.py``'s ``X-Webhook-ID`` dedupe against the same table exactly:
``principal_fingerprint`` (``app/core/security.py::compute_principal_fingerprint``, keyed here
on the caller's own user_id/guest_session_id string rather than a source_system_code),
``method="POST"``, a fixed ``route="/check-ins"``, and the caller-supplied key. A hit replays
the original result without touching ``CheckIn`` insert logic at all.

Reusing ``response_status`` to reconstruct the original ``duplicate`` flag, instead of adding a
new column: a first-time success commits ``response_status=201``; a dedupe-window duplicate (or
a replay of one) commits/replays ``response_status=200``. On replay, ``duplicate = (status ==
200)`` reconstructs exactly what the original request would have answered, with no extra schema
surface.

``client_event_id``'s own partial-unique index (see the model's docstring) is a second,
independent safety net races here fall back to gracefully - see :func:`submit_check_in`'s
``except IntegrityError`` branch, which mirrors ``app/services/favorite/service.py::
create_favorite``'s "pre-check, then re-query on the race-window IntegrityError" shape rather
than letting a raw constraint violation reach the caller as a 500.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import ColumnElement, case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import digest_secret
from app.core.config import Settings
from app.core.security import compute_principal_fingerprint
from app.models.checkin import CheckIn
from app.models.exhibitor import Booth, BoothQr
from app.models.integration import IdempotencyRecord
from app.models.matching import MatchResult
from app.models.profile import VisitSession

#: db-erd §16.2's "5분" dedupe window, applied symmetrically around the request's occurred_at
#: (see module docstring for why occurred_at, not "now", anchors the window).
DEDUPE_WINDOW = timedelta(minutes=5)

#: integration.idempotency_record scoping for this route (mirrors webhooks.py's own _ROUTE).
IDEMPOTENCY_METHOD = "POST"
IDEMPOTENCY_ROUTE = "/check-ins"

#: response_status values used as the reconstructed `duplicate` flag on idempotency replay -
#: see module docstring "Reusing response_status" section.
_STATUS_CREATED = 201
_STATUS_DUPLICATE = 200

#: HMAC purpose tag for booth QR tokens - see app/core/auth.py::digest_secret's own docstring
#: for why a distinct purpose always derives a distinct, non-reusable key.
QR_TOKEN_PURPOSE = "booth-qr"


class InvalidQrError(Exception):
    """The QR token does not resolve to a usable booth_qr row for this tenant/event.

    Deliberately a single error type for every failure mode (unknown/revoked/expired/wrong
    event) - see module docstring for why the response must not distinguish between them.
    """


class BoothClosedError(Exception):
    """The QR resolved to a real, currently-valid booth_qr, but the booth itself is CLOSED."""


class VisitSessionNotFoundError(Exception):
    """The caller has no active/planned visit_session in this tenant/event to attribute a
    check-in to."""


@dataclass(frozen=True)
class VerifiedBoothQr:
    booth_qr: BoothQr
    booth: Booth


def _owner_clause(
    *, user_id: uuid.UUID | None, guest_session_id: uuid.UUID | None
) -> ColumnElement[bool]:
    if user_id is not None:
        return VisitSession.user_id == user_id
    if guest_session_id is not None:
        return VisitSession.guest_session_id == guest_session_id
    raise ValueError("either user_id or guest_session_id is required")


async def resolve_active_visit_session_id(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    user_id: uuid.UUID | None,
    guest_session_id: uuid.UUID | None,
) -> uuid.UUID | None:
    """The caller's own most-recently-updated ACTIVE (preferred) or PLANNED visit_session in
    this tenant/event. Never COMPLETED/CANCELLED - see module docstring."""

    stmt = (
        select(VisitSession.visit_session_id)
        .where(
            VisitSession.tenant_id == tenant_id,
            VisitSession.event_id == event_id,
            _owner_clause(user_id=user_id, guest_session_id=guest_session_id),
            VisitSession.session_status.in_(("ACTIVE", "PLANNED")),
        )
        .order_by(
            case((VisitSession.session_status == "ACTIVE", 0), else_=1),
            VisitSession.updated_at.desc(),
        )
        .limit(1)
    )
    return await db.scalar(stmt)


async def verify_booth_qr(
    db: AsyncSession,
    *,
    qr_token: str,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    settings: Settings,
    now: datetime,
) -> VerifiedBoothQr:
    """Full re-verification every call - signature, event, booth, expiry, operating hours (the
    last is left to the caller via the returned Booth; see router). No result of this function
    is ever cached across requests."""

    token_hmac = digest_secret(qr_token, purpose=QR_TOKEN_PURPOSE, settings=settings)
    booth_qr = await db.scalar(select(BoothQr).where(BoothQr.token_hmac == token_hmac))
    if booth_qr is None:
        raise InvalidQrError("not_found")
    if booth_qr.status != "ACTIVE":
        raise InvalidQrError("status")
    if booth_qr.valid_from is not None and now < booth_qr.valid_from:
        raise InvalidQrError("not_yet_valid")
    if booth_qr.valid_until is not None and now > booth_qr.valid_until:
        raise InvalidQrError("expired")

    booth = await db.get(Booth, booth_qr.booth_id)
    if booth is None or booth.tenant_id != tenant_id or booth.event_id != event_id:
        # Wrong tenant/event (or a dangling booth_id) - same INVALID_QR response as "not
        # found", never disclosing that a booth exists in a different event.
        raise InvalidQrError("event_mismatch")

    return VerifiedBoothQr(booth_qr=booth_qr, booth=booth)


def _check_in_lock_stmt(visit_session_id: uuid.UUID, booth_id: uuid.UUID):
    """Transaction-scoped advisory lock keyed on this exact (visit_session, booth) pair - see
    module docstring. Released automatically at commit/rollback."""

    return select(
        func.pg_advisory_xact_lock(
            func.hashtextextended(f"check-in:{visit_session_id}:{booth_id}", 0)
        )
    )


async def find_recent_check_in(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    visit_session_id: uuid.UUID,
    booth_id: uuid.UUID,
    occurred_at: datetime,
    window: timedelta = DEDUPE_WINDOW,
) -> CheckIn | None:
    """Must be called only after :func:`_check_in_lock_stmt` has been executed in the same
    transaction (see :func:`submit_check_in`) - the lock is what makes this query+insert pair
    race-free, not the query alone."""

    stmt = (
        select(CheckIn)
        .where(
            CheckIn.tenant_id == tenant_id,
            CheckIn.event_id == event_id,
            CheckIn.visit_session_id == visit_session_id,
            CheckIn.booth_id == booth_id,
            CheckIn.checked_in_at >= occurred_at - window,
            CheckIn.checked_in_at <= occurred_at + window,
        )
        .order_by(CheckIn.checked_in_at.desc())
        .limit(1)
    )
    return await db.scalar(stmt)


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
) -> tuple[CheckIn, bool] | None:
    if record is None or record.response_reference is None:
        return None
    check_in = await db.get(CheckIn, record.response_reference)
    if check_in is None:
        return None
    return check_in, record.response_status == _STATUS_DUPLICATE


async def submit_check_in(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    user_id: uuid.UUID | None,
    guest_session_id: uuid.UUID | None,
    qr_token: str,
    activities: list[str],
    match_result_id: uuid.UUID | None,
    client_event_id: uuid.UUID | None,
    occurred_at: datetime,
    idempotency_key: str | None,
    settings: Settings,
    now: datetime,
) -> tuple[CheckIn, bool]:
    """Full ``POST /check-ins`` orchestration. Returns ``(check_in, duplicate)``.

    Raises :class:`VisitSessionNotFoundError`, :class:`InvalidQrError`, or
    :class:`BoothClosedError` for the router to translate into the matching HTTP responses -
    see that module. Every check re-runs on every call; nothing here is cached across requests
    (§13.1's "등록 시 모든 조건을 다시 검사한다").
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
            return replay

    visit_session_id = await resolve_active_visit_session_id(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        user_id=user_id,
        guest_session_id=guest_session_id,
    )
    if visit_session_id is None:
        raise VisitSessionNotFoundError()

    verified = await verify_booth_qr(
        db,
        qr_token=qr_token,
        tenant_id=tenant_id,
        event_id=event_id,
        settings=settings,
        now=now,
    )
    if verified.booth.operating_status == "CLOSED":
        raise BoothClosedError()

    # Serialize concurrent check-ins for this exact (visit_session, booth) pair before the
    # dedupe-window query - see module docstring.
    await db.execute(_check_in_lock_stmt(visit_session_id, verified.booth.booth_id))

    recent = await find_recent_check_in(
        db,
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        booth_id=verified.booth.booth_id,
        occurred_at=occurred_at,
    )
    if recent is not None:
        if idempotency_key:
            db.add(
                IdempotencyRecord(
                    tenant_id=tenant_id,
                    principal_fingerprint=principal_fingerprint,
                    method=IDEMPOTENCY_METHOD,
                    route=IDEMPOTENCY_ROUTE,
                    idempotency_key=idempotency_key,
                    response_status=_STATUS_DUPLICATE,
                    response_reference=recent.check_in_id,
                )
            )
            try:
                await db.commit()
            except IntegrityError:
                # Another concurrent replay already recorded this key - the row we found is
                # still the correct answer regardless.
                await db.rollback()
        return recent, True

    resolved_match_result_id: uuid.UUID | None = None
    if match_result_id is not None:
        # Soft validation: an unresolvable match_result_id must never block a check-in (the
        # check-in itself is the important side effect) - contrast
        # app/services/favorite/service.py::create_favorite, which hard-rejects for the same
        # field. Here it is simply dropped.
        resolved_match_result_id = await db.scalar(
            select(MatchResult.match_result_id).where(
                MatchResult.match_result_id == match_result_id,
                MatchResult.tenant_id == tenant_id,
                MatchResult.event_id == event_id,
            )
        )

    check_in = CheckIn(
        tenant_id=tenant_id,
        event_id=event_id,
        visit_session_id=visit_session_id,
        booth_id=verified.booth.booth_id,
        match_result_id=resolved_match_result_id,
        check_in_method="QR",
        activities=activities,
        qr_id=verified.booth_qr.booth_qr_id,
        qr_key_version=verified.booth_qr.key_version,
        client_event_id=client_event_id,
        checked_in_at=occurred_at,
        received_at=now,
    )
    db.add(check_in)
    try:
        await db.flush()  # populate check_in.check_in_id for the idempotency_record FK value
        if idempotency_key:
            db.add(
                IdempotencyRecord(
                    tenant_id=tenant_id,
                    principal_fingerprint=principal_fingerprint,
                    method=IDEMPOTENCY_METHOD,
                    route=IDEMPOTENCY_ROUTE,
                    idempotency_key=idempotency_key,
                    response_status=_STATUS_CREATED,
                    response_reference=check_in.check_in_id,
                )
            )
        await db.commit()
    except IntegrityError:
        # Race window: a concurrent request for the same idempotency key, or the same
        # client_event_id, or the same dedupe-window slot, committed first. Never let the raw
        # constraint violation reach the caller as a 500 - resolve to whichever row won.
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
                return replay
        recent = await find_recent_check_in(
            db,
            tenant_id=tenant_id,
            event_id=event_id,
            visit_session_id=visit_session_id,
            booth_id=verified.booth.booth_id,
            occurred_at=occurred_at,
        )
        if recent is not None:
            return recent, True
        raise
    await db.refresh(check_in)
    return check_in, False
