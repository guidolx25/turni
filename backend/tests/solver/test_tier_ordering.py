"""Lexicographic tier ordering W1 >> {W2, W2_SPREAD} >> W3 (§2.2).

A higher tier is honored even when it costs the tier below it. These tests rely
on the imported production weights being well-separated (see
`app.solver.weights`), so the assertions are about which tier is sacrificed, not
about raw penalty magnitudes.

S1 > S2 is constructed cleanly below. S2-band > S3 is now constructible too: the
W2_SPREAD rest-spread term (S2 band) gives a free-day-placement lever that trades
directly against S3's jolly_days, so a non-vacuous conflict exists without leaning
on any AM/PM tie-break — see `test_s2_spread_beats_s3_keeps_pair_split_over_jolly`.
"""

from __future__ import annotations

from app.enums import AssignmentSlot, ConstraintKind, ConstraintSlot, Day
from app.solver import PersonalConstraint, SolverInput, SolverStatus, solve
from tests.solver.fixtures import (
    AMIR,
    FRANCESCO,
    MATTEO,
    PASHA,
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


# S2-band > S3 construction. Pinning BOTH core bagnini to the same free day (Thu)
# removes the free-day partners the jolly would otherwise pair each spiaggino with:
# on Thu both bagnino slots fall to Mattia, so no spiaggino can also be free Thu.
# The only route left to jolly_days = 2 is to co-locate the two full-weekend
# spiaggini (Pasha, Amir) on one day — which trips the W2_SPREAD rest-spread term
# (S2 band). Splitting them keeps spread = 0 but leaves jolly_days = 3.
_BOTH_BAGNINI_THU = {MATTEO: Day.THU, FRANCESCO: Day.THU}


def test_s2_spread_beats_s3_keeps_pair_split_over_jolly_clustering() -> None:
    """S2-band > S3: the solver keeps the full-weekend pair SPREAD (spread = 0)
    even though co-locating them would strictly reduce jolly_days (S3) by one.

    With both bagnini pinned to Thursday, a jolly_days = 2 layout exists but ONLY
    by resting Pasha and Amir on the same day (spread = 1, an S2-band penalty).
    The solver instead spreads them (spread = 0) and accepts jolly_days = 3,
    because one unit of W2_SPREAD (200) dwarfs the one-day S3 saving (W3 = 1) —
    proving the S2 band outranks S3. Asserted on objective values, not tie-breaks.
    """
    free = solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            free_day_pins=_BOTH_BAGNINI_THU,
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )
    # Baseline proving the trade is real (non-vacuous): forcing the pair to share
    # genuinely buys a lower jolly_days — the S3 improvement the solver forgoes.
    shared = solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            free_day_pins={**_BOTH_BAGNINI_THU, PASHA: Day.MON, AMIR: Day.MON},
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )
    assert free.objective is not None and shared.objective is not None

    # The S3 improvement genuinely exists: co-locating drops jolly_days by one.
    assert shared.objective.spread_shared_pairs == 1
    assert shared.objective.jolly_days == free.objective.jolly_days - 1

    # Yet the solver keeps the S2-band spread term at its minimum, sacrificing S3.
    assert free.objective.spread_shared_pairs == 0
    assert free.objective.jolly_days == 3
    # And that spread solution is strictly optimal over the lower-jolly shared one.
    assert free.objective.weighted_total < shared.objective.weighted_total
