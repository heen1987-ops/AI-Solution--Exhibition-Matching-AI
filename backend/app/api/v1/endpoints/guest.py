"""Guest web session and guest-to-registered conversion endpoints."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import (
    ApiRequestContext,
    get_request_context,
)
from app.api.v1.endpoints.profile import UserProfileResponse, _to_response
from app.api.v1.errors import api_error
from app.db.session import get_db
from app.models.core import Event
from app.models.identity import GuestSession, UserAccount
from app.models.matching import Recommendable
from app.models.profile import SavedRecommendable, UserProfile, VisitSession

router = APIRouter()

ApiProfileType = Literal["GENERAL_REGISTERED", "BUYER_REGISTERED"]
EntryMethod = Literal[
    "EVENT_WEBSITE",
    "QR",
    "SHORT_URL",
    "EMAIL_LINK",
    "REGISTRATION_LINK",
]
SessionStatus = Literal["ACTIVE", "CONVERTED", "EXPIRED", "PURGED"]

_API_TO_DB_USER_TYPE = {
    "GENERAL_REGISTERED": "GENERAL_VISITOR",
    "BUYER_REGISTERED": "BUYER",
}
DEFAULT_GUEST_WEB_TTL_HOURS = 8
GUEST_WEB_ENTRY_CHANNEL = "WEB"
GUEST_WEB_DEVICE_TYPE = "MOBILE_WEB"
GUEST_TEMP_PROFILE_USER_TYPE = "GENERAL_VISITOR"


class ConvertGuestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    guest_session_id: uuid.UUID
    entry_code: str = Field(min_length=16, max_length=100)


class ConvertGuestResponse(BaseModel):
    profile: UserProfileResponse
    converted_at: datetime


class StartGuestWebSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    event_id: uuid.UUID
    language: str = Field(default="ko-KR", min_length=2, max_length=10)
    entry_method: EntryMethod = "EVENT_WEBSITE"
    entry_context: dict[str, Any] | None = None


class GuestFavoriteResponse(BaseModel):
    temporary_favorite_id: str
    recommendable_id: uuid.UUID
    saved_at: datetime


class GuestWebSessionResponse(BaseModel):
    guest_session_id: uuid.UUID
    channel: Literal["GUEST_WEB"] = "GUEST_WEB"
    language: str | None
    session_status: SessionStatus
    expires_at: datetime
    temporary_favorites: list[GuestFavoriteResponse]


class AddGuestFavoriteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendable_id: uuid.UUID
    saved_context_json: dict[str, Any] | None = None


class ConvertGuestWebSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    transfer_temporary_favorites: bool = True
    profile_link_token: str | None = Field(default=None, min_length=16, max_length=100)


class ConvertGuestWebSessionResponse(BaseModel):
    profile: UserProfileResponse
    transferred_favorite_count: int
    converted_at: datetime


def _now() -> datetime:
    return datetime.now(UTC)


def _new_session_hmac() -> bytes:
    return hashlib.sha256(secrets.token_bytes(32)).digest()


def _session_status(guest_session: GuestSession, now: datetime | None = None) -> SessionStatus:
    checked_at = now or _now()
    if guest_session.converted_user_id is not None:
        return "CONVERTED"
    if guest_session.expires_at <= checked_at:
        return "EXPIRED"
    return "ACTIVE"


def _target_db_user_type(context: ApiRequestContext) -> str:
    if context.user_type == "GUEST_WEB":
        raise api_error(
            "PERMISSION_DENIED",
            "이 작업을 수행할 권한이 없습니다.",
            status_code=403,
        )
    return _API_TO_DB_USER_TYPE[context.user_type]


async def _event_or_404(db: AsyncSession, event_id: uuid.UUID) -> Event:
    event = await db.get(Event, event_id)
    if event is None:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "event"},
        )
    return event


async def _require_user_account(db: AsyncSession, user_id: uuid.UUID) -> UserAccount:
    user = await db.get(UserAccount, user_id)
    if user is None or user.account_status != "ACTIVE" or user.deleted_at is not None:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "user_account"},
        )
    return user


async def _load_guest_web_session(
    db: AsyncSession,
    guest_session_id: uuid.UUID,
    *,
    require_active: bool,
) -> GuestSession:
    guest_session = await db.get(GuestSession, guest_session_id)
    if guest_session is None or guest_session.entry_channel != GUEST_WEB_ENTRY_CHANNEL:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "guest_session"},
        )
    if require_active and _session_status(guest_session) != "ACTIVE":
        raise api_error(
            "GUEST_SESSION_EXPIRED",
            "게스트 웹 세션이 만료되었습니다.",
            status_code=410,
            details={"resource": "guest_session"},
        )
    return guest_session


async def _load_convertible_guest_session(
    db: AsyncSession,
    guest_session_id: uuid.UUID,
    *,
    entry_code: str | None,
    require_entry_code: bool,
) -> GuestSession:
    guest_session = await _load_guest_web_session(
        db, guest_session_id, require_active=False
    )
    now = _now()
    if guest_session.converted_user_id is not None:
        raise api_error(
            "RESOURCE_CONFLICT",
            "요청이 현재 상태와 충돌합니다.",
            status_code=409,
            details={"resource": "guest_session", "field": "converted_user_id"},
        )
    if guest_session.expires_at <= now:
        raise api_error(
            "GUEST_SESSION_EXPIRED",
            "게스트 웹 세션이 만료되었습니다.",
            status_code=410,
            details={"resource": "guest_session"},
        )
    if (require_entry_code or entry_code is not None) and (
        entry_code is None or guest_session.entry_code != entry_code
    ):
        raise api_error(
            "WEB_ENTRY_LINK_EXPIRED",
            "웹 진입 링크가 만료되었거나 이미 사용되었습니다.",
            status_code=410,
            details={"resource": "guest_session"},
        )
    return guest_session


async def _ensure_active_recommendable(
    db: AsyncSession,
    *,
    guest_session: GuestSession,
    recommendable_id: uuid.UUID,
) -> None:
    active = await db.scalar(
        select(Recommendable.active).where(
            Recommendable.recommendable_id == recommendable_id,
            Recommendable.tenant_id == guest_session.tenant_id,
            Recommendable.event_id == guest_session.event_id,
        )
    )
    if active is not True:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "recommendable"},
        )


async def _temporary_favorites(
    db: AsyncSession, guest_session: GuestSession
) -> list[SavedRecommendable]:
    rows = await db.scalars(
        select(SavedRecommendable)
        .join(UserProfile, SavedRecommendable.profile_id == UserProfile.profile_id)
        .where(
            UserProfile.tenant_id == guest_session.tenant_id,
            UserProfile.event_id == guest_session.event_id,
            UserProfile.guest_session_id == guest_session.guest_session_id,
            UserProfile.user_id.is_(None),
            UserProfile.deleted_at.is_(None),
        )
        .order_by(SavedRecommendable.saved_at.desc())
    )
    return list(rows.all())


def _favorite_response(saved: SavedRecommendable) -> GuestFavoriteResponse:
    return GuestFavoriteResponse(
        temporary_favorite_id=str(saved.saved_recommendable_id),
        recommendable_id=saved.recommendable_id,
        saved_at=saved.saved_at,
    )


async def _session_response(
    db: AsyncSession, guest_session: GuestSession
) -> GuestWebSessionResponse:
    return GuestWebSessionResponse(
        guest_session_id=guest_session.guest_session_id,
        language=guest_session.language,
        session_status=_session_status(guest_session),
        expires_at=guest_session.expires_at,
        temporary_favorites=[
            _favorite_response(saved)
            for saved in await _temporary_favorites(db, guest_session)
        ],
    )


async def _existing_persistent_profile(
    db: AsyncSession,
    *,
    guest_session: GuestSession,
    user_id: uuid.UUID,
    user_type: str,
) -> UserProfile | None:
    return await db.scalar(
        select(UserProfile)
        .where(
            UserProfile.tenant_id == guest_session.tenant_id,
            UserProfile.event_id == guest_session.event_id,
            UserProfile.user_id == user_id,
            UserProfile.guest_session_id.is_(None),
            UserProfile.user_type == user_type,
            UserProfile.deleted_at.is_(None),
        )
        .limit(1)
    )


async def _guest_profile(
    db: AsyncSession,
    *,
    guest_session: GuestSession,
    user_type: str,
) -> UserProfile | None:
    return await db.scalar(
        select(UserProfile)
        .where(
            UserProfile.tenant_id == guest_session.tenant_id,
            UserProfile.event_id == guest_session.event_id,
            UserProfile.guest_session_id == guest_session.guest_session_id,
            UserProfile.user_id.is_(None),
            UserProfile.user_type == user_type,
            UserProfile.deleted_at.is_(None),
        )
        .limit(1)
    )


async def _ensure_persistent_profile(
    db: AsyncSession,
    *,
    guest_session: GuestSession,
    user_id: uuid.UUID,
    user_type: str,
    transfer_temporary_favorites: bool,
) -> tuple[UserProfile, int]:
    existing_profile = await _existing_persistent_profile(
        db, guest_session=guest_session, user_id=user_id, user_type=user_type
    )
    guest_profile = await _guest_profile(
        db, guest_session=guest_session, user_type=GUEST_TEMP_PROFILE_USER_TYPE
    )
    if existing_profile is not None:
        transferred_count = 0
        if guest_profile is not None:
            if transfer_temporary_favorites:
                transferred_count = await _move_temporary_favorites(
                    db,
                    from_profile_id=guest_profile.profile_id,
                    to_profile_id=existing_profile.profile_id,
                )
            guest_profile.profile_status = "INACTIVE"
            guest_profile.deleted_at = _now()
        return existing_profile, transferred_count
    if guest_profile is not None and transfer_temporary_favorites:
        transferred_count = await _favorite_count(db, guest_profile.profile_id)
        guest_profile.user_id = user_id
        guest_profile.guest_session_id = None
        guest_profile.user_type = user_type
        guest_profile.row_version += 1
        guest_profile.current_version += 1
        return guest_profile, transferred_count

    profile = UserProfile(
        tenant_id=guest_session.tenant_id,
        event_id=guest_session.event_id,
        user_id=user_id,
        user_type=user_type,
        profile_status="DRAFT",
        completeness_score=0,
    )
    db.add(profile)
    await db.flush()
    if guest_profile is not None:
        guest_profile.profile_status = "INACTIVE"
        guest_profile.deleted_at = _now()
    return profile, 0


async def _ensure_guest_profile(
    db: AsyncSession, guest_session: GuestSession
) -> UserProfile:
    profile = await _guest_profile(
        db,
        guest_session=guest_session,
        user_type=GUEST_TEMP_PROFILE_USER_TYPE,
    )
    if profile is not None:
        return profile

    profile = UserProfile(
        tenant_id=guest_session.tenant_id,
        event_id=guest_session.event_id,
        user_id=None,
        guest_session_id=guest_session.guest_session_id,
        user_type=GUEST_TEMP_PROFILE_USER_TYPE,
        profile_status="DRAFT",
        completeness_score=0,
    )
    db.add(profile)
    await db.flush()
    return profile


async def _favorite_count(db: AsyncSession, profile_id: uuid.UUID) -> int:
    count = await db.scalar(
        select(func.count())
        .select_from(SavedRecommendable)
        .where(SavedRecommendable.profile_id == profile_id)
    )
    return int(count or 0)


async def _move_temporary_favorites(
    db: AsyncSession,
    *,
    from_profile_id: uuid.UUID,
    to_profile_id: uuid.UUID,
) -> int:
    saved_rows = (
        await db.scalars(
            select(SavedRecommendable).where(
                SavedRecommendable.profile_id == from_profile_id
            )
        )
    ).all()
    transferred_count = 0
    for saved in saved_rows:
        existing = await db.scalar(
            select(SavedRecommendable.saved_recommendable_id).where(
                SavedRecommendable.profile_id == to_profile_id,
                SavedRecommendable.recommendable_id == saved.recommendable_id,
            )
        )
        if existing is not None:
            await db.delete(saved)
            continue
        saved.profile_id = to_profile_id
        transferred_count += 1
    return transferred_count


async def _convert_guest_session(
    *,
    payload: ConvertGuestWebSessionRequest,
    guest_session_id: uuid.UUID,
    context: ApiRequestContext,
    db: AsyncSession,
) -> ConvertGuestWebSessionResponse:
    if context.user_id is None:
        raise api_error(
            "AUTHENTICATION_REQUIRED",
            "로그인이 필요합니다.",
            status_code=401,
        )
    user_type = _target_db_user_type(context)
    await _require_user_account(db, context.user_id)
    guest_session = await _load_convertible_guest_session(
        db,
        guest_session_id,
        entry_code=payload.profile_link_token,
        require_entry_code=False,
    )
    profile, transferred_count = await _ensure_persistent_profile(
        db,
        guest_session=guest_session,
        user_id=context.user_id,
        user_type=user_type,
        transfer_temporary_favorites=payload.transfer_temporary_favorites,
    )

    await db.execute(
        update(VisitSession)
        .where(VisitSession.guest_session_id == guest_session.guest_session_id)
        .values(
            user_id=context.user_id,
            guest_session_id=None,
            profile_id=profile.profile_id,
        )
    )

    converted_at = _now()
    guest_session.converted_user_id = context.user_id
    guest_session.converted_at = converted_at
    guest_session.entry_code = None
    guest_session.expires_at = converted_at
    await db.commit()
    await db.refresh(profile)

    return ConvertGuestWebSessionResponse(
        profile=await _to_response(db, profile),
        transferred_favorite_count=transferred_count,
        converted_at=converted_at,
    )


@router.post(
    "/sessions",
    response_model=GuestWebSessionResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="startGuestWebSession",
)
async def start_guest_web_session(
    payload: StartGuestWebSessionRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GuestWebSessionResponse:
    event = await _event_or_404(db, payload.event_id)
    expires_at = _now() + timedelta(hours=DEFAULT_GUEST_WEB_TTL_HOURS)

    guest_session = GuestSession(
        tenant_id=event.tenant_id,
        event_id=event.event_id,
        session_token_hmac=_new_session_hmac(),
        entry_channel=GUEST_WEB_ENTRY_CHANNEL,
        device_type=GUEST_WEB_DEVICE_TYPE,
        language=payload.language,
        expires_at=expires_at,
    )
    db.add(guest_session)
    await db.commit()
    await db.refresh(guest_session)
    return await _session_response(db, guest_session)


@router.get(
    "/sessions/{guest_session_id}",
    response_model=GuestWebSessionResponse,
    operation_id="getGuestWebSession",
)
async def get_guest_web_session(
    guest_session_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GuestWebSessionResponse:
    guest_session = await _load_guest_web_session(
        db, guest_session_id, require_active=False
    )
    if _session_status(guest_session) == "EXPIRED":
        raise api_error(
            "GUEST_SESSION_EXPIRED",
            "게스트 웹 세션이 만료되었습니다.",
            status_code=410,
            details={"resource": "guest_session"},
        )
    return await _session_response(db, guest_session)


@router.post(
    "/sessions/{guest_session_id}/favorites",
    response_model=GuestFavoriteResponse,
    status_code=status.HTTP_201_CREATED,
    operation_id="addGuestWebFavorite",
)
async def add_guest_web_favorite(
    guest_session_id: uuid.UUID,
    payload: AddGuestFavoriteRequest,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> GuestFavoriteResponse:
    guest_session = await _load_guest_web_session(
        db, guest_session_id, require_active=True
    )
    await _ensure_active_recommendable(
        db, guest_session=guest_session, recommendable_id=payload.recommendable_id
    )
    profile = await _ensure_guest_profile(db, guest_session)
    saved = SavedRecommendable(
        profile_id=profile.profile_id,
        recommendable_id=payload.recommendable_id,
        saved_context_json=payload.saved_context_json,
    )
    db.add(saved)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise api_error(
            "RESOURCE_CONFLICT",
            "요청이 현재 상태와 충돌합니다.",
            status_code=409,
            details={"resource": "temporary_favorite"},
        ) from exc
    await db.refresh(saved)
    return _favorite_response(saved)


@router.delete(
    "/sessions/{guest_session_id}/favorites/{temporary_favorite_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="removeGuestWebFavorite",
)
async def remove_guest_web_favorite(
    guest_session_id: uuid.UUID,
    temporary_favorite_id: uuid.UUID,
    db: Annotated[AsyncSession, Depends(get_db)],
) -> Response:
    guest_session = await _load_guest_web_session(
        db, guest_session_id, require_active=True
    )
    profile = await _guest_profile(
        db,
        guest_session=guest_session,
        user_type=GUEST_TEMP_PROFILE_USER_TYPE,
    )
    if profile is not None:
        await db.execute(
            delete(SavedRecommendable).where(
                SavedRecommendable.saved_recommendable_id == temporary_favorite_id,
                SavedRecommendable.profile_id == profile.profile_id,
            )
        )
        await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/sessions/{guest_session_id}/convert",
    response_model=ConvertGuestWebSessionResponse,
    status_code=status.HTTP_200_OK,
    operation_id="convertGuestWebSession",
)
async def convert_guest_web_session(
    guest_session_id: uuid.UUID,
    payload: ConvertGuestWebSessionRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConvertGuestWebSessionResponse:
    return await _convert_guest_session(
        payload=payload,
        guest_session_id=guest_session_id,
        context=context,
        db=db,
    )


@router.post(
    "/convert",
    response_model=ConvertGuestResponse,
    status_code=status.HTTP_200_OK,
)
async def convert_guest(
    payload: ConvertGuestRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> ConvertGuestResponse:
    guest_session = await _load_convertible_guest_session(
        db,
        payload.guest_session_id,
        entry_code=payload.entry_code,
        require_entry_code=True,
    )
    converted = await _convert_guest_session(
        payload=ConvertGuestWebSessionRequest(
            transfer_temporary_favorites=True,
            profile_link_token=guest_session.entry_code,
        ),
        guest_session_id=payload.guest_session_id,
        context=context,
        db=db,
    )
    return ConvertGuestResponse(
        profile=converted.profile,
        converted_at=converted.converted_at,
    )
