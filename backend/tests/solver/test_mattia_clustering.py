"""S3 — Mattia (jolly) free-day clustering (§2.2, W3).

§8 expresses S3 as minimizing the number of days Mattia works ≥ 1 slot, which is
equivalent to maximizing his full free days and induces free-day PAIRING. With
four core workers the minimum feasible `jolly_days` is 2 (two pairs); all four
free on one day is infeasible (one jolly cannot cover four role-slots in a day),
so 2 is the pairing optimum.

The early-rest test is flagged PENDING-EMPIRICAL: it encodes a user-reported
*tendency*, not a spec rule, and rides on the soft S2 nudge. If it does not
reproduce at the spec-faithful weights it must be ESCALATED (a recorded decision
exists to revisit §2 with the user) — never forced, and no test here is
weakened to make it pass.
"""

from __future__ import annotations

import pytest

from app.enums import Day
from app.solver import SolverInput, SolverStatus, solve
from tests.solver.fixtures import (
    AMIR,
    FRANCESCO,
    MATTEO,
    PASHA,
    WEEK_MONDAY,
    WEIGHTS,
    canonical_prior_state,
    free_day_of,
    roster,
)

# All four cores on distinct days → Mattia works four days (jolly_days = 4): the
# maximally-spread, S3-worst configuration.
_SPREAD_PINS = {MATTEO: Day.MON, FRANCESCO: Day.TUE, PASHA: Day.WED, AMIR: Day.THU}


def _unpinned():
    return solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )


def test_s3_unpinned_solve_reaches_minimum_jolly_days() -> None:
    """S3: with free days unpinned the solver clusters them into two pairs, so
    Mattia works exactly two days (the feasible minimum) and gets full days off."""
    res = _unpinned()
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert res.objective is not None
    assert res.objective.jolly_days == 2


def test_s3_spread_free_days_is_strictly_worse_than_clustered() -> None:
    """S3: a fully-spread free-day layout (jolly_days = 4) has a strictly worse
    weighted objective than the clustered optimum — paired free days win."""
    optimal = _unpinned()
    spread = solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            free_day_pins=_SPREAD_PINS,
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )
    assert optimal.objective is not None and spread.objective is not None
    assert spread.objective.jolly_days == 4
    assert spread.objective.weighted_total > optimal.objective.weighted_total


@pytest.mark.xfail(
    reason="PENDING-EMPIRICAL / ESCALATE: at the spec-faithful weights the solver "
    "frees BOTH Pasha and Amir on Monday (also S2- and S3-optimal) rather than the "
    "user-reported one-Mon/one-Tue early split. This is a tendency, not a spec rule; "
    "a recorded decision revisits §2 with the user. Not forced, not patched — xfail "
    "keeps the assertion live so it flips to xpass if the behavior ever appears.",
    strict=False,
)
def test_early_rest_tendency_pasha_and_amir_take_monday_tuesday() -> None:
    """PENDING-EMPIRICAL (user-reported tendency, not a spec rule).

    Pasha and Amir exit the weekend FULL_DAY (canonical prior_state), so an early
    free day dodges their unavoidable Monday alternation break. This asserts the
    soft S2 nudge lands them on an early split — one Monday, one Tuesday — on an
    otherwise-unconstrained solve.

    If this FAILS at the spec-faithful weights (e.g. the solver instead frees
    BOTH on Monday, which is also S2- and S3-good), that is REPORTED for
    escalation, not patched away and not a reason to weaken any other test.
    """
    res = _unpinned()
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    pasha_free = free_day_of(res.assignments, PASHA)
    amir_free = free_day_of(res.assignments, AMIR)
    assert {pasha_free, amir_free} == {Day.MON, Day.TUE}
