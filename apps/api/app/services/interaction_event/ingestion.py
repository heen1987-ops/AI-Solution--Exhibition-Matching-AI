"""Client UI-event ingestion orchestration (WAVE 2E BACKEND-EVENT-COLLECTION).

Writes accepted events into the *existing* ``interaction.interaction_event`` +
``interaction.client_event_dedupe`` tables (``app/models/matching.py`` - see the prior-art
map in ``app/models/interaction_event.py``'s docstring), so a ``client_event_id`` claimed by
this endpoint or by ``recommendations.py``'s ``/interactions/batch`` is honoured by both.
Rejections are additionally recorded in the new ``interaction.event_ingestion_failure``
observability ledger.

Partial-success contract (task spec): one bad item never fails the batch; the response counts
``accepted`` / ``duplicated`` / ``rejected`` and lists per-item ``results`` plus ``errors``
for the rejected ones. A duplicate replay of an already-claimed ``client_event_id`` with the
same payload is *successful idempotent* behaviour (status DUPLICATED, original row id echoed,
no new row) - only a same-id-different-payload replay is an error (IDEMPOTENCY_CONFLICT).
"""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.common import new_uuid7
from app.models.interaction_event import EventIngestionFailure
from app.models.matching import InteractionClientEventDedupe, InteractionEvent
from app.schemas.interaction_event import (
    CLIENT_INTERACTION_EVENT_TYPES,
    ClientInteractionBatchRequest,
    ClientInteractionBatchResponse,
    ClientInteractionEventError,
    ClientInteractionEventIn,
    ClientInteractionEventResult,
)
from app.services.interaction_event.masking import mask_search_query, sanitize_context
from app.services.interaction_event.validation import (
    find_forbidden_kiosk_keys,
    parse_client_event,
    timestamp_out_of_range,
)

#: interaction.interaction_event.screen_code is String(30); the request schema accepts a
#: slightly looser 40 to avoid rejecting whole events over a cosmetic field.
_SCREEN_CODE_MAX_LENGTH = 30


def _payload_hash(event: ClientInteractionEventIn) -> str:
    """Stable content hash for idempotency-conflict detection (same convention as
    recommendations.py::_event_payload_hash)."""

    payload = json.dumps(
        event.model_dump(mode="json"),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


class _Rejection(Exception):
    """Internal control-flow: one item is rejected with a closed-set reason code."""

    def __init__(self, reason_code: str, message: str) -> None:
        super().__init__(message)
        self.reason_code = reason_code
        self.message = message


def _build_context_json(
    payload: ClientInteractionBatchRequest, event: ClientInteractionEventIn
) -> dict[str, Any] | None:
    """Allow-listed client context + server-derived fields (masked query, source, kiosk ids,
    client-declared target object). All ``extra`` values are constructed here, never raw."""

    extra: dict[str, Any] = {"source": payload.source}
    masked_query = mask_search_query(event.search_query)
    if masked_query is not None:
        extra["search_query"] = masked_query
    if event.object_type is not None:
        extra["object_type"] = event.object_type
    if event.object_id is not None:
        extra["object_id"] = event.object_id[:100]
    if payload.kiosk_id is not None:
        extra["kiosk_id"] = payload.kiosk_id
    if payload.kiosk_session_id is not None:
        extra["kiosk_session_id"] = str(payload.kiosk_session_id)
    return sanitize_context(event.context, extra=extra)


async def _find_existing_claim(
    db: AsyncSession, tenant_id: uuid.UUID, client_event_id: uuid.UUID
) -> InteractionClientEventDedupe | None:
    return (
        await db.execute(
            select(InteractionClientEventDedupe)
            .where(
                InteractionClientEventDedupe.tenant_id == tenant_id,
                InteractionClientEventDedupe.client_event_id == client_event_id,
            )
            .limit(1)
        )
    ).scalar_one_or_none()


def _record_failure(
    db: AsyncSession,
    payload: ClientInteractionBatchRequest,
    *,
    reason_code: str,
    detail: str,
    client_event_id: uuid.UUID | None,
    event_type: str | None = None,
    claimed_occurred_at: datetime | None = None,
    request_id: str | None = None,
) -> None:
    db.add(
        EventIngestionFailure(
            tenant_id=payload.tenant_id,
            event_id=payload.event_id,
            source=payload.source,
            client_event_id=client_event_id,
            event_type=event_type[:60] if event_type else None,
            reason_code=reason_code,
            detail=detail[:300],
            request_id=request_id,
            claimed_occurred_at=claimed_occurred_at,
        )
    )


async def ingest_client_events(
    db: AsyncSession,
    payload: ClientInteractionBatchRequest,
    *,
    request_id: str | None = None,
    now: datetime | None = None,
) -> ClientInteractionBatchResponse:
    """Ingest a validated batch envelope of raw event dicts with partial success."""

    reference_now = now or datetime.now(UTC)
    results: list[ClientInteractionEventResult] = []
    errors: list[ClientInteractionEventError] = []
    accepted = duplicated = rejected = 0

    def reject(
        client_event_id: uuid.UUID | None,
        reason_code: str,
        message: str,
        *,
        event_type: str | None = None,
        claimed_occurred_at: datetime | None = None,
    ) -> None:
        nonlocal rejected
        rejected += 1
        results.append(
            ClientInteractionEventResult(
                client_event_id=client_event_id,
                interaction_event_id=None,
                status="REJECTED",
                reason_code=reason_code,
            )
        )
        errors.append(
            ClientInteractionEventError(
                client_event_id=client_event_id,
                reason_code=reason_code,
                message=message,
            )
        )
        _record_failure(
            db,
            payload,
            reason_code=reason_code,
            detail=message,
            client_event_id=client_event_id,
            event_type=event_type,
            claimed_occurred_at=claimed_occurred_at,
            request_id=request_id,
        )

    for raw in payload.events:
        event, client_event_id, schema_error = parse_client_event(raw)
        if event is None:
            reject(client_event_id, "SCHEMA_ERROR", schema_error or "invalid item")
            continue

        if event.event_type not in CLIENT_INTERACTION_EVENT_TYPES:
            reject(
                event.client_event_id,
                "UNKNOWN_EVENT_TYPE",
                "event_type is not in the accepted client event catalog",
                event_type=event.event_type,
            )
            continue

        timestamp_error = timestamp_out_of_range(event.occurred_at, now=reference_now)
        if timestamp_error is not None:
            reject(
                event.client_event_id,
                "TIMESTAMP_OUT_OF_RANGE",
                timestamp_error,
                event_type=event.event_type,
                claimed_occurred_at=event.occurred_at,
            )
            continue

        if payload.source == "KIOSK":
            forbidden = find_forbidden_kiosk_keys(event.context)
            if forbidden:
                # Reject (not silently strip): a kiosk build sending identity fields is a
                # privacy defect operators must notice, not a payload to quietly launder.
                reject(
                    event.client_event_id,
                    "KIOSK_IDENTITY_FIELD_FORBIDDEN",
                    "kiosk events must not carry identity/contact/device-fingerprint "
                    f"context keys: {', '.join(forbidden)}",
                    event_type=event.event_type,
                )
                continue

        payload_hash = _payload_hash(event)
        existing_claim = await _find_existing_claim(
            db, payload.tenant_id, event.client_event_id
        )
        if existing_claim is not None:
            if existing_claim.payload_hash == payload_hash:
                duplicated += 1
                results.append(
                    ClientInteractionEventResult(
                        client_event_id=event.client_event_id,
                        interaction_event_id=existing_claim.interaction_event_id,
                        status="DUPLICATED",
                        reason_code="DUPLICATE_IGNORED",
                    )
                )
            else:
                reject(
                    event.client_event_id,
                    "IDEMPOTENCY_CONFLICT",
                    "client_event_id was already claimed by a different payload",
                    event_type=event.event_type,
                )
            continue

        occurred_at = (
            event.occurred_at
            if event.occurred_at.tzinfo is not None
            else event.occurred_at.replace(tzinfo=UTC)
        )
        event_date = occurred_at.astimezone(UTC).date()
        row = InteractionEvent(
            event_date=event_date,
            interaction_event_id=new_uuid7(),
            tenant_id=payload.tenant_id,
            event_id=payload.event_id,
            # Subject columns: KIOSK batches are anonymous by contract (schema validator
            # rejects any profile/user/guest field); WEB batches carry at most one of
            # user_id/guest_session_id (also schema-enforced, matching the table's
            # ``subject_at_most_one`` CHECK).
            user_id=payload.user_id,
            guest_session_id=payload.guest_session_id,
            visit_session_id=payload.visit_session_id,
            event_type=event.event_type,
            recommendable_id=None,
            recommendation_session_id=None,
            match_result_id=None,
            rank_at_event=None,
            screen_code=event.screen[:_SCREEN_CODE_MAX_LENGTH] if event.screen else None,
            context_json=_build_context_json(payload, event),
            client_event_id=event.client_event_id,
            consent_snapshot_id=None,
            occurred_at=occurred_at,
        )
        try:
            async with db.begin_nested():
                db.add(row)
                db.add(
                    InteractionClientEventDedupe(
                        tenant_id=payload.tenant_id,
                        event_id=payload.event_id,
                        client_event_id=event.client_event_id,
                        event_date=event_date,
                        interaction_event_id=row.interaction_event_id,
                        payload_hash=payload_hash,
                    )
                )
                await db.flush()
        except SQLAlchemyError:
            # Most likely a concurrent claim on the same client_event_id (unique PK on the
            # dedupe table) - re-read and translate to the idempotent outcome.
            raced_claim = await _find_existing_claim(
                db, payload.tenant_id, event.client_event_id
            )
            if raced_claim is not None and raced_claim.payload_hash == payload_hash:
                duplicated += 1
                results.append(
                    ClientInteractionEventResult(
                        client_event_id=event.client_event_id,
                        interaction_event_id=raced_claim.interaction_event_id,
                        status="DUPLICATED",
                        reason_code="DUPLICATE_IGNORED",
                    )
                )
            elif raced_claim is not None:
                reject(
                    event.client_event_id,
                    "IDEMPOTENCY_CONFLICT",
                    "client_event_id was already claimed by a different payload",
                    event_type=event.event_type,
                )
            else:
                reject(
                    event.client_event_id,
                    "PERSIST_FAILED",
                    "event row could not be persisted",
                    event_type=event.event_type,
                )
            continue

        accepted += 1
        results.append(
            ClientInteractionEventResult(
                client_event_id=event.client_event_id,
                interaction_event_id=row.interaction_event_id,
                status="ACCEPTED",
            )
        )

    await db.commit()
    return ClientInteractionBatchResponse(
        accepted=accepted,
        duplicated=duplicated,
        rejected=rejected,
        results=results,
        errors=errors,
    )
