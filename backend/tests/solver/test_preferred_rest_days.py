"""Preferred rest days emerge from SOFT (S1) requests — never hardcoded (§2.2).

The spec forbids baking a preferred free day into the model (§2.2 S3: "Do **not**
hardcode a preferred day"); per-person day habits belong in each worker's soft
(S1) constraints. The real-world habit — the two spiaggini splitting Monday and
Tuesday, the two bagnini splitting Tuesday and Wednesday — is therefore expressed
as per-worker SOFT personal constraints (`kind=SOFT`, `FULL_DAY`) that the solver
honors as the top soft tier (S1 / W1).

These tests prove the pattern is reproduced from DATA alone: the model stays
name-agnostic and spec-faithful, and each free day is an OUTPUT of the request
set, not a constant. Feeding a different request set moves the free days with it.
"""

from __future__ import annotations

from app.enums import ConstraintKind, ConstraintSlot, Day
from app.solver import PersonalConstraint, SolverInput, SolverStatus, solve
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

# The requested habit as SOFT requests (a preference, not a hard rule): the two
# spiaggini rest Mon / Tue, the two bagnini rest Tue / Wed. Feasible together —
# no two same-role workers share a day, so the jolly can always cover the gaps.
_PREFERRED_REST: dict[int, Day] = {
    PASHA: Day.MON,  # spiaggino rests Monday
    AMIR: Day.TUE,  # the other spiaggino rests Tuesday
    MATTEO: Day.TUE,  # bagnino rests Tuesday
    FRANCESCO: Day.WED,  # the other bagnino rests Wednesday
}

# A DIFFERENT feasible request set (same-role workers still on distinct days),
# used to show the output free days track the data rather than a constant.
_ALT_REST: dict[int, Day] = {
    PASHA: Day.TUE,
    AMIR: Day.MON,
    MATTEO: Day.WED,
    FRANCESCO: Day.TUE,
}


def _soft_rest_requests(pattern: dict[int, Day]) -> tuple[PersonalConstraint, ...]:
    return tuple(
        PersonalConstraint(wid, day, ConstraintSlot.FULL_DAY, ConstraintKind.SOFT)
        for wid, day in pattern.items()
    )


def _solve(pattern: dict[int, Day]):
    return solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            constraints=_soft_rest_requests(pattern),
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )


def _free_days(res, pattern: dict[int, Day]) -> dict[int, Day | None]:
    return {wid: free_day_of(res.assignments, wid) for wid in pattern}


def test_preferred_rest_days_are_all_honored() -> None:
    """All four soft rest requests are jointly satisfiable (soft_unmet == 0), so
    each core worker's OUTPUT free day matches their requested day — the habit is
    reproduced without a single hardcoded day."""
    res = _solve(_PREFERRED_REST)
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert res.objective is not None
    assert res.objective.soft_unmet == 0  # every preference honored
    assert _free_days(res, _PREFERRED_REST) == _PREFERRED_REST


def test_free_days_track_the_request_set_not_a_constant() -> None:
    """Data-driven, not baked in: a DIFFERENT soft request set yields DIFFERENT
    free days (again at soft_unmet == 0). If the split were hardcoded, the output
    could not follow the request set like this."""
    res = _solve(_ALT_REST)
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert res.objective is not None
    assert res.objective.soft_unmet == 0
    assert _free_days(res, _ALT_REST) == _ALT_REST
    # And it genuinely differs from the first pattern (proving it moved with data).
    assert _ALT_REST != _PREFERRED_REST
