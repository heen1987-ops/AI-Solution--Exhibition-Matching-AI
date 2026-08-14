"""Pydantic request/response models for ``GET``/``PATCH /me/buyer-profile``.

Docstring note on why ``verification_status`` never appears on the request model: the task spec
requires "verification_status ... buyer cannot change this themselves, only an operator-only
mutation path can". ``BuyerProfilePatchRequest`` has ``model_config = ConfigDict(extra="forbid")``
precisely so a client that tries to smuggle ``"verification_status": "VERIFIED"`` (or any other
unknown field) into the body gets a clear 422 instead of the field being silently dropped.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from app.models.buyer_profile import BUYER_TYPES

BuyerType = Literal[
    "DISTRIBUTOR",
    "RETAILER",
    "ONLINE_COMMERCE",
    "IMPORTER",
    "EXPORTER",
    "MANUFACTURER",
    "PUBLIC_BUYER",
    "CORPORATE_BUYER",
    "INVESTOR",
    "OTHER",
]

# Keep the Literal and the model's CHECK constraint from silently drifting apart.
assert set(BuyerType.__args__) == set(BUYER_TYPES)  # type: ignore[attr-defined]

_CODE_LIST_MAX_LENGTH = 50


class BuyerProfilePatchRequest(BaseModel):
    """PATCH body. Every field is optional except ``version`` - only fields actually present
    are changed (partial update); a present list field fully replaces that code group (matches
    ``app/api/v1/routers/profile.py``'s PUT-style "this is the whole group now" semantics for
    ``distribution_channels``/``desired_categories``/etc., just reused under PATCH here since
    there is no separate PUT endpoint in this task's contract)."""

    model_config = ConfigDict(extra="forbid")

    version: int = Field(ge=1)
    buyer_type: BuyerType | None = None
    industry_codes: list[str] | None = Field(default=None, max_length=_CODE_LIST_MAX_LENGTH)
    interest_codes: list[str] | None = Field(default=None, max_length=_CODE_LIST_MAX_LENGTH)
    channel_codes: list[str] | None = Field(default=None, max_length=_CODE_LIST_MAX_LENGTH)
    preferred_region_codes: list[str] | None = Field(
        default=None, max_length=_CODE_LIST_MAX_LENGTH
    )
    cooperation_codes: list[str] | None = Field(default=None, max_length=_CODE_LIST_MAX_LENGTH)
    order_scale_code: str | None = Field(default=None, max_length=50)
    decision_timeline: str | None = Field(default=None, max_length=30)


class BuyerProfileView(BaseModel):
    """``GET``/``PATCH`` response body (also used for the by-id lookup endpoint)."""

    buyer_profile_id: uuid.UUID
    buyer_type: str
    industry_codes: list[str]
    interest_codes: list[str]
    channel_codes: list[str]
    preferred_region_codes: list[str]
    cooperation_codes: list[str]
    order_scale_code: str | None
    decision_timeline: str | None
    verification_status: str
    version: int
    created_at: datetime
    updated_at: datetime
