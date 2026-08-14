"""Current-position resolution for the AI-recommended visit route feature (U-13).

THIS MODULE IS THE INTEGRATION SEAM for a future high-precision indoor positioning provider.
Today this codebase has no camera or AI-vision indoor-positioning hardware (the kind of thing
Vestella Lab's Watchmile product does - sub-2m camera+on-device-AI indoor positioning, mainly for
parking/vehicle tracking, protected by their own patents). Reimplementing that here would be
dishonest (we do not have the camera infrastructure) and pointless (their approach is
proprietary and hardware-dependent). What this module does instead is define one small
``Protocol`` - ``IndoorPositionSource`` - and implement the two providers that are actually
buildable with what this codebase has *today*:

    1. ``ManualZoneProvider``  - today's coarse fallback: the visitor states a zone (or pins a
       specific booth) and we look up its coordinates.
    2. ``QrCheckpointProvider`` - a real, deployable-today signal: reads the most recent
       ``interaction.indoor_checkpoint_scan`` row (recorded when a visitor scans a booth's
       existing QR - reuses ``exhibition.booth_qr``, see
       app/api/v1/routers/route.py::scan_checkpoint). This is authoritative and higher-confidence
       than a manual zone pick, because it has a real observation timestamp tied to a specific
       booth scan rather than a self-reported, undated zone choice.

If/when the venue gets real camera-based indoor positioning (Vestella-Lab-Watchmile-style or
otherwise), it becomes a **third** class implementing ``IndoorPositionSource`` - nothing else in
``services/routing/pathfinding.py`` or ``services/routing/service.py`` needs to change, they only
ever see a ``PositionObservation`` (or ``None``).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.core import EventZone
from app.models.exhibitor import Booth
from app.models.indoor_positioning import IndoorCheckpointScan
from app.schemas.route import RouteStartLocation

#: A checkpoint scan older than this no longer counts as "the visitor is currently there" - it
#: still exists in the audit trail, but resolve_current_position() falls back to the manual
#: signal (or "unknown") once a scan is this old. Chosen per the feature brief ("e.g. 20
#: minutes") - not derived from any measured venue walking-speed data, tune if that changes.
CHECKPOINT_FRESHNESS_TTL = timedelta(minutes=20)


@dataclass(frozen=True, slots=True)
class PositionObservation:
    map_x: float
    map_y: float
    confidence: float  # 0..1, coarse: 1.0 = certain. Not calibrated against any ground truth.
    source: str  # "MANUAL_ZONE" | "MANUAL_BOOTH" | "QR_CHECKPOINT" | (future) "CAMERA_AI" etc.
    observed_at: datetime


@dataclass(frozen=True, slots=True)
class PositionQuery:
    tenant_id: uuid.UUID
    event_id: uuid.UUID
    visit_session_id: uuid.UUID
    start_location: RouteStartLocation | None
    now: datetime


class IndoorPositionSource(Protocol):
    """The seam. Any future provider (manual, QR, camera/AI, ...) implements exactly this."""

    async def resolve_position(
        self, db: AsyncSession, query: PositionQuery
    ) -> PositionObservation | None: ...


class ManualZoneProvider:
    """Today's coarse fallback - a visitor-declared zone name, or a pinned booth id.

    ZONE: ``start_location.id`` is matched against ``exhibition.event_zone.zone_name`` (exact,
    case-sensitive - the frontend only ever sends one of its fixed ZONE_PRESETS strings:
    "입구"/"A구역"/"B구역"/"C구역"/"야외무대", see apps/user-web/app/route/page.tsx). If the
    matched zone has no ``coordinate_x``/``coordinate_y`` (nullable in the schema), this returns
    None rather than guessing - the caller degrades to "unknown position" instead of a fabricated
    point.

    BOOTH: ``start_location.id`` is the booth's UUID; resolved directly from
    ``exhibition.booth.map_x``/``map_y``.

    GPS: deliberately unsupported. This codebase has no documented GPS-to-floor-plan calibration
    (no anchor points, no coordinate transform) - fabricating one would violate the "no false
    precision" rule this whole module is built around. A future provider that does real indoor
    GPS/beacon calibration is exactly the kind of thing that becomes a new ``IndoorPositionSource``
    implementation instead of a hack bolted onto this one.
    """

    async def resolve_position(
        self, db: AsyncSession, query: PositionQuery
    ) -> PositionObservation | None:
        start_location = query.start_location
        if start_location is None:
            return None

        if start_location.type == "ZONE":
            zone = (
                await db.execute(
                    select(EventZone).where(
                        EventZone.tenant_id == query.tenant_id,
                        EventZone.event_id == query.event_id,
                        EventZone.zone_name == start_location.id,
                    )
                )
            ).scalar_one_or_none()
            if zone is None or zone.coordinate_x is None or zone.coordinate_y is None:
                return None
            return PositionObservation(
                map_x=float(zone.coordinate_x),
                map_y=float(zone.coordinate_y),
                confidence=0.4,
                source="MANUAL_ZONE",
                observed_at=query.now,
            )

        if start_location.type == "BOOTH":
            try:
                booth_id = uuid.UUID(start_location.id)
            except ValueError:
                return None
            booth = (
                await db.execute(
                    select(Booth).where(
                        Booth.booth_id == booth_id,
                        Booth.tenant_id == query.tenant_id,
                        Booth.event_id == query.event_id,
                    )
                )
            ).scalar_one_or_none()
            if booth is None or booth.map_x is None or booth.map_y is None:
                return None
            return PositionObservation(
                map_x=float(booth.map_x),
                map_y=float(booth.map_y),
                confidence=0.6,
                source="MANUAL_BOOTH",
                observed_at=query.now,
            )

        # start_location.type == "GPS" - see class docstring.
        return None


class QrCheckpointProvider:
    """Reads the visitor's most recent booth-QR checkpoint scan (any freshness).

    Freshness/precedence against the manual signal is decided by the caller
    (``resolve_current_position`` below), not by this provider - a provider only answers "what is
    the latest observation you have", it never sees the manual alternative.
    """

    async def resolve_position(
        self, db: AsyncSession, query: PositionQuery
    ) -> PositionObservation | None:
        row = (
            await db.execute(
                select(IndoorCheckpointScan, Booth)
                .join(Booth, Booth.booth_id == IndoorCheckpointScan.booth_id)
                .where(
                    IndoorCheckpointScan.visit_session_id == query.visit_session_id,
                    IndoorCheckpointScan.tenant_id == query.tenant_id,
                    IndoorCheckpointScan.event_id == query.event_id,
                )
                .order_by(IndoorCheckpointScan.scanned_at.desc())
                .limit(1)
            )
        ).first()
        if row is None:
            return None
        scan, booth = row
        if booth.map_x is None or booth.map_y is None:
            return None
        return PositionObservation(
            map_x=float(booth.map_x),
            map_y=float(booth.map_y),
            confidence=0.85,
            source="QR_CHECKPOINT",
            observed_at=scan.scanned_at,
        )


async def resolve_current_position(
    db: AsyncSession, query: PositionQuery
) -> PositionObservation | None:
    """Combine the two providers per the feature brief's precedence rule.

    "the checkpoint scan takes priority over a stale manual start_location, since it is a more
    reliable real-time signal" - a manual ``start_location`` carries no timestamp of its own (it
    is whatever the visitor picked on this request), so the honest reading of "stale manual" is:
    a *fresh* checkpoint scan always wins over the manual value, because the checkpoint has an
    actual observation time and the manual pick does not. Only once the checkpoint scan is older
    than ``CHECKPOINT_FRESHNESS_TTL`` (or there is none) does the manual ``start_location`` apply.
    A stale checkpoint is still preferred over no position at all.
    """

    checkpoint = await QrCheckpointProvider().resolve_position(db, query)
    if checkpoint is not None and (query.now - checkpoint.observed_at) <= CHECKPOINT_FRESHNESS_TTL:
        return checkpoint

    manual = await ManualZoneProvider().resolve_position(db, query)
    if manual is not None:
        return manual

    return checkpoint


__all__ = [
    "CHECKPOINT_FRESHNESS_TTL",
    "IndoorPositionSource",
    "ManualZoneProvider",
    "PositionObservation",
    "PositionQuery",
    "QrCheckpointProvider",
    "resolve_current_position",
]
