"""Per-constraint hard-constraint tests: H1, H2, H3, H4, H5, H7 (§2.1).

H1–H4 are proven on a normal feasible solve (canonical roster, no pins). H5 is
proven as a universal invariant (never a weekend row, for any input). H7 is
proven by honoring a hard personal constraint at day and slot granularity.
H6 (Mattia coverage) is proven separately as an emergent property.
"""

from __future__ import annotations

import pytest

from app.enums import (
    AssignmentRole,
    AssignmentSlot,
    ConstraintKind,
    ConstraintSlot,
    Day,
)
from app.solver import PersonalConstraint, SolverInput, SolverStatus, solve
from app.solver.types import FREE_DAYS, SOLVER_DAYS
from tests.solver.fixtures import (
    CORE_IDS,
    MATTEO,
    WEEK_MONDAY,
    WEIGHTS,
    assignments_of,
    canonical_prior_state,
    free_day_of,
    roster,
    slots_by_role,
    worker_days,
    workers_in_slot,
)

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase2

SOLVER_SLOTS = (AssignmentSlot.AM, AssignmentSlot.PM)
BOTH_ROLES = (AssignmentRole.BAGNINO, AssignmentRole.SPIAGGINO)
WEEKEND = (Day.SAT, Day.SUN)


def _feasible_result(**overrides):
    kwargs = {
        "week_monday": WEEK_MONDAY,
        "roster": roster(),
        "prior_state": canonical_prior_state(),
        "weights": WEIGHTS,
    }
    kwargs.update(overrides)
    return solve(SolverInput(**kwargs))


def test_h1_coverage_exactly_one_per_role_and_slot() -> None:
    """H1: every Mon–Fri slot has exactly one bagnino and one spiaggino."""
    res = _feasible_result()
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    by_role = slots_by_role(res.assignments)
    for day in SOLVER_DAYS:
        for slot in SOLVER_SLOTS:
            for role in BOTH_ROLES:
                assert len(by_role.get((day, slot, role), [])) == 1


def test_h2_at_most_one_role_per_slot_per_worker() -> None:
    """H2: nobody (Mattia included) holds two roles in the same slot."""
    res = _feasible_result()
    for (day, slot), ids in workers_in_slot(res.assignments).items():
        assert len(ids) == len(set(ids)), f"{day}/{slot}: {ids}"


def test_h3_exactly_one_free_day_mon_thu_per_core() -> None:
    """H3 on a no-grant solve: each core worker has exactly one free day, inside
    the default Mon–Thu domain, and works zero slots on it. (A §2.3 grant widens
    that domain for one worker — see `tests/solver/test_sacrifice_grant.py`; the
    cardinality asserted here holds in both cases.)"""
    res = _feasible_result()
    for wid in CORE_IDS:
        free = free_day_of(res.assignments, wid)
        assert free in FREE_DAYS, f"worker {wid} free day {free} not in Mon–Thu"
        assert worker_days(res.assignments, wid).get(free, []) == []


def test_h4_one_slot_per_non_free_weekday_and_friday_always_worked() -> None:
    """H4: on every non-free Mon–Fri day a core works exactly one slot. On this
    no-grant solve Friday is outside every free-day domain (H3's default is
    Mon–Thu), so it is always worked."""
    res = _feasible_result()
    for wid in CORE_IDS:
        free = free_day_of(res.assignments, wid)
        days = worker_days(res.assignments, wid)
        for day in SOLVER_DAYS:
            expected = 0 if day == free else 1
            assert len(days.get(day, [])) == expected, f"worker {wid} {day}"
        assert len(days.get(Day.FRI, [])) == 1  # H3: no grant here, so Friday is never free


def test_h5_solver_never_emits_a_weekend_assignment() -> None:
    """H5: the weekend is a fixed template, never solved — no output row is ever
    Sat/Sun, for any input (plain, pinned, or constrained)."""
    inputs = [
        SolverInput(week_monday=WEEK_MONDAY, roster=roster(), weights=WEIGHTS),
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            free_day_pins={MATTEO: Day.WED},
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        ),
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            constraints=(
                # A weekend unavailability is a legal §6 row; it must not leak a
                # weekend assignment into the Mon–Fri solver output.
                PersonalConstraint(MATTEO, Day.SAT, ConstraintSlot.FULL_DAY, ConstraintKind.HARD),
            ),
            weights=WEIGHTS,
        ),
    ]
    for inp in inputs:
        res = solve(inp)
        assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
        assert all(a.day not in WEEKEND for a in res.assignments)


def test_h7_hard_full_day_unavailability_leaves_worker_off_that_day() -> None:
    """H7: a hard day-level unavailability (Matteo Wed FULL_DAY) is honored —
    Matteo works zero slots on Wednesday."""
    res = _feasible_result(
        constraints=(
            PersonalConstraint(MATTEO, Day.WED, ConstraintSlot.FULL_DAY, ConstraintKind.HARD),
        ),
    )
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert all(a.day != Day.WED for a in assignments_of(res.assignments, MATTEO))


def test_h7_hard_am_unavailability_leaves_that_exact_slot_empty() -> None:
    """H7: a hard slot-level unavailability (Matteo Mon AM) is honored — Matteo
    is never assigned Mon AM (he may still work Mon PM)."""
    res = _feasible_result(
        constraints=(PersonalConstraint(MATTEO, Day.MON, ConstraintSlot.AM, ConstraintKind.HARD),),
    )
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    for a in assignments_of(res.assignments, MATTEO):
        assert not (a.day == Day.MON and a.slot == AssignmentSlot.AM)
