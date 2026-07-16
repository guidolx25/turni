"""Cross-week alternation boundary term (§2.2 S2, §8 solver_state).

§2.2: alternation penalizes "each pair of consecutive worked days with the same
slot, including the boundary with the previous week." `SolverInput.prior_state`
carries each worker's last-worked boundary (`PriorSlot`). These tests prove the
Monday boundary behaves per `PriorSlot`:

* AM / PM  → penalizes the matching Monday slot only (the worker takes the other);
* FULL_DAY → both Monday slots collide, so the break is unavoidable but counts
  EXACTLY ONCE (the worker works one Monday slot), never twice;
* absent   → no boundary term;
* empty prior_state → a legal first-ever week that solves without error.

Single-worker priors isolate the term: only the target worker carries a
boundary, so its effect on `alternation_breaks` is a clean constant offset.
"""

from __future__ import annotations

from app.enums import AssignmentSlot, ConstraintKind, ConstraintSlot, Day
from app.solver import PersonalConstraint, PriorSlot, SolverInput, SolverStatus, solve
from tests.solver.fixtures import (
    FRANCESCO,
    MATTEO,
    PASHA,
    WEEK_MONDAY,
    WEIGHTS,
    roster,
    worker_days,
)


def _solve(prior_state, free_day_pins, constraints=()):
    return solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            constraints=constraints,
            free_day_pins=free_day_pins,
            prior_state=prior_state,
            weights=WEIGHTS,
        )
    )


def _monday_slots(res, wid) -> set[AssignmentSlot]:
    return {a.slot for a in worker_days(res.assignments, wid).get(Day.MON, [])}


def test_prior_pm_prefers_monday_am() -> None:
    """PriorSlot.PM penalizes Mon PM but not Mon AM → the worker takes Mon AM."""
    res = _solve({MATTEO: PriorSlot.PM}, {MATTEO: Day.THU})
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert _monday_slots(res, MATTEO) == {AssignmentSlot.AM}


def test_prior_am_prefers_monday_pm() -> None:
    """PriorSlot.AM is symmetric: penalizes Mon AM → the worker takes Mon PM."""
    res = _solve({FRANCESCO: PriorSlot.AM}, {FRANCESCO: Day.THU})
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert _monday_slots(res, FRANCESCO) == {AssignmentSlot.PM}


def test_prior_full_day_breaks_monday_am_exactly_once() -> None:
    """PriorSlot.FULL_DAY collides with Mon AM. Isolate Pasha's boundary by
    forcing him to Mon AM and comparing to an otherwise-identical solve where he
    is ABSENT from prior_state: the break count rises by EXACTLY one (never two,
    which a model double-counting the FULL_DAY prior would produce)."""
    force_am = (PersonalConstraint(PASHA, Day.MON, ConstraintSlot.PM, ConstraintKind.HARD),)
    full = _solve({PASHA: PriorSlot.FULL_DAY}, {PASHA: Day.THU}, force_am)
    absent = _solve({}, {PASHA: Day.THU}, force_am)
    assert full.objective is not None and absent.objective is not None
    assert _monday_slots(full, PASHA) == {AssignmentSlot.AM}
    assert full.objective.alternation_breaks - absent.objective.alternation_breaks == 1


def test_prior_full_day_breaks_monday_pm_exactly_once() -> None:
    """FULL_DAY collides with Mon PM too — the break is unavoidable in EITHER
    direction. Forcing Pasha to Mon PM raises the count by exactly one vs absent."""
    force_pm = (PersonalConstraint(PASHA, Day.MON, ConstraintSlot.AM, ConstraintKind.HARD),)
    full = _solve({PASHA: PriorSlot.FULL_DAY}, {PASHA: Day.THU}, force_pm)
    absent = _solve({}, {PASHA: Day.THU}, force_pm)
    assert full.objective is not None and absent.objective is not None
    assert _monday_slots(full, PASHA) == {AssignmentSlot.PM}
    assert full.objective.alternation_breaks - absent.objective.alternation_breaks == 1


def test_worker_absent_from_prior_state_incurs_no_boundary_term() -> None:
    """A worker not in prior_state has no boundary: their Monday slot is chosen
    freely, so forcing either slot costs no boundary break (the `absent` solves
    in the FULL_DAY tests are the baseline; here we assert the count matches
    across both forced directions, i.e. no boundary asymmetry for an absent
    worker)."""
    force_am = (PersonalConstraint(PASHA, Day.MON, ConstraintSlot.PM, ConstraintKind.HARD),)
    force_pm = (PersonalConstraint(PASHA, Day.MON, ConstraintSlot.AM, ConstraintKind.HARD),)
    am = _solve({}, {PASHA: Day.THU}, force_am)
    pm = _solve({}, {PASHA: Day.THU}, force_pm)
    assert am.objective is not None and pm.objective is not None
    # No prior → neither Monday slot is boundary-penalized, so the achievable
    # break minimum is identical whichever slot Pasha is pinned into.
    assert am.objective.alternation_breaks == pm.objective.alternation_breaks


def test_empty_prior_state_is_a_legal_first_week() -> None:
    """§8/PriorSlot: an empty prior_state (first-ever week, no carry-forward)
    is a legal input and solves without error."""
    res = _solve({}, {})
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert res.assignments
