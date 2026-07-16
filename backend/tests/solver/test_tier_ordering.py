"""Lexicographic tier ordering W1 >> W2 >> W3 (§2.2).

A higher tier is honored even when it costs the tier below it. These tests rely
on the imported production weights being well-separated (see
`app.solver.weights`), so the assertions are about which tier is sacrificed, not
about raw penalty magnitudes.

S1 > S2 is constructed cleanly below. S2 > S3 is documented as a skip: see its
docstring — a clean, unambiguous, non-vacuous S2/S3 conflict could not be built
against the frozen interface without depending on solver tie-breaks, and the
brief forbids shipping a vacuous tier test.
"""

from __future__ import annotations

import pytest

from app.enums import AssignmentSlot, ConstraintKind, ConstraintSlot, Day
from app.solver import PersonalConstraint, SolverInput, SolverStatus, solve
from tests.solver.fixtures import (
    MATTEO,
    WEEK_MONDAY,
    WEIGHTS,
    canonical_prior_state,
    roster,
    worker_days,
)

# Matteo exits Sunday PM (canonical prior_state), so S2 alternation strictly
# prefers him on Mon AM. Pin his free day to Thu so he definitely works Monday.
_MATTEO_FREE_THU = {MATTEO: Day.THU}


def _solve(constraints=()):
    return solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            constraints=constraints,
            free_day_pins=_MATTEO_FREE_THU,
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )


def _matteo_monday_slots(res) -> set[AssignmentSlot]:
    return {a.slot for a in worker_days(res.assignments, MATTEO).get(Day.MON, [])}


def test_s2_alone_puts_matteo_on_monday_am() -> None:
    """Baseline for the S1 > S2 conflict: with no soft request, S2 places Matteo
    on Mon AM (prior PM → Mon AM avoids the cross-week boundary break). This
    proves the soft request below genuinely fights the alternation optimum."""
    res = _solve()
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert _matteo_monday_slots(res) == {AssignmentSlot.AM}


def test_s1_beats_s2_soft_request_honored_at_cost_of_alternation_break() -> None:
    """S1 > S2: a soft request forbidding Matteo's alternation-preferred Mon AM
    slot is honored (soft_unmet == 0). He moves to Mon PM — a same-slot boundary
    break with his Sunday PM exit — because one unmet soft (W1) dwarfs the extra
    alternation break (W2)."""
    soft = (PersonalConstraint(MATTEO, Day.MON, ConstraintSlot.AM, ConstraintKind.SOFT),)
    res = _solve(soft)
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert res.objective is not None
    assert res.objective.soft_unmet == 0  # S1 satisfied
    assert _matteo_monday_slots(res) == {AssignmentSlot.PM}  # forced off Mon AM

    # The satisfied soft cost a boundary break relative to the S2-only optimum,
    # confirming the trade actually happened (not a vacuous pass).
    baseline = _solve()
    assert res.objective.alternation_breaks > baseline.objective.alternation_breaks


@pytest.mark.skip(
    reason="S2 > S3 conflict not cleanly constructible against the frozen "
    "interface: jolly_days (S3) is governed by core free-day placement while "
    "alternation/fairness (S2) is governed by slot sequencing; every attempt to "
    "force a 1-for-1 trade between them depended on a CP-SAT tie-break, which "
    "would make the test vacuous or flaky. Reported for escalation — see "
    "test-engineer notes."
)
def test_s2_beats_s3_keeps_alternation_low_over_jolly_clustering() -> None:  # pragma: no cover
    """S2 > S3 (documented skip). Would assert the solver keeps alternation_breaks
    at the S2 minimum even when a jolly_days reduction (S3) is available only by
    adding a break. Not shipped as a live test because no unambiguous, non-vacuous
    instance could be constructed without leaning on tie-breaks."""
    raise AssertionError("placeholder — see skip reason")
