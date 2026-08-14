"""Pure, DB-free tests for app/services/routing/pathfinding.py (U-13 AI 추천 방문 동선).

Every test in this file constructs small synthetic coordinate sets with hand-verifiable
distances so assertions check "the actual shortest reasonable path", not just "some order" -
per the track's explicit test requirement.
"""

from __future__ import annotations

from app.services.routing import pathfinding as pf


def _candidate(
    key: str,
    point: tuple[float, float] | None,
    *,
    priority: int = 1,
    duration: int = 15,
    congested: bool = False,
) -> pf.RouteCandidate:
    return pf.RouteCandidate(
        key=key,
        point=point,
        priority=priority,
        expected_duration_minutes=duration,
        congested=congested,
    )


# ---------------------------------------------------------------------------
# Ordering by real distance
# ---------------------------------------------------------------------------


def test_nearest_neighbor_orders_a_straight_line_by_actual_distance() -> None:
    start = (0.0, 0.0)
    far = _candidate("A_far", (30.0, 0.0))
    near = _candidate("B_near", (10.0, 0.0))
    mid = _candidate("C_mid", (20.0, 0.0))

    order = pf.optimize_order(start, [far, near, mid], avoid_congestion=False)

    assert [c.key for c in order] == ["B_near", "C_mid", "A_far"]


def test_nearest_neighbor_orders_a_2d_cluster_by_actual_distance() -> None:
    start = (0.0, 0.0)
    d = _candidate("D", (0.0, 6.0))  # distance 6.0 from start
    e = _candidate("E", (8.0, 0.0))  # distance 8.0 from start
    f = _candidate("F", (3.0, 3.0))  # distance sqrt(18) ~= 4.243 from start - closest to start

    order = pf.optimize_order(start, [d, e, f], avoid_congestion=False)

    # Greedy nearest-neighbor alone would start at F (closest to the origin), giving
    # F -> D -> E (~4.243 + 4.243 + 10.0 = 18.486). But the genuinely shortest path over all
    # three points is D -> F -> E (6.0 + 4.243 + 5.831 = 16.074, hand-verified) - the bounded
    # 2-opt pass this module runs after the greedy construction finds that improvement, which is
    # exactly why optimize_order (not nearest_neighbor_order alone) is the function callers use.
    assert [c.key for c in order] == ["D", "F", "E"]


def test_two_opt_never_makes_a_route_longer_than_the_greedy_construction() -> None:
    start = (0.0, 0.0)
    candidates = [
        _candidate("p1", (5.0, 9.0)),
        _candidate("p2", (12.0, 1.0)),
        _candidate("p3", (2.0, 14.0)),
        _candidate("p4", (18.0, 8.0)),
        _candidate("p5", (7.0, 3.0)),
    ]

    greedy = pf.nearest_neighbor_order(start, candidates, avoid_congestion=False)
    improved = pf.two_opt_improve(start, greedy, avoid_congestion=False)

    greedy_cost = pf.estimate_walking_minutes(start, greedy)
    improved_cost = pf.estimate_walking_minutes(start, improved)
    assert improved_cost <= greedy_cost + 1e-9
    # 2-opt only reorders, it never drops or duplicates a stop.
    assert {c.key for c in improved} == {c.key for c in greedy}


def test_two_opt_improve_escapes_a_deliberately_bad_starting_order() -> None:
    """Regression for the python-tsp integration (2026-08-14): two_opt_improve must genuinely
    run local search from whatever order it is given, not merely validate/pass through an
    already-good one. Feeding it the worst possible ordering of a known 4-point square proves
    the improvement step does real work, not just confirms the greedy construction."""

    start = (0.0, 0.0)
    # A unit square offset from start; visiting in the given (deliberately criss-crossing) order
    # is far longer than the two possible non-crossing orders around the perimeter.
    a = _candidate("a", (0.0, 1.0))
    b = _candidate("b", (1.0, 1.0))
    c = _candidate("c", (1.0, 0.0))
    d = _candidate("d", (0.0, 0.0))
    worst_order = [b, d, a, c]  # crosses itself twice

    improved = pf.two_opt_improve(start, worst_order, avoid_congestion=False)

    worst_cost = pf.estimate_walking_minutes(start, worst_order)
    improved_cost = pf.estimate_walking_minutes(start, improved)
    assert improved_cost < worst_cost
    assert {c.key for c in improved} == {"a", "b", "c", "d"}


def test_optimize_order_handles_a_max_route_targets_scale_input_without_dropping_or_duplicating() -> (
    None
):
    """MAX_ROUTE_TARGETS (app/schemas/route.py) caps real requests at 20 - a sanity check at
    that scale that the solver returns a complete, valid permutation (no dropped/duplicated
    candidate) and never regresses versus the plain greedy construction. (A regular grid's
    boustrophedon nearest-neighbor path is already near-optimal, so this scenario alone can't
    prove *improvement* - test_two_opt_improve_escapes_a_deliberately_bad_starting_order already
    covers that with a case hand-picked to have a real, provable gap.)"""

    start = (0.0, 0.0)
    # A 4x5 grid of points, offset so the origin isn't itself a grid point.
    candidates = [
        _candidate(f"g{row}_{col}", (float(col) * 10.0 + 3.0, float(row) * 10.0 + 3.0))
        for row in range(4)
        for col in range(5)
    ]

    greedy = pf.nearest_neighbor_order(start, candidates, avoid_congestion=False)
    improved = pf.optimize_order(start, candidates, avoid_congestion=False)

    assert {c.key for c in improved} == {c.key for c in candidates}
    assert len(improved) == len(candidates)
    greedy_cost = pf.estimate_walking_minutes(start, greedy)
    improved_cost = pf.estimate_walking_minutes(start, improved)
    assert improved_cost <= greedy_cost + 1e-9


def test_euclidean_distance_is_symmetric_and_zero_for_identical_points() -> None:
    a, b = (1.0, 2.0), (4.0, 6.0)
    assert pf.euclidean_distance(a, a) == 0.0
    assert pf.euclidean_distance(a, b) == pf.euclidean_distance(b, a)
    assert pf.euclidean_distance(a, b) == 5.0  # 3-4-5 triangle


# ---------------------------------------------------------------------------
# avoid_congestion measurably changes ordering vs. a congestion-free control
# ---------------------------------------------------------------------------


def test_avoid_congestion_reorders_a_closer_but_congested_stop_after_a_farther_calm_one() -> None:
    start = (0.0, 0.0)
    congested_but_closer = _candidate("congested", (5.0, 0.0), congested=True)
    calm_but_farther = _candidate("calm", (6.0, 0.0), congested=False)

    control = pf.optimize_order(
        start, [congested_but_closer, calm_but_farther], avoid_congestion=False
    )
    assert [c.key for c in control] == ["congested", "calm"]

    avoiding = pf.optimize_order(
        start, [congested_but_closer, calm_but_farther], avoid_congestion=True
    )
    assert [c.key for c in avoiding] == ["calm", "congested"]


def test_avoid_congestion_never_hard_excludes_the_congested_target() -> None:
    start = (0.0, 0.0)
    congested = _candidate("congested", (1.0, 0.0), congested=True)
    order = pf.optimize_order(start, [congested], avoid_congestion=True)
    assert [c.key for c in order] == ["congested"]


# ---------------------------------------------------------------------------
# available_minutes drops by priority, not by truncating the visiting order
# ---------------------------------------------------------------------------


def test_fit_to_budget_drops_lowest_priority_even_when_it_is_visited_first() -> None:
    start = (0.0, 0.0)
    # Lower priority number = higher importance (repo convention). p_low_importance sits
    # CLOSEST to start (would be visited first / kept by any naive "truncate the tail" bug),
    # but it has the least important priority (3) - the correct drop target.
    p_low_importance = _candidate("closest_but_unimportant", (10.0, 0.0), priority=3, duration=20)
    p_mid = _candidate("mid", (20.0, 0.0), priority=2, duration=20)
    p_most_important = _candidate(
        "farthest_but_important", (30.0, 0.0), priority=1, duration=20
    )

    # All three: walking = (10+10+10)/20 = 1.5, total = 1.5 + 60 = 61.5 > 45.
    fitted = pf.fit_to_budget(
        start,
        [p_low_importance, p_mid, p_most_important],
        available_minutes=45,
        avoid_congestion=False,
    )

    kept_keys = {c.key for c in fitted}
    assert "closest_but_unimportant" not in kept_keys
    assert kept_keys == {"mid", "farthest_but_important"}
    walking = pf.estimate_walking_minutes(start, fitted)
    total = pf.estimate_total_minutes(walking, fitted)
    assert total <= 45


def test_fit_to_budget_is_a_no_op_when_available_minutes_is_none() -> None:
    start = (0.0, 0.0)
    candidates = [_candidate("a", (100.0, 0.0), duration=500)]
    fitted = pf.fit_to_budget(start, candidates, available_minutes=None, avoid_congestion=False)
    assert [c.key for c in fitted] == ["a"]


def test_fit_to_budget_can_drop_every_target_when_nothing_fits() -> None:
    start = (0.0, 0.0)
    candidates = [_candidate("a", (1000.0, 0.0), priority=1, duration=500)]
    fitted = pf.fit_to_budget(start, candidates, available_minutes=5, avoid_congestion=False)
    assert fitted == []


# ---------------------------------------------------------------------------
# Unlocatable candidates (no map coordinate - e.g. a PROGRAM/MEETING without booth data)
# ---------------------------------------------------------------------------


def test_unlocatable_candidates_are_appended_after_every_locatable_one() -> None:
    start = (0.0, 0.0)
    locatable = _candidate("locatable", (5.0, 0.0), duration=10)
    unlocatable = _candidate("unlocatable", None, duration=10)

    order = pf.optimize_order(start, [unlocatable, locatable], avoid_congestion=False)

    assert [c.key for c in order] == ["locatable", "unlocatable"]
    # Still counted toward total time even though it contributes no distance.
    walking = pf.estimate_walking_minutes(start, order)
    total = pf.estimate_total_minutes(walking, order)
    assert total == walking + 20  # both durations (10 + 10), zero extra distance for unlocatable


def test_unlocatable_candidate_alone_yields_zero_walking_minutes() -> None:
    start = (0.0, 0.0)
    order = pf.optimize_order(start, [_candidate("only", None, duration=15)], avoid_congestion=False)
    assert pf.estimate_walking_minutes(start, order) == 0.0
