"""Anonymous kiosk sessions, approved search, and signed QR handoff routes."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.routers.profile import build_envelope, get_request_id
from app.core.config import Settings, get_settings
from app.db.session import get_db
from app.models.core import Event
from app.schemas.kiosk import (
    KioskCloseResponse,
    KioskConfigResponse,
    KioskFeatureFlags,
    KioskHandoffRequest,
    KioskHandoffResolveRequest,
    KioskHandoffResolveResponse,
    KioskHandoffResponse,
    KioskSearchRequest,
    KioskSearchResponse,
    KioskSessionCreateRequest,
    KioskSessionResponse,
    KioskTheme,
)
from app.schemas.profile import Envelope
from app.schemas.search import SearchInterpretedQuery
from app.services.catalog_search import search_approved_catalog
from app.services.exhibition_public import get_booth_detail
from app.services.kiosk import (
    KioskSessionRecord,
    KioskStore,
    create_handoff_record,
    get_kiosk_store,
    handoff_token_matches,
    mark_handoff_claimed,
    mark_session_status,
    record_handoff,
    record_session_created,
    touch_session_activity,
    verify_handoff_token,
)

router = APIRouter(prefix="/kiosk")
SettingsDep = Annotated[Settings, Depends(get_settings)]
StoreDep = Annotated[KioskStore, Depends(get_kiosk_store)]
DbDep = Annotated[AsyncSession, Depends(get_db)]
RequestIdDep = Annotated[str, Depends(get_request_id)]


def _error(status_code: int, code: str, message: str, *, retryable: bool = False) -> HTTPException:
    return HTTPException(
        status_code=status_code,
        detail={
            "code": code,
            "message": message,
            "field_errors": [],
            "retryable": retryable,
            "retry_after_seconds": 3 if retryable else None,
        },
    )


def _config(kiosk_id: str, settings: Settings) -> KioskConfigResponse:
    languages = settings.kiosk_supported_languages
    default_language = settings.KIOSK_DEFAULT_LANGUAGE
    if default_language not in languages:
        default_language = "ko"
    return KioskConfigResponse(
        kiosk_id=kiosk_id,
        event_id=settings.KIOSK_EVENT_ID,
        event_name=settings.KIOSK_EVENT_NAME,
        default_language=default_language,
        supported_languages=languages,
        zone_id=settings.KIOSK_ZONE_ID,
        session_timeout_seconds=settings.KIOSK_SESSION_TIMEOUT_SECONDS,
        qr_expiration_minutes=settings.KIOSK_QR_EXPIRATION_MINUTES,
        theme=KioskTheme(primary_color=settings.KIOSK_PRIMARY_COLOR),
        feature_flags=KioskFeatureFlags(),
    )


async def _resolve_tenant_id(db: AsyncSession, event_id: uuid.UUID) -> uuid.UUID | None:
    """Best-effort tenant lookup for the durable audit row (see app/models/kiosk.py).

    Returns None (never raises) when the Event catalog isn't seeded yet or the DB is
    briefly unreachable - the live kiosk flow (Redis) must not depend on this succeeding.
    """

    try:
        result = await db.execute(select(Event.tenant_id).where(Event.event_id == event_id))
        return result.scalar_one_or_none()
    except SQLAlchemyError:
        return None


async def _active_session(store: KioskStore, session_id: uuid.UUID) -> KioskSessionRecord:
    try:
        session = await store.get_session(session_id)
    except RedisError as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "KIOSK_SESSION_STORE_UNAVAILABLE",
            "키오스크 세션을 확인할 수 없습니다.",
            retryable=True,
        ) from exc
    if session is None or session.expires_at <= datetime.now(UTC):
        raise _error(
            status.HTTP_410_GONE,
            "KIOSK_SESSION_EXPIRED",
            "이용 시간이 지나 세션이 초기화되었습니다.",
        )
    return session


@router.get("/config/{kiosk_id}", response_model=Envelope[KioskConfigResponse])
async def get_kiosk_config(
    kiosk_id: str, settings: SettingsDep, request_id: RequestIdDep
) -> dict[str, object]:
    return build_envelope(_config(kiosk_id, settings), request_id)


@router.post(
    "/sessions",
    response_model=Envelope[KioskSessionResponse],
    status_code=status.HTTP_201_CREATED,
)
async def create_kiosk_session(
    payload: KioskSessionCreateRequest,
    settings: SettingsDep,
    store: StoreDep,
    db: DbDep,
    request_id: RequestIdDep,
) -> dict[str, object]:
    config = _config(payload.kiosk_id, settings)
    if payload.language not in config.supported_languages:
        raise _error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "KIOSK_LANGUAGE_NOT_SUPPORTED",
            "선택한 언어를 이 키오스크에서 지원하지 않습니다.",
        )
    created_at = datetime.now(UTC)
    record = KioskSessionRecord(
        session_id=uuid.uuid4(),
        event_id=config.event_id,
        kiosk_id=config.kiosk_id,
        language=payload.language,
        created_at=created_at,
        last_activity_at=created_at,
        expires_at=created_at + timedelta(seconds=config.session_timeout_seconds),
    )
    try:
        await store.save_session(record, config.session_timeout_seconds)
    except RedisError as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "KIOSK_SESSION_STORE_UNAVAILABLE",
            "키오스크 세션을 시작할 수 없습니다.",
            retryable=True,
        ) from exc

    # Durable audit row (app/models/kiosk.py) - best-effort, never blocks session start.
    tenant_id = await _resolve_tenant_id(db, config.event_id)
    if tenant_id is not None:
        try:
            await record_session_created(db, record=record, tenant_id=tenant_id)
        except SQLAlchemyError:
            await db.rollback()

    data = KioskSessionResponse(
        session_id=record.session_id,
        event_id=record.event_id,
        kiosk_id=record.kiosk_id,
        language=payload.language,
        created_at=record.created_at,
        expires_at=record.expires_at,
        session_timeout_seconds=config.session_timeout_seconds,
    )
    return build_envelope(data, request_id)


@router.post(
    "/sessions/{session_id}/search",
    response_model=Envelope[KioskSearchResponse],
)
async def search_kiosk_catalog(
    session_id: uuid.UUID,
    payload: KioskSearchRequest,
    db: DbDep,
    settings: SettingsDep,
    store: StoreDep,
    request_id: RequestIdDep,
) -> dict[str, object]:
    session = await _active_session(store, session_id)
    try:
        results = await search_approved_catalog(
            db,
            event_id=session.event_id,
            query=payload.query,
            category_codes=payload.category_codes,
            limit=payload.limit,
        )
    except SQLAlchemyError as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "KIOSK_SEARCH_UNAVAILABLE",
            "승인된 업체 정보를 검색할 수 없습니다.",
            retryable=True,
        ) from exc

    now = datetime.now(UTC)
    session.last_activity_at = now
    session.expires_at = now + timedelta(seconds=settings.KIOSK_SESSION_TIMEOUT_SECONDS)
    session.last_query = payload.query
    session.last_result_ids = [item.result_id for item in results]
    try:
        await store.save_session(session, settings.KIOSK_SESSION_TIMEOUT_SECONDS)
    except RedisError as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "KIOSK_SESSION_STORE_UNAVAILABLE",
            "검색 세션을 갱신할 수 없습니다.",
            retryable=True,
        ) from exc

    # Durable audit row - best-effort, never blocks the search response.
    try:
        await touch_session_activity(
            db,
            session_id=session.session_id,
            last_activity_at=session.last_activity_at,
            expires_at=session.expires_at,
        )
    except SQLAlchemyError:
        await db.rollback()

    data = KioskSearchResponse(
        search_session_id=session.session_id,
        interpreted_query=SearchInterpretedQuery(concepts=payload.category_codes),
        results=results,
        expires_at=session.expires_at,
    )
    return build_envelope(data, request_id)


@router.post(
    "/sessions/{session_id}/handoff",
    response_model=Envelope[KioskHandoffResponse],
)
async def create_kiosk_handoff(
    session_id: uuid.UUID,
    payload: KioskHandoffRequest,
    settings: SettingsDep,
    store: StoreDep,
    db: DbDep,
    request_id: RequestIdDep,
) -> dict[str, object]:
    session = await _active_session(store, session_id)
    allowed = set(session.last_result_ids)
    if not allowed or any(item not in allowed for item in payload.selected_result_ids):
        raise _error(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "KIOSK_HANDOFF_SELECTION_INVALID",
            "현재 검색 결과에 포함된 업체만 휴대폰으로 보낼 수 있습니다.",
        )
    record, token, handoff_url = create_handoff_record(
        session=session,
        selected_result_ids=payload.selected_result_ids,
        expiration_minutes=settings.KIOSK_QR_EXPIRATION_MINUTES,
        secret=settings.site_context_secret,
        guest_web_base_url=settings.GUEST_WEB_BASE_URL,
    )


    try:
        await store.save_handoff(record, settings.KIOSK_QR_EXPIRATION_MINUTES * 60)
        # QR 발급과 동시에 공유 키오스크의 검색어·결과를 제거한다.
        await store.delete_session(session_id)
    except RedisError as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "KIOSK_HANDOFF_UNAVAILABLE",
            "QR을 만들 수 없습니다.",
            retryable=True,
        ) from exc

    # Durable audit row - best-effort, never blocks the handoff response. The QR is already
    # valid (it is a self-contained signed token) even if this secondary write fails.
    tenant_id = await _resolve_tenant_id(db, session.event_id)
    if tenant_id is not None:
        try:
            await record_handoff(
                db,
                record=record,
                tenant_id=tenant_id,
                kiosk_session_id=session.session_id,
            )
        except SQLAlchemyError:
            await db.rollback()

    return build_envelope(
        KioskHandoffResponse(
            handoff_id=record.handoff_id,
            token=token,
            handoff_url=handoff_url,
            expires_at=record.expires_at,
        ),
        request_id,
    )


@router.post(
    "/handoffs/resolve",
    response_model=Envelope[KioskHandoffResolveResponse],
)
async def resolve_kiosk_handoff(
    payload: KioskHandoffResolveRequest,
    settings: SettingsDep,
    store: StoreDep,
    db: DbDep,
    request_id: RequestIdDep,
) -> dict[str, object]:
    now = datetime.now(UTC)
    try:
        token_payload = verify_handoff_token(
            payload.token,
            secret=settings.site_context_secret,
            now=now,
        )
        handoff_id = uuid.UUID(token_payload["handoff_id"])
        event_id = uuid.UUID(token_payload["event_id"])
    except (KeyError, ValueError) as exc:
        code = (
            "KIOSK_HANDOFF_EXPIRED"
            if "expired" in str(exc)
            else "KIOSK_HANDOFF_INVALID"
        )
        status_code = (
            status.HTTP_410_GONE
            if code == "KIOSK_HANDOFF_EXPIRED"
            else status.HTTP_400_BAD_REQUEST
        )
        raise _error(status_code, code, "유효하지 않거나 만료된 QR입니다.") from exc

    try:
        record = await store.get_handoff(handoff_id)
    except RedisError as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "KIOSK_HANDOFF_UNAVAILABLE",
            "QR 정보를 불러올 수 없습니다.",
            retryable=True,
        ) from exc

    if (
        record is None
        or record.expires_at <= now
        or record.event_id != event_id
        or not handoff_token_matches(record, payload.token)
    ):
        raise _error(
            status.HTTP_410_GONE,
            "KIOSK_HANDOFF_EXPIRED",
            "유효하지 않거나 만료된 QR입니다.",
        )

    selected_results = []
    try:
        for result_id in record.selected_result_ids:
            parts = result_id.split(":")
            if len(parts) != 4 or parts[0] != "exhibitor" or parts[2] != "booth":
                continue
            detail = await get_booth_detail(db, booth_id=uuid.UUID(parts[3]))
            if detail is not None:
                selected_results.append(detail)
    except (SQLAlchemyError, ValueError) as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "KIOSK_HANDOFF_CATALOG_UNAVAILABLE",
            "선택한 업체 정보를 불러올 수 없습니다.",
            retryable=True,
        ) from exc

    try:
        await mark_handoff_claimed(db, handoff_id=handoff_id, claimed_at=now)
    except SQLAlchemyError:
        await db.rollback()

    return build_envelope(
        KioskHandoffResolveResponse(
            handoff_id=handoff_id,
            event_id=event_id,
            selected_results=selected_results,
            expires_at=record.expires_at,
            claimed_at=now,
        ),
        request_id,
    )


@router.post(
    "/sessions/{session_id}/close",
    response_model=Envelope[KioskCloseResponse],
)
async def close_kiosk_session(
    session_id: uuid.UUID, store: StoreDep, db: DbDep, request_id: RequestIdDep
) -> dict[str, object]:
    try:
        await store.delete_session(session_id)
    except RedisError as exc:
        raise _error(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "KIOSK_SESSION_STORE_UNAVAILABLE",
            "세션을 초기화할 수 없습니다.",
            retryable=True,
        ) from exc

    # Durable audit row - best-effort, never blocks session close.
    try:
        await mark_session_status(
            db,
            session_id=session_id,
            status="CLOSED",
            closed_at=datetime.now(UTC),
        )
    except SQLAlchemyError:
        await db.rollback()

    return build_envelope(KioskCloseResponse(session_id=session_id), request_id)
