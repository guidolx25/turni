"""GOLDEN TEST — the §8 regression anchor. DO NOT RELAX.

Reproduces the photographed week of 2026-07-13 **UNPINNED** (§8, v1.12). The free
days used to be supplied as pinned inputs; H3(b)+(c) now DERIVE the role-day
structure, so handing the solver the answer would test nothing. The input here is
the bare roster plus the §2.2 weekend seed — no `free_day_pins`, no grants — and
the photographed layout must come back out:

    Pasha Mon · Amir Tue · Francesco Tue · Matteo Wed
    jolly load Mon 1 / Tue 2 / Wed 1 / Thu 0 / Fri 0

Two kinds of assertion, deliberately separated:

* the **rule-derived** structure — each spiaggino free in {Mon, Tue}, each bagnino
  in {Tue, Wed}, no same-role pair sharing, and the emergent jolly load. §8 calls
  this a *consequence* of H1+H3, never a rule of its own, so it is asserted on the
  output rather than encoded in the input.
* the **within-pair choice** — which of the two spiaggini takes Monday, which of
  the two bagnini takes Wednesday. H3 leaves exactly four legal layouts (2×2) and
  §2.2's objective picks among them; the photo pins this half by observation.

This test asserts structural coverage, never a specific AM/PM-per-person layout:
CP-SAT may pick any equal-cost AM/PM tie-break. It may only ever become STRICTER,
never looser. If it fails, the solver is wrong (or the spec changed with approval)
— it is never edited to pass, and pins are NEVER re-added to make it green.
"""

from __future__ import annotations

import pytest

from app.enums import AssignmentRole, AssignmentSlot, Day
from app.solver import SolverInput, SolverStatus, solve
from tests.solver.fixtures import (
    AMIR,
    CORE_IDS,
    FRANCESCO,
    MATTEO,
    MATTIA,
    PASHA,
    SAME_ROLE_PAIRS,
    WEEK_MONDAY,
    WEIGHTS,
    canonical_prior_state,
    free_day_of,
    jolly_load,
    role_domain,
    roster,
    slots_by_role,
    worker_days,
    workers_in_slot,
)

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase2

# The photographed free days (§8). An EXPECTATION on the output, never an input.
GOLDEN_FREE_DAYS = {PASHA: Day.MON, AMIR: Day.TUE, FRANCESCO: Day.TUE, MATTEO: Day.WED}
# §8: the jolly load every legal H3 layout forces — emergent, never constrained.
GOLDEN_JOLLY_LOAD = {Day.MON: 1, Day.TUE: 2, Day.WED: 1, Day.THU: 0, Day.FRI: 0}
SOLVER_SLOTS = (AssignmentSlot.AM, AssignmentSlot.PM)
BOTH_ROLES = (AssignmentRole.BAGNINO, AssignmentRole.SPIAGGINO)


def _golden_result():
    """The §8 input: roster + weekend seed. Nothing that hints at the answer."""
    return solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )


def test_golden_week_is_feasible() -> None:
    """§8: the photographed week has a valid schedule, unpinned."""
    res = _golden_result()
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert res.assignments


def test_golden_input_carries_no_free_day_pins() -> None:
    """§8 v1.12 guard: the anchor is only an anchor if the solver DERIVES the
    layout. A future edit that quietly re-pins the free days to keep this file
    green fails here first, before it can make the assertions below vacuous."""
    inp = SolverInput(
        week_monday=WEEK_MONDAY,
        roster=roster(),
        prior_state=canonical_prior_state(),
        weights=WEIGHTS,
    )
    assert dict(inp.free_day_pins) == {}
    assert dict(inp.sacrifice_grants) == {}


def test_golden_h1_every_slot_has_one_bagnino_and_one_spiaggino() -> None:
    """H1: each Mon–Fri slot has exactly one bagnino and exactly one spiaggino."""
    res = _golden_result()
    by_role = slots_by_role(res.assignments)
    for day in Day.MON, Day.TUE, Day.WED, Day.THU, Day.FRI:
        for slot in SOLVER_SLOTS:
            for role in BOTH_ROLES:
                holders = by_role.get((day, slot, role), [])
                assert len(holders) == 1, f"{day}/{slot}/{role}: {holders}"


def test_golden_h2_no_worker_holds_two_roles_in_one_slot() -> None:
    """H2: a person occupies at most one role in a given slot."""
    res = _golden_result()
    for (day, slot), ids in workers_in_slot(res.assignments).items():
        assert len(ids) == len(set(ids)), f"{day}/{slot} double-booked: {ids}"


def test_golden_h3_free_days_fall_in_the_role_domain() -> None:
    """H3(a)+(b): every core worker has exactly one free day and it lies inside
    their ROLE domain — spiaggini {Mon, Tue}, bagnini {Tue, Wed}. Derived, not
    pinned: this is the structure §8 says H3 must produce on its own."""
    res = _golden_result()
    for wid in sorted(CORE_IDS):
        free = free_day_of(res.assignments, wid)
        assert free is not None, f"worker {wid} has no single free day (H3(a))"
        assert free in role_domain(wid), (
            f"worker {wid} free {free} outside role domain {role_domain(wid)}"
        )


def test_golden_h3c_no_same_role_pair_shares_a_free_day() -> None:
    """H3(c): the two bagnini rest on different days, as do the two spiaggini —
    so neither role is left to the jolly alone for a whole day."""
    res = _golden_result()
    for a, b in SAME_ROLE_PAIRS:
        assert free_day_of(res.assignments, a) != free_day_of(res.assignments, b), (
            f"workers {a} and {b} share a role and a free day"
        )


def test_golden_reproduces_the_photographed_free_days() -> None:
    """§8: the photograph itself. H3 narrows the week to four legal layouts; §2.2
    picks this one — Pasha Mon, Amir Tue, Francesco Tue, Matteo Wed. The within-pair
    choice is the only part the photo pins by observation rather than by rule, and
    it is exactly what this assertion protects."""
    res = _golden_result()
    got = {wid: free_day_of(res.assignments, wid) for wid in GOLDEN_FREE_DAYS}
    assert got == GOLDEN_FREE_DAYS


def test_golden_h4_each_core_works_one_slot_per_non_free_day() -> None:
    """H4: a core worker works zero slots on their free day and exactly one on
    every other Mon–Fri day."""
    res = _golden_result()
    for wid in sorted(CORE_IDS):
        free = free_day_of(res.assignments, wid)
        days = worker_days(res.assignments, wid)
        assert days.get(free, []) == []
        for day in Day.MON, Day.TUE, Day.WED, Day.THU, Day.FRI:
            if day == free:
                continue
            assert len(days.get(day, [])) == 1, f"worker {wid} {day}: {days.get(day)}"


def test_golden_emergent_jolly_load_is_mon1_tue2_wed1_thu0_fri0() -> None:
    """§8/§2.1 H3: the jolly load is a CONSEQUENCE of H1+H3, identical on all four
    legal layouts — Mon 1, Tue 2, Wed 1, Thu 0, Fri 0. Asserted as an output so a
    future "clustering" rule that reshapes it cannot slip in unnoticed."""
    res = _golden_result()
    assert jolly_load(res.assignments) == GOLDEN_JOLLY_LOAD


def test_golden_mattia_doubles_tuesday() -> None:
    """§8 photo: Mattia works BOTH Tuesday slots (covering the Francesco bagnino
    gap and the Amir spiaggino gap), and doubles on no other day."""
    res = _golden_result()
    days = worker_days(res.assignments, MATTIA)
    tue = days.get(Day.TUE, [])
    assert len(tue) == 2, f"Mattia Tuesday: {tue}"
    assert {a.slot for a in tue} == set(SOLVER_SLOTS)  # one AM, one PM (H2)
    assert {a.role for a in tue} == set(BOTH_ROLES)  # one bagnino, one spiaggino
    # Tuesday is his only double; the other gap-days (Mon spiaggino, Wed bagnino)
    # are single slots — see the H6 occupancy test for the full accounting.
    for day, slots in days.items():
        if day != Day.TUE:
            assert len(slots) <= 1, f"unexpected double on {day}: {slots}"
