"""S3 — Mattia (jolly) free-day clustering (§2.2, W3) and the S2 rest spread.

§8 expresses S3 as minimizing the number of days Mattia works ≥ 1 slot, which is
equivalent to maximizing his full free days and induces free-day PAIRING. With
four core workers the minimum feasible `jolly_days` is 2 (two pairs); all four
free on one day is infeasible (one jolly cannot cover four role-slots in a day),
so 2 is the pairing optimum.

The rest-spread term (§2.2, W2_SPREAD, S2 band) overrides that pairing pull for
the two full-weekend workers (prior state FULL_DAY: the full-day spiaggini): the
pair is penalized for sharing a free day, so they split. This is now a spec rule,
not a tendency — see `test_full_weekend_pair_splits_free_days_with_early_monday`.
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

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase2

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


def test_full_weekend_pair_splits_free_days_with_early_monday() -> None:
    """S2 rest spread (§2.2, W2_SPREAD): the two full-weekend workers split.

    Pasha and Amir both exit the weekend FULL_DAY (canonical prior_state), so
    they are the F-pair the rest-spread term separates. On an otherwise
    unconstrained solve the model robustly guarantees two spec-backed properties:

    * **Spread:** ``pasha_free != amir_free``. Co-locating them costs W2_SPREAD =
      200, which no S2/S3 saving (≤ 101) can recover, so every optimum splits
      them onto different days (verified by exhaustive enumeration: the best
      shared layout scores 202 vs the split optimum's 102).

    * **Early Monday rest:** ``Day.MON`` is one of the two free days. A FULL_DAY
      worker who works Monday incurs an unavoidable cross-week boundary break
      (both Sunday slots collide with either Monday slot); resting one of the
      pair on Monday dodges one such break, and every non-Monday split scores
      strictly worse (≥ 203).

    The test deliberately does NOT pin the SECOND rest day. The pure model
    resolves it to Wednesday (S3 pairs it with an unpinned bagnino's free day for
    ``jolly_days = 2``), which is the model's own deterministic optimum — NOT the
    empirically observed Tuesday. Real weeks land on Tuesday because of Matteo's
    Wed soft preference, which is DELIBERATELY not in the model (§2.3 forbids
    hardcoding a preferred day). Asserting the exact second day would smuggle in
    that unmodelled pressure, so only the spread + early-Monday invariants are
    asserted here.
    """
    res = _unpinned()
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    pasha_free = free_day_of(res.assignments, PASHA)
    amir_free = free_day_of(res.assignments, AMIR)
    assert pasha_free != amir_free  # rest spread (W2_SPREAD)
    assert Day.MON in {pasha_free, amir_free}  # early Monday rest dodges a boundary break
