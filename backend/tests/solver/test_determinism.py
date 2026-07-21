"""The solve is a pure function of its input (§8).

CP-SAT's default portfolio runs several workers in parallel and returns
whichever optimum finishes first. The §2.2 objective admits ties often — two
core workers' free days are frequently interchangeable at equal cost — so
without a pinned search the same week could publish differently on two machines,
the §8 golden test would be a coin flip, and a reported schedule could not be
reproduced while debugging it.

`app.solver.model` therefore fixes the seed and runs a single worker. These
tests are what keep that from being quietly undone: they fail the moment the
same input starts producing two different weeks.
"""

from __future__ import annotations

from dataclasses import astuple

import pytest

from app.solver import SolverInput, SolverResult, SolverStatus, solve
from tests.solver.fixtures import (
    WEEK_MONDAY,
    WEIGHTS,
    canonical_prior_state,
    roster,
)

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase4


def _input() -> SolverInput:
    """A plain week: no personal constraints, no pins, no grants — exactly the
    case with the most ties, and so the one most exposed to a nondeterministic
    search picking a different optimum each time."""
    return SolverInput(
        week_monday=WEEK_MONDAY,
        roster=roster(),
        constraints=(),
        free_day_pins={},
        sacrifice_grants={},
        prior_state=canonical_prior_state(),
        weights=WEIGHTS,
    )


def _signature(result: SolverResult) -> tuple[tuple[str, str, str, int], ...]:
    """The schedule as a comparable value: every assignment, in a stable order."""
    return tuple(
        sorted((a.day.value, a.slot.value, a.role.value, a.worker_id) for a in result.assignments)
    )


def test_the_same_input_yields_the_same_week() -> None:
    """The property the seed exists for. Ten solves, one schedule — a
    multi-worker search would drift on a week this tie-heavy."""
    first = solve(_input())
    assert first.status is not SolverStatus.INFEASIBLE
    expected = _signature(first)
    assert expected, "the week must actually contain assignments"

    for attempt in range(9):
        again = solve(_input())
        assert _signature(again) == expected, f"solve #{attempt + 2} produced a different week"


def test_the_objective_breakdown_is_stable_too() -> None:
    """Not just *a* same-cost schedule — the identical one, at the identical
    per-tier cost. A drifting breakdown would mean the tie-break moved
    underneath even where the assignment set happened to match."""
    breakdowns = {
        astuple(result.objective)
        for result in (solve(_input()) for _ in range(5))
        if result.objective is not None
    }
    assert len(breakdowns) == 1, f"the objective must not vary between solves: {breakdowns}"
