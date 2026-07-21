"""Objective breakdown arithmetic and performance sanity (§8, §11, §2.2).

§8 sets a < 1 s expectation and a 10 s hard-fail. §11 requires the solve to
surface its duration and per-tier objective values. `ObjectiveBreakdown` must
report each tier separately and its `weighted_total` must equal exactly the
value CP-SAT minimizes with the input weights.
"""

from __future__ import annotations

import pytest

from app.enums import ConstraintKind, ConstraintSlot, Day
from app.solver import PersonalConstraint, SolverInput, SolverStatus, solve
from tests.solver.fixtures import (
    MATTEO,
    WEEK_MONDAY,
    WEIGHTS,
    canonical_prior_state,
    roster,
)

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase2

# A solve carrying a non-trivial mix so the breakdown fields exercise real,
# non-zero terms: a soft request Matteo cannot fully avoid plus a pinned free day.
# The pin is WEDNESDAY, inside his H3(b) bagnino domain {Tue, Wed} — an
# out-of-domain pin (Thursday, as this fixture read before v1.12) is silently
# ignored by the model, which would quietly drain the instance of its constraint.
_INPUT = SolverInput(
    week_monday=WEEK_MONDAY,
    roster=roster(),
    constraints=(PersonalConstraint(MATTEO, Day.MON, ConstraintSlot.AM, ConstraintKind.SOFT),),
    free_day_pins={MATTEO: Day.WED},
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
    """§11: a feasible solve carries the per-tier ObjectiveBreakdown for logging.
    Three reported terms since v1.12 — `spread_shared_pairs` went hard (H3(c)) and
    `jolly_days` is now fixed by H3, so neither is an objective value any more."""
    res = solve(_INPUT)
    assert res.objective is not None
    obj = res.objective
    for field in (obj.soft_unmet, obj.alternation_breaks, obj.fairness_deviation):
        assert field >= 0


def test_the_breakdown_reports_no_deleted_tier() -> None:
    """§2.2 v1.12: a reported tier the objective no longer minimizes would be a
    number nobody can act on. `spread_shared_pairs` and `jolly_days` are gone from
    the dataclass, not merely zeroed."""
    res = solve(_INPUT)
    assert res.objective is not None
    assert not hasattr(res.objective, "spread_shared_pairs")
    assert not hasattr(res.objective, "jolly_days")


def test_weighted_total_equals_the_lexicographic_sum() -> None:
    """§2.2/§8: weighted_total == w1·soft_unmet + w2·(alternation_breaks +
    fairness_deviation), with the input weights — the two-tier v1.12 objective."""
    res = solve(_INPUT)
    assert res.objective is not None
    obj = res.objective
    expected = WEIGHTS.w1 * obj.soft_unmet + WEIGHTS.w2 * (
        obj.alternation_breaks + obj.fairness_deviation
    )
    assert obj.weighted_total == expected
