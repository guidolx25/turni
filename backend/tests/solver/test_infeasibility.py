"""Infeasibility attribution via assumption literals (§2.3, §8).

When hard personal constraints make coverage impossible, the solver must return
INFEASIBLE *and* name the responsible constraints in
`SolverResult.blocking_constraints` (from CP-SAT's
`sufficient_assumptions_for_infeasibility`). This is what drives the sacrifice
flow's "move your free day?" proposal, so "infeasible with no/incorrect
attribution" is itself a failure.
"""

from __future__ import annotations

import pytest

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

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase2

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
    """§2.3 step 1: attribution returns ONE provably-minimal unsat core.

    SEMANTICS CHANGE (user-directed, not editing-to-pass): the old "union of
    minimal cores" helper was proven buggy at a gate review — its greedy shrink
    stranded and DROPPED a genuine culprit in multi-conflict instances — and the
    user ruled it deleted in favour of a single minimal core per solve. §2.3's
    sacrifice flow is inherently iterative (propose to one worker → accept/pin →
    re-solve), so a minimal core (not a union) is the correct unit: it names the
    smallest sacrifice that unblocks *this* solve, and the next core surfaces on
    the next iteration (see ``test_blocking_core_iterates_to_the_other`` below).

    Monday needs a bagnino AM and PM; all three bagnini (Matteo, Francesco, jolly
    Mattia) are blocked, so any TWO of them make Monday uncoverable — two symmetric
    size-2 cores: {Mattia, Matteo} and {Mattia, Francesco}. A minimal core is
    therefore exactly Mattia + one core bagnino, and never the innocent, satisfiable
    Pasha/Friday request (minimality excludes bystanders by construction)."""
    res = _result()
    blocking = set(res.blocking_constraints)
    assert blocking, "INFEASIBLE with empty attribution cannot drive the sacrifice flow"

    # A genuine minimal core: a subset of the input hard constraints...
    inputs = {*_BAGNINO_BLOCKS, _INNOCENT}
    assert blocking <= inputs
    # ...that is exactly size 2 — Mattia plus exactly one of {Matteo, Francesco}...
    assert len(blocking) == 2
    mattia_block = _BAGNINO_BLOCKS[2]
    bagnino_blocks = {_BAGNINO_BLOCKS[0], _BAGNINO_BLOCKS[1]}
    assert mattia_block in blocking  # the jolly is in every Monday-coverage core
    assert len(blocking & bagnino_blocks) == 1  # exactly one symmetric core bagnino
    # ...and never the innocent bystander (minimality excludes it).
    assert _INNOCENT not in blocking

    # And it IS a core: unblocking exactly these restores feasibility.
    survivors = tuple(c for c in (*_BAGNINO_BLOCKS, _INNOCENT) if c not in blocking)
    unblocked = solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            constraints=survivors,
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )
    assert unblocked.status is not SolverStatus.INFEASIBLE


def test_blocking_core_iterates_to_the_other() -> None:
    """§2.3 iterate-per-core: unblocking the named core bagnino and re-solving
    surfaces the OTHER symmetric minimal core, so multi-conflict instances resolve
    through iteration rather than a single (buggy) union. Mattia — in every Monday
    core — stays named; the still-blocked core bagnino replaces the unblocked one."""
    first = _result()
    first_core = set(first.blocking_constraints)
    mattia_block = _BAGNINO_BLOCKS[2]
    bagnino_blocks = {_BAGNINO_BLOCKS[0], _BAGNINO_BLOCKS[1]}
    (named_bagnino,) = first_core & bagnino_blocks

    # Unblock the named bagnino (§2.3 accept → sacrifice that constraint); the
    # rest, including Mattia and the other bagnino, still block Monday coverage.
    remaining = tuple(c for c in (*_BAGNINO_BLOCKS, _INNOCENT) if c is not named_bagnino)
    second = solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            constraints=remaining,
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )
    assert second.status is SolverStatus.INFEASIBLE
    second_core = set(second.blocking_constraints)
    assert len(second_core) == 2
    assert mattia_block in second_core
    other_bagnino = (bagnino_blocks - {named_bagnino}).pop()
    assert other_bagnino in second_core
    assert named_bagnino not in second_core
