"""Infeasibility attribution via assumption literals (§2.3, §8).

When hard personal constraints make coverage impossible, the solver must return
INFEASIBLE *and* name the responsible constraints in
`SolverResult.blocking_constraints` (from CP-SAT's
`sufficient_assumptions_for_infeasibility`). This is what drives the sacrifice
flow's "move your free day?" proposal, so "infeasible with no/incorrect
attribution" is itself a failure.

**The fixture, and why it changed at v1.12.** It used to block all three bagnini
for the whole of Monday and expect two symmetric size-2 cores. Under the v1.12
role domains that instance no longer says what it meant to say: bagnini rest
Tue/Wed, so BOTH work Monday and fill Monday's two bagnino slots between them,
while exactly one *spiaggino* rests Monday (H3(b) + H3(c)) and the jolly is
therefore obligatory as a Monday spiaggino. Blocking the jolly's Monday alone is
then infeasible on its own, and the minimal core collapses to a single constraint
— correctly, but for a reason that has nothing to do with bagnino coverage.

The instance below is rebuilt on the days H3 leaves the jolly idle (Thu and Fri
carry jolly load zero), where the two same-role cores really are the only
candidates for a slot. Two INDEPENDENT conflicts are planted, which is what makes
the iteration property assertable at all.
"""

from __future__ import annotations

import pytest

from app.enums import ConstraintKind, ConstraintSlot, Day
from app.solver import PersonalConstraint, SolverInput, SolverStatus, solve
from tests.solver.fixtures import (
    AMIR,
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


def _hard(worker_id: int, day: Day, slot: ConstraintSlot) -> PersonalConstraint:
    return PersonalConstraint(worker_id, day, slot, ConstraintKind.HARD)


# Conflict A — Thursday's AM bagnino slot. Thursday is outside both role domains,
# so both bagnini work it and take one slot each (H4); barring both from AM leaves
# them fighting over the single PM slot. Minimal, and size 2.
_CONFLICT_A = (
    _hard(MATTEO, Day.THU, ConstraintSlot.AM),
    _hard(FRANCESCO, Day.THU, ConstraintSlot.AM),
)
# Conflict B — the same shape one role and one day over: Friday's AM spiaggino slot.
_CONFLICT_B = (
    _hard(PASHA, Day.FRI, ConstraintSlot.AM),
    _hard(AMIR, Day.FRI, ConstraintSlot.AM),
)
# A satisfiable hard constraint, present to prove attribution names the RIGHT
# constraints and does not sweep in an innocent one. H3 gives the jolly zero
# Thursday slots, so barring him from Thursday AM costs nothing.
_INNOCENT = _hard(MATTIA, Day.THU, ConstraintSlot.AM)


def _solve(constraints: tuple[PersonalConstraint, ...]):
    return solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            constraints=constraints,
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )


def _result():
    return _solve((*_CONFLICT_A, *_CONFLICT_B, _INNOCENT))


def test_blocking_coverage_is_infeasible() -> None:
    """§2.3 step 1: the over-constrained instance is INFEASIBLE with no output."""
    res = _result()
    assert res.status is SolverStatus.INFEASIBLE
    assert res.assignments == ()
    assert res.objective is None


def test_each_planted_conflict_is_a_core_on_its_own() -> None:
    """Fixture precondition, asserted rather than assumed: each pair blocks the
    week by itself, and neither is implied by the other. Without this the
    iteration test below could pass on an instance with only one real conflict."""
    for conflict in (_CONFLICT_A, _CONFLICT_B):
        alone = _solve(conflict)
        assert alone.status is SolverStatus.INFEASIBLE
        assert set(alone.blocking_constraints) == set(conflict)
        # And each is MINIMAL: drop either half and the week solves.
        for keep in conflict:
            assert _solve((keep,)).status is not SolverStatus.INFEASIBLE


def test_blocking_constraints_names_the_responsible_set() -> None:
    """§2.3 step 1: attribution returns ONE provably-minimal unsat core.

    SEMANTICS (user-directed): the old "union of minimal cores" helper was proven
    buggy at a gate review — its greedy shrink stranded and DROPPED a genuine
    culprit in multi-conflict instances — and the user ruled it deleted in favour of
    a single minimal core per solve. §2.3's sacrifice flow is inherently iterative
    (propose to one worker → accept/pin → re-solve), so a minimal core (not a
    union) is the correct unit: it names the smallest sacrifice that unblocks
    *this* solve, and the next core surfaces on the next iteration (see
    ``test_blocking_core_iterates_to_the_other`` below).

    With two independent conflicts planted, a minimal core is exactly one of them
    — never both, and never the innocent, satisfiable jolly request (minimality
    excludes bystanders by construction)."""
    res = _result()
    blocking = set(res.blocking_constraints)
    assert blocking, "INFEASIBLE with empty attribution cannot drive the sacrifice flow"

    inputs = {*_CONFLICT_A, *_CONFLICT_B, _INNOCENT}
    assert blocking <= inputs  # a subset of the input hard constraints...
    assert blocking in (set(_CONFLICT_A), set(_CONFLICT_B))  # ...exactly one conflict...
    assert _INNOCENT not in blocking  # ...and never the bystander.

    # And it IS a core: unblocking exactly these leaves the OTHER conflict, so the
    # week is still infeasible — but for a demonstrably different reason.
    survivors = tuple(c for c in (*_CONFLICT_A, *_CONFLICT_B, _INNOCENT) if c not in blocking)
    second = _solve(survivors)
    assert set(second.blocking_constraints) != blocking


def test_blocking_core_iterates_to_the_other() -> None:
    """§2.3 iterate-per-core: unblocking the named core and re-solving surfaces the
    OTHER independent minimal core, so multi-conflict instances resolve through
    iteration rather than a single (buggy) union. Once both are cleared the week
    solves, which proves the iteration terminates rather than merely churning."""
    first = set(_result().blocking_constraints)
    other = set(_CONFLICT_B) if first == set(_CONFLICT_A) else set(_CONFLICT_A)

    remaining = tuple(c for c in (*_CONFLICT_A, *_CONFLICT_B, _INNOCENT) if c not in first)
    second = _solve(remaining)
    assert second.status is SolverStatus.INFEASIBLE
    assert set(second.blocking_constraints) == other
    assert not (first & set(second.blocking_constraints))

    # Clear the second core too and the week resolves — the flow terminates.
    cleared = tuple(c for c in remaining if c not in other)
    assert _solve(cleared).status is not SolverStatus.INFEASIBLE
