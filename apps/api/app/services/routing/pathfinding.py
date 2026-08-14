"""Pure pathfinding/ordering helpers for the AI-recommended visit route feature (U-13).

ACCURACY NOTE - read before trusting any "distance" or "minutes" value out of this module
-------------------------------------------------------------------------------------------
This module does not implement wall-aware, turn-by-turn indoor routing. There is no aisle/
corridor graph, no wall or obstacle data, and no documented physical unit for
``exhibition.booth.map_x``/``map_y`` anywhere in this repository - re-checked
docs/db-erd-table-spec.md 13.1절 and docs/08-exhibitor-product-profile-model.md while writing
this module; neither states meters, centimeters, or any other unit. They are just
``NUMERIC(10,3)`` plan coordinates. So:

  - "distance" here means straight-line (Euclidean) distance between two ``(map_x, map_y)``
    points, in whatever unit the floor-plan authoring tool used. It is a reasonable proxy for
    "which stop is closer", not a claim about real walking distance around booths/walls.
  - "walking minutes" is that distance divided by ``WALKING_SPEED_PLAN_UNITS_PER_MINUTE``, a
    single configurable constant defined below. It is a *plan-unit* estimate, not a calibrated
    real-world ETA. Once the venue's floor-plan unit is documented, recalibrate this one constant
    instead of touching the ordering logic.

Everything in this module is a pure function/dataclass - no DB session, no FastAPI, no I/O - so
it is unit-testable without Postgres (see tests/test_routing_pathfinding.py).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

Point = tuple[float, float]

#: Plan-unit walking speed used to turn Euclidean plan-distance into a minutes estimate. See the
#: module docstring's ACCURACY NOTE - this is a documented placeholder, not a calibrated figure.
#: Tune this single constant if/when the floor-plan's real unit is documented.
WALKING_SPEED_PLAN_UNITS_PER_MINUTE: Final[float] = 20.0

#: Extra plan-distance "penalty" added (not a hard exclusion) when ``avoid_congestion`` is set
#: and a candidate's booth is at HIGH congestion. Note: the levels this repo actually implements
#: (``BOOTH_CONGESTION_LEVELS`` in app/models/exhibitor.py) are LOW/MEDIUM/HIGH/UNKNOWN, not the
#: CONGESTED/SOLD_OUT labels used loosely in the feature brief - HIGH is treated as the analog of
#: "congested" here. The penalty only changes ordering preference among otherwise-similar-length
#: routes; it never removes a target from the route (that would be a hard filter, which the task
#: explicitly says not to do).
CONGESTION_PENALTY_PLAN_UNITS: Final[float] = 15.0

#: Bound on 2-opt local-improvement passes (counted in edge-cost evaluations) so route
#: computation stays fast and deterministic even in pathological inputs.
#: MAX_ROUTE_TARGETS (app/schemas/route.py) already caps input size to a small number, so this
#: is a defense-in-depth bound, not the primary performance control.
MAX_TWO_OPT_ITERATIONS: Final[int] = 200


@dataclass(frozen=True, slots=True)
class RouteCandidate:
    """One target under consideration for the route.

    ``key`` must be unique within a single optimization call - callers use it (not object
    identity or list position) to tell which candidates survived priority-based dropping.
    """

    key: str
    point: Point | None  # None when this target has no resolvable map coordinate.
    priority: int  # Lower number = higher priority (repo-wide convention; see schemas/route.py).
    expected_duration_minutes: int
    congested: bool = False  # Booth.congestion_level == "HIGH" AND avoid_congestion requested.


def euclidean_distance(a: Point, b: Point) -> float:
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2) ** 0.5


def _edge_cost(
    a: Point, b: Point, candidate: RouteCandidate, *, avoid_congestion: bool
) -> float:
    """Distance from ``a`` to ``b``, plus the congestion penalty attached to arriving at ``b``.

    Charging the penalty on arrival biases the optimizer toward visiting congested stops later,
    or via a longer detour when a shorter, less-congested alternative exists - without ever
    excluding the stop.
    """

    cost = euclidean_distance(a, b)
    if avoid_congestion and candidate.congested:
        cost += CONGESTION_PENALTY_PLAN_UNITS
    return cost


def _route_cost(
    start: Point, order: list[RouteCandidate], *, avoid_congestion: bool
) -> float:
    total = 0.0
    cursor = start
    for candidate in order:
        if candidate.point is None:
            continue
        total += _edge_cost(
            cursor, candidate.point, candidate, avoid_congestion=avoid_congestion
        )
        cursor = candidate.point
    return total


def nearest_neighbor_order(
    start: Point, candidates: list[RouteCandidate], *, avoid_congestion: bool
) -> list[RouteCandidate]:
    """Greedy nearest-neighbor ordering from ``start``.

    Candidates with ``point is None`` (no resolvable coordinate - e.g. a MEETING or a PROGRAM
    without booth/zone coordinates, see services/routing/service.py) cannot participate in
    geometric ordering at all. They are appended, in their original input order, after every
    locatable candidate - they still count toward total duration/priority-dropping, just not
    toward walking-distance optimization.
    """

    locatable = [c for c in candidates if c.point is not None]
    unlocatable = [c for c in candidates if c.point is None]

    remaining = list(locatable)
    ordered: list[RouteCandidate] = []
    cursor = start
    while remaining:
        best_index = min(
            range(len(remaining)),
            key=lambda i: _edge_cost(
                cursor,
                remaining[i].point,  # type: ignore[arg-type]
                remaining[i],
                avoid_congestion=avoid_congestion,
            ),
        )
        nxt = remaining.pop(best_index)
        ordered.append(nxt)
        cursor = nxt.point  # type: ignore[assignment]
    return ordered + unlocatable


def two_opt_improve(
    start: Point,
    order: list[RouteCandidate],
    *,
    avoid_congestion: bool,
    max_iterations: int = MAX_TWO_OPT_ITERATIONS,
) -> list[RouteCandidate]:
    """Bounded 2-opt local improvement over the *locatable* prefix of ``order``.

    Only swaps within the contiguous locatable prefix - unlocatable candidates (``point is
    None``) stay fixed at the tail in their nearest-neighbor position, since swapping them would
    not change any real distance (there is nothing to measure).
    """

    locatable = [c for c in order if c.point is not None]
    unlocatable = [c for c in order if c.point is None]
    n = len(locatable)
    if n < 3:
        return locatable + unlocatable

    best = list(locatable)
    best_cost = _route_cost(start, best, avoid_congestion=avoid_congestion)
    iterations = 0
    improved = True
    while improved and iterations < max_iterations:
        improved = False
        for i in range(n - 1):
            for j in range(i + 1, n):
                if iterations >= max_iterations:
                    break
                candidate_order = best[:i] + list(reversed(best[i : j + 1])) + best[j + 1 :]
                cost = _route_cost(start, candidate_order, avoid_congestion=avoid_congestion)
                iterations += 1
                if cost + 1e-9 < best_cost:
                    best = candidate_order
                    best_cost = cost
                    improved = True
            if iterations >= max_iterations:
                break
    return best + unlocatable


def optimize_order(
    start: Point, candidates: list[RouteCandidate], *, avoid_congestion: bool
) -> list[RouteCandidate]:
    """Nearest-neighbor construction followed by bounded 2-opt improvement."""

    greedy = nearest_neighbor_order(start, candidates, avoid_congestion=avoid_congestion)
    return two_opt_improve(start, greedy, avoid_congestion=avoid_congestion)


def estimate_walking_minutes(start: Point, order: list[RouteCandidate]) -> float:
    """Sum of plan-distance along ``order`` converted to minutes (see module docstring).

    The congestion penalty is intentionally excluded here - it only steers ordering preference,
    it is not a claimed real walking cost.
    """

    total_distance = 0.0
    cursor = start
    for candidate in order:
        if candidate.point is None:
            continue
        total_distance += euclidean_distance(cursor, candidate.point)
        cursor = candidate.point
    return total_distance / WALKING_SPEED_PLAN_UNITS_PER_MINUTE


def estimate_total_minutes(walking_minutes: float, order: list[RouteCandidate]) -> float:
    return walking_minutes + sum(c.expected_duration_minutes for c in order)


def fit_to_budget(
    start: Point,
    candidates: list[RouteCandidate],
    *,
    available_minutes: int | None,
    avoid_congestion: bool,
) -> list[RouteCandidate]:
    """Order ``candidates`` and, if ``available_minutes`` is set, drop the lowest-priority
    remaining targets (highest ``priority`` number - repo convention: 1 is highest priority)
    until the estimated total time fits the budget.

    This is explicitly NOT a truncate-the-tail-of-the-visiting-order operation: a target is
    dropped by priority rank regardless of where the optimizer placed it, then the remaining
    targets are re-optimized (the best order can change once a stop leaves the set).
    """

    order = optimize_order(start, candidates, avoid_congestion=avoid_congestion)
    if available_minutes is None:
        return order

    while order:
        walking = estimate_walking_minutes(start, order)
        total = estimate_total_minutes(walking, order)
        if total <= available_minutes:
            return order
        # Drop the single worst-priority candidate. Tie-break deterministically: among equal
        # priority values, drop the one that currently sits later in the order.
        worst_index = max(range(len(order)), key=lambda i: (order[i].priority, i))
        order = order[:worst_index] + order[worst_index + 1 :]
        if not order:
            break
        order = optimize_order(start, order, avoid_congestion=avoid_congestion)
    return order


__all__ = [
    "CONGESTION_PENALTY_PLAN_UNITS",
    "MAX_TWO_OPT_ITERATIONS",
    "WALKING_SPEED_PLAN_UNITS_PER_MINUTE",
    "Point",
    "RouteCandidate",
    "estimate_total_minutes",
    "estimate_walking_minutes",
    "euclidean_distance",
    "fit_to_budget",
    "nearest_neighbor_order",
    "optimize_order",
    "two_opt_improve",
]
