"""H3's free-day domain on a NO-GRANT solve is exactly Mon–Thu (§2.1 H3, §8).

Scope note — read this before the test names. §2.1 H3 was amended (v1.4): Mon–Thu
is the *default* domain, and a worker holding a §2.3 **sacrifice grant** for day
`g` has the domain `Mon–Thu ∪ {g}`. Every input in this file is a **no-grant**
input (`sacrifice_grants` empty), which is what every normal solve is. So the
names below — "no core worker is ever free on Friday", "a Friday pin is refused" —
are true *of a solve carrying no grant*, and that is the property being pinned.
The granted case is legal and is covered separately in `test_sacrifice_grant.py`;
the two must never be conflated.

Why this file still matters after the amendment, in two parts:

1. **A normal solve's domain is exactly Mon–Thu.** Nothing may hand a worker a
   Friday (or weekend) free day without a grant issued by the §2.3 flow — not a
   pin, not a hard request, not the optimizer.
2. **A bare pin can never rescue an infeasible week** (the last test). This is
   what makes the grant load-bearing rather than decorative: pinning only *adds*
   `free[u][d] = 1` to an unchanged model, shrinking the feasible region, so if
   the §2.3 probe were a pin alone it could never succeed and the propose branch
   would be dead code. The probe is feasible only because the grant WIDENS the
   domain first. If this test ever starts failing, a pin has acquired the power
   to widen a domain and the grant mechanism has been quietly bypassed.
"""

from __future__ import annotations

import itertools

import pytest

from app.enums import ConstraintKind, ConstraintSlot, Day
from app.solver import PersonalConstraint, SolverInput, SolverStatus, solve
from app.solver.types import FREE_DAYS, SOLVER_DAYS
from tests.solver.fixtures import (
    CORE_IDS,
    WEEK_MONDAY,
    WEIGHTS,
    canonical_prior_state,
    roster,
    worker_days,
)

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase3

NON_FREE_DAYS = tuple(d for d in SOLVER_DAYS if d not in FREE_DAYS)


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


# --- the domain itself ------------------------------------------------------


def test_h3_free_day_domain_is_exactly_mon_thu() -> None:
    """§2.1 H3/§8: the DEFAULT free-day domain is Mon–Thu — Friday and the weekend
    are not free-day candidates absent a §2.3 grant. Asserted on the constant
    `free_day_domain` returns unchanged when no grant applies, so widening the
    default (as opposed to widening one worker via a grant) fails here first."""
    assert FREE_DAYS == (Day.MON, Day.TUE, Day.WED, Day.THU)
    assert Day.FRI not in FREE_DAYS
    assert Day.SAT not in FREE_DAYS and Day.SUN not in FREE_DAYS
    assert NON_FREE_DAYS == (Day.FRI,)


def test_h3_no_core_worker_is_ever_free_on_friday() -> None:
    """§2.1 H3 + H4: on a plain feasible NO-GRANT solve every core worker works
    Friday — nobody's single free day lands outside Mon–Thu. (Under a §2.3 grant a
    Friday free day is legal; that case is `test_sacrifice_grant.py`.)"""
    res = solve(_input())
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    for uid in sorted(CORE_IDS):
        days = worker_days(res.assignments, uid)
        assert Day.FRI in days, f"core worker {uid} must work Friday (H3 domain is Mon–Thu)"
        # And exactly one Mon–Thu rest day, so the free day really is inside H3.
        rest = [d for d in FREE_DAYS if d not in days]
        assert len(rest) == 1, f"core worker {uid} must have exactly one Mon–Thu free day"


def test_h3_friday_free_day_pin_is_refused_not_honored() -> None:
    """§8: a free-day pin outside the worker's DOMAIN cannot widen it. With no
    grant issued, pinning every core worker's free day to Friday leaves the solve
    feasible and every one of them still working Friday — an out-of-domain pin is
    ignored, never self-granting. Only §2.3 issues the grant that would make such
    a pin meaningful."""
    res = solve(_input(free_day_pins={uid: Day.FRI for uid in sorted(CORE_IDS)}))
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    for uid in sorted(CORE_IDS):
        assert Day.FRI in worker_days(res.assignments, uid), (
            f"a Friday pin must not grant worker {uid} a Friday free day"
        )


def test_h3_hard_friday_request_is_infeasible_and_names_the_worker() -> None:
    """§2.1 H3/H4 vs H7: a hard full-day Friday request has no free-day move
    available inside the default Mon–Thu domain, so the plain solve is INFEASIBLE
    and the §8 assumption literals name the requesting worker. The solver never
    invents a Friday rest day on its own — the week must go through §2.3, which
    ISSUES the grant that makes one legal (`test_sacrifice_grant.py`). This test
    pins the INFEASIBLE-plus-attribution half that opens the conversation."""
    for uid in sorted(CORE_IDS):
        res = solve(_input(constraints=(_hard(uid, Day.FRI),)))
        assert res.status is SolverStatus.INFEASIBLE, f"hard Friday off for {uid} must not solve"
        blockers = {(c.worker_id, c.day) for c in res.blocking_constraints}
        assert (uid, Day.FRI) in blockers, f"the core must name worker {uid}'s Friday request"


def test_h3_hard_friday_request_stays_infeasible_under_every_free_day_pin() -> None:
    """§2.3 probe mechanics: pinning the requesting worker's free day to ANY
    Mon–Thu day still cannot honor a hard Friday request. So the §2.3 probe must
    carry the GRANT — a pin-only probe would report INFEASIBLE here and no proposal
    could ever be opened for the one day where a move actually helps."""
    constraints = (_hard(3, Day.FRI),)  # Pasha, hard Friday off
    for day in FREE_DAYS:
        probe = solve(_input(constraints=constraints, free_day_pins={3: day}))
        assert probe.status is SolverStatus.INFEASIBLE, (
            f"pinning Pasha's free day to {day.value} must not rescue a hard Friday request"
        )


# --- the structural consequence for the §2.3 probe --------------------------


def test_h3_a_free_day_pin_can_never_rescue_an_infeasible_week() -> None:
    """§2.3: a free-day pin only ever ADDS the constraint `free[u][d] == 1` to an
    otherwise unchanged model, so the pinned instance's feasible region is a SUBSET
    of the unpinned one. An INFEASIBLE week therefore stays INFEASIBLE under every
    pin — swept here over every two-constraint conflict, with zero rescues.

    This is the property that makes the §2.3 sacrifice **grant** load-bearing
    rather than decorative. If the probe in `sacrifice_service.open_sacrifice` were
    a bare pin, it could never succeed and step 2 ("move your free day to {day}?")
    would be dead code — which is the defect this test was written to expose and
    which the v1.4 domain extension fixes. The grant widens the domain FIRST; the
    pin then lands the free day inside the widened domain. Accordingly the sweep
    below pins only Mon–Thu days and passes no grants.

    A failure here means a pin has gained the power to widen a domain — i.e. the
    grant is being bypassed. Do not "fix" it by adding a grant to the sweep.
    """
    # Full-day requests over every worker × Mon–Fri: the sharpest conflicts, and a
    # small enough sweep to stay fast. (A wider sweep including am/pm slots was run
    # once during authoring — 5150 sets, 1988 of them INFEASIBLE, zero rescued.)
    universe = [_hard(w.id, d) for w in roster() for d in SOLVER_DAYS]
    infeasible_seen = 0
    for combo in itertools.combinations(universe, 2):
        res = solve(_input(constraints=combo))
        if res.status is not SolverStatus.INFEASIBLE:
            continue
        infeasible_seen += 1
        by_id = {w.id: w for w in roster()}
        candidates = {
            (c.worker_id, c.day)
            for c in res.blocking_constraints
            if by_id.get(c.worker_id) is not None
            and by_id[c.worker_id].is_core
            and c.day in FREE_DAYS
        }
        for worker_id, day in sorted(candidates):
            probe = solve(_input(constraints=combo, free_day_pins={worker_id: day}))
            assert probe.status is SolverStatus.INFEASIBLE, (
                f"pin {worker_id}->{day.value} rescued {combo}; the §2.3 probe branch is "
                "reachable again — re-read this test's docstring before changing it"
            )
    assert infeasible_seen > 0, "the sweep must actually exercise INFEASIBLE instances"
