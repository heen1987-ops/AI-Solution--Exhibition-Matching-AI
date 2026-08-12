"""interaction.favorite CRUD service layer (BACKEND-009).

Scope: this package owns the query/mutation logic behind ``GET/POST/DELETE
/me/favorites[/{favorite_id}]`` (``app/api/v1/routers/favorites.py``). The model, its
ownership/dedup/soft-delete constraints, and the Alembic migration are CONTRACT-005's
(``app/models/favorite.py`` - read that module's docstring first, it is the source of truth
this file implements against).

Target resolution reuses the established mapping, it does not reinvent one
--------------------------------------------------------------------------------------------
``app/api/v1/routers/recommendations.py::_resolve_recommendable_id`` already resolves a
caller-supplied ``(object_type, object_id)`` pair to a ``Recommendable.recommendable_id`` for
interaction events. :func:`resolve_recommendable_id` below mirrors that function's
object_type branch exactly (same per-type joins: ``BOOTH``/``PROGRAM`` are direct
``Recommendable`` columns, ``PRODUCT`` joins through ``EventProduct.product_id``, ``EXHIBITOR``
joins through ``ExhibitorParticipation.exhibitor_id`` because ``Recommendable`` itself stores
``participation_id`` - see that function's comment). It is not imported directly because it is
coupled to ``InteractionEventIn`` (requires ``recommendation_session_id`` whenever
``match_result_id`` is set, an ``occurred_at`` timestamp, etc.) which does not fit a favorite
request; duplicating just the object_type->recommendable_id mapping here keeps the two call
sites consistent without forcing favorites through unrelated interaction-event validation.

Ownership / anonymous support
--------------------------------------------------------------------------------------------
Every function below takes ``user_id: UUID | None`` and ``guest_session_id: UUID | None``
exactly one of which the caller must supply - mirroring ``app/models/favorite.py``'s
``CHECK num_nonnulls(user_id, guest_session_id) = 1`` and the ``CurrentSubject`` shape already
used by ``app/api/v1/routers/profile.py::get_current_subject`` (the anonymous-or-authenticated
identity dependency this router reuses; see that module's docstring for why cross-router reuse
of that dependency is this repo's convention, not a new one).

Idempotent create
--------------------------------------------------------------------------------------------
``app/models/favorite.py`` enforces "one active favorite per owner+recommendable" with two
partial-unique indexes. :func:`create_favorite` pre-checks for an existing active row (the
common, non-racy path) and additionally catches ``IntegrityError`` around the insert as a
race-window fallback (two concurrent requests for the same owner+recommendable) - either path
returns the existing active row instead of letting a raw constraint violation reach the
caller as a 500, per this track's acceptance criteria.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Literal

from sqlalchemy import ColumnElement, Select, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.exhibitor import EventProduct, ExhibitorParticipation
from app.models.favorite import Favorite
from app.models.matching import MatchResult, Recommendable

FavoriteObjectType = Literal["EXHIBITOR", "PRODUCT", "BOOTH", "PROGRAM"]

#: Recommendable.object_type (CHECK-constrained to BOOTH/EVENT_PRODUCT/EXHIBITOR/PROGRAM) ->
#: the caller-facing object_type this API accepts/returns. Only PRODUCT differs from the
#: internal name (EVENT_PRODUCT) - same naming split app/api/v1/routers/recommendations.py's
#: InteractionEventIn.object_type already uses.
RECOMMENDABLE_TYPE_TO_PUBLIC: dict[str, FavoriteObjectType] = {
    "BOOTH": "BOOTH",
    "EVENT_PRODUCT": "PRODUCT",
    "EXHIBITOR": "EXHIBITOR",
    "PROGRAM": "PROGRAM",
}

_DIRECT_COLUMNS: dict[str, ColumnElement[uuid.UUID | None]] = {
    "BOOTH": Recommendable.booth_id,
    "PROGRAM": Recommendable.program_id,
}


class InvalidMatchResultError(Exception):
    """The caller-supplied match_result_id does not exist in this tenant/event."""


@dataclass(frozen=True)
class FavoriteWithTarget:
    favorite: Favorite
    object_type: FavoriteObjectType
    object_id: uuid.UUID


def _owner_clause(
    *, user_id: uuid.UUID | None, guest_session_id: uuid.UUID | None
) -> ColumnElement[bool]:
    """Exactly one of user_id/guest_session_id is set - app/models/favorite.py's
    ``subject_exactly_one`` CHECK, mirrored here rather than trusted to the caller."""

    if user_id is not None:
        return Favorite.user_id == user_id
    if guest_session_id is not None:
        return Favorite.guest_session_id == guest_session_id
    raise ValueError("either user_id or guest_session_id is required")


async def resolve_recommendable_id(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    object_type: FavoriteObjectType,
    object_id: uuid.UUID,
) -> uuid.UUID | None:
    """(object_type, object_id) -> recommendable_id, or None if it does not resolve to an
    existing target in this tenant/event. See module docstring."""

    if object_type == "PRODUCT":
        return await db.scalar(
            select(Recommendable.recommendable_id)
            .join(
                EventProduct,
                EventProduct.event_product_id == Recommendable.event_product_id,
            )
            .where(
                EventProduct.product_id == object_id,
                Recommendable.tenant_id == tenant_id,
                Recommendable.event_id == event_id,
            )
            .limit(1)
        )

    if object_type == "EXHIBITOR":
        # 공개 object_id는 exhibitor_id지만 recommendable은 participation_id를 저장한다 -
        # app/api/v1/routers/recommendations.py::_resolve_recommendable_id와 동일한 2단계 조회.
        participation_id = await db.scalar(
            select(ExhibitorParticipation.participation_id).where(
                ExhibitorParticipation.exhibitor_id == object_id,
                ExhibitorParticipation.tenant_id == tenant_id,
                ExhibitorParticipation.event_id == event_id,
            )
        )
        if participation_id is None:
            return None
        return await db.scalar(
            select(Recommendable.recommendable_id).where(
                Recommendable.participation_id == participation_id,
                Recommendable.tenant_id == tenant_id,
                Recommendable.event_id == event_id,
            )
        )

    column = _DIRECT_COLUMNS.get(object_type)
    if column is None:
        return None
    return await db.scalar(
        select(Recommendable.recommendable_id).where(
            column == object_id,
            Recommendable.tenant_id == tenant_id,
            Recommendable.event_id == event_id,
        )
    )


def active_favorite_for_target_stmt(
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    user_id: uuid.UUID | None,
    guest_session_id: uuid.UUID | None,
    recommendable_id: uuid.UUID,
) -> Select[tuple[Favorite]]:
    return select(Favorite).where(
        Favorite.tenant_id == tenant_id,
        Favorite.event_id == event_id,
        _owner_clause(user_id=user_id, guest_session_id=guest_session_id),
        Favorite.recommendable_id == recommendable_id,
        Favorite.deleted_at.is_(None),
    )


def own_favorite_stmt(
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    user_id: uuid.UUID | None,
    guest_session_id: uuid.UUID | None,
    favorite_id: uuid.UUID,
) -> Select[tuple[Favorite]]:
    """Scoped by id AND owner in one WHERE clause (never a post-filter) - a favorite_id
    belonging to a different owner resolves to None here exactly like "not found", the same
    convention ``app/services/notification/service.py::own_notification_stmt`` uses."""

    return select(Favorite).where(
        Favorite.favorite_id == favorite_id,
        Favorite.tenant_id == tenant_id,
        Favorite.event_id == event_id,
        _owner_clause(user_id=user_id, guest_session_id=guest_session_id),
    )


def list_favorites_stmt(
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    user_id: uuid.UUID | None,
    guest_session_id: uuid.UUID | None,
    limit: int,
    before: datetime | None,
) -> Select[tuple[Favorite, str, uuid.UUID | None, uuid.UUID | None, uuid.UUID | None, uuid.UUID | None]]:
    """One query, no N+1: joins Recommendable for object_type/direct target columns, and
    outer-joins EventProduct/ExhibitorParticipation to translate the two indirect target
    types (PRODUCT, EXHIBITOR) back to their public id - the reverse of
    :func:`resolve_recommendable_id`, same per-type mapping ``app/services/matching/
    candidate_generator.py`` already uses when it builds ``public_object_id`` for recommendation
    candidates."""

    stmt = (
        select(
            Favorite,
            Recommendable.object_type,
            Recommendable.booth_id,
            Recommendable.program_id,
            EventProduct.product_id,
            ExhibitorParticipation.exhibitor_id,
        )
        .join(
            Recommendable,
            (Recommendable.tenant_id == Favorite.tenant_id)
            & (Recommendable.event_id == Favorite.event_id)
            & (Recommendable.recommendable_id == Favorite.recommendable_id),
        )
        .outerjoin(
            EventProduct, EventProduct.event_product_id == Recommendable.event_product_id
        )
        .outerjoin(
            ExhibitorParticipation,
            ExhibitorParticipation.participation_id == Recommendable.participation_id,
        )
        .where(
            Favorite.tenant_id == tenant_id,
            Favorite.event_id == event_id,
            _owner_clause(user_id=user_id, guest_session_id=guest_session_id),
            Favorite.deleted_at.is_(None),
        )
        .order_by(Favorite.created_at.desc(), Favorite.favorite_id.desc())
        .limit(limit)
    )
    if before is not None:
        stmt = stmt.where(Favorite.created_at < before)
    return stmt


async def list_favorites(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    user_id: uuid.UUID | None,
    guest_session_id: uuid.UUID | None,
    limit: int,
    before: datetime | None = None,
) -> list[FavoriteWithTarget]:
    rows = await db.execute(
        list_favorites_stmt(
            tenant_id=tenant_id,
            event_id=event_id,
            user_id=user_id,
            guest_session_id=guest_session_id,
            limit=limit,
            before=before,
        )
    )
    results: list[FavoriteWithTarget] = []
    for favorite, object_type, booth_id, program_id, product_id, exhibitor_id in rows:
        if object_type == "BOOTH":
            object_id = booth_id
        elif object_type == "EVENT_PRODUCT":
            object_id = product_id
        elif object_type == "EXHIBITOR":
            object_id = exhibitor_id
        else:
            object_id = program_id
        assert object_id is not None  # exactly_one_target CHECK on Recommendable guarantees this
        results.append(
            FavoriteWithTarget(
                favorite=favorite,
                object_type=RECOMMENDABLE_TYPE_TO_PUBLIC[object_type],
                object_id=object_id,
            )
        )
    return results


async def create_favorite(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    user_id: uuid.UUID | None,
    guest_session_id: uuid.UUID | None,
    recommendable_id: uuid.UUID,
    source: str,
    match_result_id: uuid.UUID | None,
) -> tuple[Favorite, bool]:
    """Returns ``(favorite, created)``. ``created=False`` means an existing active favorite for
    this owner+recommendable was returned instead of inserting a duplicate."""

    existing = await db.scalar(
        active_favorite_for_target_stmt(
            tenant_id=tenant_id,
            event_id=event_id,
            user_id=user_id,
            guest_session_id=guest_session_id,
            recommendable_id=recommendable_id,
        )
    )
    if existing is not None:
        return existing, False

    if match_result_id is not None:
        found = await db.scalar(
            select(MatchResult.match_result_id).where(
                MatchResult.match_result_id == match_result_id,
                MatchResult.tenant_id == tenant_id,
                MatchResult.event_id == event_id,
            )
        )
        if found is None:
            raise InvalidMatchResultError(str(match_result_id))

    favorite = Favorite(
        tenant_id=tenant_id,
        event_id=event_id,
        user_id=user_id,
        guest_session_id=guest_session_id,
        recommendable_id=recommendable_id,
        source=source,
        match_result_id=match_result_id,
    )
    db.add(favorite)
    try:
        await db.commit()
    except IntegrityError:
        # Race window: another request for the same owner+recommendable committed between our
        # pre-check and our insert. Never let the raw constraint violation reach the caller -
        # fall back to the row that won the race.
        await db.rollback()
        existing = await db.scalar(
            active_favorite_for_target_stmt(
                tenant_id=tenant_id,
                event_id=event_id,
                user_id=user_id,
                guest_session_id=guest_session_id,
                recommendable_id=recommendable_id,
            )
        )
        if existing is not None:
            return existing, False
        raise
    await db.refresh(favorite)
    return favorite, True


async def soft_delete_favorite(
    db: AsyncSession,
    *,
    tenant_id: uuid.UUID,
    event_id: uuid.UUID,
    user_id: uuid.UUID | None,
    guest_session_id: uuid.UUID | None,
    favorite_id: uuid.UUID,
    now: datetime,
) -> bool:
    """Soft-deletes (sets deleted_at) the caller's own favorite. Returns False - never raises -
    when the id does not exist, is already deleted, or belongs to a different owner, so the
    router can uniformly answer 404 for all three without disclosing which one it was."""

    favorite = await db.scalar(
        own_favorite_stmt(
            tenant_id=tenant_id,
            event_id=event_id,
            user_id=user_id,
            guest_session_id=guest_session_id,
            favorite_id=favorite_id,
        )
    )
    if favorite is None or favorite.deleted_at is not None:
        return False
    favorite.deleted_at = now
    await db.commit()
    return True
