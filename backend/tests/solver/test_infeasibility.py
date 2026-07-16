"""Infeasibility attribution via assumption literals (§2.3, §8).

When hard personal constraints make coverage impossible, the solver must return
INFEASIBLE *and* name the responsible constraints in
`SolverResult.blocking_constraints` (from CP-SAT's
`sufficient_assumptions_for_infeasibility`). This is what drives the sacrifice
flow's "move your free day?" proposal, so "infeasible with no/incorrect
attribution" is itself a failure.
"""

from __future__ import annotations

from app.enums import ConstraintKind, ConstraintSlot, Day
from app.solver import PersonalConstraint, SolverInput, SolverStatus, solve
from tests.solver.fixtures import (
    FRANCESCO,
    MATTEO,
    MATTIA,
    PASHA,
    WEEK_MONDAY,
    WEIGHTS,
    canonical_prior_state,
    roster,
)

# Monday needs one bagnino AM and one bagnino PM. Block ALL THREE bagnini
# (Matteo, Francesco, and the jolly Mattia) for the whole of Monday → no bagnino
# can cover Monday → INFEASIBLE, and these three are the blocking set.
_BAGNINO_BLOCKS = (
    PersonalConstraint(MATTEO, Day.MON, ConstraintSlot.FULL_DAY, ConstraintKind.HARD),
    PersonalConstraint(FRANCESCO, Day.MON, ConstraintSlot.FULL_DAY, ConstraintKind.HARD),
    PersonalConstraint(MATTIA, Day.MON, ConstraintSlot.FULL_DAY, ConstraintKind.HARD),
)
# A satisfiable hard constraint, present to prove attribution names the RIGHT
# constraints and does not sweep in an innocent one.
_INNOCENT = PersonalConstraint(PASHA, Day.FRI, ConstraintSlot.AM, ConstraintKind.HARD)


def _result():
    return solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            constraints=(*_BAGNINO_BLOCKS, _INNOCENT),
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )


def test_blocking_coverage_is_infeasible() -> None:
    """§2.3 step 1: the over-constrained instance is INFEASIBLE with no output."""
    res = _result()
    assert res.status is SolverStatus.INFEASIBLE
    assert res.assignments == ()
    assert res.objective is None


def test_blocking_constraints_names_the_responsible_set() -> None:
    """§2.3 step 1: attribution names the three Monday bagnino blocks (the real
    conflict) and does NOT name the innocent, satisfiable Pasha/Friday request —
    §2.3 proposes the sacrifice to *that* worker, so an innocent bystander in the
    blocking set would misdirect the proposal."""
    res = _result()
    blocking = set(res.blocking_constraints)
    assert blocking, "INFEASIBLE with empty attribution cannot drive the sacrifice flow"
    assert set(_BAGNINO_BLOCKS) <= blocking  # the responsible constraints are named
    assert _INNOCENT not in blocking  # no innocent bystander → correct §2.3 targeting
