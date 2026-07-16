"""GOLDEN TEST — the §8 regression anchor. DO NOT RELAX.

Reproduces the photographed week of 2026-07-13: the core free days are pinned
(Pasha=Mon, Francesco=Tue, Amir=Tue, Matteo=Wed) and the solver must return a
schedule matching the photo's COVERAGE STRUCTURE — every slot covered, one slot
per worker per working day, and Mattia doubling Tuesday.

This test asserts structural coverage, never a specific AM/PM-per-person layout:
§8 anchors on the coverage the photo shows, and CP-SAT may pick any equal-cost
AM/PM tie-break. It may only ever become STRICTER, never looser. If it fails,
the solver is wrong (or the spec changed with approval) — it is never edited to
pass.
"""

from __future__ import annotations

from app.enums import AssignmentRole, AssignmentSlot, Day
from app.solver import SolverInput, SolverStatus, solve
from tests.solver.fixtures import (
    AMIR,
    CORE_IDS,
    FRANCESCO,
    MATTEO,
    MATTIA,
    PASHA,
    WEEK_MONDAY,
    WEIGHTS,
    canonical_prior_state,
    free_day_of,
    roster,
    slots_by_role,
    worker_days,
    workers_in_slot,
)

# The photographed free days (§8): Pasha Mon, Francesco + Amir Tue, Matteo Wed.
GOLDEN_PINS = {PASHA: Day.MON, FRANCESCO: Day.TUE, AMIR: Day.TUE, MATTEO: Day.WED}
SOLVER_SLOTS = (AssignmentSlot.AM, AssignmentSlot.PM)
BOTH_ROLES = (AssignmentRole.BAGNINO, AssignmentRole.SPIAGGINO)


def _golden_result():
    return solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            free_day_pins=GOLDEN_PINS,
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )


def test_golden_week_is_feasible() -> None:
    """§8: the pinned photographed week has a valid schedule."""
    res = _golden_result()
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert res.assignments


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


def test_golden_h3_h4_each_core_works_one_slot_per_non_free_day() -> None:
    """H3/H4: each core worker is free exactly on their pinned day (zero slots)
    and works exactly one slot on every other Mon–Fri day."""
    res = _golden_result()
    for wid in CORE_IDS:
        assert free_day_of(res.assignments, wid) == GOLDEN_PINS[wid]
        days = worker_days(res.assignments, wid)
        assert days.get(GOLDEN_PINS[wid], []) == []
        for day in Day.MON, Day.TUE, Day.WED, Day.THU, Day.FRI:
            if day == GOLDEN_PINS[wid]:
                continue
            assert len(days.get(day, [])) == 1, f"worker {wid} {day}: {days.get(day)}"


def test_golden_mattia_doubles_tuesday() -> None:
    """§8 photo: Mattia works BOTH Tuesday slots (covers the Francesco bagnino
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
