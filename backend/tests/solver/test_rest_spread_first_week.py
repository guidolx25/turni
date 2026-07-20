"""S2c rest spread fires on a first-ever week — no prior_state required (§2.2, §8).

The rest-spread term penalizes the two full-weekend workers (the full-day
spiaggini, §H5) resting on the SAME free day. Its F-pair must be derived from
THIS week's weekend-template membership (`SolverInput.full_weekend_ids`), NOT from
carried-forward `solver_state`. On a genuine first-ever week `prior_state` is empty,
yet those two spiaggini still work that week's H5 weekend template — so the term
must still fire.

Regression guard for the Phase 3 gate item: before the structural fix the F-pair
was read only from `prior_state == FULL_DAY`, so with an empty prior_state the term
silently vanished and the solver would co-locate the pair to shave a jolly day.
"""

from __future__ import annotations

import pytest

from app.enums import Day
from app.solver import SolverInput, SolverStatus, full_weekend_worker_ids, solve
from tests.solver.fixtures import (
    AMIR,
    FRANCESCO,
    MATTEO,
    PASHA,
    WEEK_MONDAY,
    WEIGHTS,
    free_day_of,
    roster,
)

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase3

# Same lever as the tier-ordering S2>S3 test: pin BOTH core bagnini to Thursday so
# the ONLY route to jolly_days = 2 is co-locating the two full-weekend spiaggini on
# one free day. S3 therefore actively pulls the pair together; only an active
# W2_SPREAD term (S2 band) keeps them apart.
_BOTH_BAGNINI_THU = {MATTEO: Day.THU, FRANCESCO: Day.THU}


def test_full_weekend_worker_ids_is_structural_not_identity() -> None:
    """The F-pair is derived from the emitted H5 template: the two full-day
    spiaggini, regardless of any prior state."""
    assert full_weekend_worker_ids(roster(), WEEK_MONDAY) == frozenset({PASHA, AMIR})


def test_rest_spread_fires_on_first_week_without_prior_state() -> None:
    """First-ever week (empty prior_state): with the structural `full_weekend_ids`
    supplied, the solver SPREADS the two full-weekend workers onto different free
    days even though co-locating them would cut jolly_days by one (S3).

    Pre-fix (F-pair read only from prior_state == FULL_DAY) this term was absent on
    an empty prior_state, so the optimizer co-located the pair — a shared free day.
    """
    res = solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            free_day_pins=_BOTH_BAGNINI_THU,
            prior_state={},  # first-ever week: no carry-forward
            full_weekend_ids=frozenset({PASHA, AMIR}),
            weights=WEIGHTS,
        )
    )
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert res.objective is not None

    pasha_free = free_day_of(res.assignments, PASHA)
    amir_free = free_day_of(res.assignments, AMIR)
    assert pasha_free is not None and amir_free is not None
    # The pair is spread despite the S3 pull to co-locate them.
    assert pasha_free != amir_free
    assert res.objective.spread_shared_pairs == 0
