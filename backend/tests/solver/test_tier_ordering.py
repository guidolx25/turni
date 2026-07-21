"""Lexicographic tier ordering W1 >> W2 (§2.2).

Two tiers, and only two, since v1.12: `W1·soft_unmet + W2·(alternation_breaks +
fairness_deviation)`. The former `W2_SPREAD` was promoted into hard H3(c) and the
former `W3` (Mattia clustering) was deleted outright, so the S2-band-vs-S3
ordering this file used to construct no longer exists to be tested — there is no
third tier to outrank.

What remains, and what is proven here, is that S1 genuinely dominates S2: the
solver honors one soft request even when honoring it costs SEVERAL alternation
breaks, and prefers that to the cheapest S2 layout that violates the request.

Non-vacuity is the whole difficulty with an ordering test, so it is established
by explicit control solves rather than asserted: a baseline shows what S2 alone
would choose, and a forced-violation control shows the S2 optimum really is
cheaper on the S2 tier. Only then is "the solver picked the S1 answer anyway"
evidence about the ordering.
"""

from __future__ import annotations

import pytest

from app.enums import AssignmentSlot, ConstraintKind, ConstraintSlot, Day
from app.solver import PersonalConstraint, SolverInput, SolverStatus, solve
from tests.solver.fixtures import (
    MATTEO,
    WEEK_MONDAY,
    WEIGHTS,
    canonical_prior_state,
    free_day_of,
    role_domain,
    roster,
    worker_days,
)

# Phase of origin (project conventions: gate runs selectable per phase).
pytestmark = pytest.mark.phase2

# Matteo exits Sunday PM (canonical prior_state), so S2 alternation strictly
# prefers him on Mon AM. Pin his free day to WED — inside his H3(b) bagnino domain
# {Tue, Wed}, so the pin is actually enforced — which guarantees he works Monday.
_MATTEO_FREE_WED = {MATTEO: Day.WED}

# The S1 request under test: keep Matteo off the Mon AM slot S2 wants him in.
_SOFT_OFF_MON_AM = (PersonalConstraint(MATTEO, Day.MON, ConstraintSlot.AM, ConstraintKind.SOFT),)
# The control that FORCES the request to be violated: H7 outranks everything, so
# barring the alternative slot leaves the solver no way to honor the soft one.
_HARD_OFF_MON_PM = (PersonalConstraint(MATTEO, Day.MON, ConstraintSlot.PM, ConstraintKind.HARD),)


def _solve(constraints=(), pins=None):
    return solve(
        SolverInput(
            week_monday=WEEK_MONDAY,
            roster=roster(),
            constraints=constraints,
            free_day_pins=_MATTEO_FREE_WED if pins is None else pins,
            prior_state=canonical_prior_state(),
            weights=WEIGHTS,
        )
    )


def _matteo_monday_slots(res) -> set[AssignmentSlot]:
    return {a.slot for a in worker_days(res.assignments, MATTEO).get(Day.MON, [])}


def test_the_pin_this_file_rests_on_is_inside_the_role_domain() -> None:
    """Guard for every construction below: the Wednesday pin is only enforced
    because Wednesday is inside Matteo's H3(b) bagnino domain. An out-of-domain pin
    is silently ignored (§8), which would leave his Monday slot unconstrained and
    quietly turn the ordering tests vacuous."""
    assert Day.WED in role_domain(MATTEO)
    res = _solve()
    assert free_day_of(res.assignments, MATTEO) is Day.WED


def test_s2_alone_puts_matteo_on_monday_am() -> None:
    """Baseline for the S1 > S2 conflict: with no soft request, S2 places Matteo
    on Mon AM (prior PM → Mon AM avoids the cross-week boundary break). This proves
    the soft request below genuinely fights the alternation optimum."""
    res = _solve()
    assert res.status in (SolverStatus.OPTIMAL, SolverStatus.FEASIBLE)
    assert _matteo_monday_slots(res) == {AssignmentSlot.AM}


def test_s2_optimum_really_is_cheaper_when_the_soft_request_is_violated() -> None:
    """The other half of non-vacuity. Force the soft request to be violated (H7
    bars Mon PM, so Mon AM is the only slot left) and read off the S2 cost of that
    layout: it is STRICTLY LOWER than the S2 cost of honoring the request. So the
    solver faces a real trade, not a free lunch."""
    honored = _solve(_SOFT_OFF_MON_AM)
    violated = _solve(_SOFT_OFF_MON_AM + _HARD_OFF_MON_PM)
    assert honored.objective is not None and violated.objective is not None
    assert violated.objective.soft_unmet == 1
    assert honored.objective.soft_unmet == 0

    def s2(obj) -> int:
        return obj.alternation_breaks + obj.fairness_deviation

    assert s2(violated.objective) < s2(honored.objective), (
        "the violating layout must be the cheaper one on the S2 tier for this to test ordering"
    )


def test_w1_beats_w2_soft_request_honored_at_the_cost_of_several_s2_units() -> None:
    """§2.2 W1 >> W2, the ordering itself: the solver honors the single soft request
    (soft_unmet == 0) even though doing so costs MORE THAN ONE alternation break
    relative to the S2 optimum. Matteo moves to Mon PM — a same-slot boundary break
    against his Sunday PM exit, plus a knock-on break — because one unmet soft (W1)
    dwarfs the whole S2 delta.

    Asserted on the objective, not on a tie-break: the honoring solve's weighted
    total is strictly lower than the violating control's, which is what "W1 >> W2"
    means operationally."""
    honored = _solve(_SOFT_OFF_MON_AM)
    baseline = _solve()
    violated = _solve(_SOFT_OFF_MON_AM + _HARD_OFF_MON_PM)
    assert honored.objective is not None
    assert baseline.objective is not None and violated.objective is not None

    assert honored.objective.soft_unmet == 0
    assert _matteo_monday_slots(honored) == {AssignmentSlot.PM}
    # The trade really happened, and cost more than a single S2 unit.
    assert honored.objective.alternation_breaks - baseline.objective.alternation_breaks > 1
    # And W1 still dominates that whole delta.
    assert honored.objective.weighted_total < violated.objective.weighted_total


def test_one_unmet_soft_outweighs_the_worst_case_s2_total() -> None:
    """§2.2 "well-separated weights", asserted as arithmetic on the production
    constants rather than on one instance: a single W1 unit exceeds W2 times the
    maximum S2 count the model can produce (`Bmax` = 71, proven in
    `app.solver.weights`). Without this margin the ordering above would hold only
    for the small S2 deltas this week happens to admit."""
    bmax = 71  # app.solver.weights: 50 alternation + 21 fairness, worst case.
    assert WEIGHTS.w1 > WEIGHTS.w2 * bmax


def test_an_unsatisfiable_soft_request_costs_exactly_one_w1_unit() -> None:
    """§2.2 S1 accounting, and the v1.12 out-of-domain case: a soft FULL-DAY request
    on a day outside the requester's H3(b) role domain can never be satisfied — the
    free day cannot go there without a §2.3 grant, and no grant is issued for a soft
    request. It is simply counted unmet, once, and the week still solves.

    The magnitude anchor for the tests above: one unmet soft contributes exactly W1
    to the total, so any S2 delta below `W1 / W2` is dominated by it."""
    res = _solve(
        (PersonalConstraint(MATTEO, Day.THU, ConstraintSlot.FULL_DAY, ConstraintKind.SOFT),),
        pins={},
    )
    assert res.status is SolverStatus.OPTIMAL
    assert res.objective is not None
    assert Day.THU not in role_domain(MATTEO)
    assert res.objective.soft_unmet == 1
    s2 = res.objective.alternation_breaks + res.objective.fairness_deviation
    assert res.objective.weighted_total == WEIGHTS.w1 + WEIGHTS.w2 * s2
