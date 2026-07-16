"""Objective breakdown arithmetic and performance sanity (§8, §11, §2.2).

§8 sets a < 1 s expectation and a 10 s hard-fail. §11 requires the solve to
surface its duration and per-tier objective values. `ObjectiveBreakdown` must
report each tier separately and its `weighted_total` must equal exactly the
value CP-SAT minimizes with the input weights.
"""

from __future__ import annotations

from app.enums import ConstraintKind, ConstraintSlot, Day
from app.solver import PersonalConstraint, SolverInput, SolverStatus, solve
from tests.solver.fixtures import (
    MATTEO,
    WEEK_MONDAY,
    WEIGHTS,
    canonical_prior_state,
    roster,
)

# A solve carrying a non-trivial mix so the breakdown fields exercise real,
# non-zero terms: a soft request Matteo cannot fully avoid plus a pinned free day.
_INPUT = SolverInput(
    week_monday=WEEK_MONDAY,
    roster=roster(),
    constraints=(PersonalConstraint(MATTEO, Day.MON, ConstraintSlot.AM, ConstraintKind.SOFT),),
    free_day_pins={MATTEO: Day.THU},
    prior_state=canonical_prior_state(),
    weights=WEIGHTS,
)


def test_solve_seconds_is_populated_and_well_under_the_hard_fail() -> None:
    """§8/§11: the solve reports its duration, and a normal instance is fast
    (< 1 s, far under the 10 s hard-fail guard)."""
    res = solve(_INPUT)
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert res.solve_seconds >= 0.0
    assert res.solve_seconds < 1.0


def test_objective_breakdown_is_present_on_a_feasible_solve() -> None:
    """§11: a feasible solve carries the per-tier ObjectiveBreakdown for logging."""
    res = solve(_INPUT)
    assert res.objective is not None
    obj = res.objective
    for field in (obj.soft_unmet, obj.alternation_breaks, obj.fairness_deviation, obj.jolly_days):
        assert field >= 0


def test_weighted_total_equals_the_lexicographic_sum() -> None:
    """§2.2/§8: weighted_total == w1·soft_unmet + w2·(alternation_breaks +
    fairness_deviation) + w3·jolly_days, with the input weights."""
    res = solve(_INPUT)
    assert res.objective is not None
    obj = res.objective
    expected = (
        WEIGHTS.w1 * obj.soft_unmet
        + WEIGHTS.w2 * (obj.alternation_breaks + obj.fairness_deviation)
        + WEIGHTS.w3 * obj.jolly_days
    )
    assert obj.weighted_total == expected
