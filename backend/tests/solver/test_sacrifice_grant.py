"""The §2.3 sacrifice grant: H3's free-day domain extension (§2.1 H3, §2.3, §8).

H3's Mon–Thu restriction is the *default* domain, not the whole rule: a worker
holding a §2.3 sacrifice grant for day ``g`` has the free-day domain
``Mon–Thu ∪ {g}``. This file proves the grant's three load-bearing properties:

1. **The domain helper is the single place the rule lives** — no grant returns
   exactly Mon–Thu, a Mon–Thu grant is a no-op, a Sat/Sun grant is refused, and a
   Friday grant is the one that actually widens (§2.3 corollary).
2. **The grant is what makes the propose branch reachable** — an INFEASIBLE hard
   Friday week that no pin can rescue (`test_h3_free_day_domain.py`) becomes
   feasible under grant + pin, with H7 honored in full: the worker works ZERO
   Friday slots and the jolly absorbs the opened slot.
3. **A granted free day is a first-class free day to the rest of the model** —
   in particular it counts toward the S2 rest-spread term (§2.2), both in what
   CP-SAT minimizes and in the reported/logged objective breakdown.

The no-grant side of every one of these lives in `test_h3_free_day_domain.py`;
the two must not be conflated. A Friday free day is legal **iff** a grant was
issued, and illegal otherwise.
"""

from __future__ import annotations

import pytest

from app.enums import AssignmentRole, ConstraintKind, ConstraintSlot, Day
from app.solver import PersonalConstraint, SolverInput, SolverStatus, solve
from app.solver.types import FREE_DAYS, SOLVER_DAYS, Weights, free_day_domain
from tests.solver.fixtures import (
    AMIR,
    FRANCESCO,
    MATTEO,
    MATTIA,
    PASHA,
    WEEK_MONDAY,
    WEIGHTS,
    canonical_prior_state,
    free_day_of,
    roster,
    worker_days,
)

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase3

# The F-pair (§2.2 rest spread): the two full-day spiaggini of the H5 template.
F_PAIR = frozenset({PASHA, AMIR})

# Same weights as production, with the rest-spread term switched OFF. Used only
# as a control: it isolates what the spread term is responsible for.
NO_SPREAD_WEIGHTS = Weights(w1=WEIGHTS.w1, w2=WEIGHTS.w2, w3=WEIGHTS.w3, w2_spread=0)


def _input(**overrides) -> SolverInput:
    kwargs = {
        "week_monday": WEEK_MONDAY,
        "roster": roster(),
        "prior_state": canonical_prior_state(),
        "full_weekend_ids": F_PAIR,
        "weights": WEIGHTS,
    }
    kwargs.update(overrides)
    return SolverInput(**kwargs)


def _hard(worker_id: int, day: Day, slot: ConstraintSlot = ConstraintSlot.FULL_DAY):
    return PersonalConstraint(worker_id, day, slot, ConstraintKind.HARD)


# --- 1. the domain helper ---------------------------------------------------


def test_h3_no_grant_domain_is_exactly_mon_thu() -> None:
    """§2.1 H3: with no grant the domain is exactly Mon–Thu — the normal-solve
    case, asserted on the single helper every `free[u][d]` key is built from."""
    assert free_day_domain(PASHA, {}) == FREE_DAYS
    assert free_day_domain(PASHA, {AMIR: Day.FRI}) == FREE_DAYS  # someone else's grant


def test_h3_friday_grant_extends_the_domain_to_mon_thu_plus_friday() -> None:
    """§2.1 H3 + §2.3: a Friday grant widens THAT worker's domain to
    `Mon–Thu ∪ {Fri}`, and only that worker's."""
    assert free_day_domain(PASHA, {PASHA: Day.FRI}) == (*FREE_DAYS, Day.FRI)
    assert set(free_day_domain(PASHA, {PASHA: Day.FRI})) == set(SOLVER_DAYS)


def test_h3_grant_for_a_mon_thu_day_is_a_no_op() -> None:
    """§2.3 corollary: Mon–Thu is already in the default domain, so a grant there
    widens nothing. The probe then reduces to the plain solve plus a pin, whose
    feasible region is a subset, so an INFEASIBLE week stays INFEASIBLE and the
    conflict escalates instead of producing a proposal."""
    for day in FREE_DAYS:
        assert free_day_domain(PASHA, {PASHA: day}) == FREE_DAYS


def test_h3_weekend_grant_is_refused_so_h3_cannot_be_voided() -> None:
    """§2.3 corollary + H5: the weekend has no solver variables, so a Sat/Sun free
    day would satisfy H3's cardinality without freeing any weekday. Refused."""
    for day in (Day.SAT, Day.SUN):
        assert free_day_domain(PASHA, {PASHA: day}) == FREE_DAYS


# --- 2. the grant is what makes §2.3 step 2 reachable -----------------------


def test_h3_friday_grant_rescues_a_week_no_pin_can() -> None:
    """§2.3 mechanics: a hard full-day Friday request is INFEASIBLE and stays so
    under every Mon–Thu pin (`test_h3_free_day_domain.py`). Carrying the GRANT for
    Friday alongside the pin makes the same week feasible — this is the difference
    between the §2.3 propose branch being reachable and being dead code.
    """
    constraints = (_hard(PASHA, Day.FRI),)
    assert solve(_input(constraints=constraints)).status is SolverStatus.INFEASIBLE

    granted = solve(
        _input(
            constraints=constraints,
            free_day_pins={PASHA: Day.FRI},
            sacrifice_grants={PASHA: Day.FRI},
        )
    )
    assert granted.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)


def test_h3_granted_free_day_honors_h7_in_full_and_keeps_h3_cardinality() -> None:
    """§2.3 "what is being traded": the worker gives up their weekday free-day
    PLACEMENT, never the request. Under the grant Pasha works ZERO Friday slots
    (H7 satisfied in full), works all four Mon–Thu days, and still has exactly one
    free day (H3's cardinality is untouched by a grant)."""
    res = solve(
        _input(
            constraints=(_hard(PASHA, Day.FRI),),
            free_day_pins={PASHA: Day.FRI},
            sacrifice_grants={PASHA: Day.FRI},
        )
    )
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)

    days = worker_days(res.assignments, PASHA)
    assert days.get(Day.FRI, []) == [], "H7: the hard Friday request is honored in full"
    for day in FREE_DAYS:
        assert len(days.get(day, [])) == 1, f"H4: Pasha works exactly one slot on {day.value}"
    assert free_day_of(res.assignments, PASHA) is Day.FRI  # exactly one free day, on the grant


def test_h3_only_the_granted_worker_may_rest_on_friday() -> None:
    """§2.3: a grant is per worker. With Pasha granted (and resting) Friday, every
    OTHER core worker still has a Mon–Thu-only domain and works Friday."""
    res = solve(
        _input(
            constraints=(_hard(PASHA, Day.FRI),),
            free_day_pins={PASHA: Day.FRI},
            sacrifice_grants={PASHA: Day.FRI},
        )
    )
    for uid in (MATTEO, FRANCESCO, AMIR):
        assert Day.FRI in worker_days(res.assignments, uid), (
            f"worker {uid} holds no grant, so H3's domain is Mon–Thu and Friday is worked"
        )
        assert free_day_of(res.assignments, uid) in FREE_DAYS


def test_h6_jolly_absorbs_the_slot_the_granted_friday_opens() -> None:
    """H6 + H1: the Friday slot Pasha no longer works is covered — the two Friday
    spiaggino slots are held by the remaining spiaggini, with the jolly taking at
    least one. Nobody is left uncovered by the trade."""
    res = solve(
        _input(
            constraints=(_hard(PASHA, Day.FRI),),
            free_day_pins={PASHA: Day.FRI},
            sacrifice_grants={PASHA: Day.FRI},
        )
    )
    covered = [
        a for a in res.assignments if a.day is Day.FRI and a.role is AssignmentRole.SPIAGGINO
    ]
    assert len(covered) == 2, "H1: both Friday spiaggino slots are covered"
    assert all(a.worker_id != PASHA for a in covered)
    assert any(a.worker_id == MATTIA for a in covered), "H6: the jolly absorbs the opened slot"


def test_h3_grant_without_a_pin_still_permits_a_mon_thu_free_day() -> None:
    """§2.3: a grant WIDENS the domain, it does not force the free day onto the
    granted day. With no conflict to absorb, the solver keeps its Mon–Thu choice
    — so a stray grant can never silently move a free day to Friday."""
    res = solve(_input(sacrifice_grants={PASHA: Day.FRI}))
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert free_day_of(res.assignments, PASHA) in FREE_DAYS


# --- 3. a granted free day is a first-class free day to S2 rest spread ------

# Both full-weekend workers hard-off Friday and both granted it: H4 forces every
# non-free weekday worked, so each one's single free day can only be Friday. The
# F-pair is therefore FORCED to share a *granted* day — the exact configuration
# whose spread penalty a domain-blind breakdown would report as zero.
_BOTH_F_PAIR_HARD_FRI = (_hard(PASHA, Day.FRI), _hard(AMIR, Day.FRI))
_BOTH_F_PAIR_GRANTED_FRI = {PASHA: Day.FRI, AMIR: Day.FRI}


def test_w2_spread_counts_an_f_pair_sharing_a_granted_friday() -> None:
    """§2.2 S2 rest spread under a grant: the term penalizes two full-weekend
    workers resting on the same day because it leaves their spiaggino role covered
    by the jolly alone for a whole day — a coverage rationale, so it is
    day-agnostic and a GRANTED day counts like any other.

    Regression guard: a breakdown that scans only Mon–Thu finds no rest day for a
    worker resting on a granted Friday, silently reporting `spread_shared_pairs=0`
    for a real W2_SPREAD (200) penalty.
    """
    res = solve(
        _input(
            constraints=_BOTH_F_PAIR_HARD_FRI,
            sacrifice_grants=_BOTH_F_PAIR_GRANTED_FRI,
        )
    )
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert free_day_of(res.assignments, PASHA) is Day.FRI
    assert free_day_of(res.assignments, AMIR) is Day.FRI

    assert res.objective is not None
    assert res.objective.spread_shared_pairs == 1, (
        "the F-pair shares a granted Friday — the spread term must count it, not report 0"
    )


def test_logged_objective_breakdown_matches_the_minimized_sum_under_a_grant() -> None:
    """§8 logging: the reported (and logged) breakdown must be the value CP-SAT
    minimized. With a granted Friday free day in play, re-derive the weighted total
    from the per-tier fields and the input weights and assert it matches — so a
    breakdown that zeroes the granted-day spread contribution cannot slip through
    while the total still looks plausible."""
    res = solve(
        _input(
            constraints=_BOTH_F_PAIR_HARD_FRI,
            sacrifice_grants=_BOTH_F_PAIR_GRANTED_FRI,
        )
    )
    obj = res.objective
    assert obj is not None
    expected = (
        WEIGHTS.w1 * obj.soft_unmet
        + WEIGHTS.w2 * (obj.alternation_breaks + obj.fairness_deviation)
        + WEIGHTS.w2_spread * obj.spread_shared_pairs
        + WEIGHTS.w3 * obj.jolly_days
    )
    assert obj.weighted_total == expected
    # And the granted-day penalty is really inside that total, not rounded away.
    assert obj.weighted_total >= WEIGHTS.w2_spread


# The behavioral counterpart: the granted day is inside what CP-SAT MINIMIZES,
# not merely inside what the breakdown reports. Setup — Pasha hard-off Friday and
# granted it (so he rests Friday), Amir granted Friday too, both bagnini pinned to
# Thursday, and the jolly hard-off Mon+Tue (which blocks Amir from resting either:
# those days then need both spiaggini). Amir's real choice is Wednesday or joining
# Pasha on the granted Friday; joining saves one jolly day (W3), so with the spread
# term blind to granted days he WOULD join.
_AMIR_CHOOSES = (_hard(PASHA, Day.FRI), _hard(MATTIA, Day.MON), _hard(MATTIA, Day.TUE))
_BAGNINI_PINNED_THU = {MATTEO: Day.THU, FRANCESCO: Day.THU}


def test_w2_spread_splits_the_f_pair_off_a_granted_friday_when_it_could_share() -> None:
    """§2.2: with the rest-spread term live, the F-pair is kept apart even when the
    shared day would be a GRANTED Friday and sharing would save a jolly day."""
    res = solve(
        _input(
            constraints=_AMIR_CHOOSES,
            free_day_pins=_BAGNINI_PINNED_THU,
            sacrifice_grants=_BOTH_F_PAIR_GRANTED_FRI,
        )
    )
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert free_day_of(res.assignments, PASHA) is Day.FRI  # forced by his hard request
    assert free_day_of(res.assignments, AMIR) is not Day.FRI, (
        "W2_SPREAD must keep the F-pair off a shared free day, granted day included"
    )
    assert res.objective is not None and res.objective.spread_shared_pairs == 0


def test_w2_spread_is_the_only_thing_keeping_them_apart_control() -> None:
    """Control for the test above: the SAME instance with `w2_spread = 0` co-locates
    the F-pair on the granted Friday, and CP-SAT does so to save a jolly day.

    This is what makes the previous test evidence about the MINIMIZED objective
    rather than about the report: the two solves differ only in that coefficient,
    so the granted Friday must be inside the model's spread term for the outcome
    to change at all.
    """
    res = solve(
        _input(
            constraints=_AMIR_CHOOSES,
            free_day_pins=_BAGNINI_PINNED_THU,
            sacrifice_grants=_BOTH_F_PAIR_GRANTED_FRI,
            weights=NO_SPREAD_WEIGHTS,
        )
    )
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert free_day_of(res.assignments, PASHA) is Day.FRI
    assert free_day_of(res.assignments, AMIR) is Day.FRI  # co-located once unpenalized
    assert res.objective is not None
    assert res.objective.spread_shared_pairs == 1  # counted even with a zero coefficient
