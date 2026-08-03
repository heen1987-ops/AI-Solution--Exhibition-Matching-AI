"""Shared v1 API dependencies.

Real authentication is not in this wave yet.  BAC-002 provides an explicit
local/test request context so protected API work can enforce profile/role
boundaries without adding signup, PII collection, or kiosk identity state.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Annotated, Literal, cast

from fastapi import Header

from app.api.v1.errors import api_error

ApiUserType = Literal["GENERAL_REGISTERED", "BUYER_REGISTERED", "GUEST_WEB"]
ActorRole = Literal["VISITOR", "BUYER", "EXHIBITOR", "OPERATOR", "ADMIN"]


@dataclass(frozen=True)
class ApiRequestContext:
    profile_id: uuid.UUID | None
    user_id: uuid.UUID | None
    user_type: ApiUserType
    actor_role: ActorRole

    @property
    def has_persistent_profile(self) -> bool:
        return self.profile_id is not None and self.user_type != "GUEST_WEB"


def _parse_uuid_header(raw_value: str | None, header_name: str) -> uuid.UUID | None:
    if raw_value is None or not raw_value.strip():
        return None
    try:
        return uuid.UUID(raw_value)
    except ValueError:
        raise api_error(
            "VALIDATION_ERROR",
            "요청 값이 올바르지 않습니다.",
            status_code=422,
            details={"field": header_name},
        ) from None


def _default_actor_role(user_type: str) -> ActorRole:
    if user_type == "BUYER_REGISTERED":
        return "BUYER"
    return "VISITOR"


async def get_request_context(
    x_meetai_profile_id: Annotated[str | None, Header()] = None,
    x_meetai_user_id: Annotated[str | None, Header()] = None,
    x_meetai_user_type: Annotated[str | None, Header()] = None,
    x_meetai_actor_role: Annotated[str | None, Header()] = None,
) -> ApiRequestContext:
    """Build an API context from explicit non-PII local/test headers.

    Headers:
      - X-MeetAI-Profile-Id: UUID of profile.user_profile.profile_id.
      - X-MeetAI-User-Id: UUID of profile.user_account.user_id for operators.
      - X-MeetAI-User-Type: GENERAL_REGISTERED, BUYER_REGISTERED, or GUEST_WEB.
      - X-MeetAI-Actor-Role: VISITOR, BUYER, EXHIBITOR, OPERATOR, or ADMIN.
    """

    normalized_user_type = (x_meetai_user_type or "GENERAL_REGISTERED").upper()
    if normalized_user_type not in {
        "GENERAL_REGISTERED",
        "BUYER_REGISTERED",
        "GUEST_WEB",
    }:
        raise api_error(
            "VALIDATION_ERROR",
            "요청 값이 올바르지 않습니다.",
            status_code=422,
            details={"field": "X-MeetAI-User-Type"},
        )
    normalized_actor_role = (
        x_meetai_actor_role or _default_actor_role(normalized_user_type)
    ).upper()
    if normalized_actor_role not in {
        "VISITOR",
        "BUYER",
        "EXHIBITOR",
        "OPERATOR",
        "ADMIN",
    }:
        raise api_error(
            "VALIDATION_ERROR",
            "요청 값이 올바르지 않습니다.",
            status_code=422,
            details={"field": "X-MeetAI-Actor-Role"},
        )

    return ApiRequestContext(
        profile_id=_parse_uuid_header(x_meetai_profile_id, "X-MeetAI-Profile-Id"),
        user_id=_parse_uuid_header(x_meetai_user_id, "X-MeetAI-User-Id"),
        user_type=cast(ApiUserType, normalized_user_type),
        actor_role=cast(ActorRole, normalized_actor_role),
    )


def require_persistent_profile(context: ApiRequestContext) -> uuid.UUID:
    if context.user_type == "GUEST_WEB":
        raise api_error(
            "PERMISSION_DENIED",
            "이 작업을 수행할 권한이 없습니다.",
            status_code=403,
        )
    if context.profile_id is None:
        raise api_error(
            "AUTHENTICATION_REQUIRED",
            "로그인이 필요합니다.",
            status_code=401,
        )
    return context.profile_id


def require_buyer(context: ApiRequestContext) -> uuid.UUID:
    profile_id = require_persistent_profile(context)
    if context.user_type != "BUYER_REGISTERED":
        raise api_error(
            "PERMISSION_DENIED",
            "이 작업을 수행할 권한이 없습니다.",
            status_code=403,
        )
    return profile_id


def require_operator(context: ApiRequestContext) -> uuid.UUID:
    if context.actor_role not in {"OPERATOR", "ADMIN"}:
        raise api_error(
            "PERMISSION_DENIED",
            "이 작업을 수행할 권한이 없습니다.",
            status_code=403,
        )
    if context.user_id is None:
        raise api_error(
            "AUTHENTICATION_REQUIRED",
            "로그인이 필요합니다.",
            status_code=401,
        )
    return context.user_id
