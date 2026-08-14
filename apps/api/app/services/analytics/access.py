"""Role resolution/authorization for ``/admin/analytics/*``.

Role model reconciliation (read before editing)
--------------------------------------------------
See ``app/schemas/analytics.py`` module docstring ("Role model reconciliation
note") for the full rationale. Summary of the mapping this module enforces:

    DB profile.role.role_code (CONTRACTS-owned, 5 canonical values)
        ADMIN     -> may act as EVENT_ADMIN or DATA_REVIEWER
        OPERATOR  -> may act as EVENT_ADMIN or DATA_REVIEWER
        EXHIBITOR -> may ONLY act as EXHIBITOR_ADMIN, scoped to the
                     exhibitor_id already attached to their own
                     profile.user_role row (never a client-supplied value)
        VISITOR / BUYER / no role at all -> no analytics access (403)

A caller may narrow which of their permitted analytics roles they want to
act as for a given request via the optional ``X-Analytics-Role`` header.
This can only ever *narrow* access (e.g. an ADMIN choosing to view the
DATA_REVIEWER-scoped report), never widen it - the header is validated
against the DB-derived permitted set on every request, so a claim of
``EVENT_ADMIN`` from an actor who only holds the DB ``EXHIBITOR`` role is
rejected with 403, not silently downgraded or upgraded.

When no header is supplied, the default is the *broadest* role the actor's DB
role_code permits (EVENT_ADMIN for ADMIN/OPERATOR, EXHIBITOR_ADMIN for
EXHIBITOR) - this keeps the already-written admin dashboard call
(``getSearchAnalytics``, which sends no role header) working unmodified.

Per-endpoint role gating (which analytics role may call which
``/admin/analytics/*`` route) lives in ``ENDPOINT_ALLOWED_ROLES`` below and is
enforced by ``require_endpoint_access``.

ANALYST was collapsed onto DATA_REVIEWER at integration (merge plan STEP 23)
----------------------------------------------------------------------------
WAVE 2E defined a fourth analytics role, ``ANALYST``. The unified repo's real
authorization vocabulary is ``auth.role_grant.role``, whose
``auth_role_grant_role_allowed`` CHECK admits exactly EVENT_ADMIN /
DATA_REVIEWER / EXHIBITOR_ADMIN (``app/models/auth.py``). Widening that CHECK
to introduce a fourth grantable admin role is a schema change this port must
not make, and it is unnecessary: ANALYST's only reach beyond DATA_REVIEWER
(overview/web/kiosk) is already fully covered by EVENT_ADMIN. So ANALYST is
gone from the permitted set and from every ``ENDPOINT_ALLOWED_ROLES`` entry;
an ``X-Analytics-Role: ANALYST`` claim from an older client is *collapsed*
onto DATA_REVIEWER by :func:`normalize_claimed_role`, which is a narrowing
(DATA_REVIEWER reaches strictly fewer endpoints than ANALYST did) and is then
still validated against the DB-derived permitted set like any other claim.

Authentication
---------------
Identity is never taken from a request header. The router resolves
``actor_user_id`` through ``app/core/router_auth.py``'s ``get_actor_user_id``,
i.e. from a verified session/JWT principal, and additionally gates the whole
router behind ``require_roles(...)``. This module only answers the
*authorization* question (does this actor's real DB role permit this
analytics role/endpoint).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.identity import Role, UserRole
from app.schemas.analytics import ANALYTICS_ROLES, AnalyticsRole

#: DB role_codes (profile.role.role_code) that may act as either
#: EVENT_ADMIN or DATA_REVIEWER - i.e. "event staff".
_STAFF_DB_ROLE_CODES = ("ADMIN", "OPERATOR")
_STAFF_CLAIMABLE_ROLES: tuple[AnalyticsRole, ...] = ("EVENT_ADMIN", "DATA_REVIEWER")

#: Deprecated analytics-role spellings still accepted on ``X-Analytics-Role``
#: and collapsed onto a canonical role. Collapsing can only ever narrow: the
#: collapsed value is validated against the DB-derived permitted set exactly
#: like a directly-claimed role (see the module docstring).
DEPRECATED_ROLE_ALIASES: dict[str, AnalyticsRole] = {"ANALYST": "DATA_REVIEWER"}

#: Which of the 3 analytics roles may call which /admin/analytics/* endpoint.
#: - EVENT_ADMIN: full access everywhere.
#: - DATA_REVIEWER: "search/data-quality focus" per this track's prompt -
#:   restricted to the three search/quality-adjacent endpoints.
#: - EXHIBITOR_ADMIN: "their own company's limited stats only" - restricted
#:   to the one endpoint (buyer) that has a natural per-exhibitor scope;
#:   event-wide endpoints (overview/web/kiosk/searches/no-results/
#:   data-quality) aren't meaningfully scopable to a single exhibitor and
#:   would otherwise leak relative-to-competitors signal, so they're denied.
EndpointName = Literal[
    "overview", "web", "kiosk", "buyer", "searches", "no_results", "data_quality"
]

ENDPOINT_ALLOWED_ROLES: dict[EndpointName, frozenset[AnalyticsRole]] = {
    "overview": frozenset({"EVENT_ADMIN"}),
    "web": frozenset({"EVENT_ADMIN"}),
    "kiosk": frozenset({"EVENT_ADMIN"}),
    "buyer": frozenset({"EVENT_ADMIN", "EXHIBITOR_ADMIN"}),
    "searches": frozenset({"EVENT_ADMIN", "DATA_REVIEWER"}),
    "no_results": frozenset({"EVENT_ADMIN", "DATA_REVIEWER"}),
    "data_quality": frozenset({"EVENT_ADMIN", "DATA_REVIEWER"}),
}


def normalize_claimed_role(claimed: str) -> AnalyticsRole | None:
    """Map a raw ``X-Analytics-Role`` header value onto a canonical role.

    Returns ``None`` for a value that is neither canonical nor a recognised
    deprecated alias, so the router can answer 400 INVALID_ANALYTICS_ROLE
    rather than silently ignoring an unparseable claim.
    """

    if claimed in ANALYTICS_ROLES:
        return claimed  # type: ignore[return-value]
    return DEPRECATED_ROLE_ALIASES.get(claimed)


class AnalyticsAccessDenied(Exception):
    """Raised for any analytics authorization failure. The router maps this
    to HTTP 403 with ``reason`` as the error code (never a raw exception
    message, consistent with the rest of this repo's error-body convention)."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class AnalyticsAccessContext:
    """The resolved, authorized view a request is allowed to see."""

    role: AnalyticsRole
    event_id: uuid.UUID
    #: Set only when role == EXHIBITOR_ADMIN. Always server-resolved from the
    #: actor's own profile.user_role row - a request can never pass this in.
    exhibitor_id: uuid.UUID | None = None


async def resolve_analytics_access(
    db: AsyncSession,
    *,
    actor_user_id: uuid.UUID,
    event_id: uuid.UUID,
    claimed_role: AnalyticsRole | None,
) -> AnalyticsAccessContext:
    """Resolve which analytics role ``actor_user_id`` may act as for
    ``event_id``, honoring ``claimed_role`` only if the actor's real DB roles
    permit it. Raises :class:`AnalyticsAccessDenied` otherwise.
    """

    stmt = select(Role.role_code, UserRole.event_id, UserRole.exhibitor_id).join(
        UserRole, UserRole.role_id == Role.role_id
    ).where(
        UserRole.user_id == actor_user_id,
        UserRole.valid_until.is_(None),
    )
    rows = (await db.execute(stmt)).all()
    if not rows:
        raise AnalyticsAccessDenied("NO_ROLE_ASSIGNED")

    # "OPERATOR requires event_id" (db-erd 8.2절) - a global role row has
    # event_id NULL, an event-scoped one must match the requested event.
    staff_rows = [
        row
        for row in rows
        if row.role_code in _STAFF_DB_ROLE_CODES
        and (row.event_id is None or row.event_id == event_id)
    ]
    exhibitor_rows = [
        row for row in rows if row.role_code == "EXHIBITOR" and row.exhibitor_id is not None
    ]

    permitted: set[AnalyticsRole] = set()
    if staff_rows:
        permitted.update(_STAFF_CLAIMABLE_ROLES)
    if exhibitor_rows:
        permitted.add("EXHIBITOR_ADMIN")

    if not permitted:
        raise AnalyticsAccessDenied("INSUFFICIENT_ROLE")

    if claimed_role is not None:
        if claimed_role not in permitted:
            raise AnalyticsAccessDenied("ROLE_NOT_PERMITTED")
        effective_role: AnalyticsRole = claimed_role
    else:
        effective_role = "EVENT_ADMIN" if staff_rows else "EXHIBITOR_ADMIN"

    exhibitor_id: uuid.UUID | None = None
    if effective_role == "EXHIBITOR_ADMIN":
        if not exhibitor_rows:
            raise AnalyticsAccessDenied("ROLE_NOT_PERMITTED")
        # A staff member can also hold an EXHIBITOR row in theory; take the
        # first exhibitor_id this actor is actually attached to server-side -
        # never anything supplied by the request.
        exhibitor_id = exhibitor_rows[0].exhibitor_id

    return AnalyticsAccessContext(role=effective_role, event_id=event_id, exhibitor_id=exhibitor_id)


def require_endpoint_access(context: AnalyticsAccessContext, endpoint: EndpointName) -> None:
    """Raise :class:`AnalyticsAccessDenied` unless ``context.role`` is
    permitted to call ``endpoint`` (see ``ENDPOINT_ALLOWED_ROLES``)."""

    if context.role not in ENDPOINT_ALLOWED_ROLES[endpoint]:
        raise AnalyticsAccessDenied("ENDPOINT_NOT_PERMITTED")
