"""Buyer-profile persistence and mutation logic (HTTP-agnostic - see errors.py).

The router (``app/api/v1/routers/buyer_profile.py``) is a thin HTTP adapter over this module,
matching how ``app/api/v1/routers/exhibition_public.py`` sits over its own ``service`` module and
``app/api/v1/routers/recommendations.py`` sits over ``app/services/matching/orchestrator.py`` -
both patterns this codebase already uses so router-level tests can monkeypatch a plain async
function instead of faking a full ``AsyncSession`` (see ``tests/test_exhibition_public_api.py``'s
``_standalone_app`` + ``monkeypatch.setattr(service, ...)`` convention, which
``tests/test_buyer_profile_api.py`` follows).
"""

from __future__ import annotations

import uuid
from functools import lru_cache

from meet_ai.ontology import Catalog, load_catalog
from meet_ai.ontology.catalog import stable_uuid
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.buyer_profile import BuyerProfile, BuyerProfileCode
from app.schemas.buyer_profile import BuyerProfilePatchRequest
from app.services.buyer_profile.errors import (
    UnknownOntologyCodeError,
    VersionConflictError,
)

#: ``BuyerProfilePatchRequest`` field name -> ``BuyerProfileCode.code_group`` value.
#: Single source of truth for which request field feeds which normalized code group
#: (module docstring "Ontology-code normalization" in app/models/buyer_profile.py).
FIELD_TO_CODE_GROUP: dict[str, str] = {
    "industry_codes": "INDUSTRY",
    "interest_codes": "INTEREST",
    "channel_codes": "CHANNEL",
    "preferred_region_codes": "PREFERRED_REGION",
    "cooperation_codes": "COOPERATION",
}


@lru_cache(maxsize=1)
def _catalog() -> Catalog:
    return load_catalog()


def _resolve_concept(field: str, code: str) -> tuple[uuid.UUID, uuid.UUID]:
    """Validate ``code`` against the canonical catalog, returning its stable IDs.

    Raises ``UnknownOntologyCodeError`` (never lets a bare ``KeyError`` escape) so the router
    can turn it into a 422 with a precise ``field``/``code`` pair - AGENTS.md invariant: "AI must
    never assert a value the source text does not contain" extends here to "the API must never
    persist a code the canonical catalog does not contain".
    """

    catalog = _catalog()
    try:
        catalog.get(code)
    except KeyError as exc:
        raise UnknownOntologyCodeError(field, code) from exc
    return stable_uuid("concept", code), stable_uuid("taxonomy-version", catalog.version)


def buyer_profile_lookup_stmt(tenant_id: uuid.UUID, user_id: uuid.UUID) -> Select:
    """The exact ``SELECT`` used to find a user's buyer profile - exposed so tests can compile
    it and assert the tenant/user boundary without a live database (mirrors
    ``app/services/catalog_search.py``'s ``_candidate_pool_stmt`` + its
    ``tests/test_search_api.py::_compiled_where`` counterpart)."""

    return select(BuyerProfile).where(
        BuyerProfile.tenant_id == tenant_id, BuyerProfile.user_id == user_id
    )


async def find_buyer_profile(
    db: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> BuyerProfile | None:
    result = await db.execute(buyer_profile_lookup_stmt(tenant_id, user_id))
    return result.scalars().first()


async def get_or_create_buyer_profile(
    db: AsyncSession, *, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> BuyerProfile:
    """Find the caller's buyer profile, or create an empty ``UNVERIFIED`` one on first access.

    Mirrors ``app/api/v1/routers/profile.py``'s ``_get_or_create_profile`` - this repo's
    established idiom for "GET /me/... creates the row on first touch" endpoints, since there is
    no separate "create buyer profile" step in the task spec.
    """

    profile = await find_buyer_profile(db, tenant_id=tenant_id, user_id=user_id)
    if profile is not None:
        return profile
    profile = BuyerProfile(tenant_id=tenant_id, user_id=user_id)
    db.add(profile)
    await db.flush()
    return profile


async def get_buyer_profile_by_id(
    db: AsyncSession, buyer_profile_id: uuid.UUID
) -> BuyerProfile | None:
    return await db.get(BuyerProfile, buyer_profile_id)


async def apply_patch(
    db: AsyncSession, profile: BuyerProfile, patch: BuyerProfilePatchRequest
) -> BuyerProfile:
    """Apply a validated ``PATCH /me/buyer-profile`` body to ``profile`` and flush.

    Order matters: the optimistic-concurrency check runs first (cheap, no catalog work wasted
    on a request that's stale anyway), then *every* ontology code across *all* provided groups
    is validated before anything is mutated (fail fast, all-or-nothing - matches
    ``app/api/v1/routers/profile.py``'s ``_resolve_concept`` usage, which never leaves a
    partially-applied group behind).
    """

    if patch.version != profile.version:
        raise VersionConflictError(expected=patch.version, actual=profile.version)

    resolved_groups: dict[str, list[tuple[str, uuid.UUID, uuid.UUID]]] = {}
    for field_name, group in FIELD_TO_CODE_GROUP.items():
        codes = getattr(patch, field_name)
        if codes is None:
            continue
        resolved: list[tuple[str, uuid.UUID, uuid.UUID]] = []
        seen: set[str] = set()
        for code in codes:
            if code in seen:
                continue
            seen.add(code)
            concept_id, taxonomy_version_id = _resolve_concept(field_name, code)
            resolved.append((code, concept_id, taxonomy_version_id))
        resolved_groups[group] = resolved

    if patch.buyer_type is not None:
        profile.buyer_type = patch.buyer_type
    if patch.order_scale_code is not None:
        profile.order_scale_code = patch.order_scale_code
    if patch.decision_timeline is not None:
        profile.decision_timeline = patch.decision_timeline

    for group, resolved in resolved_groups.items():
        profile.codes = [row for row in profile.codes if row.code_group != group]
        for code, concept_id, taxonomy_version_id in resolved:
            profile.codes.append(
                BuyerProfileCode(
                    buyer_profile_id=profile.buyer_profile_id,
                    code_group=group,
                    taxonomy_version_id=taxonomy_version_id,
                    concept_id=concept_id,
                    attribute_code=code,
                )
            )

    profile.version += 1
    await db.flush()
    return profile
