"""The §2.3 sacrifice grant: H3's free-day domain extension (§2.1 H3, §2.3, §8).

The H3(b) ROLE domain is the *default*, not the whole rule: a worker holding a
§2.3 sacrifice grant for day ``g`` has the free-day domain ``role-domain ∪ {g}``.
This file proves the grant's four load-bearing properties:

1. **The domain helper is the single place the rule lives** — no grant returns
   exactly the role domain, an in-domain grant is a no-op, a Sat/Sun grant is
   refused, and an out-of-domain weekday grant is the one that actually widens.
2. **The grant is what makes the §2.3 propose branch reachable** — and it is
   reachable on exactly the six cells of the v1.12 reachable-days table:
   a spiaggino Wed/Thu/Fri and a bagnino Mon/Thu/Fri are each INFEASIBLE plain
   and OPTIMAL under the matching grant. In-domain days are NOT reachable: there
   the grant is a no-op and the conflict escalates instead.
3. **H3(a) and H3(c) are untouched by a grant** — a granted worker still has
   exactly one free day, and still may not share it with their same-role partner.
   These are the two conflicts §2.3 says escalate systematically.
4. **A granted free day is a first-class free day to the rest of the model** —
   H4, H6 coverage and the reported objective breakdown all treat it as one.

The no-grant side of every one of these lives in `test_h3_free_day_domain.py`;
the two must not be conflated. An out-of-domain free day is legal **iff** a grant
was issued, and illegal otherwise.
"""

from __future__ import annotations

import pytest

from app.enums import AssignmentRole, ConstraintKind, ConstraintSlot, Day, UserRole
from app.solver import PersonalConstraint, SolverInput, SolverStatus, solve
from app.solver.types import ROLE_FREE_DAYS, free_day_domain
from tests.solver.fixtures import (
    AMIR,
    FRANCESCO,
    MATTEO,
    MATTIA,
    PASHA,
    SAME_ROLE_PAIRS,
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

# §2.3's reachable-days table (v1.12), as (worker, day) pairs: every cell marked
# `reachable` — outside the holder's role domain but a weekday, so a grant genuinely
# widens the domain and the extended probe is feasible.
REACHABLE_CELLS = (
    (PASHA, Day.WED),  # spiaggino: domain {Mon, Tue}
    (PASHA, Day.THU),
    (PASHA, Day.FRI),
    (MATTEO, Day.MON),  # bagnino: domain {Tue, Wed}
    (MATTEO, Day.THU),
    (MATTEO, Day.FRI),
)

# The in-domain cells, where §2.3 says a grant is a NO-OP and the conflict escalates.
IN_DOMAIN_CELLS = (
    (PASHA, Day.MON),
    (PASHA, Day.TUE),
    (MATTEO, Day.TUE),
    (MATTEO, Day.WED),
)


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


# --- 1. the domain helper ---------------------------------------------------


def test_h3b_no_grant_domain_is_exactly_the_role_domain() -> None:
    """§2.1 H3(b): with no grant the domain is exactly `ROLE_FREE_DAYS[role]` —
    the normal-solve case, asserted on the single helper every `free[u][d]` key is
    built from. Someone else's grant does not leak across workers."""
    assert free_day_domain(UserRole.SPIAGGINO, PASHA, {}) == ROLE_FREE_DAYS[UserRole.SPIAGGINO]
    assert free_day_domain(UserRole.BAGNINO, MATTEO, {}) == ROLE_FREE_DAYS[UserRole.BAGNINO]
    assert (
        free_day_domain(UserRole.SPIAGGINO, PASHA, {AMIR: Day.FRI})
        == ROLE_FREE_DAYS[UserRole.SPIAGGINO]
    )


def test_h3b_domain_is_keyed_off_role_never_identity() -> None:
    """§2.1 H3(b): "keyed off `users.role`, never off identity". The same worker id
    under the other role yields the other domain — the id only selects the grant."""
    assert free_day_domain(UserRole.BAGNINO, PASHA, {}) == ROLE_FREE_DAYS[UserRole.BAGNINO]
    assert free_day_domain(UserRole.SPIAGGINO, MATTEO, {}) == ROLE_FREE_DAYS[UserRole.SPIAGGINO]


def test_h3_out_of_domain_grant_extends_the_domain_by_exactly_that_day() -> None:
    """§2.1 H3 + §2.3: a grant widens THAT worker's domain to
    `role-domain ∪ {g}`, adding one day and nothing else."""
    for worker_id, day in REACHABLE_CELLS:
        role = UserRole.SPIAGGINO if worker_id is PASHA else UserRole.BAGNINO
        widened = free_day_domain(role, worker_id, {worker_id: day})
        assert widened == (*ROLE_FREE_DAYS[role], day)


def test_h3_grant_for_an_in_domain_day_is_a_no_op() -> None:
    """§2.3 reachable-days table: an in-domain day is already in the role domain,
    so a grant there widens nothing. The probe then reduces to the plain solve plus
    a pin, whose feasible region is a subset, so an INFEASIBLE week stays
    INFEASIBLE and the conflict escalates instead of producing a proposal."""
    for worker_id, day in IN_DOMAIN_CELLS:
        role = UserRole.SPIAGGINO if worker_id is PASHA else UserRole.BAGNINO
        assert free_day_domain(role, worker_id, {worker_id: day}) == ROLE_FREE_DAYS[role]


def test_h3_weekend_grant_is_refused_so_h3_cannot_be_voided() -> None:
    """§2.3 + H5: the weekend has no solver variables, so a Sat/Sun free day would
    satisfy H3's cardinality without freeing any weekday. Refused for both roles."""
    for role in (UserRole.SPIAGGINO, UserRole.BAGNINO):
        for day in (Day.SAT, Day.SUN):
            assert free_day_domain(role, PASHA, {PASHA: day}) == ROLE_FREE_DAYS[role]


# --- 2. all six reachable cells: INFEASIBLE plain, OPTIMAL under the grant ---


@pytest.mark.parametrize(("worker_id", "day"), REACHABLE_CELLS)
def test_h3_reachable_cell_is_infeasible_plain(worker_id: int, day: Day) -> None:
    """§2.3 reachable-days table, first half: a hard FULL-DAY request on a day
    outside the holder's role domain has no free-day move available by default, so
    the plain solve is INFEASIBLE and the §8 unsat core names the requester. This
    is the half that opens the §2.3 conversation."""
    assert day not in role_domain(worker_id)
    res = solve(_input(constraints=(_hard(worker_id, day),)))
    assert res.status is SolverStatus.INFEASIBLE
    assert (worker_id, day) in {(c.worker_id, c.day) for c in res.blocking_constraints}


@pytest.mark.parametrize(("worker_id", "day"), REACHABLE_CELLS)
def test_h3_reachable_cell_is_optimal_under_the_matching_grant(worker_id: int, day: Day) -> None:
    """§2.3 reachable-days table, second half: "every cell marked reachable has a
    feasible extended probe, so all six genuinely reach step 2". The grant alone
    rescues the week — H3(a) cardinality plus H4 then force the free day onto the
    granted day — and H7 is honored in full: zero slots on the requested day."""
    res = solve(
        _input(
            constraints=(_hard(worker_id, day),),
            sacrifice_grants={worker_id: day},
        )
    )
    assert res.status is SolverStatus.OPTIMAL
    assert free_day_of(res.assignments, worker_id) is day
    assert worker_days(res.assignments, worker_id).get(day, []) == []


@pytest.mark.parametrize(("worker_id", "day"), REACHABLE_CELLS)
def test_h3_a_grant_for_the_wrong_day_does_not_rescue_the_week(worker_id: int, day: Day) -> None:
    """§2.3: the grant is issued "only for the day named in the blocking hard
    constraint". A grant for some OTHER out-of-domain day widens the domain
    somewhere useless, and the week stays INFEASIBLE — so the rescues above are
    about the specific day, not about grants being a general escape hatch."""
    other = next(d for _, d in REACHABLE_CELLS if d is not day and d not in role_domain(worker_id))
    res = solve(
        _input(
            constraints=(_hard(worker_id, day),),
            sacrifice_grants={worker_id: other},
        )
    )
    assert res.status is SolverStatus.INFEASIBLE


@pytest.mark.parametrize(("worker_id", "day"), IN_DOMAIN_CELLS)
def test_h3_in_domain_conflicts_are_not_rescued_by_a_grant(worker_id: int, day: Day) -> None:
    """§2.3 "the unreachable cases": on an in-domain day the plain solve already
    succeeds — there is nothing to rescue and no proposal to open. Asserted as
    feasibility, with the free day landing on the requested day of its own accord."""
    res = solve(_input(constraints=(_hard(worker_id, day),)))
    assert _feasible(res)
    assert free_day_of(res.assignments, worker_id) is day


# --- 3. H3(a) and H3(c) survive a grant untouched ---------------------------


def test_h3a_cardinality_blocks_two_out_of_domain_requests_for_one_worker() -> None:
    """§2.3 systematic escalation (i): "H7 demands zero slots on both days; H3(a)
    allows exactly one free day; a grant widens *where* the free day falls, never
    how many there are. No single grant satisfies both." INFEASIBLE under either
    grant, so no probe can succeed and the flow must escalate."""
    constraints = (_hard(PASHA, Day.THU), _hard(PASHA, Day.FRI))
    assert solve(_input(constraints=constraints)).status is SolverStatus.INFEASIBLE
    for day in (Day.THU, Day.FRI):
        probe = solve(_input(constraints=constraints, sacrifice_grants={PASHA: day}))
        assert probe.status is SolverStatus.INFEASIBLE, (
            f"a grant for {day.value} cannot buy Pasha a second free day (H3(a))"
        )
    # Even granting BOTH days at once — which §2.3 never does — cannot help, since
    # the blocker is cardinality, not the domain.
    both = solve(_input(constraints=constraints, sacrifice_grants={PASHA: Day.THU}))
    assert both.status is SolverStatus.INFEASIBLE


def test_h3c_blocks_a_same_role_pair_granted_the_same_day() -> None:
    """§2.3 systematic escalation (ii): "H3(c) forbids them sharing a free day at
    any strength, granted or not." Both spiaggini hard-off Thursday and both
    granted it: each one's free day is forced onto Thursday, which (c) refuses —
    INFEASIBLE at any grant strength, so no proposal can ever resolve it."""
    constraints = (_hard(PASHA, Day.THU), _hard(AMIR, Day.THU))
    assert solve(_input(constraints=constraints)).status is SolverStatus.INFEASIBLE
    granted = solve(
        _input(constraints=constraints, sacrifice_grants={PASHA: Day.THU, AMIR: Day.THU})
    )
    assert granted.status is SolverStatus.INFEASIBLE


def test_h3c_a_granted_worker_still_may_not_join_their_partner() -> None:
    """§2.1 H3(c) survives a grant, the non-vacuous version: Pasha is hard-off
    Thursday and granted it, so he rests Thursday. Amir is ALSO granted Thursday
    but has no request forcing him there — (c) still keeps him off it, and his free
    day falls back inside his own role domain. A model that applied (c) only to
    default-domain days would let the pair co-locate here."""
    res = solve(
        _input(
            constraints=(_hard(PASHA, Day.THU),),
            sacrifice_grants={PASHA: Day.THU, AMIR: Day.THU},
        )
    )
    assert _feasible(res)
    assert free_day_of(res.assignments, PASHA) is Day.THU
    assert free_day_of(res.assignments, AMIR) is not Day.THU
    assert free_day_of(res.assignments, AMIR) in role_domain(AMIR)


def test_h3c_still_holds_across_both_pairs_under_a_grant() -> None:
    """§2.1 H3(c) as an invariant of a granted week: with one worker resting
    outside his role domain, neither same-role pair shares a free day."""
    res = solve(
        _input(
            constraints=(_hard(MATTEO, Day.FRI),),
            sacrifice_grants={MATTEO: Day.FRI},
        )
    )
    assert _feasible(res)
    for a, b in SAME_ROLE_PAIRS:
        assert free_day_of(res.assignments, a) != free_day_of(res.assignments, b)


# --- 4. a granted free day is a first-class free day ------------------------


def test_h3_only_the_granted_worker_leaves_their_role_domain() -> None:
    """§2.3: a grant is per worker. With Pasha granted (and resting) Friday, every
    OTHER core worker still has their plain role domain."""
    res = solve(
        _input(
            constraints=(_hard(PASHA, Day.FRI),),
            sacrifice_grants={PASHA: Day.FRI},
        )
    )
    assert _feasible(res)
    for uid in (MATTEO, FRANCESCO, AMIR):
        assert Day.FRI in worker_days(res.assignments, uid), f"worker {uid} holds no grant"
        assert free_day_of(res.assignments, uid) in role_domain(uid)


def test_h4_holds_on_every_other_day_of_a_granted_week() -> None:
    """§2.3 "what is being traded": the worker gives up their free-day PLACEMENT,
    never the request. Under a Friday grant Pasha works exactly one slot on each of
    Mon–Thu (H4) and zero on Friday (H7), with exactly one free day (H3(a))."""
    res = solve(
        _input(
            constraints=(_hard(PASHA, Day.FRI),),
            sacrifice_grants={PASHA: Day.FRI},
        )
    )
    days = worker_days(res.assignments, PASHA)
    assert days.get(Day.FRI, []) == []
    for day in (Day.MON, Day.TUE, Day.WED, Day.THU):
        assert len(days.get(day, [])) == 1, f"H4: Pasha works exactly one slot on {day.value}"
    assert free_day_of(res.assignments, PASHA) is Day.FRI


def test_h6_jolly_absorbs_the_slot_the_granted_free_day_opens() -> None:
    """H6 + H1: the Friday slot Pasha no longer works is covered — both Friday
    spiaggino slots are filled, with the jolly taking at least one."""
    res = solve(
        _input(
            constraints=(_hard(PASHA, Day.FRI),),
            sacrifice_grants={PASHA: Day.FRI},
        )
    )
    covered = [
        a for a in res.assignments if a.day is Day.FRI and a.role is AssignmentRole.SPIAGGINO
    ]
    assert len(covered) == 2, "H1: both Friday spiaggino slots are covered"
    assert all(a.worker_id != PASHA for a in covered)
    assert any(a.worker_id == MATTIA for a in covered), "H6: the jolly absorbs the opened slot"


def test_h3_a_grant_widens_the_domain_without_forcing_the_day() -> None:
    """§2.3: a grant is a DOMAIN extension, not a pin — it adds `free[u][g]` as a
    legal choice and constrains nothing else. Pinned here on the model rather than
    on the optimizer's preference: with a grant and no conflict the week is
    feasible, the granted worker still has exactly one free day (H3(a)), and it
    lies inside `role-domain ∪ {g}` — never anywhere else.

    Deliberately NOT asserted: that the free day stays inside the *role* domain.
    Pre-v1.12 it did, but only because the deleted S3/W3 jolly-clustering tier made
    an out-of-domain rest day cost an extra jolly day. With that tier gone, a
    granted day is simply a legal day and §2.2 may prefer it. See the module
    docstring of `test_tier_ordering.py` for what the remaining tiers do choose.
    """
    res = solve(_input(sacrifice_grants={PASHA: Day.FRI}))
    assert _feasible(res)
    free = free_day_of(res.assignments, PASHA)
    assert free is not None, "H3(a): exactly one free day, grant or no grant"
    assert free in (*role_domain(PASHA), Day.FRI)
    # And the widening is strictly local: nobody else gained a day.
    for uid in (MATTEO, FRANCESCO, AMIR):
        assert free_day_of(res.assignments, uid) in role_domain(uid)


def test_logged_objective_breakdown_matches_the_minimized_sum_under_a_grant() -> None:
    """§8 logging: the reported (and logged) breakdown must be the value CP-SAT
    minimized — two tiers since v1.12. Re-derived from the per-tier fields and the
    input weights on a granted week, so a term silently dropped on the granted-day
    path cannot slip through while the total still looks plausible."""
    res = solve(
        _input(
            constraints=(_hard(PASHA, Day.FRI),),
            sacrifice_grants={PASHA: Day.FRI},
        )
    )
    obj = res.objective
    assert obj is not None
    expected = WEIGHTS.w1 * obj.soft_unmet + WEIGHTS.w2 * (
        obj.alternation_breaks + obj.fairness_deviation
    )
    assert obj.weighted_total == expected
