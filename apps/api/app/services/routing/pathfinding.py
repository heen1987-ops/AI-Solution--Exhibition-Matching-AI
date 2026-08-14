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

Local-improvement step uses a real, tested open-source TSP solver (2026-08-14)
--------------------------------------------------------------------------------------------
The visit-order optimizer used to be a hand-rolled nearest-neighbor construction followed by a
hand-rolled, iteration-capped 2-opt loop - this module's own original docstring flagged that as
"not an exact or metaheuristic solver... a reasonable, fast, testable approximation, not the
optimum." That gap is now closed with a real library: `python-tsp
<https://github.com/fillipe-gsm/python-tsp>`_ (pure Python, MIT-licensed, actively maintained,
pip-installed as an apps/api dependency - see pyproject.toml). :func:`two_opt_improve` still does
exactly what its name says (locally improve a given order), but the 2-opt neighborhood search
itself is now ``python_tsp.heuristics.solve_tsp_local_search`` running to a genuine local
optimum (or ``MAX_LOCAL_SEARCH_SECONDS``, whichever comes first) instead of a fixed iteration
budget that could stop mid-improvement on a pathological input.

What this does NOT change (still true, still honest, still the same limitation this module has
always documented): this is still Euclidean plan-distance, not wall-aware indoor navigation.
python-tsp solves "what order should we visit these points in", not "how do we walk around a
wall" - there is still no aisle/corridor graph or obstacle data anywhere in this repository (see
the ACCURACY NOTE above), so applying a real wall-aware indoor-routing open-source project (e.g.
IndoorGML-based routing engines) would require floor-plan graph data this repo does not have -
fabricating that data to make one look integrated would repeat the exact dishonesty this feature
was explicitly built to avoid for camera-based positioning (see
``.harness/handoffs/backend/indoor-route-navigation.md``'s "Honest scope" section). The
TSP-ordering problem, by contrast, only needs the coordinates this repo already has
(``exhibition.booth.map_x``/``map_y``), which is why it is the piece a real open-source library
can honestly improve today.

Why python-tsp and not networkx's TSP approximations (christofides/greedy_tsp)
--------------------------------------------------------------------------------------------
networkx's `travelling_salesman_problem
<https://networkx.org/documentation/stable/reference/algorithms/approximation.html>`_ needs a
symmetric graph (its Christofides 3/2-approximation guarantee specifically requires a metric,
triangle-inequality-respecting distance) and always returns a closed tour (start == end).
:func:`_edge_cost` below charges the congestion penalty on arrival at the *destination* node -
an intentionally asymmetric cost (edge(u, v) != edge(v, u) whenever their congestion flags
differ) - and a visit route is an open path (a visitor does not walk back to their starting
point). python-tsp's ``solve_tsp_local_search`` takes a plain distance matrix with no symmetry
requirement, and supports open-path TSP directly (zero the first column - see
:func:`_distance_matrix`) - a closer fit for this module's actual cost model than forcing it
into networkx's symmetric/closed-tour shape.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import numpy as np
from python_tsp.heuristics import solve_tsp_local_search

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

#: Wall-clock bound (seconds) on the python-tsp local-search improvement pass, so route
#: computation stays fast even in pathological inputs. MAX_ROUTE_TARGETS (app/schemas/route.py)
#: already caps input size to a small number (<=20), so solve_tsp_local_search reaches a genuine
#: local optimum in a few milliseconds in practice - this is a defense-in-depth bound, not the
#: primary performance control.
MAX_LOCAL_SEARCH_SECONDS: Final[float] = 1.0


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


def _distance_matrix(
    start: Point, locatable: list[RouteCandidate], *, avoid_congestion: bool
) -> np.ndarray:
    """Row/column 0 is ``start``; row/column ``i`` (i >= 1) is ``locatable[i - 1]``.

    Asymmetric by design (see module docstring "Why python-tsp" section): entry ``[i][j]`` is
    ``_edge_cost`` arriving at node ``j`` from node ``i``, so the congestion penalty attached to
    the destination candidate only appears in columns, not rows. Column 0 is zeroed after
    construction - the standard python-tsp technique for turning a closed-tour solver into an
    open-path one (no cost charged for the implicit "return to start" leg the solver still
    computes internally).
    """

    points = [start] + [c.point for c in locatable]
    n = len(points)
    matrix = np.zeros((n, n))
    for i in range(n):
        for j in range(n):
            if i == j:
                continue
            destination = locatable[j - 1] if j > 0 else None
            if destination is None:
                matrix[i][j] = euclidean_distance(points[i], points[j])  # type: ignore[arg-type]
            else:
                matrix[i][j] = _edge_cost(
                    points[i],  # type: ignore[arg-type]
                    points[j],  # type: ignore[arg-type]
                    destination,
                    avoid_congestion=avoid_congestion,
                )
    matrix[:, 0] = 0.0  # open path - see docstring above.
    return matrix


def two_opt_improve(
    start: Point,
    order: list[RouteCandidate],
    *,
    avoid_congestion: bool,
    max_processing_time: float = MAX_LOCAL_SEARCH_SECONDS,
) -> list[RouteCandidate]:
    """2-opt local improvement over the *locatable* prefix of ``order``, via python-tsp's
    ``solve_tsp_local_search`` (see module docstring) - runs to a genuine local optimum from
    ``order`` as the starting tour, bounded by ``max_processing_time`` as a defense-in-depth cap.

    Only reorders the locatable prefix - unlocatable candidates (``point is None``) stay fixed
    at the tail in their nearest-neighbor position, since swapping them would not change any
    real distance (there is nothing to measure).
    """

    locatable = [c for c in order if c.point is not None]
    unlocatable = [c for c in order if c.point is None]
    n = len(locatable)
    if n < 3:
        return locatable + unlocatable

    matrix = _distance_matrix(start, locatable, avoid_congestion=avoid_congestion)
    x0 = list(range(n + 1))  # [start, locatable[0], locatable[1], ...] - order's own sequence.
    permutation, _cost = solve_tsp_local_search(
        matrix,
        x0=x0,
        perturbation_scheme="two_opt",
        max_processing_time=max_processing_time,
    )
    # solve_tsp_local_search returns a permutation of the closed tour it solved internally - in
    # practice node 0 (start) stays at index 0 since x0 starts there and 2-opt never gains
    # anything by moving it (column 0 is all zeros), but that is solver behavior, not a
    # documented API guarantee - rotate defensively so start is first regardless, then drop it
    # and map the rest back to locatable candidates (node i -> locatable[i - 1]).
    start_index = permutation.index(0)
    rotated = permutation[start_index:] + permutation[:start_index]
    best = [locatable[node - 1] for node in rotated if node != 0]
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
    "MAX_LOCAL_SEARCH_SECONDS",
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
