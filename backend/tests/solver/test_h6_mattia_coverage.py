"""H6 (Mattia coverage) verified as an EMERGENT property, not a redundant
constraint (§2.1).

H6 says the jolly fills every Mon–Fri slot left open by core free days. Rather
than assert a bespoke "H6 constraint" exists, these tests prove H6 falls out of
H1 (coverage) + H3/H4 (one free day, one slot per working day):

* occupancy   — the jolly works EXACTLY the role-days a core of that role vacates;
* necessity   — remove the jolly's availability and the instance is INFEASIBLE;
* non-insertion — the jolly never takes a slot on a (day, role) where both cores
  of that role are present (H1+H4 leave him no room, so he never displaces one).
"""

from __future__ import annotations

from app.enums import (
    AssignmentRole,
    ConstraintKind,
    ConstraintSlot,
    Day,
)
from app.solver import PersonalConstraint, SolverInput, SolverStatus, solve
from app.solver.types import SOLVER_DAYS
from tests.solver.fixtures import (
    AMIR,
    BAGNINO_CORE_IDS,
    FRANCESCO,
    MATTEO,
    MATTIA,
    PASHA,
    SPIAGGINO_CORE_IDS,
    WEEK_MONDAY,
    WEIGHTS,
    assignments_of,
    canonical_prior_state,
    free_day_of,
    roster,
)

# Free-day pins that spread the four core gaps across four distinct role-days,
# so the expected jolly occupancy is unambiguous (no doubling):
#   Mon: Matteo (bagnino) free   → Mattia bagnino Mon
#   Tue: Francesco (bagnino) free → Mattia bagnino Tue
#   Wed: Pasha (spiaggino) free   → Mattia spiaggino Wed
#   Thu: Amir (spiaggino) free    → Mattia spiaggino Thu
SPREAD_PINS = {MATTEO: Day.MON, FRANCESCO: Day.TUE, PASHA: Day.WED, AMIR: Day.THU}
EXPECTED_JOLLY_ROLE_DAYS = {
    (Day.MON, AssignmentRole.BAGNINO),
    (Day.TUE, AssignmentRole.BAGNINO),
    (Day.WED, AssignmentRole.SPIAGGINO),
    (Day.THU, AssignmentRole.SPIAGGINO),
}


def test_h6_occupancy_jolly_fills_exactly_the_vacated_role_days() -> None:
    """H6 occupancy: with core free days pinned, the jolly works exactly the
    role-slots the free days open — no more, no fewer."""
    res = solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            free_day_pins=SPREAD_PINS,
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    jolly = assignments_of(res.assignments, MATTIA)
    assert {(a.day, a.role) for a in jolly} == EXPECTED_JOLLY_ROLE_DAYS
    assert len(jolly) == len(EXPECTED_JOLLY_ROLE_DAYS)  # no redundant extra slot


def test_h6_necessity_infeasible_when_jolly_cannot_cover() -> None:
    """H6 necessity: the jolly is required. Make Mattia hard-unavailable every
    Mon–Fri day; the core free days (H3) leave gaps nobody else can fill →
    INFEASIBLE."""
    block_mattia = tuple(
        PersonalConstraint(MATTIA, day, ConstraintSlot.FULL_DAY, ConstraintKind.HARD)
        for day in SOLVER_DAYS
    )
    res = solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            constraints=block_mattia,
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )
    assert res.status is SolverStatus.INFEASIBLE


def test_h6_non_insertion_jolly_only_where_a_core_is_free() -> None:
    """H6 non-insertion: on an unpinned solve the jolly never works a (day, role)
    where both cores of that role are present. If both cores of a role work a day
    they fill both of that day's slots (H1 + H4), leaving the jolly no room — so
    every jolly assignment must coincide with a same-role core's free day."""
    res = solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    free_days = {
        wid: free_day_of(res.assignments, wid) for wid in BAGNINO_CORE_IDS | SPIAGGINO_CORE_IDS
    }
    for a in assignments_of(res.assignments, MATTIA):
        pool = BAGNINO_CORE_IDS if a.role is AssignmentRole.BAGNINO else SPIAGGINO_CORE_IDS
        assert any(free_days[wid] == a.day for wid in pool), (
            f"Mattia inserted as {a.role} on {a.day} with both cores present"
        )
