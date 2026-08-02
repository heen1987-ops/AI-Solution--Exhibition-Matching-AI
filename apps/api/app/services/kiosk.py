"""TTL kiosk session storage and privacy-preserving QR token issuance.

Redis (`RedisKioskStore`) is the live, fast-TTL cache used to gate requests (db-erd-table-
spec.md 3절). The `record_*`/`touch_*`/`mark_*` functions below write the durable,
no-PII counterpart rows defined in app/models/kiosk.py, so a session's lifecycle survives
past the Redis key's expiry for admin stats - see app/models/kiosk.py's module docstring.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import uuid
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from typing import Protocol
from urllib.parse import quote

from pydantic import BaseModel, Field
from redis.asyncio import Redis, from_url
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.security import (
    compute_webhook_signature,
    derive_webhook_secret,
    verify_webhook_signature,
)
from app.models.kiosk import KioskQrHandoff, KioskSession

SESSION_KEY_PREFIX = "backju:kiosk:session:"
HANDOFF_KEY_PREFIX = "backju:kiosk:handoff:"
TOKEN_VERSION = "v1"
#: Purpose tag fed into app/core/security.py's HMAC key derivation (`derive_webhook_secret`
#: doubles as "derive a purpose-scoped secret from SECRET_KEY" - the kiosk QR handoff isn't a
#: webhook, but it needs exactly that: a secret distinct from every other HMAC use in this
#: service). Reusing this instead of hand-rolling a new HMAC call keeps every signed value in
#: the codebase going through the one key-derivation function (see security.py's module TODO).
_HANDOFF_SECRET_PURPOSE = "kiosk-qr-handoff"


class KioskSessionRecord(BaseModel):
    session_id: uuid.UUID
    event_id: uuid.UUID
    kiosk_id: str
    language: str
    created_at: datetime
    last_activity_at: datetime
    expires_at: datetime
    last_query: str = ""
    last_result_ids: list[str] = Field(default_factory=list)


class KioskHandoffRecord(BaseModel):
    handoff_id: uuid.UUID
    event_id: uuid.UUID
    kiosk_id: str
    selected_result_ids: list[str]
    token_hash: str
    created_at: datetime
    expires_at: datetime


class KioskStore(Protocol):
    async def save_session(self, record: KioskSessionRecord, ttl_seconds: int) -> None: ...

    async def get_session(self, session_id: uuid.UUID) -> KioskSessionRecord | None: ...

    async def delete_session(self, session_id: uuid.UUID) -> None: ...

    async def save_handoff(self, record: KioskHandoffRecord, ttl_seconds: int) -> None: ...

    async def get_handoff(self, handoff_id: uuid.UUID) -> KioskHandoffRecord | None: ...


class RedisKioskStore:
    """Redis storage with server-enforced TTL and no personal-data fields."""

    def __init__(self, redis: Redis) -> None:
        self._redis = redis

    async def save_session(self, record: KioskSessionRecord, ttl_seconds: int) -> None:
        await self._redis.set(
            f"{SESSION_KEY_PREFIX}{record.session_id}",
            record.model_dump_json(),
            ex=ttl_seconds,
        )

    async def get_session(self, session_id: uuid.UUID) -> KioskSessionRecord | None:
        value = await self._redis.get(f"{SESSION_KEY_PREFIX}{session_id}")
        return KioskSessionRecord.model_validate_json(value) if value is not None else None

    async def delete_session(self, session_id: uuid.UUID) -> None:
        await self._redis.delete(f"{SESSION_KEY_PREFIX}{session_id}")

    async def save_handoff(self, record: KioskHandoffRecord, ttl_seconds: int) -> None:
        await self._redis.set(
            f"{HANDOFF_KEY_PREFIX}{record.handoff_id}",
            record.model_dump_json(),
            ex=ttl_seconds,
        )

    async def get_handoff(self, handoff_id: uuid.UUID) -> KioskHandoffRecord | None:
        value = await self._redis.get(f"{HANDOFF_KEY_PREFIX}{handoff_id}")
        return KioskHandoffRecord.model_validate_json(value) if value is not None else None


@lru_cache
def get_kiosk_store() -> RedisKioskStore:
    settings = get_settings()
    redis = from_url(settings.REDIS_URL, encoding="utf-8", decode_responses=True)
    return RedisKioskStore(redis)


def _derive_handoff_secret(secret: str) -> str:
    """Purpose-scope `secret` (Settings.site_context_secret) via the shared HMAC deriver.

    Reuses app/core/security.py's `derive_webhook_secret` rather than hashing directly with
    the raw application secret, so a kiosk QR token can never be forged with a secret derived
    for a different purpose (webhook signing, identity lookup, ...) even if one leaked.
    """

    return derive_webhook_secret(_HANDOFF_SECRET_PURPOSE, secret=secret)


def issue_handoff_token(
    *, handoff_id: uuid.UUID, event_id: uuid.UUID, expires_at: datetime, secret: str
) -> str:
    # Selected result IDs stay server-side (Redis + kiosk.kiosk_qr_handoff). The signed
    # payload contains only an opaque handoff ID, event boundary, and expiry - no personal
    # data, per docs/vibe-coding-master-spec-v1.md §23.
    payload = {
        "handoff_id": str(handoff_id),
        "event_id": str(event_id),
        "expires_at": expires_at.astimezone(UTC).isoformat(),
    }
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    encoded = base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")
    # app/core/security.py's compute_webhook_signature is a generic "HMAC-SHA256 over these
    # bytes, with this secret" primitive (used elsewhere for webhook payloads) - reused here
    # verbatim rather than re-implementing HMAC signing a second time in this module.
    signature = compute_webhook_signature(
        encoded.encode("ascii"), secret=_derive_handoff_secret(secret)
    )
    return f"{TOKEN_VERSION}.{encoded}.{signature}"


def verify_handoff_token(
    token: str, *, secret: str, now: datetime | None = None
) -> dict[str, str]:
    try:
        version, encoded, provided_signature = token.split(".", 2)
    except ValueError as exc:
        raise ValueError("invalid handoff token") from exc
    if version != TOKEN_VERSION:
        raise ValueError("unsupported handoff token version")
    verification = verify_webhook_signature(
        encoded.encode("ascii"),
        provided_signature,
        secret=_derive_handoff_secret(secret),
    )
    if not verification.valid:
        raise ValueError(f"invalid handoff token signature: {verification.reason}")
    padding = "=" * (-len(encoded) % 4)
    payload = json.loads(base64.urlsafe_b64decode(encoded + padding))
    if datetime.fromisoformat(payload["expires_at"]) <= (now or datetime.now(UTC)):
        raise ValueError("expired handoff token")
    return payload


def create_handoff_record(
    *,
    session: KioskSessionRecord,
    selected_result_ids: list[str],
    expiration_minutes: int,
    secret: str,
    guest_web_base_url: str,
) -> tuple[KioskHandoffRecord, str, str]:
    created_at = datetime.now(UTC)
    expires_at = created_at + timedelta(minutes=expiration_minutes)
    handoff_id = uuid.uuid4()
    token = issue_handoff_token(
        handoff_id=handoff_id,
        event_id=session.event_id,
        expires_at=expires_at,
        secret=secret,
    )
    record = KioskHandoffRecord(
        handoff_id=handoff_id,
        event_id=session.event_id,
        kiosk_id=session.kiosk_id,
        selected_result_ids=selected_result_ids,
        token_hash=hashlib.sha256(token.encode("utf-8")).hexdigest(),
        created_at=created_at,
        expires_at=expires_at,
    )
    url = f"{guest_web_base_url.rstrip('/')}/kiosk-handoff?token={quote(token)}"
    return record, token, url


def handoff_token_matches(record: KioskHandoffRecord, token: str) -> bool:
    """Bind a valid signed token to the exact server-side handoff record."""

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    return hmac.compare_digest(record.token_hash, token_hash)


# ---------------------------------------------------------------------------
# Durable (Postgres) audit trail - see app/models/kiosk.py's module docstring.
# Every function here is meant to be called from the router as a best-effort,
# non-blocking companion to the Redis writes above: a kiosk terminal must keep
# working even if this secondary write fails or the row it needs (e.g. the
# seed Event row) does not exist yet.
# ---------------------------------------------------------------------------


async def record_session_created(
    db: AsyncSession, *, record: KioskSessionRecord, tenant_id: uuid.UUID
) -> None:
    db.add(
        KioskSession(
            session_id=record.session_id,
            tenant_id=tenant_id,
            event_id=record.event_id,
            kiosk_id=record.kiosk_id,
            language=record.language,
            status="ACTIVE",
            created_at=record.created_at,
            last_activity_at=record.last_activity_at,
            expires_at=record.expires_at,
        )
    )
    await db.commit()


async def touch_session_activity(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    last_activity_at: datetime,
    expires_at: datetime,
) -> None:
    row = await db.get(KioskSession, session_id)
    if row is None:
        return
    row.last_activity_at = last_activity_at
    row.expires_at = expires_at
    await db.commit()


async def mark_session_status(
    db: AsyncSession,
    *,
    session_id: uuid.UUID,
    status: str,
    closed_at: datetime | None = None,
) -> None:
    row = await db.get(KioskSession, session_id)
    if row is None:
        return
    row.status = status
    if closed_at is not None:
        row.closed_at = closed_at
    await db.commit()


async def record_handoff(
    db: AsyncSession,
    *,
    record: KioskHandoffRecord,
    tenant_id: uuid.UUID,
    kiosk_session_id: uuid.UUID,
) -> None:
    db.add(
        KioskQrHandoff(
            handoff_id=record.handoff_id,
            kiosk_session_id=kiosk_session_id,
            tenant_id=tenant_id,
            event_id=record.event_id,
            selected_result_ids=record.selected_result_ids,
            token_hash=record.token_hash,
            created_at=record.created_at,
            expires_at=record.expires_at,
        )
    )
    await db.commit()
    await mark_session_status(db, session_id=kiosk_session_id, status="HANDED_OFF")


async def mark_handoff_claimed(
    db: AsyncSession, *, handoff_id: uuid.UUID, claimed_at: datetime
) -> None:
    row = await db.get(KioskQrHandoff, handoff_id)
    if row is None or row.claimed_at is not None:
        return
    row.claimed_at = claimed_at
    await db.commit()
