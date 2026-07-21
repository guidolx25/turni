"""H3's free-day domain on a NO-GRANT solve is the ROLE domain (§2.1 H3, §8).

Scope note — read this before the test names. §2.1 H3 has three hard clauses since
v1.12:

* **(a) cardinality** — exactly one free day per core worker;
* **(b) role domain** — it falls inside `ROLE_FREE_DAYS[role]`: spiaggini
  {Mon, Tue}, bagnini {Tue, Wed}. Thursday and Friday are outside *every* default
  domain. A worker holding a §2.3 **sacrifice grant** for day `g` has the domain
  `role-domain ∪ {g}`;
* **(c) same-role distinctness** — two workers sharing a role never share a free
  day, granted or not.

Every input in this file is a **no-grant** input (`sacrifice_grants` empty), which
is what every normal solve is. The granted case is legal and covered separately in
`test_sacrifice_grant.py`; the two must never be conflated.

Why this file still matters, in three parts:

1. **A normal solve's domain is exactly the role domain.** Nothing may hand a
   bagnino a Monday, a spiaggino a Wednesday, or anyone a Thu/Fri/weekend free day
   without a grant issued by the §2.3 flow — not a pin, not a hard request, not
   the optimizer.
2. **H3(c) does real work.** It is not implied by coverage: several layouts share
   a same-role free day and still cover fine under H1+H6, so without (c) the
   solver would be free to produce them.
3. **A bare pin can never rescue an infeasible week** (the last test). This is
   what makes the grant load-bearing rather than decorative: pinning only *adds*
   `free[u][d] = 1` to an unchanged model, shrinking the feasible region, so if
   the §2.3 probe were a pin alone it could never succeed and the propose branch
   would be dead code.
"""

from __future__ import annotations

import itertools

import pytest

from app.enums import ConstraintKind, ConstraintSlot, Day, UserRole
from app.solver import PersonalConstraint, SolverInput, SolverStatus, solve
from app.solver.types import ROLE_FREE_DAYS, SOLVER_DAYS
from tests.solver.fixtures import (
    AMIR,
    BAGNINO_CORE_IDS,
    CORE_IDS,
    FRANCESCO,
    MATTEO,
    PASHA,
    SAME_ROLE_PAIRS,
    SPIAGGINO_CORE_IDS,
    WEEK_MONDAY,
    WEIGHTS,
    canonical_prior_state,
    free_day_of,
    role_domain,
    roster,
    worker_days,
)

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase3

# Outside EVERY default role domain (§2.1 H3(b)): no core worker rests here
# without a §2.3 grant, whatever their role.
UNIVERSALLY_OUT_OF_DOMAIN = (Day.THU, Day.FRI)


def _input(**overrides) -> SolverInput:
    kwargs = {
        "week_monday": WEEK_MONDAY,
        "roster": roster(),
        "prior_state": canonical_prior_state(),
        "weights": WEIGHTS,
    }
    kwargs.update(overrides)
    return SolverInput(**kwargs)


def _hard(worker_id: int, day: Day, slot: ConstraintSlot = ConstraintSlot.FULL_DAY):
    return PersonalConstraint(worker_id, day, slot, ConstraintKind.HARD)


def _feasible(res) -> bool:
    return res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)


# --- (b): the domain itself -------------------------------------------------


def test_h3b_role_free_days_are_the_two_spec_domains() -> None:
    """§2.1 H3(b)/§8: the DEFAULT domain is per ROLE — spiaggini {Mon, Tue},
    bagnini {Tue, Wed} — keyed off `users.role`, never off identity. Asserted on
    the constant itself so widening it fails here first, and so the jolly's
    ABSENCE (H6: no free day at all) is pinned too."""
    assert ROLE_FREE_DAYS[UserRole.SPIAGGINO] == (Day.MON, Day.TUE)
    assert ROLE_FREE_DAYS[UserRole.BAGNINO] == (Day.TUE, Day.WED)
    assert UserRole.JOLLY not in ROLE_FREE_DAYS
    # Thu/Fri are outside every default domain; the weekend is not a candidate
    # at all (H5 — the weekend has no solver variables).
    for domain in ROLE_FREE_DAYS.values():
        assert not set(domain) & {Day.THU, Day.FRI, Day.SAT, Day.SUN}


def test_h3b_free_days_land_in_the_role_domain_on_a_plain_solve() -> None:
    """§2.1 H3(a)+(b): on a plain feasible NO-GRANT solve each core worker has
    exactly one free day and it lies in their role domain."""
    res = solve(_input())
    assert _feasible(res)
    for uid in sorted(CORE_IDS):
        free = free_day_of(res.assignments, uid)
        assert free in role_domain(uid), f"worker {uid}: {free} ∉ {role_domain(uid)}"


def test_h3b_no_core_worker_ever_rests_on_thursday_or_friday() -> None:
    """§2.1 H3(b) + H4: Thu and Fri are outside every default domain, so on a
    no-grant solve every core worker works both."""
    res = solve(_input())
    assert _feasible(res)
    for uid in sorted(CORE_IDS):
        days = worker_days(res.assignments, uid)
        for day in UNIVERSALLY_OUT_OF_DOMAIN:
            assert day in days, f"core worker {uid} must work {day.value} with no grant"


def test_h3b_a_bagnino_cannot_be_freed_on_monday() -> None:
    """§2.1 H3(b): Monday is in the SPIAGGINO domain, not the bagnino one. A hard
    full-day Monday request would need the bagnino's free day there, so the plain
    solve is INFEASIBLE and the §8 core names him. (Monday is `reachable` for a
    bagnino — the resolution is a §2.3 grant, not a wider default domain.)"""
    for uid in sorted(BAGNINO_CORE_IDS):
        assert Day.MON not in role_domain(uid)
        res = solve(_input(constraints=(_hard(uid, Day.MON),)))
        assert res.status is SolverStatus.INFEASIBLE, f"bagnino {uid} rested Monday with no grant"
        assert (uid, Day.MON) in {(c.worker_id, c.day) for c in res.blocking_constraints}


def test_h3b_a_spiaggino_cannot_be_freed_on_wednesday() -> None:
    """§2.1 H3(b), the mirror case: Wednesday is in the BAGNINO domain. A hard
    full-day Wednesday request from a spiaggino is INFEASIBLE plain, and the core
    names him."""
    for uid in sorted(SPIAGGINO_CORE_IDS):
        assert Day.WED not in role_domain(uid)
        res = solve(_input(constraints=(_hard(uid, Day.WED),)))
        assert res.status is SolverStatus.INFEASIBLE, f"spiaggino {uid} rested Wed with no grant"
        assert (uid, Day.WED) in {(c.worker_id, c.day) for c in res.blocking_constraints}


def test_h3b_an_out_of_domain_pin_is_ignored_never_self_granting() -> None:
    """§8: a free-day pin outside the worker's DOMAIN cannot widen it. Pinning
    every core worker to Thursday — outside both role domains — leaves the solve
    feasible with all four still working Thursday. Only §2.3 issues the grant that
    would make such a pin meaningful."""
    res = solve(_input(free_day_pins=dict.fromkeys(sorted(CORE_IDS), Day.THU)))
    assert _feasible(res)
    for uid in sorted(CORE_IDS):
        assert Day.THU in worker_days(res.assignments, uid), (
            f"a Thursday pin must not grant worker {uid} a Thursday free day"
        )
        assert free_day_of(res.assignments, uid) in role_domain(uid)


def test_h3b_a_cross_role_pin_is_ignored_too() -> None:
    """§8: the pin guard is about the ROLE domain, not just about Thu/Fri. Pinning
    a bagnino to Monday and a spiaggino to Wednesday — days that are perfectly
    legal for the *other* role — changes nothing: each free day stays in its own
    domain."""
    res = solve(_input(free_day_pins={MATTEO: Day.MON, PASHA: Day.WED}))
    assert _feasible(res)
    assert free_day_of(res.assignments, MATTEO) in role_domain(MATTEO)
    assert free_day_of(res.assignments, PASHA) in role_domain(PASHA)


# --- (c): same-role distinctness is HARD and does real work -----------------


def test_h3c_both_spiaggini_pinned_monday_is_infeasible() -> None:
    """§2.1 H3(c): Monday is in-domain for BOTH spiaggini and H1+H6 could cover a
    day they both rest — the jolly would simply take both spiaggino slots. (c)
    forbids it outright, so pinning both to Monday is INFEASIBLE rather than merely
    expensive. Nothing but (c) rules this layout out."""
    res = solve(_input(free_day_pins={PASHA: Day.MON, AMIR: Day.MON}))
    assert res.status is SolverStatus.INFEASIBLE


def test_h3c_both_bagnini_pinned_wednesday_is_infeasible() -> None:
    """§2.1 H3(c), the other pair: Wednesday is in-domain for both bagnini, and
    the pre-v1.12 rest-spread preference covered only the spiaggini. (c) extends
    the rule to the bagnini and hardens it."""
    res = solve(_input(free_day_pins={MATTEO: Day.WED, FRANCESCO: Day.WED}))
    assert res.status is SolverStatus.INFEASIBLE


def test_h3c_split_pins_solve_so_the_refusals_above_are_about_sharing() -> None:
    """Control for the two tests above: the SAME pins, split across the pair's two
    in-domain days, solve to OPTIMAL. So the refusals are H3(c) sharing, not a
    pinning mechanism that rejects these days generally."""
    res = solve(
        _input(
            free_day_pins={
                PASHA: Day.MON,
                AMIR: Day.TUE,
                MATTEO: Day.WED,
                FRANCESCO: Day.TUE,
            }
        )
    )
    assert res.status is SolverStatus.OPTIMAL
    for a, b in SAME_ROLE_PAIRS:
        assert free_day_of(res.assignments, a) != free_day_of(res.assignments, b)


def test_h3c_holds_on_every_plain_solve_not_only_under_pins() -> None:
    """§2.1 H3(c) as an unconditional invariant: no pins at all, and the two
    same-role pairs still rest on different days."""
    res = solve(_input())
    assert _feasible(res)
    for a, b in SAME_ROLE_PAIRS:
        assert free_day_of(res.assignments, a) != free_day_of(res.assignments, b)


# --- the structural consequence for the §2.3 probe --------------------------


def test_h3_a_free_day_pin_can_never_rescue_an_infeasible_week() -> None:
    """§2.3: a free-day pin only ever ADDS the constraint `free[u][d] == 1` to an
    otherwise unchanged model, so the pinned instance's feasible region is a SUBSET
    of the unpinned one. An INFEASIBLE week therefore stays INFEASIBLE under every
    pin — swept here over every two-constraint conflict, with zero rescues.

    This is the property that makes the §2.3 sacrifice **grant** load-bearing
    rather than decorative. If the probe in `sacrifice_service.open_sacrifice` were
    a bare pin, it could never succeed and step 2 ("move your free day to {day}?")
    would be dead code. The grant widens the domain FIRST; the pin then lands the
    free day inside the widened domain. Accordingly the sweep below pins only days
    already inside the worker's ROLE domain and passes no grants.

    A failure here means a pin has gained the power to widen a domain — i.e. the
    grant is being bypassed. Do not "fix" it by adding a grant to the sweep.
    """
    universe = [_hard(w.id, d) for w in roster() for d in SOLVER_DAYS]
    infeasible_seen = 0
    by_id = {w.id: w for w in roster()}
    for combo in itertools.combinations(universe, 2):
        res = solve(_input(constraints=combo))
        if res.status is not SolverStatus.INFEASIBLE:
            continue
        infeasible_seen += 1
        # Every core worker named by the unsat core, pinned to each day their own
        # role domain already allows — the only pins the model can act on.
        candidates = {
            (c.worker_id, day)
            for c in res.blocking_constraints
            if by_id.get(c.worker_id) is not None and by_id[c.worker_id].is_core
            for day in role_domain(c.worker_id)
        }
        for worker_id, day in sorted(candidates):
            probe = solve(_input(constraints=combo, free_day_pins={worker_id: day}))
            assert probe.status is SolverStatus.INFEASIBLE, (
                f"pin {worker_id}->{day.value} rescued {combo}; the §2.3 probe branch is "
                "reachable again — re-read this test's docstring before changing it"
            )
    assert infeasible_seen > 0, "the sweep must actually exercise INFEASIBLE instances"
