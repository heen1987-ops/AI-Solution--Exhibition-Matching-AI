"""Protected profile endpoints."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.v1.dependencies import (
    ApiRequestContext,
    get_request_context,
    require_persistent_profile,
)
from app.api.v1.errors import api_error
from app.db.session import get_db
from app.models.ontology_refs import concept, concept_revision
from app.models.profile import BuyerNeed, ProfileAttribute, ProfileVersion, UserProfile

router = APIRouter()

ApiProfileType = Literal["GENERAL_REGISTERED", "BUYER_REGISTERED"]
RequirementLevel = Literal["REQUIRED", "PREFERRED", "ACCEPTABLE", "EXCLUDED"]
ProfileSourceType = Literal[
    "USER_SELECTED",
    "USER_EDITED",
    "REGISTRATION",
    "BEHAVIOR_SINGLE",
    "AI_EXTRACTED",
]

_DB_TO_API_USER_TYPE = {
    "GENERAL_VISITOR": "GENERAL_REGISTERED",
    "BUYER": "BUYER_REGISTERED",
}


class ProfileAttributeItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    attribute_code: str = Field(min_length=3, max_length=100)
    requirement_level: RequirementLevel
    source_type: ProfileSourceType = "USER_EDITED"


class UserProfileResponse(BaseModel):
    profile_id: uuid.UUID
    user_type: ApiProfileType
    profile_status: str
    completeness_score: float
    row_version: int
    attributes: list[ProfileAttributeItem]
    buyer_need: dict[str, Any] | None = None


class UpdateProfileAttributesRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    row_version: int = Field(ge=1)
    attributes: list[ProfileAttributeItem] = Field(default_factory=list, max_length=100)


def _decimal_to_float(value: Decimal | float) -> float:
    return float(value)


def _snapshot_hash(snapshot: dict[str, Any]) -> bytes:
    return hashlib.sha256(repr(sorted(snapshot.items())).encode("utf-8")).digest()


def _api_user_type(profile: UserProfile) -> ApiProfileType:
    mapped = _DB_TO_API_USER_TYPE.get(profile.user_type)
    if mapped is None:
        raise api_error(
            "VALIDATION_ERROR",
            "요청 값이 올바르지 않습니다.",
            status_code=422,
            details={"field": "user_type"},
        )
    return mapped  # type: ignore[return-value]


async def _get_profile(db: AsyncSession, profile_id: uuid.UUID) -> UserProfile:
    profile = await db.get(UserProfile, profile_id)
    if profile is None or profile.deleted_at is not None:
        raise api_error(
            "RESOURCE_NOT_FOUND",
            "요청한 대상을 찾을 수 없습니다.",
            status_code=404,
            details={"resource": "profile"},
        )
    return profile


async def _profile_attributes(
    db: AsyncSession, profile_id: uuid.UUID
) -> list[ProfileAttribute]:
    rows = await db.scalars(
        select(ProfileAttribute)
        .where(
            ProfileAttribute.profile_id == profile_id,
            ProfileAttribute.active.is_(True),
        )
        .order_by(ProfileAttribute.created_at.asc())
    )
    return list(rows.all())


def _buyer_need_to_dict(buyer_need: BuyerNeed | None) -> dict[str, Any] | None:
    if buyer_need is None:
        return None
    return {
        "organization_type": buyer_need.organization_type,
        "target_price_min_amount": buyer_need.target_price_min_amount,
        "target_price_max_amount": buyer_need.target_price_max_amount,
        "currency": buyer_need.currency,
        "price_basis": buyer_need.price_basis,
        "monthly_units_min": buyer_need.monthly_units_min,
        "monthly_units_max": buyer_need.monthly_units_max,
        "decision_timeline": buyer_need.decision_timeline,
        "business_email_verified": buyer_need.business_email_verified,
        "company_verified": buyer_need.company_verified,
    }


async def _to_response(db: AsyncSession, profile: UserProfile) -> UserProfileResponse:
    attributes = await _profile_attributes(db, profile.profile_id)
    return UserProfileResponse(
        profile_id=profile.profile_id,
        user_type=_api_user_type(profile),
        profile_status=profile.profile_status,
        completeness_score=_decimal_to_float(profile.completeness_score),
        row_version=profile.row_version,
        attributes=[
            ProfileAttributeItem(
                attribute_code=attribute.attribute_code,
                requirement_level=attribute.requirement_level,  # type: ignore[arg-type]
                source_type=attribute.source_type,  # type: ignore[arg-type]
            )
            for attribute in attributes
        ],
        buyer_need=_buyer_need_to_dict(profile.buyer_need),
    )


async def _resolve_attribute_code(
    db: AsyncSession, attribute_code: str
) -> tuple[uuid.UUID, uuid.UUID]:
    row = (
        await db.execute(
            select(
                concept_revision.c.taxonomy_version_id,
                concept_revision.c.concept_id,
            )
            .join(concept, concept.c.concept_id == concept_revision.c.concept_id)
            .where(
                concept.c.concept_code == attribute_code,
                concept_revision.c.assignable.is_(True),
                concept_revision.c.status == "ACTIVE",
            )
            .limit(1)
        )
    ).first()
    if row is None:
        raise api_error(
            "VALIDATION_ERROR",
            "요청 값이 올바르지 않습니다.",
            status_code=422,
            details={"field": "attributes.attribute_code", "value": attribute_code},
        )
    return row.taxonomy_version_id, row.concept_id


def _snapshot(profile: UserProfile, attributes: list[ProfileAttribute]) -> dict[str, Any]:
    return {
        "profile_id": str(profile.profile_id),
        "user_type": profile.user_type,
        "profile_status": profile.profile_status,
        "completeness_score": str(profile.completeness_score),
        "row_version": profile.row_version,
        "attributes": [
            {
                "attribute_code": attribute.attribute_code,
                "requirement_level": attribute.requirement_level,
                "source_type": attribute.source_type,
            }
            for attribute in attributes
        ],
    }


@router.get("/me", response_model=UserProfileResponse, operation_id="getMyProfile")
async def get_my_profile(
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserProfileResponse:
    profile_id = require_persistent_profile(context)
    profile = await _get_profile(db, profile_id)
    return await _to_response(db, profile)


@router.patch(
    "/me/attributes",
    response_model=UserProfileResponse,
    operation_id="patchMyProfileAttributes",
)
async def patch_my_profile_attributes(
    payload: UpdateProfileAttributesRequest,
    context: Annotated[ApiRequestContext, Depends(get_request_context)],
    db: Annotated[AsyncSession, Depends(get_db)],
) -> UserProfileResponse:
    profile_id = require_persistent_profile(context)
    profile = await _get_profile(db, profile_id)
    if profile.row_version != payload.row_version:
        raise api_error(
            "RESOURCE_CONFLICT",
            "요청이 현재 상태와 충돌합니다.",
            status_code=409,
            details={"resource": "profile", "field": "row_version"},
        )

    resolved_attributes = [
        (item, await _resolve_attribute_code(db, item.attribute_code))
        for item in payload.attributes
    ]
    await db.execute(
        delete(ProfileAttribute).where(ProfileAttribute.profile_id == profile.profile_id)
    )
    for item, (taxonomy_version_id, concept_id) in resolved_attributes:
        db.add(
            ProfileAttribute(
                profile_id=profile.profile_id,
                taxonomy_version_id=taxonomy_version_id,
                concept_id=concept_id,
                attribute_code=item.attribute_code,
                value_json={"selected": True},
                requirement_level=item.requirement_level,
                source_type="USER_EDITED",
                confidence=1,
                active=True,
            )
        )

    profile.row_version += 1
    profile.current_version += 1
    profile.updated_at = datetime.now(UTC)
    await db.flush()
    attributes = await _profile_attributes(db, profile.profile_id)
    snapshot = _snapshot(profile, attributes)
    db.add(
        ProfileVersion(
            profile_id=profile.profile_id,
            version_number=profile.current_version,
            snapshot_json=snapshot,
            snapshot_hash=_snapshot_hash(snapshot),
            change_reason="USER_UPDATE",
        )
    )
    await db.commit()
    await db.refresh(profile)
    return await _to_response(db, profile)
